"""List and show subcommands."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from chistlib import db


def resolve_session_prefix(con, prefix: str) -> str:
    """Return the unique session_id starting with prefix, or raise ValueError."""
    if len(prefix) >= 32:
        return prefix
    rows = con.execute(
        "SELECT session_id FROM sessions WHERE session_id LIKE ? LIMIT 5",
        (prefix + "%",),
    ).fetchall()
    if not rows:
        raise ValueError(f"no session matches prefix '{prefix}'")
    if len(rows) > 1:
        ids = ", ".join(r["session_id"][:12] for r in rows)
        raise ValueError(f"ambiguous prefix '{prefix}'; candidates: {ids}")
    return rows[0]["session_id"]


def list_sessions(
    db_path: Path,
    project: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    if not db_path.exists():
        return []
    sql = "SELECT session_id, project, started_at, ended_at, msg_count FROM sessions WHERE 1=1"
    params: list = []
    if project:
        sql += " AND project LIKE ?"
        params.append(f"%{project}%")
    if since:
        sql += " AND (started_at >= ? OR started_at IS NULL)"
        params.append(since)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    with db.connect(db_path) as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def format_list_human(rows: list[dict]) -> str:
    out = []
    for r in rows:
        sid = r["session_id"][:8]
        date = (r.get("started_at") or "")[:16].replace("T", " ")
        out.append(f"{sid}  {r['project']}  {date}  msgs={r['msg_count']}")
    return "\n".join(out)


def show_session(
    db_path: Path, prefix: str, head: Optional[int] = None, tail: Optional[int] = None
) -> str:
    if not db_path.exists():
        raise ValueError("index not built; run 'chist index'")
    with db.connect(db_path) as con:
        sid = resolve_session_prefix(con, prefix)
        sess = con.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (sid,)
        ).fetchone()
        if head is not None:
            msgs = con.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY seq ASC LIMIT ?",
                (sid, head),
            ).fetchall()
        elif tail is not None:
            msgs = con.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY seq DESC LIMIT ?",
                (sid, tail),
            ).fetchall()
            msgs = list(reversed(msgs))
        else:
            msgs = con.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY seq ASC",
                (sid,),
            ).fetchall()

    lines = [
        f"session: {sess['session_id']}",
        f"project: {sess['project']}",
        f"started: {sess['started_at']}",
        f"ended:   {sess['ended_at']}",
        f"msgs:    {sess['msg_count']}",
        f"file:    {sess['file_path']}",
        "---",
    ]
    for m in msgs:
        ts = (m["timestamp"] or "")[:19].replace("T", " ")
        head_line = f"[{ts}] {m['role']}"
        body = (m["content"] or "")
        if len(body) > 800:
            body = body[:800] + "..."
        lines.append(head_line)
        lines.append(body)
        lines.append("")
    return "\n".join(lines)
