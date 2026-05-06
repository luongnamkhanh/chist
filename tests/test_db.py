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
