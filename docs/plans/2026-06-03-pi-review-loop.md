# Pi Review Loop Implementation Plan

> **Historical plan:** Model-selection steps below describe the original
> implementation. Since 2026-07-12 the production gate permits only
> `openai-codex/gpt-5.6-sol` and fails closed if it is unavailable. It never
> falls back to Claude/Anthropic, OpenRouter, a local model, or another provider.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill that runs a bounded review loop — Claude implements, hands the diff to a foreground Python harness that drives Pi as a fresh-context reviewer over its `--mode json` event stream, and only proceeds when Pi returns a clean, parseable verdict.

**Architecture:** A pure-stdlib Python package (`pi_review_loop/`) invoked as one foreground process per review. It assembles a bounded git bundle, spawns Pi in its own process group with observability env vars, monitors the JSONL event stream with a non-blocking 8-way state machine (bounded retries + unsuspendable global deadline), parses the verdict from the final assistant message only (fail-closed), reaps the process group on every exit path, and writes deterministic artifacts (`result.json`, `events.jsonl`, `stdout.raw.log`, `stderr.log`). A `SKILL.md` tells Claude how to drive the outer fix/re-review loop.

**Tech Stack:** Python 3 standard library only (no third-party deps — the harness runs in arbitrary repos). Tests use stdlib `unittest`. Pi `0.78.0+` CLI. Git.

**Reference spec:** `docs/specs/2026-06-03-pi-review-loop-design.md` (commit `980720b`+).

---

## File Structure

All under `claude/skills/pi-review-loop/` (the skill root, which is also the test rootdir):

- `SKILL.md` — Claude-facing instructions for the outer review→fix→re-review loop.
- `bin/pi-review-loop` — executable entry; adds skill root to `sys.path`, calls `cli.main`.
- `pi_review_loop/__init__.py` — package marker.
- `pi_review_loop/states.py` — terminal state string constants.
- `pi_review_loop/verdict.py` — extract final assistant text + parse `REVIEW:` verdict (fail-closed).
- `pi_review_loop/result.py` — `ReviewResult` dataclass + JSON serialization.
- `pi_review_loop/monitor.py` — `Monitor` state machine + `decide()` (the 8-way check).
- `pi_review_loop/model.py` — require the approved GPT-5.6 Sol model from
  `pi --list-models gpt` and reject every alternative.
- `pi_review_loop/lock.py` — atomic global-per-user lock with reuse-safe stale reclaim.
- `pi_review_loop/bundle.py` — build the bounded review bundle from git (size/diff/total caps).
- `pi_review_loop/runner.py` — spawn Pi, drive the monitor over real IO, reap, write artifacts.
- `pi_review_loop/cli.py` — argparse + wiring of `main()`.
- `tests/__init__.py`
- `tests/test_verdict.py`, `tests/test_result.py`, `tests/test_monitor.py`, `tests/test_model.py`, `tests/test_lock.py`, `tests/test_bundle.py`, `tests/test_runner.py`
- `tests/fake_pi.py` — a fake `pi` (emits canned JSONL with timing) for runner integration tests.

Shared contracts (locked here so every task is consistent):

- **State constants** (`states.py`): `CLEAN`, `ISSUES`, `INVALID`, `CRASHED`, `STALLED`, `STALLED_RETRY`, `PROVIDER_ERROR`.
- `verdict.extract_final_assistant_text(agent_end_event: dict) -> str | None`
- `verdict.parse_verdict(text: str) -> tuple[str, list[dict]]` — returns `(state, items)`; `state ∈ {CLEAN, ISSUES, INVALID}`; each item `{"severity","path","message"}`.
- `result.ReviewResult` dataclass with `.to_dict()` and `.write(path)`.
- `monitor.Decision(action: str, state: str | None)` — `action ∈ {"continue","kill","finish"}`.
- `monitor.Monitor(started_at, stall_timeout, retry_grace, global_deadline)` with `.on_event(event, now)`, `.decide(now, proc_alive) -> Decision`, and attributes `.verdict_state`, `.verdict_items`, `.provider_error`.
- `model.resolve_model(list_models_output: str, fallback: str = "openai-codex/gpt-5.5") -> str`
- `lock.Lock(lock_dir: str, meta: dict)` context manager; raises `lock.LockHeld` if a live review holds it.
- `bundle.build_bundle(repo, out_path, *, max_file_size, max_diff_bytes_per_file, max_bundle_bytes, staged_only=False) -> bundle.BundleResult` (`.path`, `.skipped_files`, `.truncations`).
- `runner.run_review(...) -> ReviewResult`
- Defaults (cli): `stall_timeout=180`, `retry_grace=30`, `global_deadline=1500`, `max_file_size=262144`, `max_diff_bytes_per_file=262144`, `max_bundle_bytes=2097152`, `max_rounds=3`.

---

## Task 0: Scaffold the package and test harness

**Files:**
- Create: `claude/skills/pi-review-loop/pi_review_loop/__init__.py`
- Create: `claude/skills/pi-review-loop/pi_review_loop/states.py`
- Create: `claude/skills/pi-review-loop/tests/__init__.py`
- Create: `claude/skills/pi-review-loop/tests/test_states.py`

- [ ] **Step 1: Create the package marker and states module**

`pi_review_loop/__init__.py`:
```python
"""Pi review-loop harness (pure stdlib)."""
```

`pi_review_loop/states.py`:
```python
"""Terminal review states. A review ends in exactly one of these."""

CLEAN = "CLEAN"
ISSUES = "ISSUES"
INVALID = "INVALID"
CRASHED = "CRASHED"
STALLED = "STALLED"
STALLED_RETRY = "STALLED_RETRY"
PROVIDER_ERROR = "PROVIDER_ERROR"

# States that mean "do not commit; not a usable clean review".
FAILED = frozenset({INVALID, CRASHED, STALLED, STALLED_RETRY, PROVIDER_ERROR})
# All valid states (used for validation/serialization sanity).
ALL = frozenset({CLEAN, ISSUES} | FAILED)
```

- [ ] **Step 2: Write the failing test**

`tests/__init__.py`: (empty file)

`tests/test_states.py`:
```python
import unittest
from pi_review_loop import states


class TestStates(unittest.TestCase):
    def test_clean_and_issues_are_not_failed(self):
        self.assertNotIn(states.CLEAN, states.FAILED)
        self.assertNotIn(states.ISSUES, states.FAILED)

    def test_invalid_is_failed(self):
        self.assertIn(states.INVALID, states.FAILED)

    def test_all_contains_every_state(self):
        self.assertEqual(len(states.ALL), 7)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it passes**

Run (from the skill root so `pi_review_loop` is importable):
```bash
cd claude/skills/pi-review-loop && python3 -m unittest discover -s tests -v
```
Expected: `test_states` passes (3 tests OK).

- [ ] **Step 4: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add claude/skills/pi-review-loop/pi_review_loop claude/skills/pi-review-loop/tests
git commit -m "feat(pi-review-loop): scaffold package + state constants"
```

---

## Task 1: Verdict parsing (final assistant message only, fail-closed)

