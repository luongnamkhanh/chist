"""Render a session as Markdown."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from chistlib import db, list_show


def _format_msg(m) -> str:
    ts = (m["timestamp"] or "")[:19].replace("T", " ")
    role = m["role"]
    body = m["content"] or ""
    if role == "tool_use":
        head = f"### Tool use ({ts})"
    elif role == "tool_result":
        head = f"### Tool result ({ts})"
    elif role == "assistant":
        head = f"## Assistant ({ts})"
    else:
        head = f"## User ({ts})"
    return f"{head}\n\n{body}\n"


def export_session(db_path: Path, prefix: str, since_message: Optional[int] = None) -> str:
    if not db_path.exists():
        raise ValueError("index not built; run 'chist index'")
    with db.connect(db_path) as con:
        sid = list_show.resolve_session_prefix(con, prefix)
        sess = con.execute(
            "SELECT * FROM sessions WHERE session_id=?", (sid,)
        ).fetchone()
        sql = "SELECT * FROM messages WHERE session_id=?"
        params: list = [sid]
        if since_message is not None:
            sql += " AND seq >= ?"
            params.append(since_message)
        sql += " ORDER BY seq ASC"
        msgs = con.execute(sql, params).fetchall()

    started = (sess["started_at"] or "")[:16].replace("T", " ")
    ended = (sess["ended_at"] or "")[:16].replace("T", " ")
    parts = [
        f"# Session {sess['session_id']} - {started[:10]} ({sess['project']})",
        "",
        f"**Started:** {started}",
        f"**Ended:** {ended}",
        f"**Messages:** {sess['msg_count']}",
        "",
        "---",
        "",
    ]
    for m in msgs:
        parts.append(_format_msg(m))
    return "\n".join(parts)
