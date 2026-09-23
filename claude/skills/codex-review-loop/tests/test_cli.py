import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest

from codex_review_loop import env as env_mod
from tests.helpers import BIN, FAKE, RepoFixture



def git_only_path(root):
    """A PATH that finds git, so the bundle builds, but no codex."""
    directory = os.path.join(root, "git-only-bin")
    os.makedirs(directory, exist_ok=True)
    link = os.path.join(directory, "git")
    if not os.path.exists(link):
        os.symlink(shutil.which("git"), link)
    return directory


class TestCliVerdicts(unittest.TestCase):
    def setUp(self):
        self.fx = RepoFixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_clean_exits_zero_and_records_the_proven_model(self):
        proc, result, _ = self.fx.run("clean")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("REVIEW: CLEAN", proc.stdout)
        self.assertEqual(result["state"], "CLEAN")
        self.assertEqual(result["observed_models"], ["gpt-6-sol"])
        self.assertEqual(result["observed_efforts"], ["medium"])
        self.assertIsNone(result["failure_kind"])

    def test_high_effort_is_passed_through_and_proven(self):
        proc, result, _ = self.fx.run("clean", "--effort", "high")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("effort=high", proc.stdout)
        with open(os.path.join(self.fx.home, "last-argv.json")) as fh:
            self.assertIn('model_reasoning_effort="high"', json.load(fh))
        self.assertEqual(result["effort"], "high")
        self.assertEqual(result["observed_efforts"], ["high"])

    def test_issues_exits_one_with_items(self):
        proc, result, _ = self.fx.run("issues")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(result["items"], [
            {"severity": "Warning", "path": "a.py", "message": "tidy this"}])

    def test_prompt_arrives_on_stdin_never_in_argv(self):
        proc, _, _ = self.fx.run("clean")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(self.fx.home, "last-argv.json")) as fh:
            argv = json.load(fh)
        with open(os.path.join(self.fx.home, "last-stdin.txt")) as fh:
            stdin = fh.read()
        self.assertEqual(argv[-1], "-")
        self.assertIn("review-bundle.md", stdin)
        self.assertNotIn(stdin.strip(), " ".join(argv))
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-sol")

    def test_inherited_codex_home_is_not_used(self):
        stray = os.path.join(self.fx.root, "stray-home")
        os.makedirs(stray)
        proc, result, _ = self.fx.run("clean", env_extra={"CODEX_HOME": stray})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(os.listdir(stray), [])
        self.assertTrue(result["session_record"].startswith(self.fx.home))


