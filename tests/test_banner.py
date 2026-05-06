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
            rc = cli.main(["banner", "--project=-proj-x"])
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
            rc = cli.main(["banner", "--project=-proj-a"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("[claude-history]", out)
        self.assertIn("abcd1234", out)
        self.assertIn("/history-resume", out)


if __name__ == "__main__":
    unittest.main()
