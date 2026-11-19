import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))

import coord_watchdog as cw  # noqa: E402

T0 = 2_000_000_000.0
MIN = 60.0


def write_exe(path: Path, body: str) -> Path:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class Fixture(unittest.TestCase):
    """A throwaway coordination dir with stubbed ps, work, herdr and claude."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cw-test-"))
        self.coord = self.tmp / "coordination"
        self.codex = self.coord / "codex"
        self.kath = self.coord / "katharina"
        for d in (self.codex, self.kath / "logs", self.coord / "acks"):
            d.mkdir(parents=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.calls = self.tmp / "calls.log"
        self.work_rc = self.tmp / "work.rc"
        self.work_rc.write_text("0")
        write_exe(self.bin / "work",
                  f'echo "work $*" >> {self.calls}\n'
                  f'rc=$(cat {self.work_rc}); [ "$1 $2" = "usage status" ] || rc=0\n'
                  f'[ "$rc" = 2 ] && printf "fresh  a\\nSTALE  claude weekly\\n"\nexit $rc\n')
        write_exe(self.bin / "herdr", f'echo "herdr $*" >> {self.calls}\n')
        self.claude_sleep = self.tmp / "claude.sleep"
        self.claude_sleep.write_text("0")
        write_exe(self.bin / "claude",
                  f'cat > {self.tmp}/claude.stdin\n'
                  f'echo "claude $* CONFIG=${{CLAUDE_CONFIG_DIR:-main}}" >> {self.calls}\n'
                  f'sleep $(cat {self.claude_sleep})\n'
                  'echo "Feeder lief nicht; neu gestartet."\n')
        self.ps = self.tmp / "ps.txt"
        self.procs = []
        self.feeder(alive=True)
        self.heartbeat(age_min=1)
        self.env = {
            "CW_COORD_DIR": str(self.coord),
            "CW_PS_OUT": str(self.ps),
            "CW_LOADAVG": "1.0",
            "CW_LOAD_THRESHOLD": "40",
            "CW_SWAPUSAGE": "total = 1024.00M  used = 252.88M  free = 771.12M  (encrypted)",
            "CW_WORK_BIN": str(self.bin / "work"),
            "CW_HERDR_BIN": str(self.bin / "herdr"),
            "CW_CLAUDE_BIN": str(self.bin / "claude"),
            "CW_NOW": str(T0),
        }
        self.write_ps()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers -------------------------------------------------------------
    def feeder(self, alive: bool):
        self.procs = [p for p in self.procs if "feeder" not in p]
        lock = self.codex / "feeder.lock"
        if lock.is_symlink():
            lock.unlink()
        os.symlink("4242", lock)
        if alive:
            self.procs.append("4242 1 0:01.00 /bin/bash ./feeder.sh")

    def write_ps(self):
        self.ps.write_text("\n".join(self.procs) + "\n")

    def heartbeat(self, age_min: float | None):
        """Heartbeat age, applied relative to each check's time (None: missing)."""
        self.hb_age = age_min

    def apply_heartbeat(self, now: float):
        hb = self.coord / "coordinator.heartbeat"
        if self.hb_age is None:
            hb.unlink(missing_ok=True)
            return
        hb.touch()
        os.utime(hb, (now - self.hb_age * MIN, now - self.hb_age * MIN))

    def touch(self, path: Path, at: float, text: str = ""):
        path.write_text(text)
        os.utime(path, (at, at))

    def run_check(self, now: float = T0, extra: dict | None = None, args=("check",)):
        env = dict(self.env, CW_NOW=str(now), **(extra or {}))
        self.write_ps()
        self.apply_heartbeat(now)
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), redirect_stdout(out):
            rc = cw.main(list(args))
        return rc, out.getvalue()

    def keys(self, output: str) -> list[str]:
        return [line.split("\t")[0] for line in output.splitlines() if "\t" in line]

    def state(self) -> dict:
        return json.loads((self.coord / "watchdog" / "state.json").read_text())

    def calls_text(self) -> str:
        return self.calls.read_text() if self.calls.exists() else ""


class HealthyTest(Fixture):
    def test_healthy_cycle_has_no_findings(self):
        rc, out = self.run_check()
        self.assertEqual(rc, 0, out)
        self.assertEqual(out, "")
        latest = json.loads((self.coord / "watchdog" / "latest.json").read_text())
        self.assertEqual(latest["findings"], [])
        self.assertIn("work usage status --max-age 1h --provider claude", self.calls_text())

    def test_dry_run_writes_no_state(self):
        rc, out = self.run_check(args=("check", "--dry-run", "-v"))
        self.assertEqual(rc, 0)
        self.assertIn("# feeder alive", out)
        self.assertFalse((self.coord / "watchdog" / "state.json").exists())


