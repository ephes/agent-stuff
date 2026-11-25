import contextlib
import fcntl
import io
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
from unittest import mock

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
        self.assertIn("no free slot, waiting (holders: pid 1 since 00:00:00: test holder)", err)
        self.assertIn("got slot-0.lock", err)

    def test_gives_up_after_max_wait(self):
        self.hold()
        rc, out, err = self.finish(self.start("--max-wait", "0.3", "--", "echo", "ran"))
        self.assertEqual(rc, hs.EX_TEMPFAIL)
        self.assertEqual(out, "")
        self.assertIn("no free slot", err)

    def test_short_wait_sleeps_to_deadline_and_releases_a_late_slot(self):
        budget = 0.015625
        for release_late in (False, True):
            with self.subTest(release_late=release_late):
                fd = self.hold()
                elapsed = 0.0
                sleeps = []

                def sleep(seconds):
                    nonlocal elapsed
                    sleeps.append(seconds)
                    self.assertGreater(seconds, 0)
                    elapsed += seconds
                    if release_late and elapsed >= budget:
                        elapsed += 0.001  # the waiter resumes after the deadline
                        fcntl.flock(fd, fcntl.LOCK_UN)

                with (
                    mock.patch.dict(os.environ, self.env, clear=True),
                    mock.patch.object(hs.time, "monotonic", side_effect=lambda: elapsed),
                    mock.patch.object(hs.time, "sleep", side_effect=sleep),
                    mock.patch.object(hs, "try_acquire", wraps=hs.try_acquire) as probe,
                    mock.patch.object(hs, "warn"),
                    mock.patch.object(hs, "become") as become,
                ):
                    try:
                        rc = hs.main(["--max-wait", str(budget), "--", "true"])
                        self.assertEqual(rc, hs.EX_TEMPFAIL)
                        self.assertEqual(sleeps, [budget / 4] * 4)
                        self.assertEqual(probe.call_count, 5)
                        become.assert_not_called()
                        if release_late:
                            self.assertFalse(hs.is_held(self.dir / "slot-0.lock"))
                    finally:
                        fcntl.flock(fd, fcntl.LOCK_UN)

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

    def test_nested_call_keeps_close_on_exec_lock_across_exec(self):
        marker = self.tmp / "started"
        launch = """
import os
import sys

sys.path.insert(0, sys.argv[1])
import heavy_slot

fd = int(os.environ["HEAVY_SLOT_HELD_FD"])
os.set_inheritable(fd, False)
raise SystemExit(heavy_slot.main(sys.argv[2:]))
"""
        replacement = "import pathlib, sys, time; pathlib.Path(sys.argv[1]).touch(); time.sleep(30)"
        nested = self.start(
            "--", sys.executable, "-c", launch, str(TOOL),
            "--max-wait", "0.3", "--", sys.executable, "-c", replacement, str(marker),
        )
        self.assertTrue(self.wait_for(lambda: marker.exists() or nested.poll() is not None))
        self.assertTrue(marker.exists())
        rc, _, err = self.finish(self.start("--max-wait", "0.3", "--", "true"))
        self.assertEqual(rc, hs.EX_TEMPFAIL, err)

    def test_nested_call_reports_failure_to_preserve_lock(self):
        fd = self.hold()
        env = dict(self.env, HEAVY_SLOT_HELD="slot-0.lock",
                   HEAVY_SLOT_HELD_DIR=str(self.dir.resolve()), HEAVY_SLOT_HELD_FD=str(fd))
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(hs.os, "set_inheritable", side_effect=OSError("cannot change flags")),
            mock.patch.object(hs.os, "execvp") as execvp,
            mock.patch.object(hs, "warn") as warn,
        ):
            rc = hs.main(["--", "true"])

        self.assertEqual(rc, hs.EX_NOEXEC)
        execvp.assert_not_called()
        warn.assert_called_once_with("heavy-slot: cannot run true: cannot preserve slot lock: cannot change flags")

    def test_nested_call_acquires_a_slot_in_another_pool(self):
        other = self.tmp / "other"
        rc, out, err = self.finish(self.start(
            "--", sys.executable, str(BIN), "--dir", str(other), "--max-wait", "0.3",
            "--", sys.executable, str(BIN), "--dir", str(other), "--status",
        ))
        self.assertEqual(rc, 0, err)
        self.assertIn("slot-0.lock\theld\t", out)

    def test_nested_call_recognizes_a_symlink_alias_of_the_pool(self):
        alias = self.tmp / "alias"
        self.dir.mkdir()
        alias.symlink_to(self.dir, target_is_directory=True)
        rc, out, err = self.finish(self.start(
            "--", sys.executable, str(BIN), "--dir", str(alias), "--max-wait", "0.3", "--", "echo", "inner",
        ))
        self.assertEqual((rc, out), (0, "inner\n"), err)

    def test_nested_call_waits_when_a_launcher_drops_or_replaces_the_lock(self):
        launch = """
import os
import subprocess
import sys

replacement, *command = sys.argv[1:]
pass_fds = ()
if replacement:
    fd = int(os.environ.get("HEAVY_SLOT_HELD_FD", "200"))
    original = os.dup(fd)  # the launcher still holds the outer lock while it waits
    other = os.open(replacement, os.O_RDWR)
    os.dup2(other, fd)
    pass_fds = (fd,)
raise SystemExit(subprocess.call(command, pass_fds=pass_fds))
"""
        for replacement in ("", os.devnull, str(self.dir / "slot-0.lock")):
            with self.subTest(replacement=replacement):
                rc, out, err = self.finish(self.start(
                    "--", sys.executable, "-c", launch, replacement,
                    sys.executable, str(BIN), "--max-wait", "0.3", "--", "echo", "inner",
                ))
                self.assertEqual((rc, out), (hs.EX_TEMPFAIL, ""), err)

    def test_nested_call_acquires_a_slot_after_unguarded_parent(self):
        blocker = self.tmp / "file"
        blocker.touch()
        rc, out, err = self.finish(self.start(
            "--dir", str(blocker / "slots"), "--", "sh", "-c",
            'echo "$HEAVY_SLOT_HELD"; exec "$@"', "sh",
            sys.executable, str(BIN), "--", "sh", "-c", 'echo "$HEAVY_SLOT_HELD"',
        ))
        self.assertEqual((rc, out), (0, "none\nslot-0.lock\n"), err)
        self.assertTrue((self.dir / "slot-0.lock").is_file())
        self.assertEqual(err.count("running WITHOUT a slot"), 1)

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

