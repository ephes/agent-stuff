import unittest
from unittest import mock
from pi_review_loop import model

SAMPLE = """\
openai-codex/gpt-5.6-sol
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
openai-codex  gpt-5.6-luna         372K     128K     yes       yes
openai-codex  gpt-5.6-sol          372K     128K     yes       yes
openai-codex  gpt-5.6-terra        372K     128K     yes       yes
anthropic     claude-opus-4-8      200K     64K      yes       yes
"""


class TestResolveModel(unittest.TestCase):
    def test_picks_highest_gpt(self):
        self.assertEqual(model.resolve_model(SAMPLE), "openai-codex/gpt-5.6-sol")

    def test_sol_preference_does_not_override_newer_version(self):
        out = "openai-codex/gpt-5.6-sol\nopenai-codex/gpt-5.7-terra\n"
        self.assertEqual(model.resolve_model(out), "openai-codex/gpt-5.7-terra")

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

    def test_rejects_gpt_text_in_diagnostic_prose_without_table_header(self):
        out = "No models available. Use /login to log into a provider.\nDefault: gpt-5.5\n"
        self.assertEqual(model.resolve_model(out, fallback="pin/x"), "pin/x")

    def test_rejects_gpt_text_in_diagnostic_prose_after_table_header(self):
        out = "provider model context\nopenai-codex gpt-5.1 272K\nDefault: gpt-5.5\n"
        self.assertEqual(model.resolve_model(out, fallback="pin/x"), "openai-codex/gpt-5.1")

    def test_resolve_from_cli_falls_back_on_missing_binary(self):
        with mock.patch("pi_review_loop.model.subprocess.run", side_effect=OSError):
            self.assertEqual(model.resolve_from_cli(fallback="pin/x"), "pin/x")

    def test_resolve_from_cli_parses_stdout(self):
        completed = mock.Mock(stdout="openai-codex/gpt-5.6-sol\n", stderr="", returncode=0)
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            self.assertEqual(model.resolve_from_cli(), "openai-codex/gpt-5.6-sol")

    def test_diagnostic_line_does_not_hide_listed_gpt_model(self):
        completed = mock.Mock(
            stdout="provider      model\nopenai-codex  gpt-5.5  272K\n",
            stderr="No API key found for anthropic.\n",
            returncode=0,
        )
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            self.assertEqual(
                model.resolve_from_cli(require_available=True),
                "openai-codex/gpt-5.5",
            )

    def test_require_available_rejects_no_models(self):
        completed = mock.Mock(
            stdout="",
            stderr="No models available. Use /login to log into a provider via OAuth or API key.",
            returncode=0,
        )
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            with self.assertRaises(model.PiUnavailable) as raised:
                model.resolve_from_cli(require_available=True)
        self.assertIn("no available models", str(raised.exception))

    def test_require_available_rejects_cli_failure(self):
        completed = mock.Mock(stdout="", stderr="No API key found for openai-codex.", returncode=1)
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            with self.assertRaises(model.PiUnavailable) as raised:
                model.resolve_from_cli(require_available=True)
        self.assertIn("No API key found", str(raised.exception))

    def test_require_available_rejects_generic_cli_failure(self):
        completed = mock.Mock(stdout="", stderr="network unreachable", returncode=2)
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            with self.assertRaises(model.PiUnavailable) as raised:
                model.resolve_from_cli(require_available=True)
        self.assertIn("failed with exit 2", str(raised.exception))

    def test_require_available_rejects_failed_cli_even_with_model_text(self):
        completed = mock.Mock(stdout="openai-codex gpt-5.5 272K\n", stderr="", returncode=2)
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            with self.assertRaises(model.PiUnavailable) as raised:
                model.resolve_from_cli(require_available=True)
        self.assertIn("failed with exit 2", str(raised.exception))

    def test_ensure_available_accepts_non_gpt_model_listing(self):
        completed = mock.Mock(
            stdout="provider      model\nanthropic     claude-opus-4-8\n",
            stderr="",
            returncode=0,
        )
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            self.assertIsNone(model.ensure_available())

    def test_ensure_available_accepts_listing_with_unrelated_diagnostic(self):
        completed = mock.Mock(
            stdout="provider      model\nopenai-codex  gpt-5.5\n",
            stderr="No API key found for anthropic.\n",
            returncode=0,
        )
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            self.assertIsNone(model.ensure_available())

    def test_ensure_available_rejects_no_models(self):
        completed = mock.Mock(stdout="", stderr="No models available.", returncode=0)
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            with self.assertRaises(model.PiUnavailable):
                model.ensure_available()

    def test_ensure_available_rejects_no_models_with_help_paths(self):
        completed = mock.Mock(
            stdout="",
            stderr=(
                "No models available. Use /login to log into a provider via OAuth or API key.\n"
                "  /opt/homebrew/Cellar/pi/docs/providers.md\n"
                "  /opt/homebrew/Cellar/pi/docs/models.md\n"
            ),
            returncode=0,
        )
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            with self.assertRaises(model.PiUnavailable):
                model.ensure_available()

    def test_ensure_available_rejects_no_models_with_prose_help(self):
        completed = mock.Mock(
            stdout="",
            stderr=(
                "No models available.\n"
                "See https://example.com/docs for setup\n"
                "Run pi and use /login\n"
            ),
            returncode=0,
        )
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            with self.assertRaises(model.PiUnavailable):
                model.ensure_available()

    def test_ensure_model_available_strips_thinking_suffix(self):
        completed = mock.Mock(
            stdout="provider model\nopenai-codex gpt-5.6-sol\n",
            stderr="",
            returncode=0,
        )
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed) as run:
            self.assertIsNone(
                model.ensure_model_available("openai-codex/gpt-5.6-sol:high")
            )
        self.assertEqual(
            run.call_args.args[0],
            ["pi", "--list-models", "openai-codex/gpt-5.6-sol"],
        )

    def test_ensure_model_available_rejects_no_match(self):
        completed = mock.Mock(
            stdout='', stderr='No models matching "bogus/model"\n', returncode=0
        )
        with mock.patch("pi_review_loop.model.subprocess.run", return_value=completed):
            with self.assertRaises(model.PiUnavailable) as raised:
                model.ensure_model_available("bogus/model")
        self.assertIn("requested model is not available", str(raised.exception))


class TestResolveTableFormat(unittest.TestCase):
    def test_parses_real_table_and_picks_highest(self):
        # fallback "pin/x" is wrong on purpose: returning Sol proves it parsed.
        self.assertEqual(model.resolve_model(REAL_TABLE, fallback="pin/x"),
                         "openai-codex/gpt-5.6-sol")

    def test_skips_header_row(self):
        # header's model column is the literal word "model" (no gpt) -> ignored
        self.assertEqual(
            model.resolve_model("provider model context\nx gpt-4 y\n", fallback="pin/x"),
            "x/gpt-4",
        )


if __name__ == "__main__":
    unittest.main()
