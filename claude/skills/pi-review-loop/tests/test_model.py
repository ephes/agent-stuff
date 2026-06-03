import unittest
from unittest import mock
from pi_review_loop import model

SAMPLE = """\
openai-codex/gpt-5.5
openai-codex/gpt-5.1
anthropic/claude-opus-4-8
google/gemini-2.5-pro
openai-codex/gpt-4.1
"""

REAL_TABLE = """\
provider      model                context  max-out  thinking  images
openai-codex  gpt-5.2              272K     128K     yes       yes
openai-codex  gpt-5.3-codex        272K     128K     yes       yes
openai-codex  gpt-5.4              272K     128K     yes       yes
openai-codex  gpt-5.5              272K     128K     yes       yes
anthropic     claude-opus-4-8      200K     64K      yes       yes
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

    def test_resolve_from_cli_falls_back_on_missing_binary(self):
        with mock.patch("pi_review_loop.model.subprocess.run", side_effect=OSError):
            self.assertEqual(model.resolve_from_cli(fallback="pin/x"), "pin/x")

    def test_resolve_from_cli_parses_stdout(self):
        completed = mock.Mock(stdout="openai-codex/gpt-5.5\n", stderr="")
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            self.assertEqual(model.resolve_from_cli(), "openai-codex/gpt-5.5")


class TestResolveTableFormat(unittest.TestCase):
    def test_parses_real_table_and_picks_highest(self):
        # fallback "pin/x" is wrong on purpose: returning gpt-5.5 proves it parsed.
        self.assertEqual(model.resolve_model(REAL_TABLE, fallback="pin/x"),
                         "openai-codex/gpt-5.5")

    def test_skips_header_row(self):
        # header's model column is the literal word "model" (no gpt) -> ignored
        self.assertEqual(
            model.resolve_model("provider model context\nx gpt-4 y\n", fallback="pin/x"),
            "x/gpt-4",
        )


if __name__ == "__main__":
    unittest.main()