class CodexTest(Fixture):
    def test_dead_feeder_is_a_finding(self):
        self.feeder(alive=False)
        rc, out = self.run_check()
        self.assertEqual(rc, 1)
        self.assertEqual(self.keys(out), ["feeder-dead"])

    def test_dead_feeder_with_deliberate_flag_is_not(self):
        self.feeder(alive=False)
        for flag in ("stop.flag", "autoround.off"):
            (self.codex / flag).write_text("owner")
            rc, out = self.run_check()
            self.assertEqual(rc, 0, out)
            (self.codex / flag).unlink()

    def test_stale_lock_pid_reused_by_other_process(self):
        self.feeder(alive=False)
        self.procs.append("4242 1 0:00.01 /usr/bin/vim notes")
        _, out = self.run_check()
        self.assertEqual(self.keys(out), ["feeder-dead"])

    def test_queue_stalled(self):
        (self.codex / "queue.txt").write_text("cx-a\ncx-b\n")
        self.touch(self.codex / "started.txt", T0 - 121 * MIN)
        self.touch(self.codex / "feeder.log", T0, "x start cx-z\n")
        _, out = self.run_check()
        self.assertEqual(self.keys(out), ["codex-queue-stalled"])
        self.touch(self.codex / "feeder.log", T0, "Tue quota guard refused\n")
        _, out = self.run_check()
        self.assertEqual(self.keys(out), [])
        self.touch(self.codex / "started.txt", T0 - 10 * MIN)
        self.touch(self.codex / "feeder.log", T0, "x\n")
        _, out = self.run_check()
        self.assertEqual(self.keys(out), [])

    def test_automerge_off_age(self):
        self.touch(self.kath / "automerge.off", T0 - 60 * MIN, "testing\n")
        _, out = self.run_check()
        self.assertEqual(self.keys(out), [])
        self.touch(self.kath / "automerge.off", T0 - 1441 * MIN, "testing\n")
        _, out = self.run_check()
        self.assertEqual(self.keys(out), ["automerge-off"])
        self.assertIn("testing", out)


