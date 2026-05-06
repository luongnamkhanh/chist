"""SessionStart banner: most recent session for current project."""
from __future__ import annotations
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from chistlib import db


def _humanize(iso: Optional[str]) -> str:
    if not iso:
        return "unknown time"
    try:
        clean = iso.rstrip("Z")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return iso
    delta = time.time() - dt.timestamp()
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)} minute(s) ago"
    if delta < 86400:
        return f"{int(delta // 3600)} hour(s) ago"
    return f"{int(delta // 86400)} day(s) ago"


def render(db_path: Path, project: str) -> str:
    if not db_path.exists():
        return ""
    with db.connect(db_path) as con:
        row = con.execute(
            "SELECT session_id, started_at, msg_count FROM sessions "
            "WHERE project = ? ORDER BY started_at DESC LIMIT 1",
            (project,),
        ).fetchone()
    if row is None:
        return ""
    sid = row["session_id"]
    when = _humanize(row["started_at"])
    return (
        f"[claude-history] Most recent session in this project: {sid[:8]} "
        f"({when}, {row['msg_count']} messages)\n"
        f"                 Resume with: /history-resume {sid[:8]}"
    )