**Files:**
- Create: `pi_review_loop/verdict.py`
- Test: `tests/test_verdict.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_verdict.py`:
```python
import unittest
from pi_review_loop import verdict
from pi_review_loop.states import CLEAN, ISSUES, INVALID


def agent_end(messages):
    return {"type": "agent_end", "messages": messages}


class TestExtractFinalAssistant(unittest.TestCase):
    def test_picks_last_assistant_concatenates_text_blocks(self):
        ev = agent_end([
            {"role": "user", "content": [{"type": "text", "text": "REVIEW: CLEAN"}]},
            {"role": "assistant", "content": [
                {"type": "thinking", "text": "ignore me"},
                {"type": "text", "text": "Looks good.\n"},
                {"type": "text", "text": "REVIEW: CLEAN"},
            ]},
        ])
        self.assertEqual(
            verdict.extract_final_assistant_text(ev),
            "Looks good.\nREVIEW: CLEAN",
        )

    def test_returns_none_when_no_assistant(self):
        ev = agent_end([{"role": "user", "content": [{"type": "text", "text": "hi"}]}])
        self.assertIsNone(verdict.extract_final_assistant_text(ev))


class TestParseVerdict(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(verdict.parse_verdict("ok\nREVIEW: CLEAN"), (CLEAN, []))

    def test_issues_with_items(self):
        text = (
            "REVIEW: ISSUES\n"
            "1. [Critical] src/a.py: boom\n"
            "2. [Warning] src/b.py: careful\n"
        )
        state, items = verdict.parse_verdict(text)
        self.assertEqual(state, ISSUES)
        self.assertEqual(items, [
            {"severity": "Critical", "path": "src/a.py", "message": "boom"},
            {"severity": "Warning", "path": "src/b.py", "message": "careful"},
        ])

    def test_issues_without_items_is_invalid(self):
        self.assertEqual(verdict.parse_verdict("REVIEW: ISSUES\n")[0], INVALID)

    def test_no_verdict_line_is_invalid(self):
        self.assertEqual(verdict.parse_verdict("I reviewed it, all fine")[0], INVALID)

    def test_takes_last_verdict_line(self):
        # An earlier quoted CLEAN must not win over the real trailing verdict.
        text = "quoting: REVIEW: CLEAN\n...\nREVIEW: ISSUES\n1. [Suggestion] x.py: tidy"
        self.assertEqual(verdict.parse_verdict(text)[0], ISSUES)

    def test_unknown_severity_item_is_ignored(self):
        # Only Critical/Warning/Suggestion count; zero valid items => INVALID.
        self.assertEqual(verdict.parse_verdict("REVIEW: ISSUES\n1. [Bogus] x: y")[0], INVALID)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_verdict -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pi_review_loop.verdict'`.

- [ ] **Step 3: Implement `verdict.py`**

```python
"""Parse Pi's review verdict from the final assistant message only.

Never scan the whole agent_end transcript: it echoes the prompt/bundle, which
contains REVIEW: examples, so a transcript scan can accept prompt text as a
verdict (false pass). Fail closed: anything unparseable is INVALID, never CLEAN.
"""
import re
from .states import CLEAN, ISSUES, INVALID

_VERDICT_RE = re.compile(r"^REVIEW: (CLEAN|ISSUES)$", re.MULTILINE)
_ITEM_RE = re.compile(
    r"^\s*\d+\.\s*\[(Critical|Warning|Suggestion)\]\s*([^:]+):\s*(.+?)\s*$"
)


def extract_final_assistant_text(agent_end_event):
    """Return the concatenated text-block content of the last assistant message,
    or None if there is no assistant message."""
    messages = agent_end_event.get("messages") or []
    last = None
    for msg in messages:
        if msg.get("role") == "assistant":
            last = msg
    if last is None:
        return None
    parts = []
    content = last.get("content")
    if isinstance(content, str):
        return content
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


def parse_verdict(text):
    """Return (state, items). state is CLEAN, ISSUES, or INVALID."""
    if not text:
        return INVALID, []
    matches = list(_VERDICT_RE.finditer(text))
    if not matches:
        return INVALID, []
    last = matches[-1]
    if last.group(1) == "CLEAN":
        return CLEAN, []
    # ISSUES: parse numbered items that appear after the verdict line.
    tail = text[last.end():]
    items = []
    for line in tail.splitlines():
        m = _ITEM_RE.match(line)
        if m:
            items.append({
                "severity": m.group(1),
                "path": m.group(2).strip(),
                "message": m.group(3).strip(),
            })
    if not items:
        return INVALID, []
    return ISSUES, items
```

- [ ] **Step 4: Run to verify pass**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_verdict -v`
Expected: PASS (all tests OK).

- [ ] **Step 5: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add claude/skills/pi-review-loop/pi_review_loop/verdict.py claude/skills/pi-review-loop/tests/test_verdict.py
git commit -m "feat(pi-review-loop): fail-closed verdict parser from final assistant message"
```

---

## Task 2: ReviewResult and artifact serialization

**Files:**
- Create: `pi_review_loop/result.py`
- Test: `tests/test_result.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_result.py`:
```python
import json
import os
import tempfile
import unittest
from pi_review_loop import result
from pi_review_loop.states import CLEAN, ISSUES


class TestReviewResult(unittest.TestCase):
    def test_scoped_clean_true_when_clean_with_skips(self):
        r = result.ReviewResult(
            state=CLEAN, items=[], model="openai-codex/gpt-5.5", cost=0.1,
            started_at=1.0, ended_at=2.0,
            skipped_files=[{"path": "big.json", "reason": "size", "size": 999999}],
            truncations=[], error=None, raw_verdict_line="REVIEW: CLEAN",
        )
        self.assertTrue(r.scoped_clean)

    def test_scoped_clean_false_when_clean_no_skips(self):
        r = result.ReviewResult(
            state=CLEAN, items=[], model="m", cost=None,
            started_at=1.0, ended_at=2.0, skipped_files=[], truncations=[],
            error=None, raw_verdict_line="REVIEW: CLEAN",
        )
        self.assertFalse(r.scoped_clean)

    def test_scoped_clean_false_when_issues(self):
        r = result.ReviewResult(
            state=ISSUES, items=[{"severity": "Warning", "path": "a", "message": "b"}],
            model="m", cost=None, started_at=1.0, ended_at=2.0,
            skipped_files=[{"path": "x"}], truncations=[], error=None,
            raw_verdict_line="REVIEW: ISSUES",
        )
        self.assertFalse(r.scoped_clean)

    def test_write_roundtrips_json(self):
        r = result.ReviewResult(
            state=CLEAN, items=[], model="m", cost=0.0, started_at=1.0,
            ended_at=2.0, skipped_files=[], truncations=[], error=None,
            raw_verdict_line=None,
        )
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "result.json")
            r.write(p)
            with open(p) as fh:
                data = json.load(fh)
        self.assertEqual(data["state"], CLEAN)
        self.assertIn("scoped_clean", data)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_result -v`
Expected: FAIL — no module `pi_review_loop.result`.

- [ ] **Step 3: Implement `result.py`**

```python
"""ReviewResult: the single structured outcome of one review, written to result.json."""
import json
from dataclasses import dataclass, field, asdict
from .states import CLEAN


@dataclass
class ReviewResult:
    state: str
    items: list
    model: str
    cost: float | None
    started_at: float
    ended_at: float
    skipped_files: list = field(default_factory=list)
    truncations: list = field(default_factory=list)
    error: str | None = None
    raw_verdict_line: str | None = None

    @property
    def scoped_clean(self):
        """A CLEAN verdict over a bundle that skipped or truncated content is only
        'clean within provided scope', not absolute."""
        return self.state == CLEAN and bool(self.skipped_files or self.truncations)

    def to_dict(self):
        d = asdict(self)
        d["scoped_clean"] = self.scoped_clean
        d["duration_s"] = round(self.ended_at - self.started_at, 3)
        return d

    def write(self, path):
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_result -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add claude/skills/pi-review-loop/pi_review_loop/result.py claude/skills/pi-review-loop/tests/test_result.py
git commit -m "feat(pi-review-loop): ReviewResult dataclass + result.json serialization"
```