class KatharinaTest(Fixture):
    def worker(self, name: str, cpu: str = "0:10.00", pid: int = 500):
        (self.kath / f"{name}.md").write_text("brief")
        self.procs = [p for p in self.procs if not p.startswith(f"{pid} ") and not p.startswith(f"{pid + 1} ")]
        self.procs.append(f"{pid} 1 0:00.01 /bin/bash ./run.sh {name}")
        self.procs.append(f"{pid + 1} {pid} {cpu} claude -p --permission-mode auto --model x")
        (self.kath / f"{name}.out").touch()
        (self.kath / "logs" / f"{name}.log").touch()

    def test_worker_detection_ignores_codex_and_deferred_starts(self):
        (self.codex / "cx-job.md").write_text("b")
        self.procs.append("600 1 0:00.01 /bin/bash ./run.sh cx-job")
        (self.kath / "later.md").write_text("b")
        self.procs.append('601 1 0:00.01 bash -c until [ 1 ]; do sleep 60; done; ./run.sh later')
        self.worker("k1")
        self.write_ps()
        procs = cw.read_procs(cw.Config.load(None, self.env))
        self.assertEqual(list(cw.katharina_workers(cw.Config.load(None, self.env), procs)), ["k1"])

    def test_stuck_worker(self):
        self.worker("k1", cpu="0:10.00")
        self.run_check(T0)
        _, out = self.run_check(T0 + 30 * MIN, {"CW_ESCALATE_MIN": "999"})
        self.assertEqual(self.keys(out), [])
        # Small CPU drift does not count as progress.
        self.worker("k1", cpu="0:15.00")
        _, out = self.run_check(T0 + 61 * MIN, {"CW_ESCALATE_MIN": "999"})
        self.assertEqual(self.keys(out), ["stuck:k1"])
        # Real CPU progress (e.g. a test run in a child) resets it.
        self.worker("k1", cpu="1:15.00")
        _, out = self.run_check(T0 + 62 * MIN, {"CW_ESCALATE_MIN": "999"})
        self.assertEqual(self.keys(out), [])

    def test_log_growth_is_progress_and_child_cpu_counts(self):
        self.worker("k1")
        self.run_check(T0)
        (self.kath / "logs" / "k1.log").write_text("warning\n")
        _, out = self.run_check(T0 + 61 * MIN)
        self.assertEqual(self.keys(out), [])
        self.procs.append("700 501 2:00.00 python -m pytest")
        _, out = self.run_check(T0 + 122 * MIN)
        self.assertEqual(self.keys(out), [])
        _, out = self.run_check(T0 + 183 * MIN)
        self.assertEqual(self.keys(out), ["stuck:k1"])

    def test_cpu_drop_after_child_exit_does_not_mask_progress(self):
        self.worker("k1", cpu="0:10.00")
        self.procs.append("700 501 5:00.00 python -m pytest")
        self.run_check(T0)
        self.procs = [p for p in self.procs if not p.startswith("700 ")]
        # Tree total fell by 300 s; the worker keeps working afterwards.
        self.worker("k1", cpu="0:20.00")
        self.run_check(T0 + 30 * MIN)
        self.worker("k1", cpu="0:45.00")
        _, out = self.run_check(T0 + 61 * MIN)
        self.assertEqual(self.keys(out), [])
        self.assertEqual(self.state()["workers"]["k1"]["progress_at"], T0 + 61 * MIN)

    def test_restarted_worker_starts_fresh(self):
        self.worker("k1", pid=500)
        self.run_check(T0)
        self.procs = [p for p in self.procs if not p.startswith(("500 ", "501 "))]
        self.worker("k1", pid=800)
        _, out = self.run_check(T0 + 61 * MIN)
        self.assertEqual(self.keys(out), [])

    def test_unacknowledged_report(self):
        self.run_check(T0)  # baseline: since = T0
        self.touch(self.kath / "old.out", T0 - 60 * MIN, "old report")
        self.touch(self.kath / "done.out", T0 + 5 * MIN, "report")
        self.touch(self.kath / "logs" / "done.log", T0 + 5 * MIN)
        _, out = self.run_check(T0 + 20 * MIN, {"CW_ESCALATE_MIN": "999"})
        self.assertEqual(self.keys(out), [])
        _, out = self.run_check(T0 + 40 * MIN, {"CW_ESCALATE_MIN": "999"})
        self.assertEqual(self.keys(out), ["unacked:done"])
        self.touch(self.coord / "acks" / "done", T0 + 41 * MIN)
        _, out = self.run_check(T0 + 42 * MIN, {"CW_ESCALATE_MIN": "999"})
        self.assertEqual(self.keys(out), [])
        # A rerun of the same name needs a new acknowledgement.
        self.touch(self.kath / "done.out", T0 + 50 * MIN, "report 2")
        _, out = self.run_check(T0 + 90 * MIN, {"CW_ESCALATE_MIN": "999"})
        self.assertEqual(self.keys(out), ["unacked:done"])

    def test_running_worker_report_is_not_unacked(self):
        self.run_check(T0)
        self.worker("k1", cpu="0:01.00")
        self.touch(self.kath / "k1.out", T0 + 1)
        self.worker("k1", cpu="0:01.00")
        os.utime(self.kath / "k1.out", (T0 + 1, T0 + 1))
        _, out = self.run_check(T0 + 40 * MIN)
        self.assertNotIn("unacked:k1", self.keys(out))


