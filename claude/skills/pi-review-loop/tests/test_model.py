import unittest
from pi_review_loop import model

SAMPLE = """\
openai-codex/gpt-5.5
openai-codex/gpt-5.1
anthropic/claude-opus-4-8
google/gemini-2.5-pro
openai-codex/gpt-4.1
"""


class TestResolveModel(unittest.TestCase):
    def test_picks_highest_gpt(self):
        self.assertEqual(model.resolve_model(SAMPLE), "openai-codex/gpt-5.5")

    def test_passes_provider_prefix_exactly(self):
        out = "someprovider/gpt-9000-turbo\nother/gpt-3"
        self.assertEqual(model.resolve_model(out), "someprovider/gpt-9000-turbo")

    def test_falls_back_when_no_gpt(self):
        self.assertEqual(
            model.resolve_model("anthropic/claude-opus-4-8\n", fallback="pin/x"),
            "pin/x",
        )

    def test_ignores_blank_and_noise_lines(self):
        out = "\n  \nAvailable models:\nopenai-codex/gpt-5.5\n"
        self.assertEqual(model.resolve_model(out), "openai-codex/gpt-5.5")


if __name__ == "__main__":
    unittest.main()