---

## Task 3: The monitor state machine (8-way decision)

**Files:**
- Create: `pi_review_loop/monitor.py`
- Test: `tests/test_monitor.py`

The `decide()` order (pure logic; the runner supplies `now` and `proc_alive`, and feeds drained final events before calling with `proc_alive=False`):
1. verdict already parsed from `agent_end` → `finish` (state CLEAN/ISSUES/INVALID)
2. provider gave up (`auto_retry_end success:false`) → `kill` PROVIDER_ERROR (checked before generic crash so `finalError` is preserved)
3. process not alive (no verdict) → `finish` CRASHED
4. past global deadline (never suspended) → `kill` STALLED
5. inside a retry window past `retry_deadline` → `kill` STALLED_RETRY
6. not in a retry window and stalled > T → `kill` STALLED
7. else → `continue`

- [ ] **Step 1: Write the failing tests**

`tests/test_monitor.py`:
```python
import unittest
from pi_review_loop.monitor import Monitor, Decision
from pi_review_loop.states import (
    CLEAN, ISSUES, INVALID, CRASHED, STALLED, STALLED_RETRY, PROVIDER_ERROR,
)


def mon():
    return Monitor(started_at=0.0, stall_timeout=180, retry_grace=30,
                   global_deadline=1500)


def agent_end_clean():
    return {"type": "agent_end", "messages": [
        {"role": "assistant", "content": [{"type": "text", "text": "REVIEW: CLEAN"}]},
    ]}


class TestMonitor(unittest.TestCase):
    def test_continue_when_fresh(self):
        m = mon()
        self.assertEqual(m.decide(now=10, proc_alive=True), Decision("continue", None))

    def test_agent_end_clean_finishes(self):
        m = mon()
        m.on_event(agent_end_clean(), now=5)
        d = m.decide(now=6, proc_alive=True)
        self.assertEqual(d, Decision("finish", CLEAN))
        self.assertEqual(m.verdict_state, CLEAN)

    def test_agent_end_without_verdict_is_invalid(self):
        m = mon()
        m.on_event({"type": "agent_end", "messages": [
            {"role": "assistant", "content": [{"type": "text", "text": "all good"}]},
        ]}, now=5)
        self.assertEqual(m.decide(now=6, proc_alive=True), Decision("finish", INVALID))

    def test_provider_giveup_before_crash(self):
        m = mon()
        m.on_event({"type": "auto_retry_end", "success": False, "finalError": "529"}, now=5)
        # Even though the process has also exited, provider error wins (keeps finalError).
        self.assertEqual(m.decide(now=6, proc_alive=False), Decision("kill", PROVIDER_ERROR))
        self.assertEqual(m.provider_error, "529")

    def test_process_exit_without_verdict_is_crashed(self):
        m = mon()
        self.assertEqual(m.decide(now=6, proc_alive=False), Decision("finish", CRASHED))

    def test_global_deadline(self):
        m = mon()
        m.on_event({"type": "message_update"}, now=1490)  # keep heartbeat fresh
        self.assertEqual(m.decide(now=1501, proc_alive=True), Decision("kill", STALLED))

    def test_stall_timeout(self):
        m = mon()
        m.on_event({"type": "message_update"}, now=10)
        self.assertEqual(m.decide(now=10 + 181, proc_alive=True), Decision("kill", STALLED))

    def test_retry_window_suspends_stall(self):
        m = mon()
        m.on_event({"type": "auto_retry_start", "delayMs": 2000}, now=10)
        # 200s later, normally a stall, but we are inside the retry window's grace.
        # retry_deadline = 10 + 2 + 30 = 42; at now=41 still inside -> continue.
        self.assertEqual(m.decide(now=41, proc_alive=True), Decision("continue", None))

    def test_retry_window_expired(self):
        m = mon()
        m.on_event({"type": "auto_retry_start", "delayMs": 2000}, now=10)
        # past retry_deadline (42) with no auto_retry_end -> STALLED_RETRY
        self.assertEqual(m.decide(now=43, proc_alive=True), Decision("kill", STALLED_RETRY))

    def test_retry_end_success_clears_window(self):
        m = mon()
        m.on_event({"type": "auto_retry_start", "delayMs": 2000}, now=10)
        m.on_event({"type": "auto_retry_end", "success": True}, now=12)
        # window cleared; fresh heartbeat at 12; at 50 well within stall timeout
        self.assertEqual(m.decide(now=50, proc_alive=True), Decision("continue", None))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_monitor -v`
Expected: FAIL — no module `pi_review_loop.monitor`.

- [ ] **Step 3: Implement `monitor.py`**

```python
"""Pure state machine for the review monitor. No IO, no clock — the runner feeds
events and the current time, so this is fully unit-testable."""
from dataclasses import dataclass
from .states import CRASHED, STALLED, STALLED_RETRY, PROVIDER_ERROR
from .verdict import extract_final_assistant_text, parse_verdict


@dataclass(frozen=True)
class Decision:
    action: str          # "continue" | "kill" | "finish"
    state: str | None    # terminal state when action in ("kill", "finish")


class Monitor:
    def __init__(self, *, started_at, stall_timeout, retry_grace, global_deadline):
        self.started_at = started_at
        self.stall_timeout = stall_timeout
        self.retry_grace = retry_grace
        self.global_deadline_at = started_at + global_deadline
        self.last_event_at = started_at
        self.verdict_state = None      # set when agent_end arrives
        self.verdict_items = []
        self.verdict_text = None
        self.provider_error = None     # finalError when provider gives up
        self.retry_until = None        # retry_deadline timestamp, or None

    def on_event(self, event, now):
        self.last_event_at = now
        etype = event.get("type")
        if etype == "agent_end":
            text = extract_final_assistant_text(event)
            self.verdict_text = text
            self.verdict_state, self.verdict_items = parse_verdict(text or "")
        elif etype == "auto_retry_start":
            delay_s = (event.get("delayMs") or 0) / 1000.0
            self.retry_until = now + delay_s + self.retry_grace
        elif etype == "auto_retry_end":
            self.retry_until = None
            if event.get("success") is False:
                self.provider_error = event.get("finalError") or "provider gave up"

    def decide(self, now, proc_alive):
        if self.verdict_state is not None:
            return Decision("finish", self.verdict_state)
        if self.provider_error is not None:
            return Decision("kill", PROVIDER_ERROR)
        if not proc_alive:
            return Decision("finish", CRASHED)
        if now > self.global_deadline_at:
            return Decision("kill", STALLED)
        if self.retry_until is not None and now > self.retry_until:
            return Decision("kill", STALLED_RETRY)
        if self.retry_until is None and (now - self.last_event_at) > self.stall_timeout:
            return Decision("kill", STALLED)
        return Decision("continue", None)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_monitor -v`
Expected: PASS (all 10 tests OK).

- [ ] **Step 5: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add claude/skills/pi-review-loop/pi_review_loop/monitor.py claude/skills/pi-review-loop/tests/test_monitor.py
git commit -m "feat(pi-review-loop): 8-way monitor state machine"
```

---

## Task 4: Model resolution (historical; superseded by the fixed-model policy)

**Files:**
- Create: `pi_review_loop/model.py`
- Test: `tests/test_model.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_model.py`:
```python
import unittest
from pi_review_loop import model

SAMPLE = """\
openai-codex/gpt-5.5
openai-codex/gpt-5.1
anthropic/claude-opus-4-8
google/gemini-2.5-pro
openai-codex/gpt-4.1
"""