class TestCliFailsClosed(unittest.TestCase):
    """Every way the run can go wrong ends in a failed state and exit 2,
    never in a verdict."""

    def setUp(self):
        self.fx = RepoFixture()

    def tearDown(self):
        self.fx.cleanup()

    def assertFailed(self, mode, state, kind, *extra, **kw):
        proc, result, run_dir = self.fx.run(mode, *extra, **kw)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(result["state"], state, result.get("error"))
        self.assertEqual(result["failure_kind"], kind, result.get("error"))
        self.assertEqual(result["items"], [])
        self.assertIsNone(result["baseline_commit"])
        return result, run_dir

    def test_another_model_is_invalid(self):
        result, _ = self.assertFailed("wrong_model", "INVALID", "model_mismatch")
        self.assertIn("gpt-5.6-sol", result["error"])

    def test_another_effort_is_invalid(self):
        self.assertFailed("wrong_effort", "INVALID", "model_mismatch")

    def test_another_effort_than_asked_for_is_invalid(self):
        # The record says low; asking for high does not widen what passes.
        result, _ = self.assertFailed("wrong_effort", "INVALID", "model_mismatch",
                                      "--effort", "high")
        self.assertIn("not high", result["error"])

    def test_a_model_reroute_is_invalid(self):
        self.assertFailed("reroute", "INVALID", "model_mismatch")

    def test_the_word_reroute_in_tool_output_is_not_a_reroute(self):
        # Every fake record carries it inside an exec call's input.
        proc, result, _ = self.fx.run("clean")
        self.assertEqual(result["state"], "CLEAN", result.get("error"))

    def test_a_missing_session_record_is_invalid(self):
        self.assertFailed("no_record", "INVALID", "model_unproven")

    def test_a_record_without_a_turn_is_invalid(self):
        self.assertFailed("no_turn_context", "INVALID", "model_unproven")

    def test_delegation_in_the_record_is_invalid(self):
        result, _ = self.assertFailed("spawn_record", "INVALID", "forbidden_tool")
        self.assertIn("collaboration.spawn_agent", result["forbidden_tool_uses"])

    def test_delegation_in_the_stream_is_invalid(self):
        self.assertFailed("spawn_stream", "INVALID", "forbidden_tool")

    def test_an_unlisted_tool_is_invalid(self):
        self.assertFailed("unlisted_tool", "INVALID", "forbidden_tool")

    def test_a_subagent_record_is_invalid(self):
        self.assertFailed("subagent_meta", "INVALID", "forbidden_tool")

    def test_capacity_is_a_provider_error(self):
        result, _ = self.assertFailed("capacity", "PROVIDER_ERROR", "provider")
        self.assertIn("capacity", result["error"])

    def test_an_error_exit_without_a_turn_is_a_provider_error(self):
        self.assertFailed("error_exit", "PROVIDER_ERROR", "provider")

    def test_a_crash_is_crashed(self):
        self.assertFailed("crash", "CRASHED", "crash")

    def test_a_silent_hang_is_killed_as_a_stall(self):
        started = time.monotonic()
        self.assertFailed("hang", "STALLED", "stall", "--stall-timeout", "1")
        self.assertLess(time.monotonic() - started, 60)

    def test_the_deadline_kills_a_run_that_stays_busy(self):
        self.assertFailed("hang", "STALLED", "deadline",
                          "--stall-timeout", "100", "--review-deadline", "1")

    def test_prose_instead_of_the_schema_is_invalid(self):
        self.assertFailed("bad_json", "INVALID", "verdict")

    def test_clean_with_findings_is_invalid(self):
        self.assertFailed("clean_with_findings", "INVALID", "verdict")

    def test_issues_without_findings_is_invalid(self):
        self.assertFailed("issues_without_findings", "INVALID", "verdict")

    def test_a_nonzero_exit_after_a_completed_turn_is_a_crash(self):
        result, _ = self.assertFailed("exit_after_turn", "CRASHED", "crash")
        self.assertIn("status 2", result["error"])

    def test_a_self_chosen_143_is_not_mistaken_for_the_harness_kill(self):
        self.assertFailed("exit_143_after_turn", "CRASHED", "crash")

    def test_an_unrecordable_round_is_not_a_verdict(self):
        blocker = os.path.join(self.fx.root, "not-a-dir")
        open(blocker, "w").close()
        proc, result, _ = self.fx.run("issues", "--slice-id", "s1",
                                      "--ledger-dir", blocker)
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual((result["state"], result["failure_kind"]),
                         ("INVALID", "ledger"))
        self.assertEqual(len(result["items"]), 1)
        self.assertIsNone(result["baseline_commit"])

    def test_the_reviewer_gets_an_allowlisted_environment(self):
        proc, _, _ = self.fx.run("clean", env_extra={
            "SOME_API_TOKEN": "leak-me", "OPENAI_BASE_URL": "http://proxy",
            "CODEX_HOME": "/elsewhere"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(self.fx.home, "last-env.json")) as fh:
            seen = json.load(fh)
        self.assertNotIn("SOME_API_TOKEN", seen)
        self.assertNotIn("OPENAI_BASE_URL", seen)
        self.assertEqual(seen["CODEX_HOME"], self.fx.home)
        # macOS adds __CF_USER_TEXT_ENCODING inside the child process itself.
        extra = {k for k in seen if k not in env_mod.ALLOWED_VARS
                 and not k.startswith("__CF_")}
        self.assertEqual(extra, {"CODEX_HOME", "FAKE_CODEX_MODE"})

    def test_failed_round_is_not_recorded_in_the_ledger(self):
        self.assertFailed("wrong_model", "INVALID", "model_mismatch",
                          "--slice-id", "s1", "--record-baseline")
        self.assertFalse(os.path.exists(os.path.join(self.fx.ledger, "s1.jsonl")))


class TestCliLifecycle(unittest.TestCase):
    def setUp(self):
        self.fx = RepoFixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_a_reviewer_that_never_exits_after_its_turn_is_reaped(self):
        proc, result, _ = self.fx.run("posthang", "--exit-grace", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(result["state"], "CLEAN")

    def test_a_child_left_behind_by_the_reviewer_is_killed(self):
        proc, result, _ = self.fx.run("orphan")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(self.fx.home, "orphan.pid")) as fh:
            pid = int(fh.read())
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            os.kill(pid, signal.SIGKILL)
            self.fail("the reviewer's child survived the harness")


class TestCliPreflight(unittest.TestCase):
    def setUp(self):
        self.fx = RepoFixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_another_model_is_refused_before_anything_runs(self):
        proc, result, run_dir = self.fx.run("clean", "--model", "gpt-5.6-sol")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("only gpt-6-sol", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.fx.home, "last-argv.json")))

    def test_an_unlisted_effort_is_refused_before_anything_runs(self):
        proc, result, _ = self.fx.run("clean", "--effort", "low")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--effort", proc.stderr)
        self.assertEqual(result["state"], "INVALID")
        self.assertFalse(os.path.exists(os.path.join(self.fx.home, "last-argv.json")))

    def test_a_non_empty_run_dir_is_refused(self):
        run_dir = os.path.join(self.fx.root, "busy")
        os.makedirs(run_dir)
        open(os.path.join(run_dir, "x"), "w").close()
        proc, result, _ = self.fx.run("clean", run_dir=run_dir)
        self.assertEqual(proc.returncode, 2)
        self.assertIsNone(result)

    def test_no_changes_is_invalid_not_clean(self):
        self.fx.write("a.py", "print(1)\n")
        proc, result, _ = self.fx.run("clean")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(result["state"], "INVALID")

    def test_busy_slot_exits_three(self):
        slot = os.path.join(self.fx.lock, "slot-0")
        os.makedirs(slot)
        with open(os.path.join(slot, "meta.json"), "w") as fh:
            fh.write('{"harness_pid": %d, "command": "codex-review-loop",'
                     ' "max_concurrent": 1}' % os.getpid())
        proc, _, _ = self.fx.run("clean")
        self.assertEqual(proc.returncode, 3, proc.stderr)

    def test_the_installed_entry_point_cannot_be_given_a_fake_reviewer(self):
        # The variable the tests use, and the one earlier revisions honoured,
        # are both ignored: with no codex on PATH there is nothing to run.
        run_dir = os.path.join(self.fx.root, "installed")
        env = dict(os.environ, PATH=git_only_path(self.fx.root),
                   CODEX_REVIEW_TEST_BIN=f"{sys.executable} {FAKE}",
                   CODEX_REVIEW_FAKE_BIN=f"{sys.executable} {FAKE}",
                   CODEX_REVIEW_HOME=self.fx.home)
        proc = subprocess.run([sys.executable, BIN, "--repo", self.fx.repo,
                               "--run-dir", run_dir, "--lock-dir", self.fx.lock],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("codex is not on PATH", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.fx.home, "last-argv.json")))
        with open(os.path.join(run_dir, "result.json")) as fh:
            self.assertEqual(json.load(fh)["failure_kind"], "preflight")

    def test_an_invalid_invocation_leaves_a_structured_result(self):
        proc, result, _ = self.fx.run("clean", "--model", "gpt-5.6-sol")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual((result["state"], result["failure_kind"]),
                         ("INVALID", "preflight"))
        self.assertIn("only gpt-6-sol", result["error"])

    def test_an_invalid_slot_limit_in_the_environment_leaves_a_result(self):
        proc, result, _ = self.fx.run(
            "clean", env_extra={"CODEX_REVIEW_MAX_CONCURRENT": "zero"})
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(result["state"], "INVALID")
        self.assertIn("CODEX_REVIEW_MAX_CONCURRENT", result["error"])

    def test_an_invalid_invocation_never_writes_into_a_used_run_dir(self):
        run_dir = os.path.join(self.fx.root, "used")
        os.makedirs(run_dir)
        open(os.path.join(run_dir, "keep"), "w").close()
        proc, result, _ = self.fx.run("clean", "--model", "x", run_dir=run_dir)
        self.assertEqual(proc.returncode, 2)
        self.assertIsNone(result)
        self.assertEqual(os.listdir(run_dir), ["keep"])