class UsageHeartbeatLoadTest(Fixture):
    def test_usage_stale_and_error(self):
        self.work_rc.write_text("2")
        _, out = self.run_check()
        self.assertEqual(self.keys(out), ["usage-stale"])
        self.assertIn("STALE claude weekly", out)
        self.assertNotIn("fresh", out)
        self.work_rc.write_text("1")
        _, out = self.run_check()
        self.assertEqual(self.keys(out), ["usage-check"])

    def test_usage_providers_setting(self):
        self.run_check(extra={"CW_USAGE_PROVIDERS": "claude, codex"})
        calls = self.calls_text()
        self.assertIn("--provider claude", calls)
        self.assertIn("--provider codex", calls)
        self.calls.unlink()
        self.run_check(extra={"CW_USAGE_PROVIDERS": ""})
        self.assertNotIn("--provider", self.calls_text())

    def test_heartbeat(self):
        self.heartbeat(age_min=46)
        _, out = self.run_check()
        self.assertEqual(self.keys(out), ["heartbeat"])
        self.heartbeat(age_min=None)
        _, out = self.run_check()
        self.assertIn("missing", out)
        self.heartbeat(age_min=44)
        _, out = self.run_check()
        self.assertEqual(self.keys(out), [])

    def test_swap_must_be_sustained(self):
        high = {"CW_SWAPUSAGE": "total = 20480.00M  used = 17408.00M  free = 3072.00M  (encrypted)"}
        _, out = self.run_check(T0, high)
        self.assertEqual(self.keys(out), [])
        _, out = self.run_check(T0 + 14 * MIN, high)
        self.assertEqual(self.keys(out), [])
        _, out = self.run_check(T0 + 16 * MIN, dict(high, CW_ESCALATE_MIN="999"))
        self.assertEqual(self.keys(out), ["swap"])
        self.assertIn("17.0 GB above 16 GB", out)
        _, out = self.run_check(T0 + 17 * MIN)
        self.assertEqual(self.keys(out), [])
        self.assertNotIn("swap_high_since", self.state())
        _, out = self.run_check(T0 + 18 * MIN, high)
        self.assertEqual(self.keys(out), [])

    def test_failed_swap_read_keeps_an_open_finding(self):
        high = {"CW_SWAPUSAGE": "total = 20480.00M  used = 17408.00M  free = 3072.00M"}
        unreadable = {"CW_SWAPUSAGE": "garbage"}
        self.run_check(T0, high)
        _, out = self.run_check(T0 + 16 * MIN, dict(high, CW_ESCALATE_MIN="999"))
        self.assertEqual(self.keys(out), ["swap"])
        _, out = self.run_check(T0 + 17 * MIN, dict(unreadable, CW_ESCALATE_MIN="999"))
        self.assertEqual(self.keys(out), ["swap"])
        self.assertIn("current reading failed", out)
        log = (self.coord / "watchdog" / "watchdog.log").read_text()
        self.assertNotIn("resolved swap", log)
        self.assertEqual(log.count("new swap"), 1)
        # a failed read never opens a finding, also not after the sustain time
        self.run_check(T0 + 18 * MIN)
        self.run_check(T0 + 19 * MIN, high)
        _, out = self.run_check(T0 + 20 * MIN, unreadable)
        self.assertEqual(self.keys(out), [])
        _, out = self.run_check(T0 + 36 * MIN, unreadable)
        self.assertEqual(self.keys(out), [])
        _, out = self.run_check(T0 + 37 * MIN, dict(high, CW_ESCALATE_MIN="999"))
        self.assertEqual(self.keys(out), ["swap"])

    def test_swap_usage_parsing(self):
        self.assertEqual(cw.swap_used_bytes("total = 1024.00M  used = 252.88M  free = 771.12M"),
                         252.88 * 1024 ** 2)
        self.assertEqual(cw.swap_used_bytes("total = 80.00G  used = 71.50G  free = 8.50G"), 71.5 * 1024 ** 3)
        self.assertEqual(cw.swap_used_bytes("used = 0"), 0.0)
        self.assertIsNone(cw.swap_used_bytes(""))
        self.assertIsNone(cw.swap_used_bytes("vm.swapusage: unknown oid"))

    def test_unreadable_swap_is_not_a_finding(self):
        real_run = cw.subprocess.run

        def run(argv, *args, **kwargs):
            if argv[0] == "sysctl":
                raise OSError("no sysctl")
            return real_run(argv, *args, **kwargs)

        with mock.patch.object(cw.subprocess, "run", side_effect=run):
            _, out = self.run_check(T0, {"CW_SWAPUSAGE": ""})
        self.assertEqual(self.keys(out), [])
        latest = json.loads((self.coord / "watchdog" / "latest.json").read_text())
        self.assertIn("swap unknown", latest["info"])

    def test_load_must_be_sustained(self):
        high = {"CW_LOADAVG": "50"}
        _, out = self.run_check(T0, high)
        self.assertEqual(self.keys(out), [])
        _, out = self.run_check(T0 + 29 * MIN, high)
        self.assertEqual(self.keys(out), [])
        _, out = self.run_check(T0 + 31 * MIN, dict(high, CW_ESCALATE_MIN="999"))
        self.assertEqual(self.keys(out), ["load"])
        _, out = self.run_check(T0 + 32 * MIN, {"CW_LOADAVG": "10"})
        self.assertEqual(self.keys(out), [])
        _, out = self.run_check(T0 + 33 * MIN, high)
        self.assertEqual(self.keys(out), [])