class TestResolveModel(unittest.TestCase):
    def test_picks_highest_gpt(self):
        self.assertEqual(model.resolve_model(SAMPLE), "openai-codex/gpt-5.5")

    def test_passes_provider_prefix_exactly(self):
        out = "someprovider/gpt-9000-turbo\nother/gpt-3"
        self.assertEqual(model.resolve_model(out), "someprovider/gpt-9000-turbo")

    def test_falls_back_when_no_gpt(self):
        self.assertEqual(
            model.resolve_model("anthropic/claude-opus-4-8\n", fallback="pin/x"),
            "pin/x",
        )

    def test_ignores_blank_and_noise_lines(self):
        out = "\n  \nAvailable models:\nopenai-codex/gpt-5.5\n"
        self.assertEqual(model.resolve_model(out), "openai-codex/gpt-5.5")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_model -v`
Expected: FAIL — no module `pi_review_loop.model`.

- [ ] **Step 3: Implement `model.py`**

```python
"""Resolve the newest available GPT model id from `pi --list-models gpt` output.

Format is tolerant: take the first whitespace-delimited token on each line as a
candidate '<provider>/<model>' id, keep those whose model part contains 'gpt',
and pick the highest by the numeric version embedded in the model name. The
chosen id is passed to `--model` exactly as listed (preserving provider prefix).
"""
import re
import subprocess

_NUM_RE = re.compile(r"(\d+(?:\.\d+)*)")


def _version_key(model_part):
    m = _NUM_RE.search(model_part)
    if not m:
        return (0,)
    return tuple(int(x) for x in m.group(1).split("."))


def resolve_model(list_models_output, fallback="openai-codex/gpt-5.5"):
    candidates = []
    for line in list_models_output.splitlines():
        line = line.strip()
        if not line or "/" not in line:
            continue
        token = line.split()[0]
        if "/" not in token:
            continue
        model_part = token.rsplit("/", 1)[1].lower()
        if "gpt" not in model_part:
            continue
        candidates.append(token)
    if not candidates:
        return fallback
    return max(candidates, key=lambda t: _version_key(t.rsplit("/", 1)[1]))


