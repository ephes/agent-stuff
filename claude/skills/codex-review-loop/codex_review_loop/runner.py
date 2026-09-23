"""Drive one Codex review: spawn in its own process group, monitor the JSON event
stream non-blockingly (raw-fd os.read so a buffered text object can never wedge
us), reap on every exit path, then judge the verdict and the session record and
always write result.json."""
import json
import os
import selectors
import shutil
import signal
import subprocess
import time
import traceback

from . import audit as audit_mod
from .env import codex_env, codex_home
from .monitor import Monitor
from .result import ReviewResult
from .states import (CLEAN, CRASHED, FAILED, INVALID, ISSUES, PROVIDER_ERROR,
                     KIND_CRASH, KIND_FORBIDDEN_TOOL, KIND_INTERRUPTED,
                     KIND_MODEL_MISMATCH, KIND_MODEL_UNPROVEN, KIND_PROVIDER,
                     KIND_VERDICT)
from .verdict import parse_verdict

SESSION_POLL_INTERVAL = 5.0


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

    The harness starts the native binary directly, but the reviewer's own
    children share its group, so the leader exiting is not evidence the group
    is gone: group liveness is.

    Returns the signals actually delivered - those for which `killpg`
    succeeded - so a caller can attribute a signal death to the harness.
    """
    delivered = set()
    if pgid is not None and pgid > 1:
        for sig, timeout in ((signal.SIGTERM, grace), (signal.SIGKILL, 1.0)):
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                break
            delivered.add(int(sig))
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
            if not _group_alive(pgid):
                return delivered
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass
    return delivered


class _Streams:
    """Reads stdout and stderr non-blockingly, splitting stdout into JSONL
    events and teeing raw output; stderr is appended to err_f and counts as
    activity."""

    def __init__(self, out_fd, err_fd, raw_f, ev_f, err_f, monitor):
        self.raw_f, self.ev_f, self.err_f = raw_f, ev_f, err_f
        self.monitor = monitor
        self._buf = b""
        os.set_blocking(out_fd, False)
        os.set_blocking(err_fd, False)
        self.sel = selectors.DefaultSelector()
        self.sel.register(out_fd, selectors.EVENT_READ, "out")
        self.sel.register(err_fd, selectors.EVENT_READ, "err")

    def pump(self, timeout):
        for key, _ in self.sel.select(timeout=timeout):
            try:
                data = os.read(key.fd, 65536)
            except BlockingIOError:
                continue
            if not data:
                try:
                    self.sel.unregister(key.fd)
                except KeyError:
                    pass
                continue
            if key.data == "out":
                self._feed_out(data)
            else:
                self.err_f.write(data.decode(errors="replace"))
                self.err_f.flush()
                self.monitor.note_activity(_now())
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
        self.raw_f.write(line + "\n")
        self.raw_f.flush()
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        if not isinstance(event, dict):
            self.ev_f.write(json.dumps({"type": "malformed_stdout", "raw": line}) + "\n")
            self.ev_f.flush()
            self.monitor.note_activity(_now())
            return
        self.ev_f.write(line + "\n")
        self.ev_f.flush()
        self.monitor.on_event(event, _now())

    def close(self):
        try:
            self.sel.close()
        except OSError:
            pass


class _SessionWatch:
    """Treat growth of Codex's session record as activity.

    Codex writes a record entry for every reasoning step and tool call, but
    prints nothing on stdout until an item completes, so a long silent think
    would otherwise read as a stall.
    """

    def __init__(self, home, monitor):
        self.home, self.monitor = home, monitor
        self.path, self.size, self.next_check = None, -1, 0.0

    def poll(self, now):
        if now < self.next_check or self.monitor.thread_id is None:
            return
        self.next_check = now + SESSION_POLL_INTERVAL
        if self.path is None:
            self.path = audit_mod.find_session_record(self.home, self.monitor.thread_id)
            if self.path is None:
                return
        try:
            size = os.stat(self.path).st_size
        except OSError:
            return
        if size != self.size:
            self.size = size
            self.monitor.note_activity(now)


def exit_is_acceptable(exit_code, *, delivered_signals):
    """Whether a completed turn may be judged given how the process ended.

    Exit 0 always may. Otherwise only a death by a signal the harness
    delivered: a negative status, which POSIX reports only for a signal death,
    naming a signal whose delivery `killpg` confirmed. This holds because the
    harness runs the native binary, not the npm launcher, which swallows the
    signal it re-raises and exits 0 (see `native.py`). A positive
    status is one the process chose, including 143 or 137 - indistinguishable
    from a self-chosen exit that raced the kill - and is never accepted.
    """
    if exit_code == 0:
        return True
    return (isinstance(exit_code, int) and exit_code < 0
            and -exit_code in delivered_signals)


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def run_review(*, cmd, run_dir, prompt_path, last_message_path, model, effort,
               stall_timeout, global_deadline, exit_grace=30.0,
               poll_interval=0.5, env=None, extra_env=None, on_spawn=None):
    os.makedirs(run_dir, exist_ok=True)
    paths = {k: os.path.join(run_dir, v) for k, v in {
        "raw": "stdout.raw.log", "events": "events.jsonl",
        "stderr": "stderr.log", "result": "result.json",
        "session": "session.jsonl"}.items()}

    started = _now()
    sub_env = codex_env(env)
    # The native binary's launch variables in production; the fake reviewer's
    # controls under the test entry point. Never the caller's environment.
    sub_env.update(extra_env or {})
    home = codex_home(env)
    monitor = Monitor(started_at=started, stall_timeout=stall_timeout,
                      global_deadline=global_deadline, exit_grace=exit_grace)
    session = _SessionWatch(home, monitor)
    proc = pgid = streams = None
    state, kind, error = None, None, None
    delivered_signals = set()

    raw_f = open(paths["raw"], "w")
    ev_f = open(paths["events"], "w")
    err_f = open(paths["stderr"], "w")
    prompt_f = open(prompt_path, "rb")
    try:
        proc = subprocess.Popen(
            cmd, stdin=prompt_f, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, env=sub_env, bufsize=0,
        )
        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            pgid = proc.pid  # start_new_session=True guarantees pgid == pid
        if on_spawn is not None:
            try:
                on_spawn(pgid)
            except Exception:
                pass  # recording the pgid must never break the review
        streams = _Streams(proc.stdout.fileno(), proc.stderr.fileno(),
                           raw_f, ev_f, err_f, monitor)
        while True:
            streams.pump(timeout=poll_interval)
            session.poll(_now())
            alive = proc.poll() is None
            if not alive:
                drain_deadline = _now() + 0.5
                while _now() < drain_deadline and streams.pump(timeout=0.05):
                    pass
                streams.flush_partial()
            decision = monitor.decide(_now(), alive)
            if decision.action == "continue":
                continue
            state, kind = decision.state, decision.kind
            # Only a run the harness ended itself after its turn completed may
            # be judged without a clean exit: Codex has been seen to hang at
            # exit. Attribution rests on the signals actually delivered and
            # the final status, never on this liveness sample.
            if alive or _group_alive(pgid):
                # The second case: the launcher exited but the native
                # reviewer did not.
                delivered_signals = _kill_group(proc, pgid)
            break
    except KeyboardInterrupt:
        state, kind = CRASHED, KIND_INTERRUPTED
        error = "review interrupted by user (KeyboardInterrupt)"
        if proc is not None:
            _kill_group(proc, pgid)
    except Exception:  # never leave the caller waiting for a result
        state, kind, error = CRASHED, KIND_CRASH, traceback.format_exc()
        if proc is not None:
            _kill_group(proc, pgid)
    finally:
        for fh in (raw_f, ev_f, err_f, prompt_f):
            fh.close()
        if streams is not None:
            streams.close()
        if proc is not None:
            for stream in (proc.stdout, proc.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass

    items, structured, raw_text = [], None, None
    exit_code = proc.returncode if proc is not None else None
    if state is None and monitor.completed_at is not None \
            and not exit_is_acceptable(exit_code, delivered_signals=delivered_signals):
        state, kind = CRASHED, KIND_CRASH
        error = (f"reviewer exited with status {exit_code} after its turn "
                 "completed; a verdict from a failed process is not accepted")
    if state is None:
        if monitor.completed_at is not None:
            raw_text = _read_text(last_message_path)
            state, items, structured, verdict_error = parse_verdict(raw_text)
            if verdict_error:
                kind, error = KIND_VERDICT, verdict_error
        elif monitor.errors:
            state, kind = PROVIDER_ERROR, KIND_PROVIDER
            error = monitor.errors[-1]
        else:
            state, kind = CRASHED, KIND_CRASH
    if state == PROVIDER_ERROR and error is None:
        error = monitor.turn_failure or (monitor.errors[-1] if monitor.errors else None)
    if error is None and state == CRASHED:
        tail = _read_text(paths["stderr"])
        error = (tail or "")[-2000:] or "reviewer exited without a completed turn"
    if state == INVALID and kind == KIND_FORBIDDEN_TOOL and error is None:
        error = "delegation in the event stream: " + ", ".join(monitor.forbidden)

    # The session record decides whether a verdict counts at all.
    record = audit_mod.find_session_record(home, monitor.thread_id)
    audit = audit_mod.audit_session(record)
    if record is not None:
        try:
            shutil.copyfile(record, paths["session"])
        except OSError:
            pass
    forbidden = list(monitor.forbidden) + list(audit.forbidden)
    if forbidden:
        # Delegation outranks every other outcome: whatever else happened, the
        # review was not one direct, sandboxed context.
        state, kind, items = INVALID, KIND_FORBIDDEN_TOOL, []
        error = "forbidden tool use: " + ", ".join(sorted(set(forbidden)))
    if state in (CLEAN, ISSUES):
        reason = audit_mod.judge(audit, model=model, effort=effort)
        if reason is not None:
            state = INVALID
            kind = KIND_MODEL_UNPROVEN if (audit.error or not audit.models) \
                else KIND_MODEL_MISMATCH
            error = reason
            items = []
    elif audit.error is None:
        reason = audit_mod.judge(audit, model=model, effort=effort)
        if reason is not None and error:
            error = f"{error}\n(session record: {reason})"

    result = ReviewResult(
        state=state, items=items, model=model, effort=effort, cost=None,
        started_at=started, ended_at=_now(), failure_kind=kind if state in FAILED else None,
        thread_id=monitor.thread_id, session_record=record,
        observed_models=audit.models, observed_efforts=audit.efforts,
        tool_uses=audit.tool_uses, forbidden_tool_uses=sorted(set(forbidden)),
        structured_output=structured, error=error, raw_verdict_line=raw_text,
    )
    try:
        result.write(paths["result"])
    except OSError:
        pass
    return result