class EscalationTest(Fixture):
    def wait_diag(self):
        diag = self.state()["diag"]
        status = Path(diag["dir"]) / "status.json"
        deadline = time.time() + 20
        while not status.exists() and time.time() < deadline:
            time.sleep(0.1)
        self.assertTrue(status.exists(), "diag run did not finish")
        return diag, json.loads(status.read_text())

    def notifications(self) -> list[str]:
        p = self.coord / "watchdog" / "notifications.log"
        return p.read_text().splitlines() if p.exists() else []

    def test_full_escalation_once(self):
        self.feeder(alive=False)
        self.run_check(T0)
        self.assertIsNone(self.state()["findings"]["feeder-dead"]["diag"])
        self.run_check(T0 + 10 * MIN)
        self.assertNotIn("diag", self.state())
        self.run_check(T0 + 16 * MIN)
        diag, status = self.wait_diag()
        self.assertEqual(status["rc"], 0)
        self.assertFalse(status["timed_out"])
        brief = (Path(diag["dir"]) / "brief.md").read_text()
        self.assertIn("feeder-dead", brief)
        self.assertIn("BACKLOG_MAX=20 BACKLOG_HOURS=48", brief)
        self.assertIn("coord-watchdog restart-feeder", brief)
        self.assertIn("You have 15 minutes", brief)
        self.assertIn("at least 15 minutes", brief)
        self.assertNotIn("{{", brief)
        self.assertIn(str(self.coord), brief)
        self.assertIn("--model claude-opus-5-5", self.calls_text())
        self.assertIn("CONFIG=" + str(Path.home() / ".claude-katharina"), self.calls_text())
        self.assertEqual(self.notifications(), [])
        self.run_check(T0 + 21 * MIN)
        notes = self.notifications()
        self.assertEqual(len(notes), 1)
        self.assertIn("feeder-dead", notes[0])
        self.assertIn("Feeder lief nicht", notes[0])
        calls = self.calls_text()
        self.assertIn("herdr notification show", calls)
        self.assertIn("work note coord-watchdog", calls)
        # No repeats while the finding stays open.
        for m in (26, 31, 90):
            self.run_check(T0 + m * MIN)
        self.assertEqual(len(self.notifications()), 1)
        self.assertEqual(self.calls_text().count("claude -p"), 1)

    def test_resolution_and_rate_limited_recurrence(self):
        self.feeder(alive=False)
        self.run_check(T0)
        self.run_check(T0 + 16 * MIN)
        self.wait_diag()
        self.feeder(alive=True)
        self.run_check(T0 + 21 * MIN)
        self.assertEqual(self.state()["findings"], {})
        notes = self.notifications()
        self.assertEqual(len(notes), 1)
        self.assertIn("behoben", notes[0])
        self.feeder(alive=False)
        self.run_check(T0 + 30 * MIN)
        self.run_check(T0 + 46 * MIN)
        notes = self.notifications()
        self.assertEqual(len(notes), 2)
        self.assertIn("kein neuer Diagnoselauf", notes[1])
        self.assertEqual(self.calls_text().count("claude -p"), 1)

    def test_finished_run_is_notified_before_a_new_run_replaces_it(self):
        self.feeder(alive=False)
        extra = {"CW_DIAG_MIN_INTERVAL_MIN": "1"}
        self.run_check(T0, extra)
        self.run_check(T0 + 16 * MIN, extra)
        self.wait_diag()
        # A second finding becomes due in the same cycle that sees run 1 done.
        self.heartbeat(age_min=60)
        self.run_check(T0 + 17 * MIN, extra)
        self.run_check(T0 + 33 * MIN, extra)
        notes = self.notifications()
        self.assertEqual(len(notes), 1)
        self.assertIn("feeder-dead", notes[0])
        self.assertTrue(self.state()["findings"]["feeder-dead"]["notified"])
        self.wait_diag()
        self.run_check(T0 + 38 * MIN, extra)
        notes = self.notifications()
        self.assertEqual(len(notes), 2)
        self.assertIn("heartbeat", notes[1])
        self.assertNotIn("feeder-dead", notes[1])

    def test_diag_disabled_notifies_directly(self):
        self.heartbeat(age_min=60)
        self.run_check(T0, {"CW_DIAG_ENABLED": "0"})
        self.run_check(T0 + 16 * MIN, {"CW_DIAG_ENABLED": "0"})
        notes = self.notifications()
        self.assertEqual(len(notes), 1)
        self.assertIn("Diagnose deaktiviert", notes[0])
        self.assertNotIn("claude -p", self.calls_text())

    def test_diag_timeout_is_killed(self):
        self.claude_sleep.write_text("30")
        self.heartbeat(age_min=60)
        extra = {"CW_DIAG_TIMEOUT_MIN": "0.03"}
        self.run_check(T0, extra)
        started = time.time()
        self.run_check(T0 + 16 * MIN, extra)
        _, status = self.wait_diag()
        self.assertTrue(status["timed_out"])
        self.assertLess(time.time() - started, 15)
        self.run_check(T0 + 21 * MIN, extra)
        self.assertIn("Zeitlimit", self.notifications()[0])

    def test_message_stage_when_configured(self):
        msg = write_exe(self.bin / "msg", f'echo "msg $*" >> {self.calls}\n')
        self.heartbeat(age_min=60)
        extra = {"CW_MESSAGE_CMD": f"{msg} --to coordinator"}
        self.run_check(T0, extra)
        self.run_check(T0 + 5 * MIN, extra)
        lines = [ln for ln in self.calls_text().splitlines() if ln.startswith("msg ")]
        self.assertEqual(len(lines), 1)
        self.assertIn("--to coordinator Watchdog: heartbeat-stale", lines[0])
        self.assertTrue(self.state()["findings"]["heartbeat"]["message"])

    def test_lock_refuses_second_check(self):
        import fcntl
        wd = self.coord / "watchdog"
        wd.mkdir()
        with open(wd / "lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            rc, _ = self.run_check()
        self.assertEqual(rc, 3)


class RestartFeederTest(Fixture):
    def setUp(self):
        super().setUp()
        write_exe(self.codex / "feeder.sh",
                  'echo "$(date) feeder started (pid $$, MAX=6, BACKLOG_MAX=${BACKLOG_MAX:-default}, '
                  'BACKLOG_HOURS=${BACKLOG_HOURS:-default})"\n')

    def restart(self):
        return self.run_check(args=("restart-feeder",))

    def test_starts_dead_feeder_with_documented_env(self):
        self.feeder(alive=False)
        rc, out = self.restart()
        self.assertEqual(rc, 0, out)
        log = (self.codex / "feeder.log").read_text()
        self.assertIn("BACKLOG_MAX=20, BACKLOG_HOURS=48", log)

    def test_refuses_live_feeder_and_deliberate_pause(self):
        rc, out = self.restart()
        self.assertEqual(rc, 1)
        self.assertIn("already running", out)
        self.feeder(alive=False)
        (self.codex / "stop.flag").touch()
        rc, out = self.restart()
        self.assertEqual(rc, 1)
        self.assertFalse((self.codex / "feeder.log").exists())

    def test_reports_feeder_that_does_not_start(self):
        self.feeder(alive=False)
        write_exe(self.codex / "feeder.sh", 'echo "feeder lock taken, exiting"; exit 1\n')
        rc, out = self.restart()
        self.assertEqual(rc, 2)
        self.assertIn("lock taken", out)


class UnitTest(unittest.TestCase):
    def test_parse_cputime(self):
        self.assertEqual(cw.parse_cputime("0:34.18"), 34.18)
        self.assertEqual(cw.parse_cputime("123:00.50"), 7380.5)
        self.assertEqual(cw.parse_cputime("1:02:03"), 3723)
        self.assertEqual(cw.parse_cputime("2-00:00:01"), 172801)

    def test_config_file_and_env(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as fh:
            fh.write("# comment\nSTUCK_MIN=90\nCW_ACK_MIN = 10\n")
        try:
            cfg = cw.Config.load(fh.name, {"CW_STUCK_MIN": "120"})
            self.assertEqual(cfg.f("STUCK_MIN"), 120)
            self.assertEqual(cfg.f("ACK_MIN"), 10)
            Path(fh.name).write_text("BOGUS=1\n")
            with self.assertRaises(cw.ConfigError):
                cw.Config.load(fh.name, {})
        finally:
            os.unlink(fh.name)
        with self.assertRaises(cw.ConfigError):
            cw.Config.load(None, {"CW_STUCK_MIN": "soon"})
        with self.assertRaises(cw.ConfigError):
            cw.Config.load(None, {"CW_USAGE_MAX_AGE": "an hour"})

    def test_default_load_threshold_scales_with_cpus(self):
        cfg = cw.Config.load(None, {})
        self.assertEqual(cfg.load_threshold, 2.5 * (os.cpu_count() or 1))


if __name__ == "__main__":
    unittest.main()