class TestCliReviewRoot(unittest.TestCase):
    def setUp(self):
        self.fx = RepoFixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_review_root_holds_only_the_bundle_and_evidence(self):
        evidence = os.path.join(self.fx.root, "backend.py")
        with open(evidence, "w") as fh:
            fh.write("API_KEY = 'sk-abcdefghijklmnopqrstuvwxyz0123'\nx = 1\n")
        proc, result, run_dir = self.fx.run("clean", "--evidence-file", evidence)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        root = os.path.join(run_dir, "review-root")
        listing = sorted(os.path.relpath(os.path.join(d, f), root)
                         for d, _, files in os.walk(root) for f in files)
        self.assertEqual(listing, ["evidence/01-backend.py", "review-bundle.md"])
        with open(os.path.join(root, "evidence", "01-backend.py")) as fh:
            copied = fh.read()
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz0123", copied)
        self.assertIn({"path": "evidence/01-backend.py", "section": "evidence file"},
                      result["redactions"])
        self.assertTrue(result["scoped_clean"])

    def test_a_secret_named_evidence_file_is_refused(self):
        secret = os.path.join(self.fx.root, "prod.env")
        with open(secret, "w") as fh:
            fh.write("X=1\n")
        proc, result, _ = self.fx.run("clean", "--evidence-file", secret)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(result["failure_kind"], "preflight")
        self.assertFalse(os.path.exists(os.path.join(self.fx.home, "last-argv.json")))

    def test_the_review_root_is_the_only_granted_path(self):
        proc, _, run_dir = self.fx.run("clean")
        with open(os.path.join(self.fx.home, "last-argv.json")) as fh:
            argv = json.load(fh)
        root = os.path.realpath(os.path.join(run_dir, "review-root"))
        self.assertEqual(argv[argv.index("-C") + 1], root)
        profile = [a for a in argv if ".filesystem=" in a]
        self.assertEqual(len(profile), 1)
        self.assertIn(json.dumps(root) + '="read"', profile[0])
        self.assertNotIn(self.fx.repo, profile[0])