def resolve_from_cli(fallback="openai-codex/gpt-5.5", timeout=30):
    """Run `pi --list-models gpt` and resolve; fall back on any failure."""
    try:
        out = subprocess.run(
            ["pi", "--list-models", "gpt"],
            capture_output=True, text=True, timeout=timeout, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return fallback
    return resolve_model(out, fallback=fallback)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_model -v`
Expected: PASS.

- [ ] **Step 5: Verify the real CLI format (one-time check, do not block on it)**

Run: `pi --list-models gpt`
Confirm each line's first token is `<provider>/<model>`. If the format differs (e.g. columns, bullets), adjust `resolve_model`'s tokenization and add a test case with the real sample. Note the observed format in a comment.

- [ ] **Step 6: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add claude/skills/pi-review-loop/pi_review_loop/model.py claude/skills/pi-review-loop/tests/test_model.py
git commit -m "feat(pi-review-loop): resolve newest GPT model id"
```

---

## Task 5: Atomic global lock with reuse-safe stale reclaim

**Files:**
- Create: `pi_review_loop/lock.py`
- Test: `tests/test_lock.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_lock.py`:
```python
import os
import tempfile
import unittest
from pi_review_loop import lock


class TestLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lock_dir = os.path.join(self.tmp.name, "pi-review.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def test_acquire_and_release(self):
        with lock.Lock(self.lock_dir, {"pi_pgid": -1}):
            self.assertTrue(os.path.isdir(self.lock_dir))
        self.assertFalse(os.path.exists(self.lock_dir))

    def test_second_acquire_raises_when_held_by_live_group(self):
        # Use our own pgid as a stand-in for a "live" Pi group.
        meta = {"pi_pgid": os.getpgrp(), "command": "pi", "cwd": os.getcwd()}
        with lock.Lock(self.lock_dir, meta):
            with self.assertRaises(lock.LockHeld):
                with lock.Lock(self.lock_dir, {"pi_pgid": -1}):
                    pass

    def test_reclaims_stale_lock_when_group_dead(self):
        # Pre-create a lock whose recorded pgid is dead (no such group).
        os.mkdir(self.lock_dir)
        lock.write_meta(self.lock_dir, {
            "pi_pgid": 2_000_000_000,  # not a live group
            "command": "pi", "cwd": os.getcwd(),
        })
        # A fresh acquire should reclaim it rather than raise.
        with lock.Lock(self.lock_dir, {"pi_pgid": -1}):
            self.assertTrue(os.path.isdir(self.lock_dir))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_lock -v`
Expected: FAIL — no module `pi_review_loop.lock`.

- [ ] **Step 3: Implement `lock.py`**

```python
"""Atomic, global-per-user lock so only one Pi review runs at a time (concurrent
reviews are what worsen provider API blocking). Uses mkdir for atomicity. Stale
reclaim is reuse-safe: it only removes a lock whose recorded process group is
genuinely gone."""
import errno
import json
import os
import signal

META_NAME = "meta.json"


class LockHeld(Exception):
    """Raised when a live review already holds the lock."""


def write_meta(lock_dir, meta):
    with open(os.path.join(lock_dir, META_NAME), "w") as fh:
        json.dump(meta, fh)


def read_meta(lock_dir):
    try:
        with open(os.path.join(lock_dir, META_NAME)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _group_alive(pgid):
    if not pgid or pgid <= 1:
        return False
    try:
        os.killpg(pgid, 0)  # signal 0 = liveness probe
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned elsewhere; treat as alive (do not reclaim)
    except OSError as e:
        return e.errno != errno.ESRCH


def _reclaim_if_stale(lock_dir):
    """Remove the lock dir iff its recorded process group is dead. Returns True
    if it reclaimed (or the dir vanished)."""
    meta = read_meta(lock_dir)
    if _group_alive(meta.get("pi_pgid")):
        return False
    # Group is gone: best-effort kill (tolerate ESRCH) then remove the dir.
    pgid = meta.get("pi_pgid")
    if pgid and pgid > 1:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        os.remove(os.path.join(lock_dir, META_NAME))
    except OSError:
        pass
    try:
        os.rmdir(lock_dir)
    except OSError:
        pass
    return True


class Lock:
    def __init__(self, lock_dir, meta):
        self.lock_dir = lock_dir
        self.meta = dict(meta)

    def __enter__(self):
        try:
            os.mkdir(self.lock_dir)
        except FileExistsError:
            if not _reclaim_if_stale(self.lock_dir):
                raise LockHeld(f"review lock held: {self.lock_dir}")
            os.mkdir(self.lock_dir)  # may raise FileExistsError if a real race; let it propagate
        write_meta(self.lock_dir, self.meta)
        return self

    def __exit__(self, *exc):
        try:
            os.remove(os.path.join(self.lock_dir, META_NAME))
        except OSError:
            pass
        try:
            os.rmdir(self.lock_dir)
        except OSError:
            pass
        return False
```

- [ ] **Step 4: Run to verify pass**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_lock -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add claude/skills/pi-review-loop/pi_review_loop/lock.py claude/skills/pi-review-loop/tests/test_lock.py
git commit -m "feat(pi-review-loop): atomic global lock with reuse-safe stale reclaim"
```

---

## Task 6: Build the bounded review bundle from git

**Files:**
- Create: `pi_review_loop/bundle.py`
- Test: `tests/test_bundle.py`

The bundle (a single Markdown file passed to Pi as `@review-bundle.md`) contains, in priority order: header + diffstat, the staged diff, the unstaged diff, untracked file contents (under the size cap), binary/renamed/deleted notes, and an explicit skipped/truncated list. Per-file diffs are truncated past `max_diff_bytes_per_file`; the whole file is capped at `max_bundle_bytes` by dropping lowest-priority sections last.

- [ ] **Step 1: Write the failing tests**

`tests/test_bundle.py`:
```python
import os
import subprocess
import tempfile
import unittest
from pi_review_loop import bundle


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


class TestBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("print('one')\n")
        git(self.repo, "add", "a.py")
        git(self.repo, "commit", "-qm", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self, **kw):
        out = os.path.join(self.repo, "review-bundle.md")
        defaults = dict(max_file_size=262144, max_diff_bytes_per_file=262144,
                        max_bundle_bytes=2097152)
        defaults.update(kw)
        return bundle.build_bundle(self.repo, out, **defaults)

    def test_includes_unstaged_diff(self):
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("print('two')\n")
        res = self._build()
        text = open(res.path).read()
        self.assertIn("two", text)
        self.assertIn("diffstat", text.lower())

    def test_untracked_file_contents_included(self):
        with open(os.path.join(self.repo, "new.py"), "w") as fh:
            fh.write("NEW_MARKER = 1\n")
        res = self._build()
        self.assertIn("NEW_MARKER", open(res.path).read())

    def test_oversized_file_is_skipped_not_inlined(self):
        big = "x" * 5000
        with open(os.path.join(self.repo, "big.txt"), "w") as fh:
            fh.write(big + "\n")
        res = self._build(max_file_size=1000)
        self.assertTrue(any(s["path"] == "big.txt" for s in res.skipped_files))
        self.assertNotIn(big, open(res.path).read())

    def test_per_file_diff_truncated(self):
        with open(os.path.join(self.repo, "a.py"), "w") as fh:
            fh.write("\n".join(f"line{i}" for i in range(2000)) + "\n")
        res = self._build(max_diff_bytes_per_file=500)
        self.assertTrue(res.truncations)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_bundle -v`
Expected: FAIL — no module `pi_review_loop.bundle`.

- [ ] **Step 3: Implement `bundle.py`**

```python
"""Assemble a bounded review bundle from the working tree's git state. Because Pi
runs with --no-tools, this bundle is the entire review surface, so its contents
are explicit and its omissions are recorded (never silent)."""
import os
import subprocess
from dataclasses import dataclass, field


@dataclass
class BundleResult:
    path: str
    skipped_files: list = field(default_factory=list)
    truncations: list = field(default_factory=list)


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def _truncate(text, limit, label, truncations):
    if len(text.encode()) <= limit:
        return text
    cut = text.encode()[:limit].decode(errors="ignore")
    truncations.append({"section": label, "kept_bytes": len(cut.encode())})
    return cut + f"\n... [truncated {label} at {limit} bytes] ...\n"


def build_bundle(repo, out_path, *, max_file_size, max_diff_bytes_per_file,
                 max_bundle_bytes, staged_only=False):
    skipped, truncations = [], []
    sections = []  # (priority, title, body) — lower priority dropped first

    diffstat = _git(repo, "diff", "--stat", "HEAD")
    sections.append((0, "Diffstat", diffstat or "(no tracked changes)"))

    staged = _git(repo, "diff", "--cached")
    if staged.strip():
        staged = _truncate(staged, max_diff_bytes_per_file, "staged diff", truncations)
        sections.append((1, "Staged diff", staged))

    if not staged_only:
        unstaged = _git(repo, "diff")
        if unstaged.strip():
            unstaged = _truncate(unstaged, max_diff_bytes_per_file, "unstaged diff", truncations)
            sections.append((1, "Unstaged diff", unstaged))

    # Untracked files (porcelain '??'); renamed/deleted noted via name-status.
    porcelain = _git(repo, "status", "--porcelain")
    untracked_bodies, notes = [], []
    for line in porcelain.splitlines():
        code, path = line[:2], line[3:]
        if code == "??":
            full = os.path.join(repo, path)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size > max_file_size:
                skipped.append({"path": path, "reason": "size", "size": size})
                continue
            try:
                with open(full, "rb") as fh:
                    raw = fh.read()
                if b"\x00" in raw:
                    notes.append(f"- {path}: untracked BINARY (omitted)")
                    continue
                untracked_bodies.append(f"### {path}\n```\n{raw.decode(errors='replace')}\n```")
            except OSError:
                continue
    name_status = _git(repo, "diff", "--name-status", "HEAD")
    for line in name_status.splitlines():
        tag = line.split("\t", 1)[0]
        if tag.startswith("R"):
            notes.append(f"- {line} (renamed)")
        elif tag.startswith("D"):
            notes.append(f"- {line} (deleted)")
    numstat = _git(repo, "diff", "--numstat", "HEAD")
    for line in numstat.splitlines():
        if line.startswith("-\t-\t"):
            notes.append(f"- {line.split(chr(9))[-1]}: BINARY (no content)")

    if untracked_bodies:
        sections.append((2, "Untracked files", "\n\n".join(untracked_bodies)))
    if notes:
        sections.append((3, "Renamed / deleted / binary", "\n".join(notes)))

    # Render, dropping lowest-priority sections if over the total cap.
    def render(secs):
        parts = ["# Review bundle\n"]
        for _, title, body in secs:
            parts.append(f"\n## {title}\n\n{body}\n")
        if skipped:
            parts.append("\n## Skipped for size\n\n" +
                         "\n".join(f"- {s['path']} ({s['size']} bytes)" for s in skipped) + "\n")
        return "".join(parts)

    secs = sorted(sections, key=lambda s: s[0])
    text = render(secs)
    while len(text.encode()) > max_bundle_bytes and len(secs) > 1:
        dropped = secs.pop()  # highest priority number = lowest importance
        truncations.append({"section": dropped[1], "dropped": True})
        text = render(secs)

    with open(out_path, "w") as fh:
        fh.write(text)
    return BundleResult(path=out_path, skipped_files=skipped, truncations=truncations)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_bundle -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add claude/skills/pi-review-loop/pi_review_loop/bundle.py claude/skills/pi-review-loop/tests/test_bundle.py
git commit -m "feat(pi-review-loop): bounded git review bundle with size/diff/total caps"
```

---

## Task 7: The runner — spawn, monitor over real IO, drain, reap, artifacts

**Files:**
- Create: `pi_review_loop/runner.py`
- Create: `tests/fake_pi.py`
- Test: `tests/test_runner.py`

`run_review` ties the pieces together. It is parameterized by `cmd` (the argv list) so tests can substitute `tests/fake_pi.py` for the real `pi`. It uses `selectors` for non-blocking reads (so M1/M2 — "no new line arrives" — still reach the timeout checks), reads stdout and stderr concurrently, tees raw stdout to `stdout.raw.log`, writes valid events (and `malformed_stdout` records) to `events.jsonl`, and always writes `result.json` — even on an internal exception.

> **Critical IO note (the one subtlety to get right):** a `selectors`-readable Python *text-mode* file object can still **block** inside `.read()` because its internal buffer hides bytes the OS-level `select` can't see — the exact deadlock this whole project exists to avoid. The implementation below therefore sets the pipe fds **non-blocking** (`os.set_blocking(fd, False)`) and reads with `os.read(fd, ...)` on the raw fds, decoding bytes manually, so a readable-but-incomplete pipe never wedges the monitor. Do not switch to `for line in proc.stdout` or buffered `.readline()`. The `fake_pi.py` `hang`/`posthang` tests are the regression guard for this.

- [ ] **Step 1: Write the fake Pi and the failing tests**

`tests/fake_pi.py`:
```python
#!/usr/bin/env python3
"""Fake `pi` for runner tests. Modes via argv[1]:
  clean      -> emit a CLEAN agent_end and exit 0
  issues     -> emit an ISSUES agent_end and exit 0
  hang       -> emit one event then sleep forever (stall)
  crash      -> print a malformed line then exit 1 (no agent_end)
  posthang   -> emit a CLEAN agent_end then sleep forever (M3 exit hang)
"""
import json
import sys
import time


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def agent_end(text):
    return {"type": "agent_end", "messages": [
        {"role": "assistant", "content": [{"type": "text", "text": text}]},
    ]}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "clean"
    emit({"type": "agent_start"})
    if mode == "clean":
        emit(agent_end("REVIEW: CLEAN"))
    elif mode == "issues":
        emit(agent_end("REVIEW: ISSUES\n1. [Warning] a.py: tidy this"))
    elif mode == "hang":
        emit({"type": "message_update"})
        time.sleep(3600)
    elif mode == "crash":
        sys.stdout.write("this is not json\n")
        sys.stdout.flush()
        sys.exit(1)
    elif mode == "posthang":
        emit(agent_end("REVIEW: CLEAN"))
        time.sleep(3600)


if __name__ == "__main__":
    main()
```

`tests/test_runner.py`:
```python
import os
import sys
import tempfile
import unittest
from pi_review_loop import runner
from pi_review_loop.states import CLEAN, ISSUES, CRASHED, STALLED

FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_pi.py")]


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, mode, **kw):
        defaults = dict(stall_timeout=2, retry_grace=1, global_deadline=30,
                        poll_interval=0.05, model="fake/model")
        defaults.update(kw)
        return runner.run_review(cmd=FAKE + [mode], run_dir=self.run_dir, **defaults)

    def test_clean(self):
        r = self._run("clean")
        self.assertEqual(r.state, CLEAN)
        self.assertTrue(os.path.exists(os.path.join(self.run_dir, "result.json")))
        self.assertTrue(os.path.exists(os.path.join(self.run_dir, "events.jsonl")))

    def test_issues_items_parsed(self):
        r = self._run("issues")
        self.assertEqual(r.state, ISSUES)
        self.assertEqual(r.items[0]["severity"], "Warning")

    def test_hang_is_stalled_and_killed(self):
        r = self._run("hang", stall_timeout=1)
        self.assertEqual(r.state, STALLED)

    def test_crash_with_malformed_output(self):
        r = self._run("crash")
        self.assertEqual(r.state, CRASHED)
        # malformed line preserved as a record, events.jsonl stays valid JSONL
        import json
        with open(os.path.join(self.run_dir, "events.jsonl")) as fh:
            for line in fh:
                json.loads(line)  # must not raise

    def test_posthang_returns_clean_without_waiting(self):
        # M3: verdict present, process won't exit -> must finish CLEAN promptly.
        r = self._run("posthang", global_deadline=30)
        self.assertEqual(r.state, CLEAN)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_runner -v`
Expected: FAIL — no module `pi_review_loop.runner`.

- [ ] **Step 3: Implement `runner.py`**

```python
"""Drive one Pi review: spawn in its own process group, monitor the JSON event
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


def _kill_group(proc, pgid, grace=5.0):
    """SIGTERM the group, wait briefly, SIGKILL if needed, then reap. Never wait
    for natural exit (M3 means it may never come). pgid is cached at spawn."""
    if pgid is not None and pgid > 1:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                break
            try:
                proc.wait(timeout=grace if sig == signal.SIGTERM else 1.0)
                return
            except subprocess.TimeoutExpired:
                continue
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
        any_open = False
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
            any_open = True
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


def run_review(*, cmd, run_dir, model, stall_timeout, retry_grace,
               global_deadline, poll_interval=0.5, env=None):
    os.makedirs(run_dir, exist_ok=True)
    paths = {k: os.path.join(run_dir, v) for k, v in {
        "raw": "stdout.raw.log", "events": "events.jsonl",
        "stderr": "stderr.log", "result": "result.json"}.items()}

    started = _now()
    sub_env = dict(os.environ)
    sub_env.update({"PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"})
    if env:
        sub_env.update(env)

    monitor = Monitor(started_at=started, stall_timeout=stall_timeout,
                      retry_grace=retry_grace, global_deadline=global_deadline)
    proc = None
    pgid = None
    state = CRASHED
    error = None

    raw_f = open(paths["raw"], "w")
    ev_f = open(paths["events"], "w")
    err_f = open(paths["stderr"], "w")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, env=sub_env, bufsize=0,
        )
        try:
            pgid = os.getpgid(proc.pid)  # cache immediately, before any exit
        except ProcessLookupError:
            pgid = None
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
    except Exception:  # never leave Claude polling a result that never appears
        error = traceback.format_exc()
        state = CRASHED
        if proc is not None and proc.poll() is None:
            _kill_group(proc, pgid)
    finally:
        raw_f.close(); ev_f.close(); err_f.close()

    if monitor.provider_error and not error:
        error = monitor.provider_error
    if error is None and state == CRASHED:
        try:
            with open(paths["stderr"]) as fh:
                error = fh.read()[-2000:] or None
        except OSError:
            pass

    result = ReviewResult(
        state=state, items=monitor.verdict_items, model=model, cost=None,
        started_at=started, ended_at=_now(), error=error,
        raw_verdict_line=monitor.verdict_text,
    )
    result.write(paths["result"])
    return result
```

Note on `result.skipped_files`/`truncations`: the runner does not build the bundle; `cli.main` builds it (Task 8) and copies `skipped_files`/`truncations` onto the result before writing. To keep `run_review` focused, it accepts no bundle metadata; Task 8 sets those fields and re-writes `result.json`.

- [ ] **Step 4: Run to verify pass**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_runner -v`
Expected: PASS (5 tests). `test_posthang` must return promptly (well under the 30s deadline), proving M3 is handled by killing once the verdict is seen.

- [ ] **Step 5: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add claude/skills/pi-review-loop/pi_review_loop/runner.py claude/skills/pi-review-loop/tests/fake_pi.py claude/skills/pi-review-loop/tests/test_runner.py
git commit -m "feat(pi-review-loop): runner — spawn, non-blocking monitor, drain, reap, artifacts"
```

---

## Task 8: CLI wiring + executable entry

**Files:**
- Create: `pi_review_loop/cli.py`
- Create: `bin/pi-review-loop`
- Test: `tests/test_cli.py`

`cli.main`: parse args → resolve model → acquire lock (storing pid/pgid/cwd/command after spawn is owned by runner, so the lock stores harness pid + cwd + command, and the runner updates pgid via a callback is overkill; instead the lock records the harness PID and cwd, and stale reclaim probes that the run_dir's `result.json` is absent + harness PID dead — simpler and sufficient) → build bundle → run review → fold bundle skips/truncations into result → print a one-line summary + the result path → exit code by state.

To keep the lock reuse-safe without a live Pi pgid (the runner owns the process), the lock records `harness_pid` and reclaim probes `harness_pid` liveness via `os.kill(pid, 0)`. Update `lock._group_alive` usage accordingly: `cli` passes `{"harness_pid": os.getpid(), "cwd": ..., "command": ...}` and a small `lock.pid_alive` helper is used by reclaim. (Add `pid_alive` to `lock.py` and switch `_reclaim_if_stale` to prefer `harness_pid` when present, falling back to `pi_pgid`.)

- [ ] **Step 1: Extend `lock.py` with `pid_alive` and harness-pid reclaim**

Add to `lock.py`:
```python
def pid_alive(pid):
    if not pid or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as e:
        return e.errno != errno.ESRCH
```
And in `_reclaim_if_stale`, before the pgid check:
```python
    if "harness_pid" in meta:
        if pid_alive(meta.get("harness_pid")):
            return False
        # harness dead: also try to kill any recorded pi group, then reclaim
        pgid = meta.get("pi_pgid")
        if pgid and pgid > 1:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        _remove_lock_dir(lock_dir)
        return True
```
Refactor the existing dir-removal into a `_remove_lock_dir(lock_dir)` helper and call it in both branches.

- [ ] **Step 2: Write the failing test**

`tests/test_cli.py`:
```python
import os
import subprocess
import sys
import tempfile
import unittest

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(SKILL_ROOT, "tests", "fake_pi.py")


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # a tiny git repo with an unstaged change
        self.repo = self.tmp.name
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

    def test_clean_exit_zero(self):
        env = dict(os.environ, PI_REVIEW_FAKE_CMD=f"{sys.executable} {FAKE} clean")
        proc = subprocess.run(
            [sys.executable, os.path.join(SKILL_ROOT, "bin", "pi-review-loop"),
             "--repo", self.repo, "--run-dir", os.path.join(self.tmp.name, "run"),
             "--lock-dir", os.path.join(self.tmp.name, "lock"),
             "--model", "fake/model"],  # hermetic: skip real `pi --list-models`
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("CLEAN", proc.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Implement `cli.py`**

```python
"""CLI entry: assemble bundle, run one Pi review under the lock, emit result."""
import argparse
import os
import shlex
import sys

from . import bundle as bundle_mod
from . import model as model_mod
from .lock import Lock, LockHeld
from .runner import run_review
from .states import CLEAN, ISSUES, FAILED

EXIT_BY_STATE = {CLEAN: 0, ISSUES: 1}  # everything in FAILED -> 2


def _build_parser():
    p = argparse.ArgumentParser(prog="pi-review-loop",
                                description="Run one Pi review over a git diff.")
    p.add_argument("--repo", default=".")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--lock-dir",
                   default=os.path.expanduser("~/.cache/pi-review-loop/lock"))
    p.add_argument("--model", default=None, help="override model id")
    p.add_argument("--stall-timeout", type=float, default=180)
    p.add_argument("--retry-grace", type=float, default=30)
    p.add_argument("--review-deadline", type=float, default=1500)
    p.add_argument("--max-file-size", type=int, default=262144)
    p.add_argument("--max-diff-bytes-per-file", type=int, default=262144)
    p.add_argument("--max-bundle-bytes", type=int, default=2097152)
    p.add_argument("--staged-only", action="store_true")
    return p


def _pi_cmd(model, bundle_path):
    # Test seam: PI_REVIEW_FAKE_CMD replaces the `pi ...` argv entirely.
    fake = os.environ.get("PI_REVIEW_FAKE_CMD")
    if fake:
        return shlex.split(fake)
    return [
        "pi", "--mode", "json", "--no-session", "--no-tools",
        "--no-extensions", "--no-skills", "--no-prompt-templates",
        "--no-context-files", "--model", model, f"@{bundle_path}",
    ]


def main(argv=None):
    args = _build_parser().parse_args(argv)
    os.makedirs(args.run_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.lock_dir) or ".", exist_ok=True)

    model = args.model or model_mod.resolve_from_cli()
    bundle_path = os.path.join(args.run_dir, "review-bundle.md")
    b = bundle_mod.build_bundle(
        args.repo, bundle_path,
        max_file_size=args.max_file_size,
        max_diff_bytes_per_file=args.max_diff_bytes_per_file,
        max_bundle_bytes=args.max_bundle_bytes,
        staged_only=args.staged_only,
    )

    meta = {"harness_pid": os.getpid(), "cwd": os.path.abspath(args.repo),
            "command": "pi-review-loop", "model": model, "run_dir": args.run_dir}
    try:
        with Lock(args.lock_dir, meta):
            result = run_review(
                cmd=_pi_cmd(model, bundle_path), run_dir=args.run_dir,
                model=model, stall_timeout=args.stall_timeout,
                retry_grace=args.retry_grace, global_deadline=args.review_deadline,
            )
    except LockHeld as e:
        print(f"pi-review-loop: {e}", file=sys.stderr)
        return 3

    # Fold bundle scope into the result and re-write result.json.
    result.skipped_files = b.skipped_files
    result.truncations = b.truncations
    result.write(os.path.join(args.run_dir, "result.json"))

    scope = " (scoped)" if result.scoped_clean else ""
    print(f"REVIEW: {result.state}{scope}  items={len(result.items)}  "
          f"model={model}  result={os.path.join(args.run_dir, 'result.json')}")
    for it in result.items:
        print(f"  - [{it['severity']}] {it['path']}: {it['message']}")
    if result.error and result.state in FAILED:
        print(f"  error: {result.error.splitlines()[-1] if result.error else ''}",
              file=sys.stderr)
    return EXIT_BY_STATE.get(result.state, 2)
```

- [ ] **Step 4: Create the executable entry**

`bin/pi-review-loop`:
```python
#!/usr/bin/env python3
import os
import sys

# Make the skill root importable when run as a standalone script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pi_review_loop.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

Then: `chmod +x claude/skills/pi-review-loop/bin/pi-review-loop`

- [ ] **Step 5: Run to verify pass**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest tests.test_cli -v`
Expected: PASS (exit 0, "CLEAN" in stdout).

- [ ] **Step 6: Run the full suite**

Run: `cd claude/skills/pi-review-loop && python3 -m unittest discover -s tests -v`
Expected: all tests across all modules PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add claude/skills/pi-review-loop/pi_review_loop/cli.py claude/skills/pi-review-loop/pi_review_loop/lock.py claude/skills/pi-review-loop/bin/pi-review-loop claude/skills/pi-review-loop/tests/test_cli.py
git commit -m "feat(pi-review-loop): CLI entry + harness-pid lock reclaim"
```

---

## Task 9: Live smoke test against real Pi

**Files:** none (verification task) — but record findings.

- [ ] **Step 1: Resolve the real model**

Run: `pi --list-models gpt`
Confirm `model.resolve_from_cli()` returns a sane id:
`cd claude/skills/pi-review-loop && python3 -c "from pi_review_loop.model import resolve_from_cli; print(resolve_from_cli())"`
Expected: e.g. `openai-codex/gpt-5.5`. If the format differs, fix Task 4's parser + add a test, then re-commit.

- [ ] **Step 2: Real review of a tiny diff**

In a scratch git repo with one small change, run:
```bash
python3 /Users/jochen/projects/agent-stuff/claude/skills/pi-review-loop/bin/pi-review-loop \
  --repo /path/to/scratch --run-dir /tmp/pi-review-smoke
```
Expected: terminates well under the deadline; `result.json` has `state` CLEAN or ISSUES; `events.jsonl` ends with an `agent_end`; the verdict came from the final assistant message. Confirm the process is gone afterward (`pgrep -f "pi --mode json"` is empty).

- [ ] **Step 3: Confirm env vars don't break the model call**

The smoke in Step 2 already proves `PI_SKIP_VERSION_CHECK=1` + `PI_TELEMETRY=0` still reach the provider (a verdict came back). Note this in `docs/review-cycle-log.md`.

- [ ] **Step 4: Record the smoke in the log**

Append a dated entry to `docs/review-cycle-log.md` (summary-safe: expected/actual/impact/status) noting the live verification and the resolved model.

- [ ] **Step 5: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add docs/review-cycle-log.md
git commit -m "docs(pi-review-loop): record live Pi review smoke"
```

---

## Task 10: SKILL.md — the Claude-facing outer loop

**Files:**
- Create: `claude/skills/pi-review-loop/SKILL.md`

- [ ] **Step 1: Write `SKILL.md`**

```markdown
---
name: pi-review-loop
description: Use when you want a fresh-context code review gate before committing — runs Pi (latest GPT model) as a reviewer over the current git diff in a bounded, observable loop, and only proceeds when Pi returns CLEAN. Drives review → fix → re-review up to a round cap.
---

# Pi Review Loop

Run a bounded review cycle: hand the current diff to Pi as a fresh-context
reviewer via the harness, read its structured verdict, and only continue when it
is `CLEAN`. The harness owns Pi's whole lifecycle (spawn, observe, kill/reap), so
you never poll a process or guess whether Pi is stuck.

## When to use

Before committing a change you want externally reviewed by a different model
family. You implement and fix; Pi reviews.

## The loop (you drive this)

1. Ensure the change you want reviewed is in the working tree (staged and/or
   unstaged). The harness bundles the diff; you do not paste code.
2. Run one review:

   ```bash
   python3 ~/projects/agent-stuff/claude/skills/pi-review-loop/bin/pi-review-loop \
     --repo "$PWD" --run-dir "$(mktemp -d)/pi-review"
   ```

   Optional flags: `--model`, `--stall-timeout`, `--retry-grace`,
   `--review-deadline`, `--max-rounds` is *your* concern (see below),
   `--max-bundle-bytes`, `--staged-only`.

3. Read the printed verdict and `result.json`. Interpret by exit code:
   - `0` → `CLEAN`. If it printed `(scoped)`, the bundle skipped/truncated files
     (huge or binary); treat as **clean within provided scope** and decide whether
     the skipped files matter.
   - `1` → `ISSUES`. Fix each listed `[Severity] path: message`, then **re-run the
     review** (a fresh review, not an edit of the old one).
   - `2` → failed review (`INVALID` / `CRASHED` / `STALLED` / `STALLED_RETRY` /
     `PROVIDER_ERROR`). This is **not** a clean review. Inspect `result.json`
     `error`, `stderr.log`, and `events.jsonl`; fix the cause (often a provider
     blip or an oversized bundle) and re-run. Never treat a failed review as a
     pass.
   - `3` → another review already holds the lock. Wait or investigate the stale
     lock; do not run concurrent reviews.

4. Stop after at most **3 rounds**. If still not `CLEAN` after 3 rounds, report
   the outstanding items to the user rather than looping forever.

## Hard rules

- A commit-gate "clean" means exit `0` **and** you are satisfied any `(scoped)`
  skips are irrelevant. Exit `1`/`2`/`3` are never clean.
- One review at a time (the harness enforces this with a global lock).
- Do not background the harness and poll it — it is foreground and returns a
  structured result. Let it run.
- Severities are `Critical`, `Warning`, `Suggestion`. Fix Critical/Warning before
  re-review; use judgement on Suggestion (avoid over-engineering).

## Artifacts (in `--run-dir`)

`result.json` (verdict, items, state, model, error, scoped_clean),
`events.jsonl` (strict JSONL event stream), `stdout.raw.log`, `stderr.log`,
`review-bundle.md` (exactly what Pi saw).
```

- [ ] **Step 2: Lint the frontmatter**

Confirm the `name`/`description` match the repo's other skills' style (see `claude/skills/handoff-review/SKILL.md`). Adjust wording to fit.

- [ ] **Step 3: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add claude/skills/pi-review-loop/SKILL.md
git commit -m "feat(pi-review-loop): add SKILL.md outer-loop instructions"
```

---

## Task 11: Wire into chezmoi + update repo docs

**Files:**
- Modify: `README.md` (skill inventory table + repo structure)
- Modify: `pi/README.md`? No — this is a Claude skill; update the Claude rows only.
- Create (in dotfiles repo): `~/.local/share/chezmoi/dot_claude/skills/symlink_pi-review-loop.tmpl`

- [ ] **Step 1: Add the symlink template in the dotfiles repo**

Per `README.md` "How skills get installed", create
`~/.local/share/chezmoi/dot_claude/skills/symlink_pi-review-loop.tmpl` containing:
```
{{ .chezmoi.homeDir }}/projects/agent-stuff/claude/skills/pi-review-loop
```
(Whole-directory symlink — the skill has `bin/` and a package, so it must be
symlinked as a directory, like `review-handoff/scripts/`.)

- [ ] **Step 2: Apply chezmoi**

Run: `chezmoi apply` then verify:
`ls -la ~/.claude/skills/pi-review-loop` (should be a symlink to the repo path).

- [ ] **Step 3: Update `README.md`**

Add to the Claude skill-inventory table:
```
| Claude | `pi-review-loop` | Bounded fresh-context review gate: drive Pi (latest GPT) over the diff until CLEAN |
```
And under the `claude/skills/` tree in "Repo structure", add `pi-review-loop/`.

- [ ] **Step 4: Verify the skill loads**

Run: in a Claude Code session, `/pi-review-loop` should be discoverable (or confirm it appears in the skills list). At minimum, confirm `~/.claude/skills/pi-review-loop/SKILL.md` resolves through the symlink.

- [ ] **Step 5: Commit**

```bash
cd /Users/jochen/projects/agent-stuff
git add README.md
git commit -m "docs(pi-review-loop): add to skill inventory + repo structure"
```
(The dotfiles symlink template is committed separately in the chezmoi repo.)

---

## Self-Review checklist (run after implementation)

- [ ] **Spec coverage:** every spec section maps to a task — four stuck shapes (monitor branches, Tasks 3+7), `--mode json`/`--no-*` invocation (Task 8), model resolution (Task 4), atomic global lock + reuse-safe reclaim (Tasks 5+8), bundle git contract + caps (Task 6), final-assistant fail-closed verdict + ISSUES≥1 + severities (Task 1), bounded retries + global deadline (Task 3), drain-before-crash + concurrent stderr + non-blocking reads (Task 7), strict JSONL + malformed records + always-write result.json (Tasks 7+2), env vars (Task 7), SKILL.md outer loop + round cap (Task 10).
- [ ] **Placeholder scan:** no TBD/TODO; every code step shows real code.
- [ ] **Type consistency:** `ReviewResult` fields, `Decision(action,state)`, `Monitor` attributes (`verdict_state`, `verdict_items`, `verdict_text`, `provider_error`), `build_bundle` signature, `_kill_group(proc, pgid)`, and state constants are used identically across Tasks 1–8.

## Known deviation from the spec (decide during plan review)

- **Lock identity uses the harness PID, not the Pi PGID.** The spec wanted the lock
  to record the Pi PGID so a dead harness's orphaned Pi group is killed on reclaim.
  Here the CLI holds the lock (harness PID) while the runner owns the Pi process, so
  reclaim keys off harness liveness. With `start_new_session=True` a Pi process could
  briefly outlive a hard-killed harness. **Mitigation if we want full parity:** after
  spawn, have `run_review` write its cached `pgid` into the lock meta
  (`lock.write_meta`), so reclaim can also `killpg` an orphaned group. Low risk for a
  single-user tool; flagged for the plan reviewer to accept or require.
