import unittest
from claude_review_loop import verdict
from claude_review_loop.states import CLEAN, ISSUES, INVALID


class TestStructuredVerdict(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(verdict.validate_structured_verdict(
            {"verdict": "CLEAN", "findings": []}), (CLEAN, [], None))

    def test_issues(self):
        payload = {"verdict": "ISSUES", "findings": [
            {"severity": "Critical", "path": "x.py:3", "message": "broken"}
        ]}
        self.assertEqual(
            verdict.validate_structured_verdict(payload),
            (ISSUES, payload["findings"], None),
        )

    def test_clean_with_findings_is_invalid(self):
        state, _, error = verdict.validate_structured_verdict({"verdict": "CLEAN", "findings": [
            {"severity": "Warning", "path": "x", "message": "bad"}
        ]})
        self.assertEqual(state, INVALID)
        self.assertEqual(error, "CLEAN structured verdict must have no findings")

    def test_issues_without_findings_is_invalid(self):
        state, _, error = verdict.validate_structured_verdict(
            {"verdict": "ISSUES", "findings": []})
        self.assertEqual(state, INVALID)
        self.assertEqual(error, "ISSUES structured verdict must include findings")

    def test_every_invalid_shape_has_a_stable_diagnostic(self):
        cases = (
            (None, "missing structured output"),
            ({"verdict": "CLEAN"},
             "structured output must contain only verdict and findings"),
            ({"verdict": "MAYBE", "findings": []},
             "structured output has an invalid verdict or findings array"),
            ({"verdict": "ISSUES", "findings": ["bad"]},
             "structured output contains a malformed finding"),
            ({"verdict": "ISSUES", "findings": [
                {"severity": "Info", "path": "x", "message": "bad"}
            ]}, "structured output contains an invalid severity"),
            ({"verdict": "ISSUES", "findings": [
                {"severity": "Warning", "path": " ", "message": "bad"}
            ]}, "structured output contains an empty finding path"),
            ({"verdict": "ISSUES", "findings": [
                {"severity": "Warning", "path": "x", "message": " "}
            ]}, "structured output contains an empty finding message"),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected):
                state, items, error = verdict.validate_structured_verdict(payload)
                self.assertEqual((state, items, error), (INVALID, [], expected))

    def test_finding_text_is_trimmed(self):
        state, items, error = verdict.validate_structured_verdict({
            "verdict": "ISSUES",
            "findings": [{"severity": "Suggestion", "path": " x.py ",
                          "message": " tidy "}],
        })
        self.assertEqual(state, ISSUES)
        self.assertEqual(items, [{"severity": "Suggestion", "path": "x.py",
                                  "message": "tidy"}])
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
