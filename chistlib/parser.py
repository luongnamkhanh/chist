"""Parse Claude Code session JSONL into normalized records."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


@dataclass
class Record:
    role: str           # user | assistant | tool_use | tool_result
    timestamp: Optional[str]
    content: str


def _flatten_content(content) -> tuple[str, str]:
    """Return (role_override, flattened_text). role_override is non-empty for
    tool_use / tool_result blocks."""
    if content is None:
        return ("", "")
    if isinstance(content, str):
        return ("", content)
    if not isinstance(content, list):
        return ("", json.dumps(content, ensure_ascii=False))

    texts: list[str] = []
    role_override = ""
    for block in content:
        if not isinstance(block, dict):
            texts.append(str(block))
            continue
        btype = block.get("type", "")
        if btype == "text":
            texts.append(block.get("text", ""))
        elif btype == "tool_use":
            role_override = "tool_use"
            name = block.get("name", "")
            inp = block.get("input", {})
            texts.append(f"[tool_use:{name}] {json.dumps(inp, ensure_ascii=False)}")
        elif btype == "tool_result":
            role_override = "tool_result"
            inner = block.get("content", "")
            if isinstance(inner, list):
                inner_texts = []
                for ib in inner:
                    if isinstance(ib, dict) and ib.get("type") == "text":
                        inner_texts.append(ib.get("text", ""))
                    else:
                        inner_texts.append(json.dumps(ib, ensure_ascii=False))
                inner = "\n".join(inner_texts)
            texts.append(f"[tool_result] {inner}")
        else:
            texts.append(json.dumps(block, ensure_ascii=False))
    return (role_override, "\n".join(t for t in texts if t))


def parse_line(line: str) -> Optional[Record]:
    if not line or not line.strip():
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(obj, dict):
        return None

    msg = obj.get("message") or {}
    raw_role = msg.get("role") or obj.get("type") or "unknown"
    content = msg.get("content", obj.get("content", ""))
    role_override, text = _flatten_content(content)
    role = role_override or raw_role
    ts = obj.get("timestamp")
    return Record(role=role, timestamp=ts, content=text)


def parse_file(path: Path) -> Iterator[Record]:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            rec = parse_line(line)
            if rec is not None:
                yield rec


_CODEX_INJECTED = ("<environment_context>", "AGENTS.md instructions", "<user_instructions>")


def _codex_record(obj: dict) -> Optional[Record]:
    if obj.get("type") != "response_item":
        return None
    p = obj.get("payload") or {}
    ptype = p.get("type")
    ts = obj.get("timestamp")
    if ptype == "message" and p.get("role") in ("user", "assistant"):
        text = "\n".join(
            c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict)
        )
        if not text or text.lstrip().startswith(_CODEX_INJECTED):
            return None
        return Record(role=p["role"], timestamp=ts, content=text)
    if ptype in ("function_call", "custom_tool_call"):
        args = p.get("arguments") or p.get("input") or ""
        return Record(role="tool_use", timestamp=ts, content=f"[tool_use:{p.get('name', '')}] {args}")
    if ptype in ("function_call_output", "custom_tool_call_output"):
        out = p.get("output")
        out = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return Record(role="tool_result", timestamp=ts, content=f"[tool_result] {out}")
    return None


def parse_codex_file(path: Path) -> tuple[str, str, list[Record]]:
    """Return (session_id, cwd, records) for a Codex rollout-*.jsonl."""
    sid, cwd, records = path.stem, "", []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("type") == "session_meta":
                meta = obj.get("payload") or {}
                sid, cwd = meta.get("id") or sid, meta.get("cwd") or ""
                continue
            rec = _codex_record(obj)
            if rec is not None:
                records.append(rec)
    return sid, cwd, records


def _kiro_record(obj: dict) -> Optional[Record]:
    p = obj.get("payload") or {}
    ptype, ts = p.get("type"), obj.get("timestamp")
    if ptype == "user" or (ptype == "assistant" and p.get("operationType") != "Reasoning"):
        text = p.get("content")
        return Record(role=ptype, timestamp=ts, content=text) if isinstance(text, str) and text else None
    if ptype == "tool_call":
        return Record(role="tool_use", timestamp=ts,
                      content=f"[tool_use:{p.get('toolName', '')}] {json.dumps(p.get('args'), ensure_ascii=False)}")
    if ptype == "tool_result":
        out = p.get("content")
        out = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return Record(role="tool_result", timestamp=ts, content=f"[tool_result] {out}")
    return None


def parse_kiro_session(session_dir: Path) -> tuple[str, str, list[Record]]:
    """Return (session_id, cwd, records) for a Kiro ~/.kiro/sessions/<hash>/sess_<uuid>/ dir."""
    sid, cwd = session_dir.name.removeprefix("sess_"), ""
    try:
        meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
        sid = (meta.get("id") or sid).removeprefix("sess_")
        cwd = (meta.get("workspacePaths") or [""])[0]
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    records = []
    with (session_dir / "messages.jsonl").open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec = _kiro_record(obj) if isinstance(obj, dict) else None
            if rec is not None:
                records.append(rec)
    return sid, cwd, records


def agy_workspace_map(summaries_db: Optional[Path]) -> dict[str, str]:
    """Return {conversation_id: first_workspace_path} from Antigravity's SQLite db."""
    if summaries_db is None or not summaries_db.exists():
        return {}
    import sqlite3
    from urllib.parse import unquote, urlparse
    out: dict[str, str] = {}
    try:
        con = sqlite3.connect(f"file:{summaries_db}?mode=ro", uri=True, timeout=2.0)
        try:
            rows = con.execute(
                "SELECT conversation_id, workspace_uris FROM conversation_summaries"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    for cid, raw in rows:
        try:
            uris = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            continue
        if isinstance(uris, list) and uris:
            u = urlparse(uris[0])
            out[cid] = unquote(u.path) if u.scheme == "file" else uris[0]
    return out


def _unwrap_agy_args(args: dict) -> dict:
    out = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            try:
                out[k] = json.loads(v)
                continue
            except json.JSONDecodeError:
                pass
        out[k] = v
    return out


def _extract_agy_user_text(text: str) -> str:
    start = text.find("<USER_REQUEST>\n")
    end = text.find("\n</USER_REQUEST>")
    if start != -1 and end != -1 and end > start:
        return text[start + len("<USER_REQUEST>\n"):end]
    return text


def parse_agy_session(transcript: Path, workspace_map: Optional[dict[str, str]] = None) -> tuple[str, str, list[Record]]:
    """Return (session_id, cwd, records) for an Antigravity transcript.jsonl."""
    # <appDataDir>/brain/<uuid>/.system_generated/logs/transcript.jsonl
    sid = transcript.parent.parent.parent.name
    cwd = (workspace_map or {}).get(sid, "")
    records: list[Record] = []
    with transcript.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            stype, ts = obj.get("type"), obj.get("created_at")
            if stype == "USER_INPUT":
                text = _extract_agy_user_text(obj.get("content") or "")
                if text:
                    records.append(Record(role="user", timestamp=ts, content=text))
            elif stype == "PLANNER_RESPONSE":
                text = obj.get("content") or ""
                if text:
                    records.append(Record(role="assistant", timestamp=ts, content=text))
                for tc in obj.get("tool_calls") or []:
                    if isinstance(tc, dict):
                        args = _unwrap_agy_args(tc.get("args") or {})
                        records.append(Record(
                            role="tool_use",
                            timestamp=ts,
                            content=f"[tool_use:{tc.get('name', '')}] {json.dumps(args, ensure_ascii=False)}",
                        ))
            elif stype == "GENERIC":
                text = obj.get("content") or ""
                if text:
                    records.append(Record(role="tool_result", timestamp=ts, content=f"[tool_result] {text}"))
    return sid, cwd, records