class TestCliRounds(unittest.TestCase):
    def setUp(self):
        self.fx = RepoFixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_baseline_and_ledger_across_rounds(self):
        proc, first, _ = self.fx.run("issues", "--slice-id", "s1",
                                     "--record-baseline")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertTrue(first["baseline_commit"])
        self.assertEqual(first["round"], 1)
        self.fx.write("a.py", "print(3)\n")
        proc, second, second_dir = self.fx.run(
            "clean", "--slice-id", "s1", "--record-baseline",
            "--baseline-ref", first["baseline_commit"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(second["round"], 2)
        tree = subprocess.run(
            ["git", "rev-parse", first["baseline_commit"] + "^{tree}"],
            cwd=self.fx.repo, capture_output=True, text=True).stdout.strip()
        self.assertEqual(second["baseline_ref"], tree)
        with open(os.path.join(second_dir, "review-root", "review-bundle.md")) as fh:
            bundle = fh.read()
        self.assertIn("+print(3)", bundle)
        self.assertNotIn("+print(2)", bundle)
        with open(os.path.join(self.fx.home, "last-argv.json")) as fh:
            argv = json.load(fh)
        instruction = [a for a in argv if a.startswith("developer_instructions=")][0]
        self.assertIn("This is a re-review", instruction)

    def test_cumulative_review_is_framed_as_a_whole_review(self):
        from tests.helpers import git
        git(self.fx.repo, "commit", "-qam", "c2")
        base = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=self.fx.repo,
                              capture_output=True, text=True).stdout.strip()
        self.fx.write("b.py", "y = 1\n")
        git(self.fx.repo, "add", "b.py")
        git(self.fx.repo, "commit", "-qm", "c3")
        proc, result, run_dir = self.fx.run("clean", "--baseline-ref", base,
                                            "--cumulative")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(run_dir, "review-root", "review-bundle.md")) as fh:
            bundle = fh.read()
        self.assertIn("+print(2)", bundle)
        self.assertIn("+y = 1", bundle)
        with open(os.path.join(self.fx.home, "last-argv.json")) as fh:
            argv = json.load(fh)
        instruction = [a for a in argv if a.startswith("developer_instructions=")][0]
        self.assertNotIn("This is a re-review", instruction)
        with open(os.path.join(run_dir, "review-prompt.txt")) as fh:
            self.assertIn("cumulative review of everything since", fh.read())

    def test_cumulative_without_a_baseline_is_refused(self):
        proc, result, _ = self.fx.run("clean", "--cumulative")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(result["state"], "INVALID")
        self.assertIn("--cumulative needs --baseline-ref", result["error"])
        self.assertFalse(os.path.exists(os.path.join(self.fx.home, "last-argv.json")))


if __name__ == "__main__":
    unittest.main()
