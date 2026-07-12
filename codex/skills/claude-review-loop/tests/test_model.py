import unittest
from claude_review_loop import model


class TestResolveModel(unittest.TestCase):
    def test_defaults_to_opus_alias(self):
        self.assertEqual(model.resolve_model(), "opus")

    def test_explicit_model_passes_through(self):
        self.assertEqual(model.resolve_model("claude-opus-4-8"), "claude-opus-4-8")

    def test_resolve_from_cli_returns_fallback_without_shelling_out(self):
        self.assertEqual(model.resolve_from_cli(fallback="pin/x"), "pin/x")


if __name__ == "__main__":
    unittest.main()
