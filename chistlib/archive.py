"""Prune old JSONL files into a gzipped archive while keeping the index intact."""
from __future__ import annotations
import gzip
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from chistlib import db


@dataclass
class PruneResult:
    archived: int
    would_archive: int
    bytes_freed: int


def prune(
    db_path: Path,
    archive_root: Path,
    projects_root: Path,
    older_than_days: int,
    dry_run: bool = False,
) -> PruneResult:
    cutoff = time.time() - older_than_days * 86400
    archived = 0
    would_archive = 0
    bytes_freed = 0

    if not projects_root.exists():
        return PruneResult(0, 0, 0)

    db.init_schema(db_path)

    for jsonl in projects_root.glob("*/*.jsonl"):
        if jsonl.stat().st_mtime > cutoff:
            continue

        if dry_run:
            would_archive += 1
            continue

        rel = jsonl.relative_to(projects_root)
        year = datetime.fromtimestamp(jsonl.stat().st_mtime).strftime("%Y")
        out = archive_root / year / rel.parent.name / (jsonl.name + ".gz")
        out.parent.mkdir(parents=True, exist_ok=True)
        with jsonl.open("rb") as src, gzip.open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)

        bytes_freed += jsonl.stat().st_size
        sid = jsonl.stem
        with db.connect(db_path) as con:
            con.execute(
                "UPDATE sessions SET archived=1, file_path=? WHERE session_id=?",
                (str(out), sid),
            )
        jsonl.unlink()
        archived += 1

    return PruneResult(archived=archived, would_archive=would_archive, bytes_freed=bytes_freed)


def vacuum(db_path: Path) -> None:
    if not db_path.exists():
        return
    with db.connect(db_path) as con:
        con.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        con.execute("VACUUM")
        con.commit()
    finally:
        con.close()
