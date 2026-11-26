"""tm-guard: hermetic tests with stub tmutil, defaults, ssh and ps programs."""

from __future__ import annotations

import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tm_guard as tg

NOW = 1_795_170_000

IDLE = {"ClientID": "com.apple.backupd", "Percent": -1.0, "Running": False}
RUNNING = {
    "BackupPhase": "Copying",
    "ClientID": "com.apple.backupd",
    "DateOfStateChange": datetime(2026, 11, 20, 10, 0, 0),
    "DestinationID": "961C5A71-4F55-429C-9B9F-D9C8D03C16B7",
    "Percent": 0.25,
    "Progress": {"Percent": 0.25, "bytes": 1000, "files": 10, "totalBytes": 4000, "totalFiles": 40, "TimeRemaining": 99},
    "Running": 1,
    "Stopping": 0,
}


def script(path: Path, body: str) -> str:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tm-guard-test-"))
        self.state = self.tmp / "state"
        self.status = self.tmp / "status.plist"
        self.set_status(IDLE)
        (self.tmp / "auto").write_text("0\n")
        (self.tmp / "band").write_text(f"{NOW - 600}.123456\n")
        (self.tmp / "ps").write_text("")
        env = {
            "TM_GUARD_STATE": str(self.state),
            "TM_GUARD_TMUTIL": script(
                self.tmp / "tmutil",
                f'echo run >> "{self.tmp}/tmutil.calls"\n'
                f'if [ -f "{self.tmp}/tmutil.sleep" ]; then sleep 30; fi\n'
                f'if [ -f "{self.tmp}/tmutil.fail" ]; then echo broken >&2; exit 4; fi\n'
                f'cat "{self.status}"\n',
            ),
            "TM_GUARD_DEFAULTS": script(self.tmp / "defaults", f'cat "{self.tmp}/auto"\n'),
            "TM_GUARD_PS": script(self.tmp / "ps-stub", f'cat "{self.tmp}/ps"\n'),
            "TM_GUARD_SSH": script(
                self.tmp / "ssh",
                f'printf "%s\\n" "$@" > "{self.tmp}/ssh.args.$$"\n'
                'last="${@: -1}"\n'
                'case "$last" in\n'
                f'  *" timemachine") cat > "{self.tmp}/sent.json"; exit "$(cat "{self.tmp}/send.exit" 2>/dev/null || echo 0)";;\n'
                f'  *) if [ -f "{self.tmp}/band.fail" ]; then echo "no route" >&2; exit 255; fi; cat "{self.tmp}/band";;\n'
                "esac\n",
            ),
            "TM_GUARD_BAND_HOST": "root@fractal.example",
            "TM_GUARD_BUNDLE": "/fast/timemachine/studio.sparsebundle",
            "TM_GUARD_HOST": "root@macmini.example",
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_status(self, data: dict) -> None:
        self.status.write_bytes(plistlib.dumps(data))

    def run_check(self, *args: str) -> int:
        with mock.patch("sys.stdout"):
            return tg.main(list(args))

    def sent(self) -> dict:
        return json.loads((self.tmp / "sent.json").read_text())

    def tmutil_calls(self) -> int:
        path = self.tmp / "tmutil.calls"
        return len(path.read_text().splitlines()) if path.exists() else 0


class ParseTests(unittest.TestCase):
    def test_running_status(self) -> None:
        fields = tg.parse_status(plistlib.dumps(RUNNING))
        self.assertEqual(
            fields,
            {
                "running": True,
                "stopping": False,
                "phase": "Copying",
                "percent": 0.25,
                "bytes": 1000,
                "files": 10,
                "total_bytes": 4000,
                "total_files": 40,
                "state_changed": "2026-11-20T10:00:00",
                "destination_id": RUNNING["DestinationID"].lower(),
            },
        )

    def test_counts_accept_only_exact_integers_in_range(self) -> None:
        for value, expected in (
            ("9007199254740993", 9007199254740993), ("1.0", 1), ("1e3", 1000), (4.0, 4),
            (10**16 - 1, 10**16 - 1), (10**16, None), ("0.01", None),
            ("9007199254740992.01", None), (1.5, None), (True, None), (-1, None),
            ("Infinity", None), ("NaN", None),
        ):
            with self.subTest(value=value):
                fields = tg.parse_status(plistlib.dumps({"Running": True, "bytes": value}))
                self.assertEqual(fields["bytes"], expected)

    def test_idle_status_has_no_percent(self) -> None:
        fields = tg.parse_status(plistlib.dumps(IDLE))
        self.assertFalse(fields["running"])
        self.assertIsNone(fields["percent"])
        self.assertEqual(fields["phase"], "")

    def test_odd_phase_characters_are_replaced(self) -> None:
        fields = tg.parse_status(plistlib.dumps({**RUNNING, "BackupPhase": "Thin;ning$" + "x" * 80}))
        self.assertEqual(fields["phase"], ("Thin_ning_" + "x" * 80)[:60])
        # What macmini's obs_ctl.py accepts (ops-deploy: [A-Za-z0-9_. -]{0,60}).
        self.assertRegex(fields["phase"], r"^[A-Za-z0-9_. -]{0,60}$")

    def test_boolean_flags(self) -> None:
        fields = tg.parse_status(plistlib.dumps({**RUNNING, "Running": True, "Stopping": True}))
        self.assertEqual((fields["running"], fields["stopping"]), (True, True))
        fields = tg.parse_status(plistlib.dumps({**RUNNING, "Running": False, "Stopping": False}))
        self.assertEqual((fields["running"], fields["stopping"]), (False, False))

    def test_a_status_without_running_is_unreadable(self) -> None:
        with self.assertRaises(ValueError):
            tg.parse_status(plistlib.dumps({"ClientID": "com.apple.backupd"}))
        with self.assertRaises(ValueError):
            tg.parse_status(plistlib.dumps({"Running": "maybe"}))

    def test_not_a_plist(self) -> None:
        with self.assertRaises(ValueError):
            tg.parse_status(b"Backup session status:\n{\n}")
        with self.assertRaises(ValueError):
            tg.parse_status(plistlib.dumps([1, 2]))


class TrackTests(unittest.TestCase):
    def fields(self, **changes: object) -> dict:
        return {**tg.parse_status(plistlib.dumps(RUNNING)), **changes}

    def test_idle_never_stalls(self) -> None:
        state, stalled = tg.track(None, "ok", {"running": False}, NOW, NOW)
        state, stalled = tg.track(state, "ok", {"running": False}, NOW, NOW + 9 * 3600)
        self.assertEqual(stalled, 0)
        self.assertEqual(state["progress_epoch"], NOW + 9 * 3600)

    def test_a_running_backup_without_any_change_stalls(self) -> None:
        state, stalled = tg.track(None, "ok", self.fields(), NOW, NOW)
        self.assertEqual(stalled, 0)
        state, stalled = tg.track(state, "ok", self.fields(), NOW, NOW + 3 * 3600)
        self.assertEqual(stalled, 3 * 3600)

    def test_counter_or_phase_changes_are_progress(self) -> None:
        state, _ = tg.track(None, "ok", self.fields(), NOW, NOW)
        state, stalled = tg.track(state, "ok", self.fields(bytes=2000), NOW, NOW + 3600)
        self.assertEqual(stalled, 0)
        state, stalled = tg.track(state, "ok", self.fields(bytes=2000, phase="ThinningPostBackup"), NOW, NOW + 7200)
        self.assertEqual(stalled, 0)
        state, stalled = tg.track(state, "ok", self.fields(bytes=2000, phase="ThinningPostBackup"), NOW, NOW + 9000)
        self.assertEqual(stalled, 1800)

    def test_a_newer_band_write_is_progress_while_counters_stand_still(self) -> None:
        state, _ = tg.track(None, "ok", self.fields(), NOW, NOW)
        state, stalled = tg.track(state, "ok", self.fields(), NOW + 3000, NOW + 3600)
        self.assertEqual(stalled, 0)
        # The same newest band again, or a failed read, is no progress.
        state, stalled = tg.track(state, "ok", self.fields(), NOW + 3000, NOW + 7200)
        self.assertEqual(stalled, 3600)
        state, stalled = tg.track(state, "ok", self.fields(), None, NOW + 9000)
        self.assertEqual(stalled, 5400)
        self.assertEqual(state["band_max"], NOW + 3000)

    def test_a_backup_that_just_started_counts_from_now(self) -> None:
        state, _ = tg.track(None, "ok", {"running": False}, NOW, NOW)
        state, stalled = tg.track(state, "ok", self.fields(), NOW, NOW + 7200)
        self.assertEqual(stalled, 0)

    def test_a_new_backup_after_idle_can_make_progress_with_older_bands(self) -> None:
        running, _ = tg.track(None, "ok", self.fields(), NOW, NOW)
        idle, _ = tg.track(running, "ok", {"running": False}, NOW, NOW + 300)
        for first_band in (NOW - 900, None):
            with self.subTest(first_band=first_band):
                state, stalled = tg.track(idle, "ok", self.fields(), first_band, NOW + 600)
                self.assertEqual((state["band_max"], stalled), (first_band, 0))
                state, stalled = tg.track(state, "ok", self.fields(), NOW - 900, NOW + 900)
                self.assertEqual((state["band_max"], stalled), (NOW - 900, 300))
                _, stalled = tg.track(state, "ok", self.fields(), NOW - 600, NOW + 1200)
                self.assertEqual(stalled, 0)

    def test_a_silent_tmutil_carries_the_count_on(self) -> None:
        state, _ = tg.track(None, "ok", self.fields(), NOW, NOW)
        state, stalled = tg.track(state, "timeout", {}, NOW, NOW + 7200)
        self.assertEqual(stalled, 7200)
        self.assertTrue(state["running"])
        # Bands still written while tmutil hangs: progress.
        state, stalled = tg.track(state, "hung", {}, NOW + 7000, NOW + 7500)
        self.assertEqual(stalled, 0)

    def test_a_clock_rollback_restarts_stall_accounting(self) -> None:
        state, _ = tg.track(None, "ok", self.fields(), NOW, NOW)
        state, stalled = tg.track(state, "ok", self.fields(), NOW, NOW + 600)
        self.assertEqual(stalled, 600)
        for rolled_back in (NOW - 3600, NOW + 300):
            with self.subTest(rolled_back=rolled_back):
                rebased, stalled = tg.track(state, "timeout", {}, None, rolled_back)
                self.assertEqual(stalled, 0)
                self.assertEqual(rebased["progress_epoch"], rolled_back)
                self.assertTrue(rebased["running"])
                self.assertEqual(rebased["fingerprint"], state["fingerprint"])
                rebased, stalled = tg.track(rebased, "ok", self.fields(), NOW, rolled_back + 300)
                self.assertEqual(stalled, 300)
                _, stalled = tg.track(rebased, "ok", self.fields(bytes=2000), NOW, rolled_back + 600)
                self.assertEqual(stalled, 0)

    def test_band_writes_after_a_clock_rollback_count_while_tmutil_is_silent(self) -> None:
        state, _ = tg.track(None, "ok", self.fields(), NOW + 3000, NOW)
        state, _ = tg.track(state, "ok", self.fields(), NOW + 3000, NOW + 3600)
        rolled_back = NOW - 3600
        state, stalled = tg.track(state, "timeout", {}, rolled_back - 60, rolled_back)
        self.assertEqual((state["band_max"], stalled), (rolled_back - 60, 0))
        state, stalled = tg.track(state, "timeout", {}, rolled_back + 500, rolled_back + 600)
        self.assertEqual((state["band_max"], stalled), (rolled_back + 500, 0))
        _, stalled = tg.track(state, "hung", {}, rolled_back + 500, rolled_back + 1200)
        self.assertEqual(stalled, 600)

    def test_a_foreign_state_format_starts_over(self) -> None:
        state, stalled = tg.track({"format": 99, "running": True, "progress_epoch": 0}, "ok", self.fields(), NOW, NOW)
        self.assertEqual((stalled, state["format"]), (0, tg.STATE_FORMAT))


class StateReadTests(unittest.TestCase):
    def test_fifo_is_missing_state_without_a_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            os.mkfifo(state)
            result = subprocess.run(
                [sys.executable, "-c", "import sys, tm_guard; from pathlib import Path; "
                 "assert tm_guard.read_json(Path(sys.argv[1])) is None", str(state)],
                cwd=Path(tg.__file__).parent,
                timeout=2,
            )
            self.assertEqual(result.returncode, 0)

    def test_oversized_valid_json_is_missing_but_small_state_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            progress, _ = tg.track(None, "ok", {"running": True}, NOW, NOW)
            tg.write_atomic(state, progress)
            self.assertEqual(tg.read_json(state), progress)
            with state.open("ab") as handle:
                handle.write(b" " * (64 * 1024))
            self.assertIsNone(tg.read_json(state))


class BoundedTests(unittest.TestCase):
    def test_output_and_exit_code(self) -> None:
        done = tg.bounded(["/bin/sh", "-c", "echo out; echo err >&2; exit 3"], 10)
        self.assertEqual((done.status, done.code, done.stdout, done.stderr), ("ok", 3, b"out\n", b"err\n"))

    def test_stdin_is_passed(self) -> None:
        done = tg.bounded(["/bin/cat"], 10, stdin=b"payload")
        self.assertEqual(done.stdout, b"payload")

    def test_a_slow_child_is_killed_by_its_own_pid(self) -> None:
        started = time.monotonic()
        done = tg.bounded(["/bin/sleep", "30"], 0.5)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(done.status, "timeout")
        self.assertTrue(done.reaped)
        with self.assertRaises(ProcessLookupError):
            os.kill(done.pid, 0)

    def test_a_child_that_keeps_its_pipes_open_is_still_bounded(self) -> None:
        started = time.monotonic()
        done = tg.bounded(["/bin/sh", "-c", "echo partial; exec sleep 30"], 0.5)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual((done.status, done.stdout), ("timeout", b"partial\n"))

    def test_a_missing_program_is_an_error(self) -> None:
        self.assertEqual(tg.bounded(["/nonexistent/tmutil"], 1).status, "error")

    def test_output_is_capped(self) -> None:
        with mock.patch.object(tg, "MAX_OUTPUT", 10):
            done = tg.bounded(["/bin/sh", "-c", "printf '%0100d' 0"], 10)
        self.assertEqual(len(done.stdout), 10)


class CycleTests(Base):
    def test_idle_with_automatic_backups_off_is_ok(self) -> None:
        self.assertEqual(self.run_check(), 0)
        sent = self.sent()
        self.assertEqual(
            {k: sent[k] for k in ("tmutil", "running", "auto_backup", "stalled_seconds", "band_check", "cross_check_ok")},
            {
                "tmutil": "ok",
                "running": False,
                "auto_backup": False,
                "stalled_seconds": 0,
                "band_check": "ok",
                "cross_check_ok": True,
            },
        )
        self.assertEqual(sent["band_newest_epoch"], NOW - 600)
        self.assertEqual(sent["host"], os.uname().nodename.split(".")[0])
        self.assertTrue((self.state / "state.json").exists())

    def test_the_report_goes_to_obs_ctl_timemachine_on_macmini(self) -> None:
        self.assertEqual(self.run_check(), 0)
        args = [p.read_text().splitlines() for p in self.tmp.glob("ssh.args.*")]
        report = [a for a in args if a[-1].endswith(" timemachine")]
        band = [a for a in args if not a[-1].endswith(" timemachine")]
        self.assertEqual(len(report), 1)
        self.assertIn("root@macmini.example", report[0])
        self.assertIn("BatchMode=yes", report[0])
        self.assertTrue(report[0][-1].startswith("/usr/bin/python3 -I /usr/local/lib/obs-daily/obs_ctl.py"))
        self.assertEqual(len(band), 1)
        self.assertIn("root@fractal.example", band[0])
        command = band[0][-1]
        self.assertIn("/fast/timemachine/studio.sparsebundle/bands", command)
        self.assertIn("/fast/timemachine/studio.sparsebundle/mapped", command)
        self.assertTrue(command.startswith(f"timeout -s KILL {tg.REMOTE_FIND_TIMEOUT} bash -c 'set -o pipefail; find "))
        self.assertLess(tg.REMOTE_FIND_TIMEOUT, tg.BAND_TIMEOUT)
        self.assertNotIn("rm ", command)

    def test_a_stalled_running_backup_reports_its_stalled_seconds(self) -> None:
        self.set_status(RUNNING)
        with mock.patch("time.time", return_value=NOW):
            self.assertEqual(self.run_check(), 0)
        with mock.patch("time.time", return_value=NOW + 3 * 3600):
            self.assertEqual(self.run_check(), 0)
        sent = self.sent()
        self.assertEqual((sent["running"], sent["phase"], sent["stalled_seconds"]), (True, "Copying", 3 * 3600))
        self.assertEqual((sent["bytes"], sent["percent"]), (1000, 0.25))

    def test_one_byte_of_progress_above_float_precision(self) -> None:
        for now, count in ((NOW, 2**53), (NOW + 300, 2**53 + 1)):
            with self.subTest(count=count):
                self.set_status({**RUNNING, "Progress": {"bytes": count}})
                with mock.patch.object(time, "time", return_value=now):
                    self.assertEqual(self.run_check(), 0)
                report = self.sent()
                self.assertEqual((report["bytes"], report["stalled_seconds"]), (count, 0))

    def test_only_an_admitted_destination_change_resets_the_band_baseline(self) -> None:
        old = "a0000000-0000-4000-8000-000000000001"
        new = "b0000000-0000-4000-8000-000000000002"
        for offset, destination, band, expected in (
            (0, old.upper(), NOW, NOW),
            (300, old, NOW - 1200, NOW),
            (600, "invalid", NOW - 1200, NOW),
            (900, new, NOW - 1200, NOW - 1200),
            (1200, new, NOW - 900, NOW - 900),
        ):
            with self.subTest(destination=destination, offset=offset):
                self.set_status({**RUNNING, "DestinationID": destination})
                (self.tmp / "band").write_text(f"{band}\n")
                with mock.patch.object(time, "time", return_value=NOW + offset):
                    self.assertEqual(self.run_check(), 0)
                self.assertEqual(tg.read_json(self.state / "state.json")["band_max"], expected)
        self.assertEqual(self.sent()["stalled_seconds"], 0)

    def test_a_failed_band_read_fails_the_cross_check_only_while_running(self) -> None:
        (self.tmp / "band.fail").write_text("")
        self.assertEqual(self.run_check(), 0)
        self.assertEqual((self.sent()["band_check"], self.sent()["cross_check_ok"]), ("failed", True))
        self.assertIn("exit 255", self.sent()["band_detail"])
        self.set_status(RUNNING)
        self.assertEqual(self.run_check(), 0)
        self.assertEqual((self.sent()["band_check"], self.sent()["cross_check_ok"]), ("failed", False))

    def test_an_empty_band_answer_is_a_failure(self) -> None:
        (self.tmp / "band").write_text("")
        self.assertEqual(self.run_check(), 0)
        self.assertEqual((self.sent()["band_check"], self.sent()["band_detail"]), ("failed", "band read: no band files"))

    def test_unsafe_bundle_paths_are_not_sent(self) -> None:
        with mock.patch.dict(os.environ, {"TM_GUARD_BUNDLE": "/fast/x'; rm -rf /"}):
            self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.sent()["band_check"], "failed")
        self.assertEqual(len(list(self.tmp.glob("ssh.args.*"))), 1)

    def test_a_tmutil_error_is_reported(self) -> None:
        (self.tmp / "tmutil.fail").write_text("")
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.sent()["tmutil"], "error")
        self.assertIn("exit 4", self.sent()["tmutil_detail"])
        self.assertIsNone(self.sent()["running"])

    def test_only_boolean_and_legacy_integer_running_flags_reach_the_report(self) -> None:
        for raw, expected in ((True, True), (False, False), (1, True), (0, False),
                              (0.5, None), (-1, None), (2, None), (1.0, None), ("1", None)):
            with self.subTest(raw=raw):
                self.set_status({**IDLE, "Running": raw})
                self.assertEqual(self.run_check(), 0)
                report = self.sent()
                self.assertIs(report["running"], expected)
                self.assertEqual(report["tmutil"], "error" if expected is None else "ok")
                if expected is None:
                    self.assertIn("no readable Running field", report["tmutil_detail"])

    def test_a_tmutil_that_does_not_answer_is_killed_and_reported(self) -> None:
        (self.tmp / "tmutil.sleep").write_text("")
        with mock.patch.object(tg, "TMUTIL_TIMEOUT", 0.5):
            self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.sent()["tmutil"], "timeout")
        self.assertIn("killed, exited", self.sent()["tmutil_detail"])
        self.assertEqual(json.loads((self.state / "hung.json").read_text()), [])

    def never_reaped(self):
        """``_wait_until`` for which the gated tmutil never exits: as with a thread in an uninterruptible wait."""

        real_wait = tg._wait_until

        def wait(proc, deadline):
            if list(proc.args[-2:]) == ["status", "-X"]:
                return None
            return real_wait(proc, deadline)

        return wait

    def test_an_unreapable_tmutil_blocks_further_tmutil_runs_while_it_lives(self) -> None:
        (self.tmp / "tmutil.sleep").write_text("")
        (self.tmp / "ps").write_text("Fri Nov 20 11:00:00 2026\n")  # the gate's start, taken before the go line
        with mock.patch.object(tg, "TMUTIL_TIMEOUT", 0.5), mock.patch.object(tg, "_wait_until", self.never_reaped()):
            self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.sent()["tmutil"], "timeout")
        self.assertIn("has not exited", self.sent()["tmutil_detail"])
        hung = json.loads((self.state / "hung.json").read_text())
        self.assertIsInstance(hung[0]["pid"], int)
        self.assertIsInstance(hung[0]["killed_at"], int)
        self.assertEqual(hung[0]["lstart_utc"], "Fri Nov 20 11:00:00 2026")

        (self.tmp / "tmutil.sleep").unlink()
        calls = self.tmutil_calls()
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.sent()["tmutil"], "hung")
        self.assertEqual(self.tmutil_calls(), calls)  # no second tmutil next to the hung one

        # Same PID, another start time (PID reused): the hung one is gone, whatever the clock did.
        (self.tmp / "ps").write_text("Fri Nov 20 10:30:00 2026\n")
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.sent()["tmutil"], "ok")
        self.assertEqual(json.loads((self.state / "hung.json").read_text()), [])

    def test_a_ps_that_cannot_tell_keeps_the_record(self) -> None:
        (self.tmp / "tmutil.sleep").write_text("")
        script(self.tmp / "ps-stub", f'cat "{self.tmp}/ps"; exit "$(cat "{self.tmp}/ps.exit" 2>/dev/null || echo 0)"\n')
        (self.tmp / "ps").write_text("Fri Nov 20 11:00:00 2026\n")
        with mock.patch.object(tg, "TMUTIL_TIMEOUT", 0.5), mock.patch.object(tg, "_wait_until", self.never_reaped()):
            self.assertEqual(self.run_check(), 0)
        (self.tmp / "tmutil.sleep").unlink()
        calls = self.tmutil_calls()
        for exit_code, output in (("2", ""), ("0", "garbage"), ("0", "")):
            (self.tmp / "ps.exit").write_text(exit_code)
            (self.tmp / "ps").write_text(output)
            self.assertEqual(self.run_check(), 0)
            self.assertEqual((self.sent()["tmutil"], self.tmutil_calls()), ("hung", calls), (exit_code, output))
        # ps says the PID does not exist (exit 1, no line, no diagnostic): gone, tmutil runs again.
        (self.tmp / "ps.exit").write_text("1")
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.sent()["tmutil"], "ok")
        self.assertEqual(self.tmutil_calls(), calls + 1)

    def test_a_tmutil_left_by_a_stopped_probe_counts_as_hung(self) -> None:
        # A probe stopped while it waited (launchd reload) leaves the record written before tmutil started.
        (self.tmp / "ps").write_text("Fri Nov 20 11:00:00 2026\n")
        self.state.mkdir(parents=True)
        (self.state / "hung.json").write_text(
            json.dumps([{"pid": 4242, "started_at": NOW, "lstart_utc": "Fri Nov 20 11:00:00 2026"}])
        )
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.sent()["tmutil"], "hung")
        self.assertIn("by an earlier probe", self.sent()["tmutil_detail"])
        self.assertEqual(self.tmutil_calls(), 0)

    def test_an_unreadable_ownership_record_blocks_tmutil_without_overwriting_it(self) -> None:
        self.state.mkdir()
        receipt = self.state / "hung.json"
        for contents in (b"[{", b"null", b'[{"pid": 0}]', b" " * (tg.MAX_STATE_BYTES + 1)):
            with self.subTest(contents=contents[:20]):
                receipt.write_bytes(contents)
                with mock.patch.object(tg, "bounded", wraps=tg.bounded) as runner:
                    status, detail, fields = tg.read_tmutil(self.state)
                self.assertEqual(receipt.read_bytes(), contents)
                runner.assert_not_called()
                self.assertEqual((status, fields), ("error", {}))
                self.assertIn("hung.json", detail)
                self.assertIn("Verify", detail)

    def test_missing_ownership_record_allows_one_probe(self) -> None:
        self.assertFalse((self.state / "hung.json").exists())
        status, _, fields = tg.read_tmutil(self.state)
        self.assertEqual((status, fields["running"], self.tmutil_calls()), ("ok", False, 1))

    def test_a_live_record_with_a_bad_timestamp_still_blocks_tmutil(self) -> None:
        lstart = "Fri Nov 20 11:00:00 2026"
        (self.tmp / "ps").write_text(lstart + "\n")
        self.state.mkdir()
        for stamp in ({}, {"started_at": "bad"}, {"started_at": 10**100}, {"killed_at": 10**100},
                      {"started_at": float("inf")}, {"killed_at": None}, {"started_at": True}):
            with self.subTest(stamp=stamp):
                record = {"pid": 4242, "lstart_utc": lstart, **stamp}
                (self.state / "hung.json").write_text(json.dumps([record]))
                status, detail, fields = tg.read_tmutil(self.state)
                self.assertEqual((status, fields, self.tmutil_calls()), ("hung", {}, 0))
                self.assertIn("unknown time", detail)

    def test_the_record_is_written_before_tmutil_may_start_and_cleared_after(self) -> None:
        seen: list = []
        real = tg.bounded

        def spy(argv, seconds, stdin=None, on_start=None, extra_env=None):
            def wrapped(pid):
                on_start(pid)
                seen.append((json.loads((self.state / "hung.json").read_text()), self.tmutil_calls()))
            return real(argv, seconds, stdin, wrapped if on_start else None, extra_env)

        (self.tmp / "ps").write_text("Fri Nov 20 11:00:00 2026\n")
        with mock.patch.object(tg, "bounded", spy):
            self.assertEqual(self.run_check(), 0)
        self.assertEqual(len(seen), 1)
        record, calls = seen[0]
        self.assertEqual(calls, 0)  # the gate held tmutil back until the record was written
        self.assertEqual(set(record[0]), {"pid", "started_at", "lstart_utc"})
        self.assertEqual(json.loads((self.state / "hung.json").read_text()), [])
        self.assertEqual((self.sent()["tmutil"], self.tmutil_calls()), ("ok", 1))

    def test_ownership_publication_is_durable_before_gate_release(self) -> None:
        self.state.mkdir()
        (self.tmp / "ps").write_text("Fri Nov 20 11:00:00 2026\n")
        events = []
        replace, popen = os.replace, tg.subprocess.Popen

        def sync(fd):
            events.append("sync directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "sync file")

        def publish(source, destination):
            events.append("replace")
            replace(source, destination)

        def start(argv, **kwargs):
            proc = popen(argv, **kwargs)
            if proc.stdin is not None:
                write = proc.stdin.write

                def release(data):
                    events.append("release")
                    return write(data)

                proc.stdin.write = release
            return proc

        with (mock.patch.object(os, "fsync", sync), mock.patch.object(os, "replace", publish),
              mock.patch.object(tg.subprocess, "Popen", start)):
            self.assertEqual(tg.read_tmutil(self.state)[0], "ok")
        publication = ["sync file", "replace", "sync directory"]
        self.assertEqual(events, publication * 2 + ["release"] + publication)
        self.assertEqual(self.tmutil_calls(), 1)

    def test_ownership_sync_failure_keeps_the_gate_closed(self) -> None:
        self.state.mkdir()
        with mock.patch.object(os, "fsync", side_effect=[None, OSError("directory sync failed")]):
            status, detail, fields = tg.read_tmutil(self.state)
        self.assertEqual((status, fields, self.tmutil_calls()), ("error", {}, 0))
        self.assertIn("directory sync failed", detail)

    def test_the_gate_never_starts_tmutil_without_its_go_line(self) -> None:
        tmutil = os.environ["TM_GUARD_TMUTIL"]
        gate = ["/bin/sh", "-c", 'read -r go || exit 97; exec "$0" "$@"', tmutil, "status", "-X"]
        done = tg.bounded(gate, 10)  # standard input closed: as when the probe died before writing it
        self.assertEqual((done.status, done.code, self.tmutil_calls()), ("ok", 97, 0))

    def test_a_record_without_start_time_is_kept_while_the_pid_runs_tmutil_or_the_gate(self) -> None:
        self.state.mkdir(parents=True)
        (self.state / "hung.json").write_text(json.dumps([{"pid": 4242, "started_at": NOW}]))
        names = self.tmp / "ucomm"
        script(
            self.tmp / "ps-stub",
            f'case "$*" in *ucomm*) [ -s "{names}" ] || exit 1; cat "{names}";; *) echo "Fri Nov 20 11:00:00 2026";; esac\n',
        )
        for name in ("tmutil", "sh", "bash"):
            names.write_text(name + "\n")
            self.assertEqual(self.run_check(), 0)
            self.assertEqual((self.sent()["tmutil"], self.tmutil_calls()), ("hung", 0), name)
        names.write_text("Finder\n")  # positively another program: a reused PID
        self.assertEqual(self.run_check(), 0)
        self.assertEqual((self.sent()["tmutil"], self.tmutil_calls()), ("ok", 1))

    def test_the_real_gate_is_recognised_before_its_exec(self) -> None:
        # /bin/sh waiting in the gate's read, as the probe leaves it: its accounting name must count as the gate.
        with mock.patch.dict(os.environ, {"TM_GUARD_PS": "/bin/ps"}):
            gate = tg.subprocess.Popen(["/bin/sh", "-c", "read -r go; exit 0"], stdin=tg.subprocess.PIPE)
            try:
                time.sleep(0.3)
                self.assertIn(tg.ps_name(gate.pid), tg.GATE_NAMES)
            finally:
                gate.stdin.close()
                gate.wait(10)

    def test_markers_cannot_be_program_names(self) -> None:
        for name in ("gone", "unknown"):
            script(self.tmp / "ps-stub", f"echo {name}\n")
            self.assertEqual(tg.ps_name(1), name)
            self.assertNotIn(name, (tg.GONE, tg.UNKNOWN))

    def test_ps_name(self) -> None:
        script(self.tmp / "ps-stub", "echo tmutil\n")
        self.assertEqual(tg.ps_name(1), "tmutil")
        for body in ('echo "a b"\n', "echo tmutil; echo warn >&2\n", "exit 2\n", "echo\n"):
            script(self.tmp / "ps-stub", body)
            self.assertEqual(tg.ps_name(1), tg.UNKNOWN, body)
        script(self.tmp / "ps-stub", "exit 1\n")
        self.assertEqual(tg.ps_name(1), tg.GONE)

    def test_an_older_local_time_record_counts_as_one_without_identity(self) -> None:
        self.state.mkdir(parents=True)
        (self.state / "hung.json").write_text(
            json.dumps([{"pid": 4242, "started_at": NOW, "lstart": "Fri Nov 20 12:00:00 2026"}])
        )
        (self.tmp / "ps").write_text("Fri Nov 20 11:00:00 2026\n")  # the same instant in UTC
        self.assertEqual(self.run_check(), 0)
        self.assertEqual((self.sent()["tmutil"], self.tmutil_calls()), ("hung", 0))

    def test_ps_lstart(self) -> None:
        (self.tmp / "ps").write_text("  Fri Nov  6 09:05:01 2026\n")
        self.assertEqual(tg.ps_lstart(1), "Fri Nov 6 09:05:01 2026")
        for body in (
            'echo "ps: malloc failed" >&2; exit 1\n',
            'echo >&2; exit 1\n',  # whitespace on stderr is a diagnostic too
            'echo "Fri Nov 20 11:00:00 2026"; echo "ps: warning" >&2\n',
            'echo "not a time"\n',
            "exit 2\n",
        ):
            script(self.tmp / "ps-stub", body)
            self.assertEqual(tg.ps_lstart(1), tg.UNKNOWN, body)
        script(self.tmp / "ps-stub", "exit 1\n")
        self.assertEqual(tg.ps_lstart(1), tg.GONE)

    def test_ps_runs_in_utc(self) -> None:
        script(self.tmp / "ps-stub", 'if [ "$TZ" = UTC0 ]; then echo "Fri Nov 20 10:00:00 2026"; else echo "Fri Nov 20 11:00:00 2026"; fi\n')
        with mock.patch.dict(os.environ, {"TZ": "Europe/Berlin"}):
            self.assertEqual(tg.ps_lstart(1), "Fri Nov 20 10:00:00 2026")
        self.assertEqual(tg.ps_lstart(os.getpid()), tg.ps_lstart(os.getpid()))

    def test_the_answer_deadline_starts_when_the_gate_opens(self) -> None:
        started = time.monotonic()
        done = tg.bounded(["/bin/sh", "-c", "read -r go; sleep 1; echo answered"], 1.5, stdin=b"go\n",
                          on_start=lambda pid: time.sleep(1))  # fmt: skip
        self.assertEqual((done.status, done.stdout), ("ok", b"answered\n"))
        self.assertGreater(time.monotonic() - started, 2)

    def test_children_run_in_their_own_session(self) -> None:
        own = tg.bounded(["/bin/sh", "-c", "ps -o pgid= -p $$; echo $$"], 10).stdout.decode().split()
        self.assertEqual(own[0], own[1])  # the child leads its own process group
        self.assertNotEqual(int(own[0]), os.getpgrp())

    def test_a_failed_report_keeps_the_progress_state_and_exits_1(self) -> None:
        (self.tmp / "send.exit").write_text("1")
        self.assertEqual(self.run_check(), 1)
        self.assertTrue((self.state / "state.json").exists())

    def test_dry_run_writes_and_sends_nothing(self) -> None:
        self.assertEqual(self.run_check("--dry-run"), 0)
        self.assertFalse((self.tmp / "sent.json").exists())
        self.assertFalse((self.state / "state.json").exists())

    def test_a_held_lock_exits_3(self) -> None:
        with tg.run_lock(self.state) as held:
            self.assertTrue(held)
            self.assertEqual(self.run_check(), 3)

    def test_a_displaced_lock_refuses_the_probe(self) -> None:
        flock = tg.fcntl.flock
        for replace_directory in (False, True):
            with self.subTest(replace_directory=replace_directory):
                lock = self.state / "run.lock"

                def rotate_before_flock(fd: int, flags: int) -> None:
                    if replace_directory:
                        self.state.rename(self.tmp / "old-state")
                        self.state.mkdir()
                    else:
                        lock.rename(self.state / "old.lock")
                    lock.touch()
                    flock(fd, flags)

                with mock.patch.object(tg.fcntl, "flock", side_effect=rotate_before_flock):
                    self.assertEqual(self.run_check(), 3)
                self.assertEqual(self.tmutil_calls(), 0)
                self.assertFalse((self.state / "state.json").exists())
                self.assertFalse((self.tmp / "sent.json").exists())

    def test_auto_backup_values(self) -> None:
        for raw, expected in (("1\n", True), ("0\n", False), ("", None)):
            (self.tmp / "auto").write_text(raw)
            self.assertEqual(tg.read_auto_backup(), expected)


class SummaryTests(unittest.TestCase):
    def test_lines(self) -> None:
        base = {"tmutil": "ok", "tmutil_detail": "", "running": False, "auto_backup": False, "phase": "",
                "stalled_seconds": 0, "band_check": "ok", "band_detail": ""}  # fmt: skip
        self.assertEqual(tg.summary(base), "idle, automatic backups off; bands ok")
        self.assertEqual(
            tg.summary({**base, "running": True, "phase": "Copying", "stalled_seconds": 7260}),
            "running Copying, 121 min without progress; bands ok",
        )
        self.assertEqual(tg.summary({**base, "tmutil": "hung", "tmutil_detail": "pid 9"}), "tmutil hung: pid 9; bands ok")


if __name__ == "__main__":
    unittest.main()
