"""Resume a session: distilled summary or full transcript."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from chistlib import db, distill, export, list_show, parser


def _last_session_id(con, project: Optional[str]) -> Optional[str]:
    sql = "SELECT session_id FROM sessions WHERE 1=1"
    params: list = []
    if project:
        sql += " AND project LIKE ?"
        params.append(f"%{project}%")
    sql += " ORDER BY started_at DESC LIMIT 1"
    row = con.execute(sql, params).fetchone()
    return row["session_id"] if row else None


def resume(
    db_path: Path,
    prefix: Optional[str] = None,
    last: bool = False,
    project: Optional[str] = None,
    full: bool = False,
) -> str:
    if not db_path.exists():
        raise ValueError("index not built; run 'chist index'")
    with db.connect(db_path) as con:
        if last:
            sid = _last_session_id(con, project)
            if sid is None:
                raise ValueError("no sessions found")
        else:
            if not prefix:
                raise ValueError("either provide a prefix or use --last")
            sid = list_show.resolve_session_prefix(con, prefix)
        sess = con.execute(
            "SELECT * FROM sessions WHERE session_id=?", (sid,)
        ).fetchone()

    if full:
        return export.export_session(db_path, sid)

    with db.connect(db_path) as con:
        rows = con.execute(
            "SELECT role, timestamp, content FROM messages WHERE session_id=? ORDER BY seq",
            (sid,),
        ).fetchall()
    records = [parser.Record(role=r["role"], timestamp=r["timestamp"], content=r["content"]) for r in rows]
    d = distill.extract(records)
    return distill.render_markdown(d, dict(sess))