class SlotFileTest(Fixture):
    def test_nested_call_requires_the_replacement_slot_after_lock_confirmation(self):
        inherited_fd = self.hold()
        path = self.dir / "slot-0.lock"
        detached = self.dir / "detached.lock"
        env = dict(self.env, HEAVY_SLOT_HELD=path.name,
                   HEAVY_SLOT_HELD_DIR=str(self.dir.resolve()), HEAVY_SLOT_HELD_FD=str(inherited_fd))
        flock = fcntl.flock

        def replace_after_flock(fd, operation):
            flock(fd, operation)
            if fd == inherited_fd:
                path.rename(detached)
                self.hold()

        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(fcntl, "flock", side_effect=replace_after_flock),
            mock.patch.object(hs.time, "monotonic", side_effect=[0.0, 1.0]),
            mock.patch.object(hs, "warn"),
            mock.patch.object(hs, "become", return_value=0) as become,
        ):
            rc = hs.main(["--max-wait", "1", "--", "true"])

        self.assertEqual(rc, hs.EX_TEMPFAIL)
        become.assert_not_called()
        self.assertTrue(hs.is_held(detached))

    def test_replaced_slot_cannot_admit_a_command_on_the_detached_lock(self):
        self.dir.mkdir()
        path = self.dir / "slot-0.lock"
        detached = self.dir / "detached.lock"
        path.write_text("original contents")
        flock = fcntl.flock
        elapsed = 0.0

        def replace_then_flock(fd, operation):
            if not detached.exists():
                path.rename(detached)
                self.hold()
            return flock(fd, operation)

        def sleep(seconds):
            nonlocal elapsed
            elapsed += seconds

        with (
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(fcntl, "flock", side_effect=replace_then_flock),
            mock.patch.object(hs.time, "monotonic", side_effect=lambda: elapsed),
            mock.patch.object(hs.time, "sleep", side_effect=sleep),
            mock.patch.object(hs, "warn"),
            mock.patch.object(hs, "become", return_value=0) as become,
        ):
            rc = hs.main(["--max-wait", "1", "--", "true"])

        self.assertEqual(rc, hs.EX_TEMPFAIL)
        become.assert_not_called()
        self.assertEqual(elapsed, 1.0)
        self.assertEqual(detached.read_text(), "original contents")
        self.assertFalse(hs.is_held(detached))

    def test_slot_hard_linked_after_open_must_be_retried(self):
        self.dir.mkdir()
        path = self.dir / "slot-0.lock"
        alias = self.tmp / "alias"
        flock = fcntl.flock

        def link_then_flock(fd, operation):
            alias.hardlink_to(path)
            return flock(fd, operation)

        with mock.patch.object(fcntl, "flock", side_effect=link_then_flock):
            acquired = hs.try_acquire([path])
        if acquired is not None:
            self.addCleanup(os.close, acquired[0])
        self.assertIsNone(acquired)

        alias.unlink()
        fd, acquired_path = hs.try_acquire([path])
        self.addCleanup(os.close, fd)
        self.assertEqual(acquired_path, path)

    def test_invalid_slot_leaves_healthy_slots_usable(self):
        self.hold("slot-1.lock")
        (self.dir / "slot-0.lock").mkdir()
        command = ("--", "sh", "-c", 'echo "$HEAVY_SLOT_HELD"')
        rc, out, err = self.finish(self.start(*command, HEAVY_SLOTS="3"))
        self.assertEqual((rc, out, err), (0, "slot-2.lock\n", ""))

        rc, out, err = self.finish(self.start("--max-wait", "0.1", *command, HEAVY_SLOTS="2"))
        self.assertEqual((rc, out), (hs.EX_TEMPFAIL, ""))
        self.assertIn("no free slot", err)
        self.assertNotIn("WITHOUT a slot", err)

    def test_all_invalid_slots_allow_unguarded_execution(self):
        self.dir.mkdir()
        (self.dir / "slot-0.lock").mkdir()
        (self.dir / "slot-1.lock").symlink_to("missing")
        rc, out, err = self.finish(self.start("--", "sh", "-c", 'echo "$HEAVY_SLOT_HELD"', HEAVY_SLOTS="2"))
        self.assertEqual((rc, out), (0, "none\n"))
        self.assertIn("running WITHOUT a slot", err)

    def test_aliases_leave_target_untouched(self):
        self.dir.mkdir()
        path = self.dir / "slot-0.lock"
        target = self.tmp / "unrelated"
        for link in (path.symlink_to, path.hardlink_to):
            with self.subTest(link=link.__name__):
                target.write_bytes(b"unrelated data\n")
                link(target)
                try:
                    rc, out, err = self.finish(self.start("--", "sh", "-c", 'echo "$HEAVY_SLOT_HELD"'))
                    self.assertEqual(target.read_bytes(), b"unrelated data\n")
                    self.assertEqual((rc, out), (0, "none\n"))
                    self.assertIn("running WITHOUT a slot", err)
                finally:
                    path.unlink()

    def test_status_does_not_read_holder_through_symlink(self):
        self.hold("other.lock")
        path = self.dir / "slot-0.lock"
        path.symlink_to("other.lock")
        self.assertEqual(hs.holder(path), "")
        rc, out, _ = self.finish(self.start("--status"))
        self.assertEqual((rc, out), (0, "slot-0.lock\tunavailable\n"))

    def test_holder_omits_the_detached_lock_metadata(self):
        path = self.dir / "slot-0.lock"
        self.hold()
        flock = fcntl.flock

        def replace_then_flock(fd, operation):
            path.rename(self.dir / "original.lock")
            path.write_text("unrelated data")
            return flock(fd, operation)

        with mock.patch.object(fcntl, "flock", side_effect=replace_then_flock):
            self.assertEqual(hs.holder(path), "")

    def test_status_marks_replaced_held_and_free_slots_unavailable(self):
        self.hold()
        (self.dir / "slot-1.lock").touch()
        paths = hs.slot_paths(self.dir, 2)
        open_slot = hs.open_slot

        def open_then_replace(path, flags):
            fd = open_slot(path, flags)
            path.rename(path.with_suffix(".detached"))
            path.write_text("replacement contents")
            return fd

        with (
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(hs, "open_slot", side_effect=open_then_replace),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(hs.main(["--slots", "2", "--status"]), 0)

        self.assertEqual(stdout.getvalue().splitlines(), [f"{path.name}\tunavailable" for path in paths])

    def test_fifo_slot_is_rejected_without_blocking(self):
        self.dir.mkdir()
        os.mkfifo(self.dir / "slot-0.lock")
        rc, out, err = self.finish(self.start("--", "sh", "-c", 'echo "$HEAVY_SLOT_HELD"'), timeout=5)
        self.assertEqual((rc, out), (0, "none\n"))
        self.assertIn("running WITHOUT a slot", err)
        rc, out, _ = self.finish(self.start("--status"), timeout=5)
        self.assertEqual((rc, out), (0, "slot-0.lock\tunavailable\n"))

    def test_contenders_reuse_the_same_regular_inode(self):
        path = self.dir / "slot-0.lock"
        fd = self.hold()
        self.assertIsNone(hs.try_acquire([path]))
        fcntl.flock(fd, fcntl.LOCK_UN)
        acquired, slot = hs.try_acquire([path])
        self.addCleanup(os.close, acquired)
        self.assertEqual(slot, path)
        self.assertTrue(os.path.samestat(os.fstat(fd), os.fstat(acquired)))


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

    def test_exception_during_launch_closes_the_new_lock(self):
        failure = RuntimeError("flush failed")
        with (
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch("sys.stdout") as stdout,
            mock.patch.object(hs.os, "execvp") as execvp,
        ):
            stdout.flush.side_effect = failure
            with self.assertRaises(RuntimeError) as raised:
                hs.main(["--", "true"])
            fd = int(os.environ["HEAVY_SLOT_HELD_FD"])
            try:
                self.assertIs(raised.exception, failure)
                execvp.assert_not_called()
                self.assertFalse(hs.is_held(self.dir / "slot-0.lock"))
                with self.assertRaises(OSError):
                    os.fstat(fd)
            finally:
                # Clean up even when the test exposes the descriptor leak.
                with contextlib.suppress(OSError):
                    os.close(fd)

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
        self.assertTrue(self.wait_for(lambda: hs.holder(self.dir / "slot-0.lock").endswith(": sh")))
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

    def test_oversized_slot_count_is_rejected_before_path_allocation(self):
        for source in ("--slots", "HEAVY_SLOTS"):
            args = ["--slots", "65"] if source == "--slots" else []
            env = dict(self.env, HEAVY_SLOTS="65") if source == "HEAVY_SLOTS" else self.env
            for action in (["--status"], ["--", "true"]):
                with (
                    self.subTest(source=source, action=action),
                    mock.patch.dict(os.environ, env, clear=True),
                    mock.patch.object(hs, "slot_paths", side_effect=AssertionError("allocated paths")) as paths,
                    mock.patch("sys.stderr"),
                ):
                    with self.assertRaises(SystemExit) as error:
                        hs.main(args + action)
                    self.assertNotEqual(error.exception.code, 0)
                    paths.assert_not_called()

    def test_maximum_slot_count_allows_status_and_acquisition(self):
        rc, out, err = self.finish(self.start("--slots", "64", "--status"))
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.splitlines(), [f"slot-{index}.lock\tfree" for index in range(64)])
        rc, out, err = self.finish(self.start("--", "sh", "-c", 'echo "$HEAVY_SLOT_HELD"', HEAVY_SLOTS="64"))
        self.assertEqual((rc, out), (0, "slot-0.lock\n"), err)

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

    def test_default_label_omits_command_arguments(self):
        path = self.dir / "slot-0.lock"
        self.start("--", "/bin/sh", "-c", ": synthetic-holder-argument; exec sleep 30")
        self.assertTrue(self.wait_for(lambda: bool(hs.holder(path))))

        stored = path.read_text()
        self.assertEqual(stored.split(": ", 1)[1], "sh\n")
        rc, out, _ = self.finish(self.start("--status"))
        self.assertEqual((rc, out), (0, f"slot-0.lock\theld\t{stored}"))

        rc, _, err = self.finish(self.start("--max-wait", "0.5", "--", "/bin/echo", "synthetic-waiter-argument"))
        self.assertEqual(rc, hs.EX_TEMPFAIL)
        self.assertIn(f"holders: {stored.rstrip()})", err)
        self.assertTrue(err.rstrip().endswith("not run: echo"), err)
        self.assertNotIn("synthetic-waiter-argument", err)

    def test_explicit_label_is_bounded_to_one_printable_line(self):
        path = self.dir / "slot-0.lock"
        label = "batch\nnext\rstep\u2028then\t" + "x" * 150
        self.start("--label", label, "--", "sleep", "30")
        self.assertTrue(self.wait_for(lambda: bool(hs.holder(path))))

        stored = path.read_text()
        self.assertEqual(stored.split(": ", 1)[1], ("batch next step then " + "x" * 150)[:120] + "\n")
        rc, out, _ = self.finish(self.start("--status"))
        self.assertEqual((rc, out), (0, f"slot-0.lock\theld\t{stored}"))

    def test_status_normalizes_existing_multiline_holder_metadata(self):
        fd = self.hold()
        os.write(fd, b"continuation\n")
        rc, out, _ = self.finish(self.start("--status"))
        self.assertEqual((rc, out), (0, "slot-0.lock\theld\tpid 1 since 00:00:00: test holder continuation\n"))

    def test_free_slot_shows_no_old_holder(self):
        self.finish(self.start("--", "true"))
        rc, out, _ = self.finish(self.start("--status"))
        self.assertEqual(out, "slot-0.lock\tfree\n")
        self.assertEqual(hs.holder(self.dir / "slot-0.lock"), "")

if __name__ == "__main__":
    unittest.main()
