import unittest
from pi_review_loop import verdict
from pi_review_loop.states import CLEAN, ISSUES, INVALID


def agent_end(messages):
    return {"type": "agent_end", "messages": messages}


class TestExtractFinalAssistant(unittest.TestCase):
    def test_picks_last_assistant_concatenates_text_blocks(self):
        ev = agent_end([
            {"role": "user", "content": [{"type": "text", "text": "REVIEW: CLEAN"}]},
            {"role": "assistant", "content": [
                {"type": "thinking", "text": "ignore me"},
                {"type": "text", "text": "Looks good.\n"},
                {"type": "text", "text": "REVIEW: CLEAN"},
            ]},
        ])
        self.assertEqual(
            verdict.extract_final_assistant_text(ev),
            "Looks good.\nREVIEW: CLEAN",
        )

    def test_returns_none_when_no_assistant(self):
        ev = agent_end([{"role": "user", "content": [{"type": "text", "text": "hi"}]}])
        self.assertIsNone(verdict.extract_final_assistant_text(ev))


class TestParseVerdict(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(verdict.parse_verdict("ok\nREVIEW: CLEAN"), (CLEAN, []))

    def test_issues_with_items(self):
        text = (
            "REVIEW: ISSUES\n"
            "1. [Critical] src/a.py: boom\n"
            "2. [Warning] src/b.py: careful\n"
        )
        state, items = verdict.parse_verdict(text)
        self.assertEqual(state, ISSUES)
        self.assertEqual(items, [
            {"severity": "Critical", "path": "src/a.py", "message": "boom"},
            {"severity": "Warning", "path": "src/b.py", "message": "careful"},
        ])

    def test_issues_without_items_is_invalid(self):
        self.assertEqual(verdict.parse_verdict("REVIEW: ISSUES\n")[0], INVALID)

    def test_no_verdict_line_is_invalid(self):
        self.assertEqual(verdict.parse_verdict("I reviewed it, all fine")[0], INVALID)

    def test_takes_last_verdict_line(self):
        text = "quoting: REVIEW: CLEAN\n...\nREVIEW: ISSUES\n1. [Suggestion] x.py: tidy"
        self.assertEqual(verdict.parse_verdict(text)[0], ISSUES)

    def test_takes_last_of_two_matching_verdict_lines(self):
        # Two genuinely-anchored ^REVIEW: lines — the last one wins.
        text = "REVIEW: CLEAN\nanalysis text\nREVIEW: ISSUES\n1. [Warning] x.py: bad"
        self.assertEqual(verdict.parse_verdict(text)[0], ISSUES)

    def test_unknown_severity_item_is_ignored(self):
        self.assertEqual(verdict.parse_verdict("REVIEW: ISSUES\n1. [Bogus] x: y")[0], INVALID)


if __name__ == "__main__":
    unittest.main()
