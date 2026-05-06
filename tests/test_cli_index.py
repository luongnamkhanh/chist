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
