import unittest
from pi_review_loop import states


class TestStates(unittest.TestCase):
    def test_clean_and_issues_are_not_failed(self):
        self.assertNotIn(states.CLEAN, states.FAILED)
        self.assertNotIn(states.ISSUES, states.FAILED)

    def test_invalid_is_failed(self):
        self.assertIn(states.INVALID, states.FAILED)

    def test_all_contains_every_state(self):
        self.assertEqual(len(states.ALL), 7)


if __name__ == "__main__":
    unittest.main()
