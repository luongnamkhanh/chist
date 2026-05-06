"""Heuristic session summary."""
from __future__ import annotations
import json
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Iterable

from chistlib.parser import Record

DECISION_PREFIXES = (
    "Decision:", "Going with", "Picked", "Locked in", "Approved",
    "Final answer:", "We will use", "Chose",
)
ACK_TOKENS = ("done", "completed", "fixed", "resolved", "merged", "shipped")


@dataclass
class Distill:
    open_threads: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    files_touched: list[dict] = field(default_factory=list)
    commands_run: list[dict] = field(default_factory=list)
    last_assistant: str = ""


_TOOL_USE_RE = re.compile(r"^\[tool_use:(?P<name>[^\]]+)\]\s+(?P<rest>.*)$", re.DOTALL)


def _parse_tool_use(content: str) -> tuple[str, dict]:
    m = _TOOL_USE_RE.match(content or "")
    if not m:
        return ("", {})
    try:
        return (m.group("name"), json.loads(m.group("rest")))
    except json.JSONDecodeError:
        return (m.group("name"), {})


def extract(records: Iterable[Record]) -> Distill:
    records = list(records)
    d = Distill()

    for r in records:
        if r.role != "assistant":
            continue
        for line in (r.content or "").splitlines():
            line = line.strip()
            for p in DECISION_PREFIXES:
                if line.startswith(p):
                    d.decisions.append(line)
                    break

    file_counter: "OrderedDict[str, int]" = OrderedDict()
    cmd_counter: Counter[str] = Counter()
    for r in records:
        if r.role != "tool_use":
            continue
        name, payload = _parse_tool_use(r.content)
        if name in {"Read", "Edit", "Write", "NotebookEdit"}:
            fp = payload.get("file_path")
            if fp:
                file_counter[fp] = file_counter.get(fp, 0) + 1
        if name == "Bash":
            cmd = payload.get("command")
            if cmd:
                cmd_counter[cmd] += 1

    d.files_touched = [{"path": p, "count": c} for p, c in file_counter.items()]
    d.commands_run = [{"command": c, "count": n} for c, n in cmd_counter.most_common()]

    user_msgs = [r for r in records if r.role == "user"]
    open_threads: list[str] = []
    for u in reversed(user_msgs):
        idx = records.index(u)
        following = records[idx + 1:]
        following_assistants = [x for x in following if x.role == "assistant"]
        if not following_assistants:
            open_threads.insert(0, u.content)
            continue
        joined = " ".join(a.content.lower() for a in following_assistants)
        if not any(t in joined for t in ACK_TOKENS):
            open_threads.insert(0, u.content)
        if len(open_threads) >= 5:
            break
    d.open_threads = open_threads

    last_a = next((r for r in reversed(records) if r.role == "assistant"), None)
    d.last_assistant = (last_a.content or "")[:500] if last_a else ""

    return d


def render_markdown(d: Distill, sess_meta: dict) -> str:
    started = (sess_meta.get("started_at") or "")[:16].replace("T", " ")
    parts = [
        f"# Session {sess_meta['session_id']} - {started[:10]} ({sess_meta['project']})",
        "",
        "## Open threads",
    ]
    if d.open_threads:
        parts.extend(f"- {t}" for t in d.open_threads)
    else:
        parts.append("(none)")

    parts += ["", "## Decisions"]
    parts.extend(f"- {x}" for x in d.decisions) if d.decisions else parts.append("(none)")

    parts += ["", "## Files touched"]
    parts.extend(
        f"- {f['path']} (x{f['count']})" for f in d.files_touched
    ) if d.files_touched else parts.append("(none)")

    parts += ["", "## Commands run"]
    parts.extend(
        f"- {c['command']} (x{c['count']})" for c in d.commands_run
    ) if d.commands_run else parts.append("(none)")

    parts += ["", "## Last assistant message", "", d.last_assistant or "(none)"]
    return "\n".join(parts)
