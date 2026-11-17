import tempfile
import unittest
from pathlib import Path

from chistlib import db, indexer
from tests import fixtures


def _rollout(root: Path, folder: str = "codex", sid: str = "abc") -> Path:
    p = root / folder / "2026" / "10" / "23" / f"rollout-x-{sid}.jsonl"
    ri = lambda payload, ts="2026-10-23T02:00:00Z": {"timestamp": ts, "type": "response_item", "payload": payload}
    fixtures.write_jsonl(p, [
        {"type": "session_meta", "payload": {"id": sid, "cwd": "/workspace/proj"}},
        ri({"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "sys"}]}),
        ri({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>x"}]}),
        ri({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "fix the monitor"}]}),
        ri({"type": "custom_tool_call", "name": "exec", "input": "pytest"}),
        ri({"type": "custom_tool_call_output", "output": "339 passed"}),
        ri({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "done"}]}),
    ])
    return p


class TestCodexIndex(unittest.TestCase):
    def test_codex_rollout_indexed_under_claude_style_project(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            dbp = root / "history.db"
            _rollout(root)
            res = indexer.index(dbp, root / "projects", incremental=True, codex_root=root / "codex")
            self.assertEqual((res.sessions_indexed, res.messages_indexed), (1, 4))
            with db.connect(dbp) as con:
                s = con.execute("SELECT * FROM sessions").fetchone()
                roles = [r["role"] for r in con.execute("SELECT role FROM messages ORDER BY seq")]
            self.assertEqual((s["session_id"], s["project"]), ("codex-abc", "-workspace-proj"))
            self.assertEqual(roles, ["user", "tool_use", "tool_result", "assistant"])
            again = indexer.index(dbp, root / "projects", incremental=True, codex_root=root / "codex")
            self.assertEqual((again.sessions_indexed, again.sessions_skipped), (0, 1))
            full = indexer.index(dbp, root / "projects", incremental=False, codex_root=root / "codex")
            self.assertEqual(full.sessions_indexed, 1)

    def test_multiple_codex_roots_indexed_together(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            dbp = root / "history.db"
            _rollout(root, folder="codex1", sid="s1")
            _rollout(root, folder="codex2", sid="s2")
            res = indexer.index(
                dbp, root / "projects", incremental=False,
                codex_root=[root / "codex1", root / "codex2", root / "missing"],
            )
            self.assertEqual(res.sessions_indexed, 2)
            with db.connect(dbp) as con:
                ids = {r["session_id"] for r in con.execute("SELECT session_id FROM sessions")}
            self.assertEqual(ids, {"codex-s1", "codex-s2"})


if __name__ == "__main__":
    unittest.main()
