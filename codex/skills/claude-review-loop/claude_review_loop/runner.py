"""Drive one Claude review: spawn in its own process group, monitor JSON
stream non-blockingly (raw-fd os.read so a buffered text object can never wedge
us), reap on every exit path, and always write artifacts."""
import json
import os
import selectors
import signal
import subprocess
import time
import traceback

from .monitor import Monitor
from .result import ReviewResult
from .states import CRASHED


def _now():
    return time.monotonic()


def _group_alive(pgid):
    if pgid is None or pgid <= 1:
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True


def _kill_group(proc, pgid, grace=5.0):
    """SIGTERM the group, wait briefly, SIGKILL if needed, then reap.

    Never wait for natural exit (M3 means it may never come). pgid is cached at
    spawn. Wrapper processes such as fish can exit before Claude does, so the
    process group liveness check is authoritative.
    """
    if pgid is not None and pgid > 1:
        for sig, timeout in ((signal.SIGTERM, grace), (signal.SIGKILL, 1.0)):
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                break
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
            if not _group_alive(pgid):
                return
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


class _Streams:
    """Reads two raw fds non-blockingly, splitting stdout into lines and teeing
    raw/event output. stderr is appended to err_f."""

    def __init__(self, out_fd, err_fd, raw_f, ev_f, err_f, monitor):
        self.out_fd, self.err_fd = out_fd, err_fd
        self.raw_f, self.ev_f, self.err_f = raw_f, ev_f, err_f
        self.monitor = monitor
        self._buf = b""
        os.set_blocking(out_fd, False)
        os.set_blocking(err_fd, False)
        self.sel = selectors.DefaultSelector()
        self.sel.register(out_fd, selectors.EVENT_READ, "out")
        self.sel.register(err_fd, selectors.EVENT_READ, "err")

    def pump(self, timeout):
        """Read whatever is available within `timeout`. Returns False if both
        streams hit EOF."""
        for key, _ in self.sel.select(timeout=timeout):
            try:
                data = os.read(key.fd, 65536)
            except BlockingIOError:
                continue
            if not data:  # EOF on this fd
                try:
                    self.sel.unregister(key.fd)
                except KeyError:
                    pass
                continue
            if key.data == "out":
                self._feed_out(data)
            else:
                self.err_f.write(data.decode(errors="replace")); self.err_f.flush()
        return bool(self.sel.get_map())

    def _feed_out(self, data):
        self._buf += data
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            self._ingest(raw.decode(errors="replace"))

    def flush_partial(self):
        if self._buf.strip():
            self._ingest(self._buf.decode(errors="replace").strip())
            self._buf = b""

    def _ingest(self, line):
        if line == "":
            return
        self.raw_f.write(line + "\n"); self.raw_f.flush()
        try:
            event = json.loads(line)
        except ValueError:
            self.ev_f.write(json.dumps({"type": "malformed_stdout", "raw": line}) + "\n")
            self.ev_f.flush()
            return
        self.ev_f.write(line + "\n"); self.ev_f.flush()
        self.monitor.on_event(event, _now())

    def close(self):
        try:
            self.sel.close()
        except OSError:
            pass


