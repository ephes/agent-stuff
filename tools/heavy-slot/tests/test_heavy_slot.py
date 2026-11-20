import fcntl
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1]
BIN = TOOL / "bin" / "heavy-slot"
sys.path.insert(0, str(TOOL))

import heavy_slot as hs  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="heavy-slot-test-"))
        self.dir = self.tmp / "slots"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("HEAVY_SLOT")}
        self.env.update(HEAVY_SLOT_DIR=str(self.dir), HEAVY_SLOTS="1")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.communicate()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, *args, new_group=False, **env):
        p = subprocess.Popen([sys.executable, str(BIN), *args], env=dict(self.env, **env),
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             process_group=0 if new_group else None)
        self.procs.append(p)
        return p

    def finish(self, p, timeout=30):
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err

    def hold(self, name="slot-0.lock"):
        """Hold a slot from the test process itself (released by closing the fd)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.dir / name, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, b"pid 1 since 00:00:00: test holder\n")
        self.addCleanup(os.close, fd)
        return fd

    @staticmethod
    def kill_quietly(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def waiting(self, p):
        """True once heavy-slot announced that it waits (it writes nothing else to stderr before)."""
        import select
        ready, _, _ = select.select([p.stderr], [], [], 0)
        if ready:
            self.seen_stderr = getattr(self, "seen_stderr", "") + p.stderr.readline()
        return "waiting" in getattr(self, "seen_stderr", "")

    def wait_for(self, predicate, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return True
            time.sleep(0.05)
        return False


class CapTest(Fixture):
    def test_one_slot_serializes_two_runs(self):
        log = self.tmp / "log"
        script = f'echo "start $$" >> {shlex.quote(str(log))}; sleep 0.6; echo "end $$" >> {shlex.quote(str(log))}'
        a = self.start("--", "sh", "-c", script)
        b = self.start("--", "sh", "-c", script)
        self.assertEqual(self.finish(a)[0], 0)
        self.assertEqual(self.finish(b)[0], 0)
        kinds = [line.split()[0] for line in log.read_text().splitlines()]
        self.assertEqual(kinds, ["start", "end", "start", "end"])

    def test_two_slots_run_two_at_once(self):
        marker = self.tmp / "running"
        script = f'echo x >> {shlex.quote(str(marker))}; sleep 1'
        a = self.start("--", "sh", "-c", script, HEAVY_SLOTS="2")
        b = self.start("--", "sh", "-c", script, HEAVY_SLOTS="2")
        self.assertTrue(self.wait_for(lambda: marker.exists() and len(marker.read_text().split()) == 2,
                                      timeout=0.9))
        self.finish(a)
        self.finish(b)

    def test_waits_while_busy_and_runs_once_free(self):
        fd = self.hold()
        p = self.start("--", "echo", "ran")
        self.assertTrue(self.wait_for(lambda: (self.dir / "slot-0.lock").exists()))
        time.sleep(0.5)
        self.assertIsNone(p.poll())
        fcntl.flock(fd, fcntl.LOCK_UN)
        rc, out, err = self.finish(p)
        self.assertEqual((rc, out), (0, "ran\n"))
        self.assertIn("all 1 slots busy, waiting (holders: pid 1 since 00:00:00: test holder)", err)
        self.assertIn("got slot-0.lock", err)

    def test_gives_up_after_max_wait(self):
        self.hold()
        rc, out, err = self.finish(self.start("--max-wait", "0.3", "--", "echo", "ran"))
        self.assertEqual(rc, hs.EX_TEMPFAIL)
        self.assertEqual(out, "")
        self.assertIn("no free slot", err)

    def test_zero_max_wait_waits_until_a_slot_is_free(self):
        fd = self.hold()
        marker = self.tmp / "ran"
        p = self.start("--", "touch", str(marker), HEAVY_SLOT_MAX_WAIT="0")
        self.assertTrue(self.wait_for(lambda: self.waiting(p)))
        self.assertIsNone(p.poll())
        self.assertFalse(marker.exists())
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(self.finish(p)[0], 0)
        self.assertTrue(marker.exists())

    def test_release_after_max_wait_is_too_late(self):
        fd = self.hold()
        p = self.start("--max-wait", "0.3", "--", "echo", "ran")
        time.sleep(0.8)
        fcntl.flock(fd, fcntl.LOCK_UN)
        rc, out, _ = self.finish(p)
        self.assertEqual((rc, out), (hs.EX_TEMPFAIL, ""))

    def test_short_max_wait_still_retries(self):
        fd = self.hold()
        p = self.start("--max-wait", "1", "--", "echo", "ran")
        self.assertTrue(self.wait_for(lambda: p.poll() is not None or self.waiting(p), timeout=5))
        time.sleep(0.15)
        fcntl.flock(fd, fcntl.LOCK_UN)
        rc, out, _ = self.finish(p)
        self.assertEqual((rc, out), (0, "ran\n"))

    def test_command_reusing_fd_3_keeps_the_slot(self):
        first = self.start("--", "sh", "-c", "exec 3>&1; exec 4>&1; exec 5>&1; sleep 1")
        self.assertTrue(self.wait_for(lambda: hs.is_held(self.dir / "slot-0.lock")))
        time.sleep(0.3)  # the shell has replaced its low descriptors by now
        rc, _, _ = self.finish(self.start("--max-wait", "0.3", "--", "true"))
        self.assertEqual(rc, hs.EX_TEMPFAIL)
        self.assertEqual(self.finish(first)[0], 0)

    def test_nested_call_does_not_wait_for_itself(self):
        inner = f"{sys.executable} {BIN} --max-wait 0.3 -- echo inner"
        rc, out, err = self.finish(self.start("--", "sh", "-c", inner))
        self.assertEqual((rc, out), (0, "inner\n"), err)

    def test_killed_holder_frees_its_slot(self):
        holder = self.start("--", "sleep", "30")
        self.assertTrue(self.wait_for(lambda: hs.is_held(self.dir / "slot-0.lock")))
        holder.kill()  # heavy-slot became the command: this kills the command itself
        holder.communicate()
        rc, out, _ = self.finish(self.start("--max-wait", "5", "--", "echo", "after"))
        self.assertEqual((rc, out), (0, "after\n"))

    def test_background_child_keeps_the_slot_until_it_ends(self):
        # the shell exits at once; the sleep it started inherited the slot and holds it ~1.5 s
        first = self.start("--", "sh", "-c", "sleep 1.5 >/dev/null 2>&1 & exit 0")
        self.assertEqual(self.finish(first)[0], 0)
        rc, _, _ = self.finish(self.start("--max-wait", "0.3", "--", "true"))
        self.assertEqual(rc, hs.EX_TEMPFAIL)
        rc, out, _ = self.finish(self.start("--max-wait", "10", "--", "echo", "later"))
        self.assertEqual((rc, out), (0, "later\n"))

class RunTest(Fixture):
    def test_exit_code_passes_through(self):
        self.assertEqual(self.finish(self.start("--", "sh", "-c", "exit 3"))[0], 3)
        p = self.start("--", "sh", "-c", "kill -TERM $$")
        self.assertEqual(self.finish(p)[0], -signal.SIGTERM)

    def test_sigpipe_has_its_default_disposition(self):
        p = self.start("--", "sh", "-c", "kill -PIPE $$; exit 0")
        self.assertEqual(self.finish(p)[0], -signal.SIGPIPE)

    def test_low_descriptor_limit_still_runs_the_command(self):
        p = subprocess.run(["sh", "-c", f'ulimit -n 64; "{sys.executable}" "{BIN}" -- sh -c "exit 6"'],
                           env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 6, p.stderr)

    def test_low_limit_keeps_the_lock_off_low_descriptors(self):
        script = 'ulimit -n 64; "$1" "$2" -- sh -c "exec 3>&1; exec 4>&1; exec 5>&1; sleep 1" >/dev/null'
        first = subprocess.Popen(["sh", "-c", script, "sh", sys.executable, str(BIN)], env=self.env,
                                 stdin=subprocess.DEVNULL)
        self.assertTrue(self.wait_for(lambda: hs.is_held(self.dir / "slot-0.lock")))
        time.sleep(0.3)
        rc, _, _ = self.finish(self.start("--max-wait", "0.3", "--", "true"))
        self.assertEqual(rc, hs.EX_TEMPFAIL)
        self.assertEqual(first.wait(timeout=30), 0)

    def test_closed_stdout_keeps_output_out_of_the_lock_file(self):
        p = subprocess.run(["sh", "-c", 'ulimit -n 64; "$1" "$2" -- sh -c "echo leaked; exit 0" >&-',
                            "sh", sys.executable, str(BIN)],
                           env=self.env, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        direct = subprocess.run(["sh", "-c", 'sh -c "echo leaked; exit 0" >&-'], capture_output=True, timeout=30)
        self.assertEqual(p.returncode, direct.returncode)  # same as without heavy-slot
        lines = (self.dir / "slot-0.lock").read_text().splitlines()
        self.assertEqual(len(lines), 1, lines)  # only the holder line, no command output
        self.assertTrue(lines[0].startswith("pid "), lines)

    def test_failed_exec_keeps_127_on_a_broken_stderr(self):
        r, w = os.pipe()
        os.close(r)
        try:
            p = subprocess.run([sys.executable, str(BIN), "--", str(self.tmp / "nope")], env=self.env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=w, timeout=30)
        finally:
            os.close(w)
        self.assertEqual(p.returncode, 127)

    def test_closed_stderr_while_waiting_keeps_the_lock_file_clean(self):
        fd = self.hold()
        waiting = self.tmp / "waiting"
        # time.sleep runs only after a failed acquisition: it marks that the waiter really waited
        code = ("import os, sys, time; sys.path.insert(0, sys.argv[1]); import heavy_slot as hs; "
                "real = time.sleep; "
                "hs.time.sleep = lambda s: (open(sys.argv[2], 'a').close(), real(s)); "
                "assert sys.stderr is None; sys.exit(hs.main(['--', 'true']))")
        # stderr is closed before the interpreter starts, as a caller's `2>&-` does (sys.stderr is None)
        p = subprocess.Popen(["sh", "-c", '"$1" -c "$2" "$3" "$4" 2>&-', "sh", sys.executable, code, str(TOOL),
                              str(waiting)], env=self.env, stdin=subprocess.DEVNULL)
        self.assertTrue(self.wait_for(waiting.exists))
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(p.wait(timeout=30), 0)
        rc, out, _ = self.finish(self.start("--status"))
        self.assertEqual(out, "slot-0.lock\tfree\n")
        self.assertNotIn("heavy-slot:", (self.dir / "slot-0.lock").read_text())

    def test_non_utf8_argument(self):
        p = subprocess.run([sys.executable, str(BIN), "--", "sh", "-c", "exit 0", b"\xff".decode("utf-8", "surrogateescape")],
                           env=self.env, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_closed_stdout_and_stderr(self):
        p = subprocess.run(["sh", "-c", f'"{sys.executable}" "{BIN}" -- sh -c "exit 5" >&- 2>&-'],
                           env=self.env, stdin=subprocess.DEVNULL, timeout=30)
        self.assertEqual(p.returncode, 5)

    def test_child_sees_its_slot(self):
        rc, out, _ = self.finish(self.start("--", "sh", "-c", 'echo "$HEAVY_SLOT_HELD"'))
        self.assertEqual((rc, out), (0, "slot-0.lock\n"))

    def test_command_is_the_process(self):
        """exec: same pid, so every signal reaches the command directly and no wrapper is left."""
        p = self.start("--", "sh", "-c", 'echo "$$"')
        rc, out, _ = self.finish(p)
        self.assertEqual((rc, out), (0, f"{p.pid}\n"))

    def test_sigterm_reaches_the_command(self):
        flag = self.tmp / "term"
        p = self.start("--", "sh", "-c", "trap 'echo got > \"$1\"; exit 9' TERM; while :; do sleep 0.1; done",
                       "sh", str(flag))
        self.assertTrue(self.wait_for(lambda: "sh -c" in hs.holder(self.dir / "slot-0.lock")))
        time.sleep(0.3)
        p.send_signal(signal.SIGTERM)
        rc, _, _ = self.finish(p)
        self.assertEqual(rc, 9)
        self.assertEqual(flag.read_text(), "got\n")
    def test_group_kill_reaches_the_command(self):
        """A tool timeout that SIGKILLs the caller's process group kills the command itself."""
        marker = self.tmp / "started"
        p = self.start("--", "sh", "-c", f"echo $$ > {shlex.quote(str(marker))}; exec sleep 30", new_group=True)
        self.assertTrue(self.wait_for(lambda: marker.exists() and marker.read_text().strip()))
        self.assertEqual(int(marker.read_text()), p.pid)
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        self.assertEqual(p.returncode, -signal.SIGKILL)  # the command was heavy-slot's own pid
        self.assertFalse(hs.is_held(self.dir / "slot-0.lock"))

    def test_holder_line_failure_does_not_stop_the_command(self):
        out = self.tmp / "out"
        code = ("import os, sys; from unittest import mock; sys.path.insert(0, sys.argv[1]); import heavy_slot as hs; "
                "err = OSError(28, 'No space left on device'); "
                "w = mock.patch.object(hs.os, 'write', side_effect=err); t = mock.patch.object(hs.os, 'ftruncate', side_effect=err); "
                "w.start(); t.start(); sys.exit(hs.main(sys.argv[2:]))")
        p = subprocess.run([sys.executable, "-c", code, str(TOOL), "--", "sh", "-c", f"echo ran > {shlex.quote(str(out))}; exit 4"],
                           env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 4, p.stderr)
        self.assertEqual(out.read_text(), "ran\n")
    def test_missing_command_and_bad_settings(self):
        rc, _, err = self.finish(self.start())
        self.assertEqual(rc, hs.EX_USAGE)
        self.assertIn("no command", err)
        rc, _, _ = self.finish(self.start("--slots", "0", "--", "true"))
        self.assertEqual(rc, 2)
        rc, _, err = self.finish(self.start("--", "true", HEAVY_SLOTS="many"))
        self.assertNotEqual(rc, 0)
        self.assertIn("HEAVY_SLOTS='many' is not valid", err)

    def test_invalid_max_wait_is_rejected_before_admission(self):
        marker = self.tmp / "ran"
        for value in ("nan", "inf", "-inf", "1e999", "-1", "bad"):
            for source in ("--max-wait", "HEAVY_SLOT_MAX_WAIT"):
                with self.subTest(value=value, source=source):
                    args = (f"--max-wait={value}",) if source == "--max-wait" else ()
                    env = {source: value} if source == "HEAVY_SLOT_MAX_WAIT" else {}
                    rc, _, err = self.finish(self.start(*args, "--", "touch", str(marker), **env))
                    self.assertNotEqual(rc, 0)
                    self.assertIn(source, err)
                    self.assertFalse(marker.exists())
                    self.assertFalse(self.dir.exists())

    def test_unknown_program(self):
        rc, _, err = self.finish(self.start("--", str(self.tmp / "nope")))
        self.assertEqual(rc, 127)
        self.assertIn("cannot run", err)

    def test_unusable_slot_dir_runs_without_a_slot(self):
        blocker = self.tmp / "file"
        blocker.write_text("")
        rc, out, err = self.finish(self.start("--", "sh", "-c", 'echo "$HEAVY_SLOT_HELD"',
                                              HEAVY_SLOT_DIR=str(blocker / "slots")))
        self.assertEqual((rc, out), (0, "none\n"))
        self.assertIn("running WITHOUT a slot", err)
        self.dir.mkdir()
        self.dir.chmod(0o500)
        try:
            rc, out, err = self.finish(self.start("--", "echo", "ran"))
        finally:
            self.dir.chmod(0o700)
        self.assertEqual((rc, out), (0, "ran\n"))
        self.assertIn(f"cannot use {self.dir}", err)

    def test_status_lists_holders(self):
        self.hold("slot-1.lock")
        rc, out, _ = self.finish(self.start("--status", HEAVY_SLOTS="2"))
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["slot-0.lock\tfree",
                                            "slot-1.lock\theld\tpid 1 since 00:00:00: test holder"])

    def test_free_slot_shows_no_old_holder(self):
        self.finish(self.start("--", "true"))
        rc, out, _ = self.finish(self.start("--status"))
        self.assertEqual(out, "slot-0.lock\tfree\n")
        self.assertEqual(hs.holder(self.dir / "slot-0.lock"), "")

if __name__ == "__main__":
    unittest.main()
