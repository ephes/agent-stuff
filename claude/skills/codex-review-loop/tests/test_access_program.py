"""`--cyber-access-program`: passed through to Codex, proven from the session
record, and tied to the one model each program runs on."""
import json
import os
import unittest

from tests.helpers import RepoFixture

BLUE_MODEL = "gpt-daybreak-blue-latest"


class TestAccessProgram(unittest.TestCase):
    def setUp(self):
        self.fx = RepoFixture()

    def tearDown(self):
        self.fx.cleanup()

    def argv(self):
        with open(os.path.join(self.fx.home, "last-argv.json")) as fh:
            return json.load(fh)

    def assertNotRun(self):
        self.assertFalse(os.path.exists(os.path.join(self.fx.home, "last-argv.json")))

    def test_without_the_flag_nothing_changes(self):
        proc, result, _ = self.fx.run("clean")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        argv = self.argv()
        self.assertNotIn("--cyber-access-program", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6.1-sol")
        self.assertIsNone(result["access_program"])
        self.assertEqual(result["model"], "gpt-6.1-sol")
        # Recorded as observed, but not judged: the server picks the program.
        self.assertEqual(result["observed_access_programs"], ["standard"])
        self.assertNotIn("access_program=", proc.stdout)

    def test_daybreak_blue_derives_its_model_and_proves_both(self):
        proc, result, _ = self.fx.run("clean", "--cyber-access-program",
                                      "daybreak_blue")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        argv = self.argv()
        self.assertEqual(argv[argv.index("--cyber-access-program") + 1],
                         "daybreak_blue")
        self.assertEqual(argv[argv.index("-m") + 1], BLUE_MODEL)
        self.assertIn('model_reasoning_effort="high"', argv)
        self.assertEqual(result["state"], "CLEAN")
        self.assertEqual(result["model"], BLUE_MODEL)
        self.assertEqual(result["access_program"], "daybreak_blue")
        self.assertEqual(result["observed_models"], [BLUE_MODEL])
        self.assertEqual(result["observed_efforts"], ["high"])
        self.assertEqual(result["observed_access_programs"], ["daybreak_blue"])
        self.assertIn(f"model={BLUE_MODEL}", proc.stdout)
        self.assertIn("access_program=daybreak_blue", proc.stdout)

    def test_daybreak_blue_with_its_model_named_explicitly(self):
        proc, result, _ = self.fx.run(
            "clean", "--cyber-access-program", "daybreak_blue",
            "--model", BLUE_MODEL, "--effort", "medium")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(result["observed_efforts"], ["medium"])
        self.assertEqual(result["observed_models"], [BLUE_MODEL])

    def test_standard_keeps_sol_and_proves_the_program(self):
        proc, result, _ = self.fx.run("clean", "--cyber-access-program", "standard")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        argv = self.argv()
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6.1-sol")
        self.assertEqual(argv[argv.index("--cyber-access-program") + 1], "standard")
        self.assertEqual(result["access_program"], "standard")

    def test_a_daybreak_program_with_sol_is_refused_before_anything_runs(self):
        proc, result, _ = self.fx.run("clean", "--cyber-access-program",
                                      "daybreak_blue", "--model", "gpt-6.1-sol")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual((result["state"], result["failure_kind"]),
                         ("INVALID", "preflight"))
        self.assertIn(f"runs only {BLUE_MODEL}", result["error"])
        self.assertNotRun()

    def test_a_daybreak_model_without_its_program_is_refused(self):
        for extra in ([], ["--cyber-access-program", "standard"],
                      ["--cyber-access-program", "daybreak_red"]):
            with self.subTest(extra=extra):
                proc, result, _ = self.fx.run("clean", "--model", BLUE_MODEL, *extra)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(result["state"], "INVALID")
                self.assertNotRun()

    def test_an_unknown_program_is_refused(self):
        proc, result, _ = self.fx.run("clean", "--cyber-access-program", "daybreak")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(result["state"], "INVALID")
        self.assertNotRun()

    def test_a_daybreak_run_answered_by_sol_is_a_mismatch(self):
        proc, result, _ = self.fx.run("wrong_model", "--cyber-access-program",
                                      "daybreak_blue")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual((result["state"], result["failure_kind"]),
                         ("INVALID", "model_mismatch"))
        self.assertIn(f"not {BLUE_MODEL}", result["error"])
        self.assertEqual(result["items"], [])

    def test_a_run_under_another_program_is_a_mismatch(self):
        proc, result, _ = self.fx.run("wrong_program", "--cyber-access-program",
                                      "daybreak_blue")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual((result["state"], result["failure_kind"]),
                         ("INVALID", "model_mismatch"))
        self.assertIn("access program standard, not daybreak_blue", result["error"])
        self.assertIsNone(result["baseline_commit"])

    def test_the_cyber_filter_is_its_own_failure_with_a_hint(self):
        proc, result, _ = self.fx.run("cyber_policy", "--slice-id", "s1",
                                      "--record-baseline")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual((result["state"], result["failure_kind"]),
                         ("PROVIDER_ERROR", "cyber_policy"))
        self.assertIn("--cyber-access-program daybreak_blue", result["error"])
        self.assertIn("flagged for possible cybersecurity risk", result["error"])
        self.assertIn("cyber_policy", proc.stderr)
        self.assertIsNone(result["baseline_commit"])
        self.assertIsNone(result["round"])

    def test_the_cyber_filter_under_daybreak_says_to_stop(self):
        proc, result, _ = self.fx.run("cyber_policy", "--cyber-access-program",
                                      "daybreak_blue")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(result["failure_kind"], "cyber_policy")
        self.assertIn("even under --cyber-access-program daybreak_blue",
                      result["error"])

    def test_another_provider_failure_stays_provider(self):
        proc, result, _ = self.fx.run("capacity")
        self.assertEqual(result["failure_kind"], "provider")


if __name__ == "__main__":
    unittest.main()
