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
