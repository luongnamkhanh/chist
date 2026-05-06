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

    def test_full_reindex_removes_sessions_whose_files_were_deleted(self):
        keep = _make_session(self.root, "-proj-a", "keep", fixtures.sample_session_records())
        gone = _make_session(self.root, "-proj-a", "gone", fixtures.sample_session_records())
        indexer.index(self.dbp, self.root / "projects", incremental=False)
        gone.unlink()
        result = indexer.index(self.dbp, self.root / "projects", incremental=False)
        self.assertEqual(result.sessions_indexed, 1)
        with db.connect(self.dbp) as con:
            ids = {r["session_id"] for r in con.execute("SELECT session_id FROM sessions")}
            self.assertEqual(ids, {"keep"})
            n_msgs = con.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE session_id='gone'"
            ).fetchone()["c"]
            self.assertEqual(n_msgs, 0)

    def test_incremental_reindex_does_not_remove_deleted_files(self):
        _make_session(self.root, "-proj-a", "keep", fixtures.sample_session_records())
        gone = _make_session(self.root, "-proj-a", "gone", fixtures.sample_session_records())
        indexer.index(self.dbp, self.root / "projects", incremental=False)
        gone.unlink()
        indexer.index(self.dbp, self.root / "projects", incremental=True)
        with db.connect(self.dbp) as con:
            ids = {r["session_id"] for r in con.execute("SELECT session_id FROM sessions")}
            self.assertEqual(ids, {"keep", "gone"})

    def test_disappearing_file_is_skipped_not_fatal(self):
        path = _make_session(
            self.root, "-proj-a", "ghost", fixtures.sample_session_records()
        )
        # Pre-populate state for one good session
        _make_session(self.root, "-proj-a", "good", fixtures.sample_session_records())
        # Simulate disappearance: delete after glob would see it (we mimic
        # by patching Path.stat on the ghost path to raise FileNotFoundError)
        from unittest.mock import patch
        original_stat = Path.stat

        def fake_stat(self_path, *args, **kwargs):
            if self_path.name == "ghost.jsonl":
                raise FileNotFoundError(str(self_path))
            return original_stat(self_path, *args, **kwargs)

        with patch.object(Path, "stat", fake_stat):
            result = indexer.index(self.dbp, self.root / "projects", incremental=False)
        # ghost was skipped, good was indexed
        self.assertEqual(result.sessions_indexed, 1)
        self.assertEqual(result.sessions_skipped, 1)


if __name__ == "__main__":
    unittest.main()
