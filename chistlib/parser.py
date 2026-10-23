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
