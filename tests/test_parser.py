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
        text = "xin chào thế giới"
        rec = parser.parse_line(json.dumps(fixtures.user_msg(text)))
        self.assertEqual(rec.content, text)

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

    def test_parse_file_skips_malformed_lines(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            jp = Path(tmp) / "s.jsonl"
            jp.write_text(
                json.dumps(fixtures.user_msg("first")) + "\n"
                + "\n"
                + "{not valid json\n"
                + json.dumps(fixtures.assistant_msg("second")) + "\n",
                encoding="utf-8",
            )
            recs = list(parser.parse_file(jp))
            self.assertEqual(len(recs), 2)
            self.assertEqual(recs[0].content, "first")
            self.assertEqual(recs[1].content, "second")

    def test_parse_non_dict_json_returns_none(self):
        self.assertIsNone(parser.parse_line('"a string"'))
        self.assertIsNone(parser.parse_line('[1,2,3]'))
        self.assertIsNone(parser.parse_line('42'))
        self.assertIsNone(parser.parse_line('null'))

    def test_parse_null_content_yields_empty_string(self):
        rec = parser.parse_line(
            '{"type":"user","message":{"role":"user","content":null},"timestamp":"2026-05-06T10:00:00Z"}'
        )
        self.assertEqual(rec.content, "")


if __name__ == "__main__":
    unittest.main()
