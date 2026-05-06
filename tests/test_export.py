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
