import json
import unittest

from chistlib import distill, parser


def _records(*items):
    return list(items)


class TestDistill(unittest.TestCase):
    def test_extract_decisions(self):
        recs = [
            parser.Record(role="user", timestamp=None, content="should we use B?"),
            parser.Record(role="assistant", timestamp=None,
                          content="Decision: going with option B."),
        ]
        d = distill.extract(recs)
        self.assertTrue(any("B" in s for s in d.decisions))

    def test_extract_files_touched_from_tool_use(self):
        tu = json.dumps({"file_path": "/tmp/a.txt"}, sort_keys=True)
        recs = [
            parser.Record(role="tool_use", timestamp=None,
                          content=f"[tool_use:Read] {tu}"),
            parser.Record(role="tool_use", timestamp=None,
                          content=f"[tool_use:Read] {tu}"),
            parser.Record(role="tool_use", timestamp=None,
                          content="[tool_use:Edit] " +
                                  json.dumps({"file_path": "/tmp/b.txt"})),
        ]
        d = distill.extract(recs)
        files = {f["path"]: f for f in d.files_touched}
        self.assertEqual(files["/tmp/a.txt"]["count"], 2)
        self.assertEqual(files["/tmp/b.txt"]["count"], 1)

    def test_extract_commands_from_bash(self):
        recs = [
            parser.Record(role="tool_use", timestamp=None,
                          content="[tool_use:Bash] " +
                                  json.dumps({"command": "ls -la"})),
            parser.Record(role="tool_use", timestamp=None,
                          content="[tool_use:Bash] " +
                                  json.dumps({"command": "ls -la"})),
            parser.Record(role="tool_use", timestamp=None,
                          content="[tool_use:Bash] " +
                                  json.dumps({"command": "git status"})),
        ]
        d = distill.extract(recs)
        cmds = {c["command"]: c["count"] for c in d.commands_run}
        self.assertEqual(cmds["ls -la"], 2)
        self.assertEqual(cmds["git status"], 1)

    def test_open_threads_returns_recent_user_messages(self):
        recs = [
            parser.Record(role="user", timestamp=None, content="q1"),
            parser.Record(role="assistant", timestamp=None, content="ack done"),
            parser.Record(role="user", timestamp=None, content="q2"),
            parser.Record(role="assistant", timestamp=None, content="thinking..."),
            parser.Record(role="user", timestamp=None, content="q3"),
        ]
        d = distill.extract(recs)
        self.assertIn("q3", d.open_threads)


if __name__ == "__main__":
    unittest.main()