def run_review(*, cmd, run_dir, model, stall_timeout, retry_grace,
               global_deadline, poll_interval=0.5, env=None, on_spawn=None,
               input_path=None, cwd=None, effort=None):
    os.makedirs(run_dir, exist_ok=True)
    paths = {k: os.path.join(run_dir, v) for k, v in {
        "raw": "stdout.raw.log", "events": "events.jsonl",
        "stderr": "stderr.log", "result": "result.json"}.items()}

    started = _now()
    sub_env = dict(os.environ)
    sub_env.update({"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    if env:
        sub_env.update(env)

    monitor = Monitor(
        started_at=started, stall_timeout=stall_timeout,
        retry_grace=retry_grace, global_deadline=global_deadline,
        review_root=cwd or run_dir,
    )
    proc = None
    pgid = None
    streams = None
    state = CRASHED
    error = None
    stdin_f = None

    raw_f = open(paths["raw"], "w", encoding="utf-8")
    ev_f = open(paths["events"], "w", encoding="utf-8")
    err_f = open(paths["stderr"], "w", encoding="utf-8")
    try:
        if input_path is not None:
            stdin_f = open(input_path, "rb")
        proc = subprocess.Popen(
            cmd,
            stdin=stdin_f if stdin_f is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True, env=sub_env, bufsize=0, cwd=cwd,
        )
        try:
            pgid = os.getpgid(proc.pid)  # cache immediately, before any exit
        except ProcessLookupError:
            pgid = proc.pid  # start_new_session=True guarantees pgid == pid
        if on_spawn is not None:
            # Lifecycle ownership must be recorded before review proceeds.
            # Any failure here is handled by the outer fail-closed path, which
            # kills/reaps the just-spawned process group and writes CRASHED.
            on_spawn(pgid)
        streams = _Streams(proc.stdout.fileno(), proc.stderr.fileno(),
                           raw_f, ev_f, err_f, monitor)

        decision_state = None
        while True:
            streams.pump(timeout=poll_interval)
            alive = proc.poll() is None
            if not alive:
                # Bounded, non-blocking drain of anything still buffered, then
                # parse a final unterminated line, before classifying.
                drain_deadline = _now() + 0.5
                while _now() < drain_deadline and streams.pump(timeout=0.05):
                    pass
                streams.flush_partial()
            decision = monitor.decide(_now(), alive)
            if decision.action != "continue":
                decision_state = decision.state
                if alive:
                    _kill_group(proc, pgid)
                break
        state = decision_state or CRASHED
    except KeyboardInterrupt:
        error = "review interrupted by user (KeyboardInterrupt)"
        state = CRASHED
        if proc is not None:
            _kill_group(proc, pgid)
    except Exception:  # never leave Claude polling a result that never appears
        error = traceback.format_exc()
        state = CRASHED
        if proc is not None:
            _kill_group(proc, pgid)
    finally:
        raw_f.close(); ev_f.close(); err_f.close()
        if streams is not None:
            streams.close()
        if proc is not None:
            for stream in (proc.stdout, proc.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
        if stdin_f is not None:
            try:
                stdin_f.close()
            except OSError:
                pass

    if not error:
        # A forbidden tool is the stronger local safety signal; preserve it
        # ahead of any provider failure observed in the same stream.
        observed_errors = [e for e in (
            monitor.invalid_error, monitor.provider_error
        ) if e]
        error = "; ".join(observed_errors) or None
    if error is None and state == CRASHED:
        try:
            with open(paths["stderr"], encoding="utf-8") as fh:
                error = fh.read()[-2000:].strip() or None
        except OSError:
            pass
        if error is None:
            returncode = proc.returncode if proc is not None else None
            error = (
                f"reviewer exited with status {returncode} without a valid "
                "structured verdict"
            )

    try:
        result = ReviewResult(
            state=state, items=monitor.verdict_items, model=model, cost=monitor.cost,
            started_at=started, ended_at=_now(), error=error,
            effort=effort, structured_output=monitor.structured_output,
            tool_uses=monitor.tool_uses,
            forbidden_tool_uses=monitor.forbidden_tool_uses,
        )
        result.write(paths["result"])
    except Exception:
        # Never leave the caller without a result: degrade to a CRASHED result
        # and best-effort write (a failed write must still not raise).
        result = ReviewResult(
            state=CRASHED, items=[], model=model, cost=None,
            started_at=started, ended_at=_now(),
            error=((error or "") + "\n" + traceback.format_exc()).strip(),
            effort=effort, structured_output=monitor.structured_output,
            tool_uses=monitor.tool_uses,
            forbidden_tool_uses=monitor.forbidden_tool_uses,
        )
        try:
            result.write(paths["result"])
        except OSError:
            pass
    return result
