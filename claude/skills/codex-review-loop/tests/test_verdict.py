import json
import unittest

from codex_review_loop.verdict import parse_verdict


class TestParseVerdict(unittest.TestCase):
    def test_clean(self):
        state, items, _, error = parse_verdict('{"verdict":"CLEAN","findings":[]}')
        self.assertEqual((state, items, error), ("CLEAN", [], None))

    def test_issues(self):
        text = json.dumps({"verdict": "ISSUES", "findings": [
            {"severity": "Critical", "path": " a.py ", "message": " bad "}]})
        state, items, _, _ = parse_verdict(text)
        self.assertEqual(state, "ISSUES")
        self.assertEqual(items, [{"severity": "Critical", "path": "a.py",
                                  "message": "bad"}])

    def test_everything_else_is_invalid(self):
        for text in (None, "", "   ", "REVIEW: CLEAN", "[]", "{}",
                     '{"verdict":"CLEAN"}',
                     '{"verdict":"CLEAN","findings":[],"extra":1}',
                     '{"verdict":"clean","findings":[]}',
                     '{"verdict":"CLEAN","findings":{}}',
                     '{"verdict":"ISSUES","findings":[]}',
                     '{"verdict":"CLEAN","findings":[{"severity":"Warning","path":"a","message":"m"}]}',
                     '{"verdict":"ISSUES","findings":[{"severity":"Major","path":"a","message":"m"}]}',
                     '{"verdict":"ISSUES","findings":[{"severity":"Warning","path":"","message":"m"}]}',
                     '{"verdict":"ISSUES","findings":[{"severity":"Warning","path":"a"}]}',
                     '{"verdict":"ISSUES","findings":["x"]}',
                     '{"verdict":"CLEAN","findings":[]}\n{"verdict":"CLEAN","findings":[]}'):
            with self.subTest(text=text):
                self.assertEqual(parse_verdict(text)[0], "INVALID")


if __name__ == "__main__":
    unittest.main()
