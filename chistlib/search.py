"""FTS5 search over indexed messages."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

from chistlib import db


@dataclass
class Hit:
    session_id: str
    project: str
    started_at: Optional[str]
    role: str
    seq: int
    snippet: str
    rank: float


def _build_query(query: str) -> str:
    """FTS5 MATCH expression. Quote each token to avoid syntax errors on
    user input that contains FTS operators."""
    tokens = [t for t in query.split() if t]
    if not tokens:
        return '""'
    return " ".join(f'"{t.replace(chr(34), "")}"' for t in tokens)


def is_index_stale(db_path: Path, projects_root: Path) -> int:
    """Return count of JSONL files with mtime > last_incremental_at."""
    if not db_path.exists() or not projects_root.exists():
        return 0
    with db.connect(db_path) as con:
        row = con.execute(
            "SELECT value FROM index_meta WHERE key='last_incremental_at'"
        ).fetchone()
    if row is None:
        return 0
    try:
        last = float(row["value"])
    except (TypeError, ValueError):
        return 0
    n = 0
    for jsonl in projects_root.glob("*/*.jsonl"):
        try:
            if jsonl.stat().st_mtime > last:
                n += 1
        except OSError:
            continue
    return n


def search(
    db_path: Path,
    query: str,
    project: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = 20,
) -> list[Hit]:
    if not db_path.exists():
        return []
    fts_q = _build_query(query)

    sql = """
    SELECT
        s.session_id   AS session_id,
        s.project      AS project,
        s.started_at   AS started_at,
        m.role         AS role,
        m.seq          AS seq,
        snippet(messages_fts, 0, '**', '**', '...', 12) AS snippet,
        bm25(messages_fts) AS rank
    FROM messages_fts
    JOIN messages m ON m.msg_id = messages_fts.rowid
    JOIN sessions s ON s.session_id = m.session_id
    WHERE messages_fts MATCH ?
    """
    params: list = [fts_q]
    if project:
        sql += " AND s.project LIKE ?"
        params.append(f"%{project}%")
    if since:
        sql += " AND (s.started_at >= ? OR s.started_at IS NULL)"
        params.append(since)
    if until:
        sql += " AND (s.started_at <= ? OR s.started_at IS NULL)"
        params.append(until)
    if role:
        sql += " AND m.role = ?"
        params.append(role)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    with db.connect(db_path) as con:
        rows = con.execute(sql, params).fetchall()

    return [
        Hit(
            session_id=r["session_id"],
            project=r["project"],
            started_at=r["started_at"],
            role=r["role"],
            seq=r["seq"],
            snippet=r["snippet"],
            rank=r["rank"],
        )
        for r in rows
    ]


def format_human(hits: Iterable[Hit]) -> str:
    lines = []
    for h in hits:
        date = (h.started_at or "")[:16].replace("T", " ")
        sid = h.session_id[:8]
        lines.append(f"{sid}  {h.project}  {date}  {h.snippet}")
    return "\n".join(lines)


def format_json(hits: Iterable[Hit]) -> str:
    return json.dumps([asdict(h) for h in hits], ensure_ascii=False)
