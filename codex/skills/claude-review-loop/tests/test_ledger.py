import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from claude_review_loop import ledger


def item(severity="Warning", path="a.py", message="fix the guard"):
    return {"severity": severity, "path": path, "message": message}


def round_record(items, state="ISSUES"):
    counts, findings = ledger.summarize(items)
    return {"state": state, "counts": counts, "findings": findings}


class TestFingerprint(unittest.TestCase):
    def test_line_numbers_do_not_change_a_finding_identity(self):
        # The same complaint after a repair moved the code down a few lines.
        self.assertEqual(
            ledger.fingerprint(item(message="unchecked return at line 42")),
            ledger.fingerprint(item(message="unchecked return at line 87")),
        )

    def test_a_different_path_is_a_different_finding(self):
        self.assertNotEqual(
            ledger.fingerprint(item(path="a.py")),
            ledger.fingerprint(item(path="b.py")),
        )

    def test_a_different_severity_is_a_different_finding(self):
        self.assertNotEqual(
            ledger.fingerprint(item(severity="Critical")),
            ledger.fingerprint(item(severity="Warning")),
        )

    def test_summarize_keeps_counts_and_paths_but_no_finding_text(self):
        counts, findings = ledger.summarize(
            [item(severity="Critical"), item(), item(severity="Suggestion")])
        self.assertEqual(counts, {"Critical": 1, "Warning": 1, "Suggestion": 1})
        self.assertNotIn("message", json.dumps(findings))
        self.assertNotIn("fix the guard", json.dumps(findings))


class TestAssess(unittest.TestCase):
    def test_no_history_is_not_a_stop_signal(self):
        status, _ = ledger.assess([])
        self.assertEqual(status, ledger.PROGRESS)

    def test_a_round_with_no_findings_converges(self):
        status, _ = ledger.assess([round_record([], state="CLEAN")])
        self.assertEqual(status, ledger.CONVERGED)

    def test_suggestion_only_converges_rather_than_earning_a_round(self):
        status, reason = ledger.assess(
            [round_record([item(severity="Suggestion")])])
        self.assertEqual(status, ledger.CONVERGED)
        self.assertIn("proportionality", reason)

    def test_falling_required_counts_keep_the_loop_going(self):
        # Each round finds different things, and fewer of them.
        rounds = [
            round_record([item(severity="Critical", path="a.py"),
                          item(path="b.py"), item(path="c.py")]),
            round_record([item(path="d.py"), item(path="e.py")]),
            round_record([item(path="f.py")]),
        ]
        status, _ = ledger.assess(rounds)
        self.assertEqual(status, ledger.PROGRESS)

    def test_a_flat_required_count_escalates(self):
        # Three rounds, two transitions, nothing removed.
        rounds = [round_record([item(path=f"{n}.py")]) for n in range(3)]
        status, reason = ledger.assess(rounds)
        self.assertEqual(status, ledger.ESCALATE)
        self.assertIn("not decreased", reason)

    def test_two_rounds_without_progress_are_not_yet_an_escalation(self):
        rounds = [round_record([item(path=f"{n}.py")]) for n in range(2)]
        status, _ = ledger.assess(rounds)
        self.assertEqual(status, ledger.PROGRESS)

    def test_a_finding_surviving_two_repairs_escalates(self):
        stubborn = item(severity="Critical", path="core.py",
                        message="the lock is still released early")
        rounds = [
            round_record([stubborn, item(), item()]),
            round_record([stubborn, item()]),
            round_record([stubborn]),
        ]
        status, reason = ledger.assess(rounds)
        self.assertEqual(status, ledger.ESCALATE)
        self.assertIn("core.py", reason)
        self.assertIn("survived", reason)

    def test_a_finding_that_came_back_after_being_fixed_is_not_a_survivor(self):
        recurring = item(severity="Critical", path="core.py")
        rounds = [
            round_record([recurring, item(), item()]),
            round_record([item()]),
            round_record([recurring]),
        ]
        status, _ = ledger.assess(rounds)
        # Counts still fell overall, and the finding did not survive a repair
        # untouched, so this is a new problem rather than a stuck loop.
        self.assertEqual(status, ledger.PROGRESS)

    def test_a_repeated_suggestion_does_not_escalate(self):
        nit = item(severity="Suggestion", path="a.py")
        rounds = [round_record([nit]) for _ in range(3)]
        status, _ = ledger.assess(rounds)
        self.assertEqual(status, ledger.CONVERGED)


class TestLedgerFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "ledger")

    def tearDown(self):
        self.tmp.cleanup()

    def test_slice_ids_that_clean_to_the_same_name_get_separate_files(self):
        self.assertNotEqual(ledger.slug("feature/one"), ledger.slug("feature one"))

    def test_slug_is_a_safe_filename(self):
        name = ledger.slug("../../etc/passwd")
        self.assertNotIn("/", name)
        self.assertFalse(name.startswith("."))

    def test_round_trip(self):
        path = ledger.path_for(self.dir, "slice-a")
        ledger.append_round(path, {"state": "ISSUES", "counts": {"Warning": 1}})
        ledger.append_round(path, {"state": "CLEAN", "counts": {}})
        rounds = ledger.read_rounds(path)
        self.assertEqual([r["state"] for r in rounds], ["ISSUES", "CLEAN"])

    def test_a_missing_ledger_reads_as_no_history(self):
        self.assertEqual(ledger.read_rounds(
            ledger.path_for(self.dir, "never-written")), [])

    def test_a_damaged_line_is_skipped_not_fatal(self):
        path = ledger.path_for(self.dir, "slice-b")
        ledger.append_round(path, {"state": "ISSUES"})
        with open(path, "a") as fh:
            fh.write("{not json\n\n")
        ledger.append_round(path, {"state": "CLEAN"})
        self.assertEqual([r["state"] for r in ledger.read_rounds(path)],
                         ["ISSUES", "CLEAN"])

    def test_concurrent_rounds_do_not_tear_each_other(self):
        # Independent reviews of one slice may finish at the same moment; a
        # torn line would silently drop the history the stop rules run on.
        path = ledger.path_for(self.dir, "slice-c")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(
                lambda n: ledger.append_round(
                    path, {"state": "ISSUES", "n": n, "pad": "x" * 5000}),
                range(64)))
        rounds = ledger.read_rounds(path)
        self.assertEqual(len(rounds), 64)
        self.assertEqual(sorted(r["n"] for r in rounds), list(range(64)))


SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(SKILL_ROOT, "tests", "fake_claude.py")


class TestLedgerCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        for args in (["init", "-q"], ["config", "user.email", "t@t"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True,
                           capture_output=True)
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("print(1)\n")
        subprocess.run(["git", "add", "a.py"], cwd=self.repo, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", "i"], cwd=self.repo, check=True,
                       capture_output=True)
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("print(2)\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, name, mode="issues", *extra):
        run_dir = os.path.join(self.tmp.name, name)
        env = dict(os.environ,
                   CLAUDE_REVIEW_FAKE_CMD=f"{sys.executable} {FAKE} {mode}")
        proc = subprocess.run(
            [sys.executable, os.path.join(SKILL_ROOT, "bin", "claude-review-loop"),
             "--repo", self.repo, "--run-dir", run_dir,
             "--lock-dir", os.path.join(self.tmp.name, "lock"),
             "--ledger-dir", os.path.join(self.tmp.name, "ledger"),
             "--model", "fake/model", *extra],
            capture_output=True, text=True, env=env,
        )
        with open(os.path.join(run_dir, "result.json")) as fh:
            return proc, json.load(fh)

    def test_rounds_accumulate_under_one_slice_id(self):
        _, first = self._run("r1", "issues", "--slice-id", "my-slice")
        _, second = self._run("r2", "issues", "--slice-id", "my-slice")
        self.assertEqual(first["round"], 1)
        self.assertEqual(second["round"], 2)
        self.assertEqual(second["slice_id"], "my-slice")

    def test_a_stuck_finding_escalates_with_its_own_exit_code(self):
        # The fake reviewer returns the same Warning every round.
        self._run("r1", "issues", "--slice-id", "stuck")
        proc, second = self._run("r2", "issues", "--slice-id", "stuck")
        self.assertEqual(proc.returncode, 1, "two rounds is not yet a stuck loop")
        self.assertEqual(second["convergence"]["status"], "progress")
        proc, third = self._run("r3", "issues", "--slice-id", "stuck")
        self.assertEqual(proc.returncode, 4, proc.stdout + proc.stderr)
        self.assertEqual(third["convergence"]["status"], "escalate")
        self.assertIn("LOOP: escalate", proc.stdout)

    def test_a_clean_round_reports_convergence_and_still_exits_zero(self):
        proc, result = self._run("r1", "clean", "--slice-id", "done")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(result["convergence"]["status"], "converged")

    def test_separate_slices_do_not_share_history(self):
        self._run("a1", "issues", "--slice-id", "slice-a")
        self._run("a2", "issues", "--slice-id", "slice-a")
        proc, other = self._run("b1", "issues", "--slice-id", "slice-b")
        self.assertEqual(other["round"], 1)
        self.assertEqual(proc.returncode, 1)

    def test_a_failed_round_is_not_recorded_as_history(self):
        self._run("r1", "issues", "--slice-id", "failing")
        env_run = self._run("r2", "crash", "--slice-id", "failing")
        self.assertEqual(env_run[0].returncode, 2)
        self.assertIsNone(env_run[1]["round"])
        # The next real round is round 2, not round 3.
        _, third = self._run("r3", "issues", "--slice-id", "failing")
        self.assertEqual(third["round"], 2)

    def test_without_a_slice_id_nothing_is_recorded(self):
        proc, result = self._run("r1", "issues")
        self.assertIsNone(result["convergence"])
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("LOOP:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
