"""Programmatic JSONL fixture builders."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable


def write_jsonl(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def user_msg(text: str, ts: str = "2026-05-06T10:00:00.000Z") -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        "uuid": f"u-{abs(hash(text)) % 10**8}",
    }


def assistant_msg(text: str, ts: str = "2026-05-06T10:00:01.000Z") -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        "uuid": f"a-{abs(hash(text)) % 10**8}",
    }


def tool_use_msg(tool: str, input_obj: dict, ts: str = "2026-05-06T10:00:02.000Z") -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": tool, "input": input_obj, "id": "tu-1"}],
        },
        "uuid": f"tu-{abs(hash(tool + json.dumps(input_obj, sort_keys=True))) % 10**8}",
    }


def tool_result_msg(text: str, ts: str = "2026-05-06T10:00:03.000Z") -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "content": text, "tool_use_id": "tu-1"}],
        },
        "uuid": f"tr-{abs(hash(text)) % 10**8}",
    }


def malformed_line() -> str:
    return "{this is not valid json"


def sample_session_records() -> list[dict]:
    return [
        user_msg("hello"),
        assistant_msg("hi - how can I help?"),
        tool_use_msg("Read", {"file_path": "/tmp/foo.txt"}),
        tool_result_msg("file contents"),
        user_msg("ok thanks"),
        assistant_msg("Decision: going with option B."),
    ]
