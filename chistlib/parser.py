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
