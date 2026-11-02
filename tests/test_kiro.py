import json
import tempfile
import unittest
from pathlib import Path

from chistlib import db, indexer
from tests import fixtures


def _session(root: Path) -> None:
    d = root / "kiro" / "6314a02d" / "sess_abc"
    d.mkdir(parents=True)
    (d / "session.json").write_text(json.dumps({"id": "sess_abc", "workspacePaths": ["/workspace/proj"]}))
    m = lambda payload, ts="2026-11-02T03:00:00Z": {"timestamp": ts, "payload": payload}
    fixtures.write_jsonl(d / "messages.jsonl", [
        m({"type": "agent_note", "content": "<session_context>"}),
        m({"type": "user", "content": "drop freshness gate"}),
        m({"type": "assistant", "content": "...", "operationType": "Reasoning"}),
        m({"type": "tool_call", "toolName": "execute_bash", "args": {"command": "git log"}}),
        m({"type": "tool_result", "content": "Exit Code: 0"}),
        m({"type": "assistant", "content": "done", "operationType": "Say"}),
        m({"type": "turn_end"}),
    ])


class TestKiroIndex(unittest.TestCase):
    def test_kiro_session_indexed_under_claude_style_project(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            dbp = root / "history.db"
            _session(root)
            res = indexer.index(dbp, root / "projects", incremental=True, kiro_root=root / "kiro")
            self.assertEqual((res.sessions_indexed, res.messages_indexed), (1, 4))
            with db.connect(dbp) as con:
                s = con.execute("SELECT * FROM sessions").fetchone()
                roles = [r["role"] for r in con.execute("SELECT role FROM messages ORDER BY seq")]
            self.assertEqual((s["session_id"], s["project"]), ("kiro-abc", "-workspace-proj"))
            self.assertEqual(roles, ["user", "tool_use", "tool_result", "assistant"])
            from chistlib import distill, parser
            d = distill.extract(parser.parse_kiro_session(root / "kiro" / "6314a02d" / "sess_abc")[2])
            self.assertEqual(d.commands_run, [{"command": "git log", "count": 1}])
            again = indexer.index(dbp, root / "projects", incremental=True, kiro_root=root / "kiro")
            self.assertEqual((again.sessions_indexed, again.sessions_skipped), (0, 1))


if __name__ == "__main__":
    unittest.main()
