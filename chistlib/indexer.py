"""Walk Claude Code projects directory and upsert into SQLite."""
from __future__ import annotations
import time
from dataclasses import dataclass
from pathlib import Path

from chistlib import db, parser


@dataclass
class IndexResult:
    sessions_indexed: int
    messages_indexed: int
    sessions_skipped: int
    elapsed_seconds: float


def _session_id_from_path(p: Path) -> str:
    return p.stem


def _project_from_path(p: Path, projects_root: Path) -> str:
    return p.relative_to(projects_root).parts[0]


def _upsert_session(con, session_id: str, project: str, file_path: Path,
                    file_mtime: float, records: list[parser.Record]) -> int:
    started = records[0].timestamp if records else None
    ended = records[-1].timestamp if records else None
    msg_count = len(records)

    con.execute(
        """INSERT INTO sessions(session_id, project, file_path, file_mtime,
                                started_at, ended_at, msg_count, archived)
           VALUES(?,?,?,?,?,?,?,0)
           ON CONFLICT(session_id) DO UPDATE SET
               project=excluded.project,
               file_path=excluded.file_path,
               file_mtime=excluded.file_mtime,
               started_at=excluded.started_at,
               ended_at=excluded.ended_at,
               msg_count=excluded.msg_count
        """,
        (session_id, project, str(file_path), file_mtime, started, ended, msg_count),
    )
    con.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    con.executemany(
        "INSERT INTO messages(session_id, seq, role, timestamp, content) VALUES(?,?,?,?,?)",
        [
            (session_id, i, r.role, r.timestamp, r.content)
            for i, r in enumerate(records)
        ],
    )
    return msg_count


def index(db_path: Path, projects_root: Path, incremental: bool = True) -> IndexResult:
    start = time.time()
    sessions_indexed = 0
    messages_indexed = 0
    sessions_skipped = 0

    if not projects_root.exists():
        return IndexResult(0, 0, 0, time.time() - start)

    db.init_schema(db_path)

    with db.connect(db_path) as con:
        prior = {
            r["session_id"]: r["file_mtime"]
            for r in con.execute("SELECT session_id, file_mtime FROM sessions")
        }

        for jsonl in projects_root.glob("*/*.jsonl"):
            sid = _session_id_from_path(jsonl)
            try:
                mtime = jsonl.stat().st_mtime
                if incremental and sid in prior and mtime <= prior[sid]:
                    sessions_skipped += 1
                    continue
                records = list(parser.parse_file(jsonl))
            except OSError:
                sessions_skipped += 1
                continue
            project = _project_from_path(jsonl, projects_root)
            n = _upsert_session(con, sid, project, jsonl, mtime, records)
            sessions_indexed += 1
            messages_indexed += n

        con.execute(
            "INSERT INTO index_meta(key,value) VALUES('last_incremental_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(time.time()),),
        )
        if not incremental:
            con.execute(
                "INSERT INTO index_meta(key,value) VALUES('last_full_index_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(time.time()),),
            )

    return IndexResult(sessions_indexed, messages_indexed, sessions_skipped, time.time() - start)
