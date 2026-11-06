import unittest
from claude_review_loop import states


class TestStates(unittest.TestCase):
    def test_clean_and_issues_are_not_failed(self):
        self.assertNotIn(states.CLEAN, states.FAILED)
        self.assertNotIn(states.ISSUES, states.FAILED)

    def test_suggestions_only_passes_and_is_not_failed(self):
        self.assertNotIn(states.SUGGESTIONS_ONLY, states.FAILED)
        self.assertEqual(states.PASSING,
                         {states.CLEAN, states.SUGGESTIONS_ONLY})
        self.assertTrue(states.PASSING.isdisjoint(states.FAILED))
        self.assertNotIn(states.ISSUES, states.PASSING)

    def test_invalid_is_failed(self):
        self.assertIn(states.INVALID, states.FAILED)

    def test_all_contains_every_state(self):
        self.assertEqual(
            states.ALL,
            {states.CLEAN, states.ISSUES, states.SUGGESTIONS_ONLY,
             states.INVALID, states.CRASHED,
             states.STALLED, states.STALLED_RETRY, states.PROVIDER_ERROR},
        )

    def test_all_error_states_are_failed(self):
        for s in (states.INVALID, states.CRASHED, states.STALLED,
                  states.STALLED_RETRY, states.PROVIDER_ERROR):
            self.assertIn(s, states.FAILED)


if __name__ == "__main__":
    unittest.main()
