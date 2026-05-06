# Claude History (`chist`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `chist`, a Python 3 stdlib CLI plus Claude Code slash commands, skill, and hooks that index, search, resume, and export Claude Code session transcripts.

**Architecture:** A SQLite FTS5 index at `~/.claude/history.db` mirrors raw JSONL transcripts under `~/.claude/projects/`. The `chist` CLI (Python 3 stdlib only) handles index, search, list, show, export, resume, banner, prune, vacuum. Three slash commands and one auto-trigger skill shell out to the CLI from inside Claude Code. Two hooks (`SessionEnd`, `SessionStart`) keep the index fresh and surface prior context.

**Tech Stack:** Python 3 stdlib (`sqlite3`, `json`, `argparse`, `pathlib`, `gzip`, `unittest`); SQLite FTS5; bash slash commands; Claude Code hooks.

**Spec:** `~/tools/claude-history/docs/specs/2026-05-06-design.md`

---

## File Structure

```
~/tools/claude-history/
  chist                            # entrypoint shim (calls chistlib.cli:main)
  chistlib/
    __init__.py                    # version constant
    paths.py                       # locate ~/.claude/projects/, history.db, archive/, log
    db.py                          # schema, migrations, connection helper
    parser.py                      # JSONL line -> normalized record
    indexer.py                     # walk projects, upsert sessions+messages
    search.py                      # FTS5 query with filters
    list_show.py                   # list + show subcommands
    export.py                      # session -> Markdown
    distill.py                     # heuristic summary extraction
    resume.py                      # full or distilled, --last support
    banner.py                      # one-line cwd-project banner
    archive.py                     # gzip+mark archived; rehydrate
    cli.py                         # argparse dispatcher (top-level main)
  tests/
    __init__.py
    fixtures.py                    # synthetic JSONL builders (programmatic)
    test_parser.py
    test_indexer.py
    test_search.py
    test_list_show.py
    test_export.py
    test_distill.py
    test_resume.py
    test_banner.py
    test_archive.py
  docs/
    specs/2026-05-06-design.md     # already written
    plans/2026-05-06-claude-history.md  # this file
  README.md
  pyproject.toml                   # optional editable install
  .gitignore
```

**Per-task scope:** each task creates or modifies a small, related set of files. After each task, all tests still pass and the repo is in a coherent state.

---

## Task 1: Repo Scaffolding, Paths, DB Schema

**Files:**
- Create: `~/tools/claude-history/.gitignore`
- Create: `~/tools/claude-history/pyproject.toml`
- Create: `~/tools/claude-history/chistlib/__init__.py`
- Create: `~/tools/claude-history/chistlib/paths.py`
- Create: `~/tools/claude-history/chistlib/db.py`
- Create: `~/tools/claude-history/chist`
- Create: `~/tools/claude-history/tests/__init__.py`
- Create: `~/tools/claude-history/tests/test_db.py`

- [ ] **Step 1.1: Write `.gitignore`**

```
__pycache__/
*.pyc
*.pyo
*.egg-info/
.pytest_cache/
.coverage
*.db
*.db-journal
.venv/
.idea/
.vscode/
```

- [ ] **Step 1.2: Write `pyproject.toml`**

```toml
[project]
name = "chist"
version = "0.1.0"
description = "Claude Code history search, resume, export"
requires-python = ">=3.9"
dependencies = []

[project.scripts]
chist = "chistlib.cli:main"

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["chistlib*"]
exclude = ["tests*"]
```

- [ ] **Step 1.3: Write `chistlib/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 1.4: Write `chistlib/paths.py`**

```python
"""Locate Claude Code data directories and chist artifacts."""
from __future__ import annotations
import os
from pathlib import Path


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))


def projects_dir() -> Path:
    return claude_home() / "projects"


def db_path() -> Path:
    return claude_home() / "history.db"


def archive_dir() -> Path:
    return claude_home() / "archive"


def log_path() -> Path:
    return claude_home() / "history-index.log"


def cwd_project_name(cwd: Path | None = None) -> str:
    """Return Claude Code's sanitized cwd format: '/foo/bar' -> '-foo-bar'."""
    p = cwd if cwd is not None else Path.cwd()
    return str(p.resolve()).replace("/", "-")
```

- [ ] **Step 1.5: Write the failing test for `db.init_schema`**

`tests/test_db.py`:

```python
import sqlite3
import tempfile
import unittest
from pathlib import Path

from chistlib import db


