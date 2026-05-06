import json
import unittest

from chistlib import parser
from tests import fixtures


class TestParseLine(unittest.TestCase):
    def test_parse_user_text(self):
        rec = parser.parse_line(json.dumps(fixtures.user_msg("hello world")))
        self.assertEqual(rec.role, "user")
        self.assertEqual(rec.content, "hello world")
        self.assertEqual(rec.timestamp, "2026-05-06T10:00:00.000Z")

    def test_parse_assistant_text(self):
        rec = parser.parse_line(json.dumps(fixtures.assistant_msg("hi there")))
        self.assertEqual(rec.role, "assistant")
        self.assertEqual(rec.content, "hi there")

    def test_parse_tool_use(self):
        rec = parser.parse_line(
            json.dumps(fixtures.tool_use_msg("Bash", {"command": "ls -la"}))
        )
        self.assertEqual(rec.role, "tool_use")
        self.assertIn("Bash", rec.content)
        self.assertIn("ls -la", rec.content)

    def test_parse_tool_result(self):
        rec = parser.parse_line(json.dumps(fixtures.tool_result_msg("output text")))
        self.assertEqual(rec.role, "tool_result")
        self.assertIn("output text", rec.content)

    def test_parse_malformed_returns_none(self):
        self.assertIsNone(parser.parse_line(fixtures.malformed_line()))

    def test_parse_empty_returns_none(self):
        self.assertIsNone(parser.parse_line(""))
        self.assertIsNone(parser.parse_line("   \n"))

    def test_parse_unicode(self):
        rec = parser.parse_line(json.dumps(fixtures.user_msg("xin chao the gioi")))
        self.assertEqual(rec.content, "xin chao the gioi")

    def test_parse_file_yields_records(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            jp = Path(tmp) / "s.jsonl"
            fixtures.write_jsonl(jp, fixtures.sample_session_records())
            recs = list(parser.parse_file(jp))
            self.assertEqual(len(recs), 6)
            self.assertEqual(recs[0].role, "user")
            self.assertEqual(recs[-1].role, "assistant")


if __name__ == "__main__":
    unittest.main()
