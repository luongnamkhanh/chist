import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from chistlib import db, distill, indexer, parser
from tests import fixtures


def _session(root: Path) -> Path:
    agy = root / "agy"
    logs = agy / "brain" / "abc12345" / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    dbp = agy / "conversation_summaries.db"
    con = sqlite3.connect(dbp)
    con.execute(
        "CREATE TABLE conversation_summaries (conversation_id TEXT PRIMARY KEY, workspace_uris TEXT)"
    )
    con.execute(
        "INSERT INTO conversation_summaries VALUES (?, ?)",
        ("abc12345", json.dumps(["file:///workspace/proj"])),
    )
    con.commit()
    con.close()

    fixtures.write_jsonl(logs / "transcript.jsonl", [
        {"type": "USER_INPUT", "created_at": "2026-11-17T03:00:00Z", "content": "<USER_REQUEST>\nsetup agy\n</USER_REQUEST>"},
        {"type": "PLANNER_RESPONSE", "created_at": "2026-11-17T03:00:01Z", "tool_calls": [{"name": "run_command", "args": {"CommandLine": "\"git status\""}}]},
        {"type": "GENERIC", "created_at": "2026-11-17T03:00:02Z", "content": "Command exited with code 0."},
        {"type": "PLANNER_RESPONSE", "created_at": "2026-11-17T03:00:03Z", "content": "done"},
    ])
    return dbp


class TestAgyIndex(unittest.TestCase):
    def test_agy_session_indexed_under_claude_style_project(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            dbp = root / "history.db"
            sum_db = _session(root)
            res = indexer.index(
                dbp, root / "projects", incremental=True,
                agy_root=root / "agy" / "brain", agy_summaries_db=sum_db,
            )
            self.assertEqual((res.sessions_indexed, res.messages_indexed), (1, 4))
            with db.connect(dbp) as con:
                s = con.execute("SELECT * FROM sessions").fetchone()
                roles = [r["role"] for r in con.execute("SELECT role FROM messages ORDER BY seq")]
            self.assertEqual((s["session_id"], s["project"]), ("agy-abc12345", "-workspace-proj"))
            self.assertEqual(roles, ["user", "tool_use", "tool_result", "assistant"])
            wmap = parser.agy_workspace_map(sum_db)
            d = distill.extract(parser.parse_agy_session(
                root / "agy" / "brain" / "abc12345" / ".system_generated" / "logs" / "transcript.jsonl", wmap
            )[2])
            self.assertEqual(d.commands_run, [{"command": "git status", "count": 1}])
            again = indexer.index(
                dbp, root / "projects", incremental=True,
                agy_root=root / "agy" / "brain", agy_summaries_db=sum_db,
            )
            self.assertEqual((again.sessions_indexed, again.sessions_skipped), (0, 1))


if __name__ == "__main__":
    unittest.main()