class TestDb(unittest.TestCase):
    def test_init_schema_creates_all_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbp = Path(tmp) / "test.db"
            db.init_schema(dbp)
            con = sqlite3.connect(dbp)
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )}
            con.close()
            self.assertIn("sessions", tables)
            self.assertIn("messages", tables)
            self.assertIn("messages_fts", tables)
            self.assertIn("index_meta", tables)

    def test_init_schema_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbp = Path(tmp) / "test.db"
            db.init_schema(dbp)
            db.init_schema(dbp)  # second call must not raise

    def test_connect_returns_row_factory(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbp = Path(tmp) / "test.db"
            db.init_schema(dbp)
            with db.connect(dbp) as con:
                row = con.execute("SELECT 1 AS x").fetchone()
                self.assertEqual(row["x"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 1.6: Run the test to verify it fails**

```
cd ~/tools/claude-history && python -m unittest tests.test_db -v
```

Expected: ModuleNotFoundError or AttributeError on `db.init_schema`.

- [ ] **Step 1.7: Implement `chistlib/db.py`**

```python
"""SQLite schema, migrations, connection helper."""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    project      TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    file_mtime   REAL NOT NULL,
    started_at   TEXT,
    ended_at     TEXT,
    msg_count    INTEGER NOT NULL DEFAULT 0,
    archived     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);

CREATE TABLE IF NOT EXISTS messages (
    msg_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    role         TEXT NOT NULL,
    timestamp    TEXT,
    content      TEXT NOT NULL,
    UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    role UNINDEXED,
    session_id UNINDEXED,
    seq UNINDEXED,
    content='messages',
    content_rowid='msg_id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, role, session_id, seq)
    VALUES (new.msg_id, new.content, new.role, new.session_id, new.seq);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, role, session_id, seq)
    VALUES ('delete', old.msg_id, old.content, old.role, old.session_id, old.seq);
END;

CREATE TABLE IF NOT EXISTS index_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def init_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(DDL)
        con.execute(
            "INSERT OR IGNORE INTO index_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        con.commit()
    finally:
        con.close()


@contextmanager
def connect(path: Path):
    con = sqlite3.connect(path, timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()
```

- [ ] **Step 1.8: Run the test to verify it passes**

```
cd ~/tools/claude-history && python -m unittest tests.test_db -v
```

Expected: 3 tests pass.

- [ ] **Step 1.9: Write `chist` entrypoint shim**

`~/tools/claude-history/chist`:

```python
#!/usr/bin/env python3
"""chist: Claude Code history manager."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chistlib.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:

```
chmod +x ~/tools/claude-history/chist
```

We will create `chistlib/cli.py` in Task 4. For now, an import error here is acceptable since we are not invoking the script yet.

- [ ] **Step 1.10: Commit**

```
cd ~/tools/claude-history && git add -A && git commit -m "feat: scaffold repo, paths, sqlite schema"
```

---

## Task 2: JSONL Parser

**Files:**
- Create: `~/tools/claude-history/chistlib/parser.py`
- Create: `~/tools/claude-history/tests/fixtures.py`
- Create: `~/tools/claude-history/tests/test_parser.py`

- [ ] **Step 2.1: Write fixture builder**

`tests/fixtures.py`:

```python
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
```

- [ ] **Step 2.2: Write the failing test for `parser.parse_line`**

`tests/test_parser.py`:

```python
import json
import unittest

from chistlib import parser
from tests import fixtures


class TestParseLine(unittest.TestCase):
    def test_parse_user_text(self):
        rec = parser.parse_line(json.dumps(fixtures.user_msg("hello world")))
        self.assertEqual(rec.role, "user")
        self.assertEqual(rec.content, "hello world")
        self.assertEqual(rec.timestamp, "2026-05-06T10:00:00.000Z")

    def test_parse_assistant_text(self):
        rec = parser.parse_line(json.dumps(fixtures.assistant_msg("hi there")))
        self.assertEqual(rec.role, "assistant")
        self.assertEqual(rec.content, "hi there")

    def test_parse_tool_use(self):
        rec = parser.parse_line(
            json.dumps(fixtures.tool_use_msg("Bash", {"command": "ls -la"}))
        )
        self.assertEqual(rec.role, "tool_use")
        self.assertIn("Bash", rec.content)
        self.assertIn("ls -la", rec.content)

    def test_parse_tool_result(self):
        rec = parser.parse_line(json.dumps(fixtures.tool_result_msg("output text")))
        self.assertEqual(rec.role, "tool_result")
        self.assertIn("output text", rec.content)

    def test_parse_malformed_returns_none(self):
        self.assertIsNone(parser.parse_line(fixtures.malformed_line()))

    def test_parse_empty_returns_none(self):
        self.assertIsNone(parser.parse_line(""))
        self.assertIsNone(parser.parse_line("   \n"))

    def test_parse_unicode(self):
        rec = parser.parse_line(json.dumps(fixtures.user_msg("xin chao the gioi")))
        self.assertEqual(rec.content, "xin chao the gioi")

    def test_parse_file_yields_records(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            jp = Path(tmp) / "s.jsonl"
            fixtures.write_jsonl(jp, fixtures.sample_session_records())
            recs = list(parser.parse_file(jp))
            self.assertEqual(len(recs), 6)
            self.assertEqual(recs[0].role, "user")
            self.assertEqual(recs[-1].role, "assistant")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2.3: Run the test to verify it fails**

```
cd ~/tools/claude-history && python -m unittest tests.test_parser -v
```

Expected: ModuleNotFoundError on `chistlib.parser`.

- [ ] **Step 2.4: Implement `chistlib/parser.py`**

```python
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
```

- [ ] **Step 2.5: Run tests to verify they pass**

```
cd ~/tools/claude-history && python -m unittest tests.test_parser -v
```

Expected: 8 tests pass.

- [ ] **Step 2.6: Commit**

```
cd ~/tools/claude-history && git add -A && git commit -m "feat: jsonl parser with tool_use/tool_result flattening"
```

---

## Task 3: Indexer (full + incremental)

**Files:**
- Create: `~/tools/claude-history/chistlib/indexer.py`
- Create: `~/tools/claude-history/tests/test_indexer.py`

- [ ] **Step 3.1: Write the failing test**

`tests/test_indexer.py`:

```python
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from chistlib import db, indexer
from tests import fixtures


def _make_session(root: Path, project: str, sid: str, records) -> Path:
    p = root / "projects" / project / f"{sid}.jsonl"
    fixtures.write_jsonl(p, records)
    return p


class TestIndexer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dbp = self.root / "history.db"
        db.init_schema(self.dbp)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_index_populates_sessions_and_messages(self):
        _make_session(self.root, "-proj-a", "sess1", fixtures.sample_session_records())
        result = indexer.index(self.dbp, self.root / "projects", incremental=False)
        self.assertEqual(result.sessions_indexed, 1)
        self.assertEqual(result.messages_indexed, 6)

        with db.connect(self.dbp) as con:
            sess = con.execute("SELECT * FROM sessions").fetchall()
            self.assertEqual(len(sess), 1)
            self.assertEqual(sess[0]["session_id"], "sess1")
            self.assertEqual(sess[0]["project"], "-proj-a")
            msgs = con.execute(
                "SELECT * FROM messages WHERE session_id='sess1' ORDER BY seq"
            ).fetchall()
            self.assertEqual(len(msgs), 6)
            self.assertEqual(msgs[0]["seq"], 0)

    def test_incremental_skips_unchanged(self):
        _make_session(self.root, "-proj-a", "sess1", fixtures.sample_session_records())
        indexer.index(self.dbp, self.root / "projects", incremental=False)
        result2 = indexer.index(self.dbp, self.root / "projects", incremental=True)
        self.assertEqual(result2.sessions_indexed, 0)

    def test_incremental_picks_up_modified_file(self):
        sid = "sess1"
        path = _make_session(self.root, "-proj-a", sid, fixtures.sample_session_records())
        indexer.index(self.dbp, self.root / "projects", incremental=False)

        # Append two more messages and bump mtime.
        with path.open("a", encoding="utf-8") as f:
            import json
            f.write(json.dumps(fixtures.user_msg("follow up")) + "\n")
            f.write(json.dumps(fixtures.assistant_msg("ack")) + "\n")
        future = time.time() + 10
        import os
        os.utime(path, (future, future))

        result = indexer.index(self.dbp, self.root / "projects", incremental=True)
        self.assertEqual(result.sessions_indexed, 1)
        with db.connect(self.dbp) as con:
            n = con.execute(
                "SELECT msg_count FROM sessions WHERE session_id=?", (sid,)
            ).fetchone()["msg_count"]
            self.assertEqual(n, 8)

    def test_index_is_idempotent(self):
        _make_session(self.root, "-proj-a", "sess1", fixtures.sample_session_records())
        indexer.index(self.dbp, self.root / "projects", incremental=False)
        indexer.index(self.dbp, self.root / "projects", incremental=False)
        with db.connect(self.dbp) as con:
            n = con.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
            self.assertEqual(n, 6)

    def test_fts_is_populated(self):
        _make_session(self.root, "-proj-a", "sess1", fixtures.sample_session_records())
        indexer.index(self.dbp, self.root / "projects", incremental=False)
        with db.connect(self.dbp) as con:
            hits = con.execute(
                "SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?",
                ("Decision",),
            ).fetchall()
            self.assertGreaterEqual(len(hits), 1)

    def test_malformed_line_is_skipped_not_fatal(self):
        path = _make_session(
            self.root, "-proj-a", "sess1", fixtures.sample_session_records()
        )
        with path.open("a", encoding="utf-8") as f:
            f.write("{not json\n")
            f.write('{"type":"user","message":{"role":"user","content":[{"type":"text","text":"after garbage"}]},"timestamp":"2026-05-06T11:00:00Z"}\n')
        import os, time as _t
        future = _t.time() + 10
        os.utime(path, (future, future))
        result = indexer.index(self.dbp, self.root / "projects", incremental=True)
        self.assertEqual(result.sessions_indexed, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3.2: Run the test to verify it fails**

```
cd ~/tools/claude-history && python -m unittest tests.test_indexer -v
```

Expected: ModuleNotFoundError on `chistlib.indexer`.

- [ ] **Step 3.3: Implement `chistlib/indexer.py`**

```python
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
            mtime = jsonl.stat().st_mtime
            if incremental and sid in prior and mtime <= prior[sid]:
                sessions_skipped += 1
                continue
            try:
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
```

- [ ] **Step 3.4: Run tests to verify they pass**

```
cd ~/tools/claude-history && python -m unittest tests.test_indexer -v
```

Expected: 6 tests pass.

- [ ] **Step 3.5: Commit**

```
cd ~/tools/claude-history && git add -A && git commit -m "feat: indexer with full and incremental modes"
```

---

## Task 4: CLI Dispatcher + `chist index`

**Files:**
- Create: `~/tools/claude-history/chistlib/cli.py`
- Create: `~/tools/claude-history/tests/test_cli_index.py`

- [ ] **Step 4.1: Write the failing test**

`tests/test_cli_index.py`:

```python
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chistlib import cli
from tests import fixtures


class TestCliIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()
        os.environ["CLAUDE_HOME"] = str(self.root)

        sess = self.root / "projects" / "-proj-a" / "sess1.jsonl"
        fixtures.write_jsonl(sess, fixtures.sample_session_records())

    def tearDown(self):
        os.environ.pop("CLAUDE_HOME", None)
        self.tmp.cleanup()

    def test_index_command_prints_summary(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["index"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("indexed", out.lower())
        self.assertIn("1 session", out.lower())

    def test_index_quiet_suppresses_output(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["index", "--quiet"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "")

    def test_index_stats(self):
        cli.main(["index"])
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["index", "--stats"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("sessions:", out.lower())
        self.assertIn("messages:", out.lower())

    def test_index_incremental_flag(self):
        cli.main(["index"])
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["index", "--incremental"])
        self.assertEqual(rc, 0)
        self.assertIn("0 session", buf.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4.2: Run the test to verify it fails**

```
cd ~/tools/claude-history && python -m unittest tests.test_cli_index -v
```

Expected: ModuleNotFoundError on `chistlib.cli`.

- [ ] **Step 4.3: Implement `chistlib/cli.py`**

```python
"""chist CLI dispatcher."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from chistlib import paths, indexer, db


def _cmd_index(args: argparse.Namespace) -> int:
    if args.stats:
        return _print_stats(args)
    res = indexer.index(
        db_path=paths.db_path(),
        projects_root=paths.projects_dir(),
        incremental=args.incremental,
    )
    if not args.quiet:
        print(
            f"indexed {res.sessions_indexed} session(s), "
            f"{res.messages_indexed} message(s), "
            f"skipped {res.sessions_skipped}, "
            f"elapsed {res.elapsed_seconds:.2f}s"
        )
    return 0


def _print_stats(args: argparse.Namespace) -> int:
    dbp = paths.db_path()
    if not dbp.exists():
        print("index not built yet; run 'chist index'")
        return 0
    with db.connect(dbp) as con:
        rows = con.execute(
            "SELECT COUNT(DISTINCT project) AS p, COUNT(*) AS s, "
            "COALESCE(SUM(msg_count),0) AS m FROM sessions"
        ).fetchone()
        meta = {
            r["key"]: r["value"]
            for r in con.execute("SELECT key, value FROM index_meta")
        }
    size_kb = dbp.stat().st_size // 1024
    print(f"projects: {rows['p']}")
    print(f"sessions: {rows['s']}")
    print(f"messages: {rows['m']}")
    print(f"db size: {size_kb} KB")
    print(f"last incremental: {meta.get('last_incremental_at', 'never')}")
    print(f"last full: {meta.get('last_full_index_at', 'never')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="chist", description="Claude Code history manager")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="build or refresh the index")
    pi.add_argument("--incremental", action="store_true", help="only re-index changed files")
    pi.add_argument("--quiet", action="store_true", help="suppress normal output")
    pi.add_argument("--stats", action="store_true", help="print index statistics and exit")
    pi.set_defaults(func=_cmd_index)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4.4: Run tests to verify they pass**

```
cd ~/tools/claude-history && python -m unittest tests.test_cli_index -v
```

Expected: 4 tests pass.

- [ ] **Step 4.5: Smoke test the entrypoint**

```
~/tools/claude-history/chist index --stats
```

Expected: prints stats (or "index not built yet" if `~/.claude/history.db` does not exist; either is fine, the script must not error).

- [ ] **Step 4.6: Commit**

```
cd ~/tools/claude-history && git add -A && git commit -m "feat: chist cli with index and index --stats"
```

---

## Task 5: Search

**Files:**
- Create: `~/tools/claude-history/chistlib/search.py`
- Modify: `~/tools/claude-history/chistlib/cli.py` (add `search` subparser)
- Create: `~/tools/claude-history/tests/test_search.py`

**Note:** This task also implements the stale-index warning required by the spec ("if any source JSONL has mtime > index_meta.last_incremental_at, print a single-line warning to stderr").

- [ ] **Step 5.1: Write the failing test**

`tests/test_search.py`:

```python
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chistlib import cli, indexer, paths
from tests import fixtures


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()
        os.environ["CLAUDE_HOME"] = str(self.root)

        fixtures.write_jsonl(
            self.root / "projects" / "-proj-a" / "sessA.jsonl",
            [
                fixtures.user_msg("looking for the kmdc foreign catalog"),
                fixtures.assistant_msg("kmdc is a Lakehouse Federation source"),
            ],
        )
        fixtures.write_jsonl(
            self.root / "projects" / "-proj-b" / "sessB.jsonl",
            [
                fixtures.user_msg("nothing related"),
                fixtures.assistant_msg("ok"),
            ],
        )
        indexer.index(paths.db_path(), paths.projects_dir(), incremental=False)

    def tearDown(self):
        os.environ.pop("CLAUDE_HOME", None)
        self.tmp.cleanup()

    def test_search_returns_relevant_session(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["search", "kmdc"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("sessA", out)
        self.assertNotIn("sessB", out)

    def test_search_filter_by_project(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["search", "ok", "--project", "-proj-b"])
        self.assertEqual(rc, 0)
        self.assertIn("sessB", buf.getvalue())
        self.assertNotIn("sessA", buf.getvalue())

    def test_search_role_filter(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["search", "kmdc", "--role", "assistant"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("sessA", out)

    def test_search_json_format(self):
        import json
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            cli.main(["search", "kmdc", "--format", "json"])
        rows = json.loads(buf.getvalue())
        self.assertIsInstance(rows, list)
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("session_id", rows[0])
        self.assertIn("snippet", rows[0])

    def test_stale_index_emits_warning(self):
        # Touch the on-disk JSONL so its mtime is newer than the last index run
        import time as _t, os as _os
        sess = self.root / "projects" / "-proj-a" / "sessA.jsonl"
        future = _t.time() + 60
        _os.utime(sess, (future, future))
        err = io.StringIO()
        with patch("sys.stderr", err), patch("sys.stdout", io.StringIO()):
            cli.main(["search", "kmdc"])
        self.assertIn("stale", err.getvalue().lower())

    def test_search_limit(self):
        # Add many matches
        for i in range(20):
            fixtures.write_jsonl(
                self.root / "projects" / "-proj-c" / f"s{i}.jsonl",
                [fixtures.user_msg(f"kmdc match {i}")],
            )
        indexer.index(paths.db_path(), paths.projects_dir(), incremental=False)
        import json
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            cli.main(["search", "kmdc", "--limit", "3", "--format", "json"])
        rows = json.loads(buf.getvalue())
        self.assertLessEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5.2: Run the test to verify it fails**

```
cd ~/tools/claude-history && python -m unittest tests.test_search -v
```

Expected: AttributeError or argparse error since `search` subcommand does not exist.

- [ ] **Step 5.3: Implement `chistlib/search.py`**

```python
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
        if jsonl.stat().st_mtime > last:
            n += 1
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
```

- [ ] **Step 5.4: Add `search` subcommand to `chistlib/cli.py`**

In `cli.py`, after the existing `pi.set_defaults(...)` line and before `return p`, add:

```python
    ps = sub.add_parser("search", help="search past sessions")
    ps.add_argument("query", help="search terms")
    ps.add_argument("--project", default=None)
    ps.add_argument("--since", default=None, help="ISO date or datetime")
    ps.add_argument("--until", default=None)
    ps.add_argument("--role", choices=["user", "assistant", "tool_use", "tool_result"], default=None)
    ps.add_argument("--limit", type=int, default=20)
    ps.add_argument("--format", choices=["human", "json"], default="human")
    ps.set_defaults(func=_cmd_search)
```

And add the handler near `_cmd_index`:

```python
def _cmd_search(args: argparse.Namespace) -> int:
    from chistlib import search as searchmod
    stale = searchmod.is_index_stale(paths.db_path(), paths.projects_dir())
    if stale > 0:
        print(
            f"[chist] index stale by {stale} file(s); run 'chist index --incremental'",
            file=sys.stderr,
        )
    hits = searchmod.search(
        db_path=paths.db_path(),
        query=args.query,
        project=args.project,
        since=args.since,
        until=args.until,
        role=args.role,
        limit=args.limit,
    )
    if args.format == "json":
        print(searchmod.format_json(hits))
    else:
        print(searchmod.format_human(hits))
    return 0
```

- [ ] **Step 5.5: Run tests to verify they pass**

```
cd ~/tools/claude-history && python -m unittest tests.test_search -v
```

Expected: 6 tests pass.

- [ ] **Step 5.6: Commit**

```
cd ~/tools/claude-history && git add -A && git commit -m "feat: chist search with project/date/role filters and json output"
```

---

## Task 6: List + Show

**Files:**
- Create: `~/tools/claude-history/chistlib/list_show.py`
- Modify: `~/tools/claude-history/chistlib/cli.py` (add `list`, `show` subparsers)
- Create: `~/tools/claude-history/tests/test_list_show.py`

- [ ] **Step 6.1: Write the failing test**

`tests/test_list_show.py`:

```python
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chistlib import cli, indexer, paths
from tests import fixtures


class TestListShow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()
        os.environ["CLAUDE_HOME"] = str(self.root)
        for sid in ("aaaa1111", "aaaa2222", "bbbb1111"):
            fixtures.write_jsonl(
                self.root / "projects" / "-proj-a" / f"{sid}.jsonl",
                fixtures.sample_session_records(),
            )
        indexer.index(paths.db_path(), paths.projects_dir(), incremental=False)

    def tearDown(self):
        os.environ.pop("CLAUDE_HOME", None)
        self.tmp.cleanup()

    def test_list_prints_all_sessions(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["list"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        for sid in ("aaaa1111", "aaaa2222", "bbbb1111"):
            self.assertIn(sid[:8], out)

    def test_show_with_unique_prefix(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["show", "bbbb"])
        self.assertEqual(rc, 0)
        self.assertIn("bbbb1111", buf.getvalue())

    def test_show_with_ambiguous_prefix_errors(self):
        buf = io.StringIO()
        err = io.StringIO()
        with patch("sys.stdout", buf), patch("sys.stderr", err):
            rc = cli.main(["show", "aaaa"])
        self.assertEqual(rc, 1)
        self.assertIn("ambiguous", err.getvalue().lower())

    def test_show_tail(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["show", "bbbb", "--tail", "2"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Decision", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6.2: Run the test to verify it fails**

```
cd ~/tools/claude-history && python -m unittest tests.test_list_show -v
```

Expected: argparse error, no `list`/`show` subcommand.

- [ ] **Step 6.3: Implement `chistlib/list_show.py`**

```python
"""List and show subcommands."""
from __future__ import annotations
import json
import sys
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
```

- [ ] **Step 6.4: Wire `list` and `show` into `cli.py`**

In `chistlib/cli.py`, add to `build_parser` (after `search`):

```python
    pl = sub.add_parser("list", help="list sessions")
    pl.add_argument("--project", default=None)
    pl.add_argument("--since", default=None)
    pl.add_argument("--limit", type=int, default=50)
    pl.add_argument("--format", choices=["human", "json"], default="human")
    pl.set_defaults(func=_cmd_list)

    psh = sub.add_parser("show", help="show a session by id or prefix")
    psh.add_argument("prefix")
    psh.add_argument("--head", type=int, default=None)
    psh.add_argument("--tail", type=int, default=None)
    psh.set_defaults(func=_cmd_show)
```

Add handlers near the others:

```python
def _cmd_list(args: argparse.Namespace) -> int:
    from chistlib import list_show
    rows = list_show.list_sessions(
        paths.db_path(), project=args.project, since=args.since, limit=args.limit
    )
    if args.format == "json":
        import json as _json
        print(_json.dumps(rows, ensure_ascii=False))
    else:
        print(list_show.format_list_human(rows))
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    from chistlib import list_show
    try:
        out = list_show.show_session(
            paths.db_path(), args.prefix, head=args.head, tail=args.tail
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(out)
    return 0
```

- [ ] **Step 6.5: Run tests to verify they pass**

```
cd ~/tools/claude-history && python -m unittest tests.test_list_show -v
```

Expected: 4 tests pass.

- [ ] **Step 6.6: Commit**

```
cd ~/tools/claude-history && git add -A && git commit -m "feat: chist list and show with prefix matching"
```

---

## Task 7: Export

**Files:**
- Create: `~/tools/claude-history/chistlib/export.py`
- Modify: `~/tools/claude-history/chistlib/cli.py` (add `export` subparser)
- Create: `~/tools/claude-history/tests/test_export.py`

- [ ] **Step 7.1: Write the failing test**

`tests/test_export.py`:

```python
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chistlib import cli, indexer, paths
from tests import fixtures


class TestExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()
        os.environ["CLAUDE_HOME"] = str(self.root)
        fixtures.write_jsonl(
            self.root / "projects" / "-proj-a" / "exportme.jsonl",
            fixtures.sample_session_records(),
        )
        indexer.index(paths.db_path(), paths.projects_dir(), incremental=False)

    def tearDown(self):
        os.environ.pop("CLAUDE_HOME", None)
        self.tmp.cleanup()

    def test_export_to_stdout(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["export", "exportme"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("# Session", out)
        self.assertIn("Decision", out)
        self.assertIn("## User", out)
        self.assertIn("## Assistant", out)

    def test_export_to_file(self):
        outp = self.root / "out.md"
        rc = cli.main(["export", "exportme", "-o", str(outp)])
        self.assertEqual(rc, 0)
        text = outp.read_text(encoding="utf-8")
        self.assertIn("# Session", text)

    def test_export_since_message(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["export", "exportme", "--since-message", "4"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Decision", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 7.2: Run the test to verify it fails**

```
cd ~/tools/claude-history && python -m unittest tests.test_export -v
```

Expected: argparse error.

- [ ] **Step 7.3: Implement `chistlib/export.py`**

```python
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
```

- [ ] **Step 7.4: Wire `export` into `cli.py`**

In `build_parser`:

```python
    pe = sub.add_parser("export", help="export a session to Markdown")
    pe.add_argument("prefix")
    pe.add_argument("-o", "--output", default=None)
    pe.add_argument("--since-message", type=int, default=None)
    pe.set_defaults(func=_cmd_export)
```

Handler:

```python
def _cmd_export(args: argparse.Namespace) -> int:
    from chistlib import export as exportmod
    try:
        text = exportmod.export_session(
            paths.db_path(), args.prefix, since_message=args.since_message
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0
```

- [ ] **Step 7.5: Run tests to verify they pass**

```
cd ~/tools/claude-history && python -m unittest tests.test_export -v
```

Expected: 3 tests pass.

- [ ] **Step 7.6: Commit**

```
cd ~/tools/claude-history && git add -A && git commit -m "feat: chist export to markdown with --since-message"
```

---

## Task 8: Distill + Resume

**Files:**
- Create: `~/tools/claude-history/chistlib/distill.py`
- Create: `~/tools/claude-history/chistlib/resume.py`
- Modify: `~/tools/claude-history/chistlib/cli.py` (add `resume` subparser)
- Create: `~/tools/claude-history/tests/test_distill.py`
- Create: `~/tools/claude-history/tests/test_resume.py`

- [ ] **Step 8.1: Write the failing distill test**

`tests/test_distill.py`:

```python
import json
import unittest

from chistlib import distill, parser


def _records(*items):
    return list(items)


class TestDistill(unittest.TestCase):
    def test_extract_decisions(self):
        recs = [
            parser.Record(role="user", timestamp=None, content="should we use B?"),
            parser.Record(role="assistant", timestamp=None,
                          content="Decision: going with option B."),
        ]
        d = distill.extract(recs)
        self.assertTrue(any("B" in s for s in d.decisions))

    def test_extract_files_touched_from_tool_use(self):
        tu = json.dumps({"file_path": "/tmp/a.txt"}, sort_keys=True)
        recs = [
            parser.Record(role="tool_use", timestamp=None,
                          content=f"[tool_use:Read] {tu}"),
            parser.Record(role="tool_use", timestamp=None,
                          content=f"[tool_use:Read] {tu}"),
            parser.Record(role="tool_use", timestamp=None,
                          content="[tool_use:Edit] " +
                                  json.dumps({"file_path": "/tmp/b.txt"})),
        ]
        d = distill.extract(recs)
        files = {f["path"]: f for f in d.files_touched}
        self.assertEqual(files["/tmp/a.txt"]["count"], 2)
        self.assertEqual(files["/tmp/b.txt"]["count"], 1)

    def test_extract_commands_from_bash(self):
        recs = [
            parser.Record(role="tool_use", timestamp=None,
                          content="[tool_use:Bash] " +
                                  json.dumps({"command": "ls -la"})),
            parser.Record(role="tool_use", timestamp=None,
                          content="[tool_use:Bash] " +
                                  json.dumps({"command": "ls -la"})),
            parser.Record(role="tool_use", timestamp=None,
                          content="[tool_use:Bash] " +
                                  json.dumps({"command": "git status"})),
        ]
        d = distill.extract(recs)
        cmds = {c["command"]: c["count"] for c in d.commands_run}
        self.assertEqual(cmds["ls -la"], 2)
        self.assertEqual(cmds["git status"], 1)

    def test_open_threads_returns_recent_user_messages(self):
        recs = [
            parser.Record(role="user", timestamp=None, content="q1"),
            parser.Record(role="assistant", timestamp=None, content="ack done"),
            parser.Record(role="user", timestamp=None, content="q2"),
            parser.Record(role="assistant", timestamp=None, content="thinking..."),
            parser.Record(role="user", timestamp=None, content="q3"),
        ]
        d = distill.extract(recs)
        self.assertIn("q3", d.open_threads)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 8.2: Run the test to verify it fails**

```
cd ~/tools/claude-history && python -m unittest tests.test_distill -v
```

Expected: ModuleNotFoundError on `chistlib.distill`.

- [ ] **Step 8.3: Implement `chistlib/distill.py`**

```python
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
```

- [ ] **Step 8.4: Run distill tests to verify they pass**

```
cd ~/tools/claude-history && python -m unittest tests.test_distill -v
```

Expected: 4 tests pass.

- [ ] **Step 8.5: Write the failing resume test**

`tests/test_resume.py`:

```python
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chistlib import cli, indexer, paths
from tests import fixtures


class TestResume(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()
        os.environ["CLAUDE_HOME"] = str(self.root)
        fixtures.write_jsonl(
            self.root / "projects" / "-proj-a" / "resumeme.jsonl",
            fixtures.sample_session_records(),
        )
        indexer.index(paths.db_path(), paths.projects_dir(), incremental=False)

    def tearDown(self):
        os.environ.pop("CLAUDE_HOME", None)
        self.tmp.cleanup()

    def test_resume_default_is_distilled(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["resume", "resumeme"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Open threads", out)
        self.assertIn("Decisions", out)

    def test_resume_full_emits_full_transcript(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["resume", "resumeme", "--full"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("## User", out)
        self.assertIn("## Assistant", out)

    def test_resume_last_with_project(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["resume", "--last", "--project", "-proj-a"])
        self.assertEqual(rc, 0)
        self.assertIn("resumeme"[:8], buf.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 8.6: Run the test to verify it fails**

```
cd ~/tools/claude-history && python -m unittest tests.test_resume -v
```

Expected: argparse error.

- [ ] **Step 8.7: Implement `chistlib/resume.py`**

```python
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
```

- [ ] **Step 8.8: Wire `resume` into `cli.py`**

```python
    pr = sub.add_parser("resume", help="resume a session (distilled by default)")
    pr.add_argument("prefix", nargs="?", default=None)
    pr.add_argument("--last", action="store_true")
    pr.add_argument("--project", default=None)
    pr.add_argument("--full", action="store_true")
    pr.set_defaults(func=_cmd_resume)
```

Handler:

```python
def _cmd_resume(args: argparse.Namespace) -> int:
    from chistlib import resume as resumemod
    try:
        text = resumemod.resume(
            paths.db_path(),
            prefix=args.prefix,
            last=args.last,
            project=args.project,
            full=args.full,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(text)
    return 0
```

- [ ] **Step 8.9: Run all resume tests to verify they pass**

```
cd ~/tools/claude-history && python -m unittest tests.test_resume tests.test_distill -v
```

Expected: 7 tests pass total.

- [ ] **Step 8.10: Commit**

```
cd ~/tools/claude-history && git add -A && git commit -m "feat: chist resume with distill heuristics and --full mode"
```

---

## Task 9: Banner

**Files:**
- Create: `~/tools/claude-history/chistlib/banner.py`
- Modify: `~/tools/claude-history/chistlib/cli.py` (add `banner` subparser)
- Create: `~/tools/claude-history/tests/test_banner.py`

- [ ] **Step 9.1: Write the failing test**

`tests/test_banner.py`:

```python
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chistlib import cli, indexer, paths
from tests import fixtures


class TestBanner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()
        os.environ["CLAUDE_HOME"] = str(self.root)

    def tearDown(self):
        os.environ.pop("CLAUDE_HOME", None)
        self.tmp.cleanup()

    def test_banner_empty_when_no_sessions(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["banner", "--project", "-proj-x"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "")

    def test_banner_prints_recent_session(self):
        fixtures.write_jsonl(
            self.root / "projects" / "-proj-a" / "abcd1234.jsonl",
            fixtures.sample_session_records(),
        )
        indexer.index(paths.db_path(), paths.projects_dir(), incremental=False)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["banner", "--project", "-proj-a"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("[claude-history]", out)
        self.assertIn("abcd1234", out)
        self.assertIn("/history-resume", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 9.2: Run the test to verify it fails**

```
cd ~/tools/claude-history && python -m unittest tests.test_banner -v
```

Expected: argparse error.

- [ ] **Step 9.3: Implement `chistlib/banner.py`**

```python
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
```

- [ ] **Step 9.4: Wire `banner` into `cli.py`**

```python
    pb = sub.add_parser("banner", help="print one-line cwd-project banner")
    pb.add_argument("--project", default=None)
    pb.add_argument("--cwd-project", action="store_true")
    pb.set_defaults(func=_cmd_banner)
```

Handler:

```python
def _cmd_banner(args: argparse.Namespace) -> int:
    from chistlib import banner as bannermod
    project = args.project
    if args.cwd_project or project is None:
        project = paths.cwd_project_name()
    text = bannermod.render(paths.db_path(), project)
    if text:
        print(text)
    return 0
```

- [ ] **Step 9.5: Run banner tests to verify they pass**

```
cd ~/tools/claude-history && python -m unittest tests.test_banner -v
```

Expected: 2 tests pass.

- [ ] **Step 9.6: Commit**

```
cd ~/tools/claude-history && git add -A && git commit -m "feat: chist banner for SessionStart hook"
```

---

## Task 10: Archive (Prune) + Vacuum

**Files:**
- Create: `~/tools/claude-history/chistlib/archive.py`
- Modify: `~/tools/claude-history/chistlib/cli.py` (add `prune` and `vacuum` subparsers)
- Create: `~/tools/claude-history/tests/test_archive.py`

- [ ] **Step 10.1: Write the failing test**

`tests/test_archive.py`:

```python
import gzip
import os
import tempfile
import time
import unittest
from pathlib import Path

from chistlib import archive, indexer, paths
from tests import fixtures


class TestArchive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()
        os.environ["CLAUDE_HOME"] = str(self.root)

        old = self.root / "projects" / "-proj-a" / "old.jsonl"
        fixtures.write_jsonl(old, fixtures.sample_session_records())
        ancient = time.time() - 365 * 86400
        os.utime(old, (ancient, ancient))

        recent = self.root / "projects" / "-proj-a" / "recent.jsonl"
        fixtures.write_jsonl(recent, fixtures.sample_session_records())

        indexer.index(paths.db_path(), paths.projects_dir(), incremental=False)

    def tearDown(self):
        os.environ.pop("CLAUDE_HOME", None)
        self.tmp.cleanup()

    def test_prune_archives_only_old_files(self):
        result = archive.prune(paths.db_path(), paths.archive_dir(),
                               paths.projects_dir(), older_than_days=180,
                               dry_run=False)
        self.assertEqual(result.archived, 1)
        # Old jsonl is gone, gz exists
        self.assertFalse((self.root / "projects" / "-proj-a" / "old.jsonl").exists())
        gzs = list((self.root / "archive").rglob("old.jsonl.gz"))
        self.assertEqual(len(gzs), 1)
        # Recent file untouched
        self.assertTrue((self.root / "projects" / "-proj-a" / "recent.jsonl").exists())

    def test_prune_dry_run_changes_nothing(self):
        result = archive.prune(paths.db_path(), paths.archive_dir(),
                               paths.projects_dir(), older_than_days=180,
                               dry_run=True)
        self.assertEqual(result.archived, 0)
        self.assertEqual(result.would_archive, 1)
        self.assertTrue((self.root / "projects" / "-proj-a" / "old.jsonl").exists())

    def test_archived_jsonl_is_recoverable(self):
        archive.prune(paths.db_path(), paths.archive_dir(),
                      paths.projects_dir(), older_than_days=180, dry_run=False)
        gz = next((self.root / "archive").rglob("*.gz"))
        with gzip.open(gz, "rt", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Decision", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 10.2: Run the test to verify it fails**

```
cd ~/tools/claude-history && python -m unittest tests.test_archive -v
```

Expected: ModuleNotFoundError on `chistlib.archive`.

- [ ] **Step 10.3: Implement `chistlib/archive.py`**

```python
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
    # VACUUM cannot run inside a transaction; open separately.
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        con.execute("VACUUM")
        con.commit()
    finally:
        con.close()
```

- [ ] **Step 10.4: Wire `prune` and `vacuum` into `cli.py`**

```python
    pp = sub.add_parser("prune", help="archive old JSONL files (gzip)")
    pp.add_argument("--older-than", required=True, help="duration like 180d, 12w, 1y")
    pp.add_argument("--dry-run", action="store_true")
    pp.set_defaults(func=_cmd_prune)

    pv = sub.add_parser("vacuum", help="rebuild FTS5 index and VACUUM the db")
    pv.set_defaults(func=_cmd_vacuum)
```

Handlers:

```python
def _parse_duration(s: str) -> int:
    s = s.strip().lower()
    units = {"d": 1, "w": 7, "y": 365}
    if not s or s[-1] not in units:
        raise ValueError(f"invalid duration '{s}'; use Nd, Nw, or Ny")
    n = int(s[:-1])
    return n * units[s[-1]]


def _cmd_prune(args: argparse.Namespace) -> int:
    from chistlib import archive as archivemod
    days = _parse_duration(args.older_than)
    res = archivemod.prune(
        db_path=paths.db_path(),
        archive_root=paths.archive_dir(),
        projects_root=paths.projects_dir(),
        older_than_days=days,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(f"would archive {res.would_archive} session(s)")
    else:
        print(f"archived {res.archived} session(s), freed {res.bytes_freed} bytes")
    return 0


def _cmd_vacuum(args: argparse.Namespace) -> int:
    from chistlib import archive as archivemod
    archivemod.vacuum(paths.db_path())
    print("vacuum complete")
    return 0
```

- [ ] **Step 10.5: Run archive tests to verify they pass**

```
cd ~/tools/claude-history && python -m unittest tests.test_archive -v
```

Expected: 3 tests pass.

- [ ] **Step 10.6: Run all tests for full regression**

```
cd ~/tools/claude-history && python -m unittest discover tests -v
```

Expected: all tests pass (35+).

- [ ] **Step 10.7: Commit**

```
cd ~/tools/claude-history && git add -A && git commit -m "feat: chist prune and vacuum"
```

---

## Task 11: README, PATH Install, Slash Commands, Skill

**Files:**
- Create: `~/tools/claude-history/README.md`
- Create: `~/.claude/commands/history-search.md`
- Create: `~/.claude/commands/history-resume.md`
- Create: `~/.claude/commands/history-export.md`
- Create: `~/.claude/skills/claude-history/SKILL.md`
- Symlink: `~/.local/bin/chist` -> `~/tools/claude-history/chist` (if `~/.local/bin` is on PATH)

- [ ] **Step 11.1: Write `README.md`**

```markdown
# chist - Claude Code history manager

`chist` indexes, searches, resumes, and exports Claude Code session transcripts (the JSONL files written under `~/.claude/projects/`).

## Install

```
git clone <repo> ~/tools/claude-history
ln -s ~/tools/claude-history/chist ~/.local/bin/chist
chist index           # initial full index of all existing sessions
```

Requires Python 3.9+. No third-party dependencies.

## Usage

```
chist index --incremental      # refresh index after sessions change
chist search "<query>"         # ranked full-text search
chist list                     # all sessions, newest first
chist show <id-prefix>         # session metadata + messages
chist export <id-prefix>       # session as Markdown
chist resume <id-prefix>       # distilled summary; --full for verbatim
chist resume --last            # most recent session in cwd's project
chist banner --cwd-project     # one-line "most recent session" banner
chist prune --older-than 180d  # archive old JSONL into gzip
chist vacuum                   # rebuild FTS5 + VACUUM
```

## Slash commands and skill

Three slash commands shell out to the CLI:

- `/history-search <query>`
- `/history-resume <id>`
- `/history-export <id>`

The `claude-history` skill auto-triggers on natural-language queries like "find that chat about X".

## Hooks

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionEnd": [{"matcher": "*", "hooks": [{"type": "command",
      "command": "chist index --incremental --quiet >> ~/.claude/history-index.log 2>&1 &"}]}],
    "SessionStart": [{"matcher": "*", "hooks": [{"type": "command",
      "command": "chist banner --cwd-project"}]}]
  }
}
```

## Tests

```
python -m unittest discover tests -v
```
```

- [ ] **Step 11.2: Symlink `chist` onto PATH**

```
ls ~/.local/bin/ 2>/dev/null || mkdir -p ~/.local/bin
ln -sf ~/tools/claude-history/chist ~/.local/bin/chist
which chist
```

Expected: `which chist` prints `/home/<user>/.local/bin/chist`. If `~/.local/bin` is not on PATH, add to `~/.zshrc`:

```
export PATH="$HOME/.local/bin:$PATH"
```

- [ ] **Step 11.3: Initial full index of real sessions**

```
chist index
chist index --stats
```

Expected: indexes 250+ existing sessions, prints stats with non-zero counts.

- [ ] **Step 11.4: Write `~/.claude/commands/history-search.md`**

```markdown
---
description: Search past Claude Code sessions by full-text query
---

Run the following bash command and present the top hits to the user as a numbered list.
On user confirmation, suggest using `/history-resume <id>` for the chosen session.

```
chist search "$ARGUMENTS" --project "$(basename "$(pwd)")" --limit 10 --format human
```
```

- [ ] **Step 11.5: Write `~/.claude/commands/history-resume.md`**

```markdown
---
description: Resume context from a past session by id (or prefix, or --last)
---

Run the following bash command. The output is a distilled Markdown summary of the past session
(or the full transcript if --full was passed). Read it as context for the current task.

```
chist resume $ARGUMENTS
```
```

- [ ] **Step 11.6: Write `~/.claude/commands/history-export.md`**

```markdown
---
description: Export a past session to Markdown under docs/history/
---

Run the following bash command and report the file path written.

```
mkdir -p docs/history && chist export $ARGUMENTS -o "docs/history/$(date +%Y-%m-%d)-$(echo $ARGUMENTS | head -c 8).md"
```
```

- [ ] **Step 11.7: Write `~/.claude/skills/claude-history/SKILL.md`**

```markdown
---
name: claude-history
description: Use when the user asks to find, recall, resume, summarize, or export a past Claude Code conversation. Triggers on phrases like "find that chat about X", "what did we decide about Y last week", "resume the session where we did Z", "show prior sessions on this project", "summarize last week's work". Auto-invokes the chist CLI.
---

# Claude History Skill

When the user asks to find or recall a past conversation:

1. Identify the search query and any filters (project, time range).
2. Default to the cwd's project: run
   `chist search "<query>" --project "$(basename "$(pwd)")" --limit 10 --format json`.
3. Parse the JSON; present a numbered list with date, project, and snippet.
4. Ask the user which session to resume or export.
5. On confirmation, run `chist resume <id>` for context, or `chist export <id>` for a saved file.
6. If the heuristic summary is insufficient, offer `chist resume <id> --full`.

Do NOT run `chist index` proactively; the SessionEnd hook keeps the index fresh.
```

- [ ] **Step 11.8: Smoke-test slash commands manually**

In a Claude Code session in any project:

1. `/history-search foreign catalog`  - confirm it lists matching sessions.
2. `/history-resume <some-prefix>`  - confirm it prints a distilled summary.
3. `/history-export <some-prefix>`  - confirm it writes a file under `docs/history/`.

Document any deviations and fix the slash command markdown if needed.

- [ ] **Step 11.9: Commit**

```
cd ~/tools/claude-history && git add README.md && git commit -m "docs: README with install + usage"
```

---

## Deferred to v2

- **Log self-rotation** (spec mentioned 1MB rotation in `chistlib/banner.py` and `indexer.py`). The hook command appends via shell redirect (`>> ~/.claude/history-index.log`), so the chistlib code does not write to the log directly. Users who need rotation can configure `logrotate(8)`. Self-rotating Python helper deferred until disk pressure shows up.
- **LLM-quality summaries** (`--llm` flag for `chist resume`).
- **Tagging/favoriting**, **cross-machine sync**, **web UI**, **token-cost estimation**.

---

## Task 12: Hooks Wiring + End-to-End Smoke Test

**Files:**
- Modify: `~/.claude/settings.json` (add SessionEnd + SessionStart hooks)

- [ ] **Step 12.1: Inspect current `~/.claude/settings.json`**

```
cat ~/.claude/settings.json 2>/dev/null || echo "no settings.json"
```

Note any existing `hooks` section.

- [ ] **Step 12.2: Add or merge hooks**

If `hooks` does not exist, write the full block. If `hooks.SessionEnd` or `hooks.SessionStart` arrays already exist, append our entries rather than replacing.

Target shape (using `update-config` skill is recommended for safe merge):

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "chist index --incremental --quiet >> ~/.claude/history-index.log 2>&1 &"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "chist banner --cwd-project"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 12.3: Verify hook syntax**

```
python -c "import json; json.load(open('$HOME/.claude/settings.json'))"
```

Expected: no output (valid JSON).

- [ ] **Step 12.4: End-to-end manual smoke test**

1. Start a new Claude Code session in `/workspace/databricks-account-infra/`.
2. Confirm the SessionStart banner appears (or empty if no prior session for that project).
3. Run a few user messages; end the session via `/clear` or quit.
4. Verify `~/.claude/history-index.log` shows a successful incremental run with no errors:

```
tail -n 20 ~/.claude/history-index.log
```

5. Re-open Claude Code; confirm the banner now references the just-ended session.

- [ ] **Step 12.5: Commit**

`~/tools/claude-history/` has no changes for this step. The settings.json change is on the user's machine; we do not version-control `~/.claude/settings.json` here. Document the hook block in `README.md` (already done in Task 11.1).

---

## Verification Checklist

Run before declaring done:

- [ ] `cd ~/tools/claude-history && python -m unittest discover tests -v` - all tests pass.
- [ ] `chist index --stats` - prints non-zero session and message counts after initial index.
- [ ] `chist search "foreign catalog"` - returns ranked matches in under 200 ms.
- [ ] `chist resume <prefix>` - prints distilled summary under 500 ms.
- [ ] `chist banner --cwd-project` - returns immediately (under 100 ms).
- [ ] SessionEnd hook fires after a real session and writes to `~/.claude/history-index.log`.
- [ ] SessionStart hook prints a banner when a prior session exists.
- [ ] All three slash commands work end-to-end inside a Claude Code session.
- [ ] Skill auto-triggers on at least 3 sample natural-language queries.
- [ ] `git log --oneline` in `~/tools/claude-history/` shows clean, scoped commits per task.
