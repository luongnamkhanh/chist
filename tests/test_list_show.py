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
