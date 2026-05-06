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
            rc = cli.main(["resume", "--last", "--project=-proj-a"])
        self.assertEqual(rc, 0)
        self.assertIn("resumeme"[:8], buf.getvalue())


if __name__ == "__main__":
    unittest.main()
