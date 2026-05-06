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
        self.assertFalse((self.root / "projects" / "-proj-a" / "old.jsonl").exists())
        gzs = list((self.root / "archive").rglob("old.jsonl.gz"))
        self.assertEqual(len(gzs), 1)
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
