"""obs-triage: the LLM half of the daily observability routine, and two small Studio jobs around it.

Python 3 stdlib only. Three subcommands:

``run``
    Once a day (LaunchAgent): fetch the deterministic evidence pack that
    macmini built (``obs_ctl.py pack`` over root SSH: an inventory of hosts,
    services and volumes, raw log samples, changes against the baseline),
    add the Studio's own launchd picture and the ledger's items, and let
    Codex (``gpt-6.2-sol``, medium, read-only sandbox, no network, structured
    output) review the last 24 hours open-endedly. In up to ``MAX_ROUNDS``
    rounds the model asks for read-only Loki and InfluxDB queries, which this
    tool runs on macmini (``obs_ctl.py query``) and hands back, until it
    decides what is genuinely new and worth attention. New findings
    become ledger items (stage ``idea``); the digest of new findings goes back
    to macmini (``obs_ctl.py deliver``), which sends it through Nyxmon's
    Telegram notifier. No new finding: no message. When Codex cannot run
    (quota guard, error, timeout) there is no fallback to another model: the
    day is reported as "skipped" in one short message.
``launchd-check``
    Every ten minutes (LaunchAgent): Studio launchd jobs in a crash loop (runs
    rose by ``LOOP_RUNS`` or more since the last sample and the last exit was
    not 0) go to macmini (``obs_ctl.py launchd``), whose status endpoint
    Nyxmon checks.
``weekly``
    Monday (LaunchAgent): write the weekly review brief into the Katharina
    coordination folder and start it there with ``run.sh`` on the main
    account (``ACCOUNT=main``).

Exit status: 0 done, 1 delivery or a step failed, 2 bad usage.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BRIEF = HERE / "triage-brief.md"
SCHEMA = HERE / "triage-schema.json"
WEEKLY_BRIEF = HERE / "weekly-brief.md"

MODEL = "gpt-6.2-sol"
EFFORT = "medium"
CODEX_TIMEOUT = 25 * 60  # one round
MAX_ROUNDS = 6  # Codex calls per day: up to five with drill-down queries, then the answer
TRIAGE_BUDGET = 150 * 60  # all rounds together
FINAL_RESERVE = 20 * 60  # with less left, the next round must answer
MAX_ROUND_QUERIES = 8
MAX_DRILL_BYTES = 600 * 1024  # query results carried into the next rounds
QUERY_TIMEOUT = 660  # obs_ctl.py query starts no query after 480 s, each may take 60 s more
SSH_TIMEOUT = 120
# obs_ctl.py deliver waits up to 60 s for its lock, and its one send may take 180 s.
DELIVER_TIMEOUT = 300
WORK_TIMEOUT = 120
MAX_NEW_ITEMS = 5
LOOP_RUNS = 5
OPEN_STAGES = {"idea", "designed", "prototype", "implementing", "reviewed", "local", "pushed", "blocked", "parked"}
RECENT_DAYS = 21
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{2,40}")  # used with fullmatch; created items get the "obs-" prefix
SLUG_PREFIX = "obs-"
MAX_SUMMARY = 600
# Model text that reaches the ledger or Telegram. Values the model may have copied from a log are
# not masked by guessing where a value ends: a text field that names a credential anywhere outside a
# strict marker ``[secret:<type> <fingerprint>]`` is withheld as a whole (the full finding stays in
# the local run report); so is one that holds a token-like run (``looks_like_token``) or a character
# outside ``ALLOWED_TEXT``. Mail addresses become ``<mail>``. Nothing is masked by guesswork.
CREDENTIAL_WORDS = (
    "passw", "pwd", "secret", "token", "apikey", "accesskey", "privatekey", "cookie", "sessionid",
    "credential", "authoriz", "bearer",
)  # fmt: skip
# Short words count only as whole words (too common as parts of other words: author, keyboard).
CREDENTIAL_SHORT_WORDS = ("key", "keys", "basic", "auth", "session", "sessions", "sid", "jwt", "otp")
SECRET_TYPES = (
    "password", "token", "secret", "api-key", "access-key", "private-key", "key", "cookie", "session-id",
    "credential", "authorization", "bearer", "basic",
)  # fmt: skip
_MARKER = re.compile(r"\[secret:(" + "|".join(SECRET_TYPES) + r") ([^\s…\[\]]{0,4})…\((\d{1,7})\)\]")
_MAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Runs that may be a key, a token, hex or base64 (slashes, plus and equals included).
_RUN = re.compile(r"[A-Za-z0-9+/=_]{20,}")
_WORD_RUN = re.compile(r"[A-Za-z0-9_-]+")  # maximal runs, found in one linear pass
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def looks_like_token(text: str) -> bool:
    """Whether ``text`` holds something that may be a key or token (detected, never masked: the caller
    withholds the whole field):

    - a run of 20 or more of ``[A-Za-z0-9+/=_]`` (base64 and hex included) with at least four
      letters and two digits (one from 24 characters on), unless it is an absolute path (starts
      with ``/``) of short plain segments (each under 16 characters, without ``+`` or ``=``);
    - a hyphenated run of 24 or more characters (any number of hyphens; UUIDs set aside) with a
      piece longer than four characters that mixes letters and digits, or three such pieces.
    """

    for run in _RUN.findall(text):
        letters = sum(ch.isalpha() for ch in run)
        digits = sum(ch.isdigit() for ch in run)
        if letters < 4 or digits < (1 if len(run) >= 24 else 2):
            continue
        segments = run.split("/")
        if run.startswith("/") and all(len(seg) < 16 and "+" not in seg and "=" not in seg for seg in segments):
            continue
        return True
    for run in _WORD_RUN.findall(_UUID.sub("uuid", text)):
        if "-" not in run or len(run) < 24:
            continue
        mixed = [p for p in run.split("-") if re.search(r"[A-Za-z]", p) and re.search(r"[0-9]", p)]
        # One long mixed piece, or several short ones (``Ab12--Cd34--Ef56``): a slug has at most
        # a version or two (``v2``).
        if any(len(p) > 4 for p in mixed) or len(mixed) >= 3:
            return True
    return False


def names_credential(text: str) -> bool:
    """Whether ``text`` (already limited to ``ALLOWED_TEXT``) names a credential outside the markers:
    the long words as substrings of the text with everything but ASCII letters and digits removed,
    the short ones as whole words."""

    def marker(m: re.Match[str]) -> str:
        # Valid only with a prefix no longer than ``fingerprint`` writes for the declared length.
        return " " if len(m.group(2)) <= min(4, int(m.group(3)) // 4) else m.group(0)

    # Every admitted letter lower-cases to exactly one letter (``ALLOWED_TEXT`` has no "ß").
    folded = _MARKER.sub(marker, text).lower()
    squashed = re.sub(r"[^a-z0-9]", "", folded)
    # Words end only at whitespace, ASCII punctuation and the typographic signs; the German letters
    # inside a word are dropped (``ALLOWED_TEXT`` admits nothing else).
    pieces = re.split(r"[\s!-/:-@\[-`{-~" + re.escape(TYPOGRAPHIC_SIGNS) + r"]+", folded)
    words = {re.sub(r"[^a-z0-9]", "", piece) for piece in pieces}
    return any(word in squashed for word in CREDENTIAL_WORDS) or bool(words & set(CREDENTIAL_SHORT_WORDS))


def mask_secrets(text: str) -> str:
    """Mail addresses as ``<mail>``."""

    return _MAIL.sub("<mail>", text)


# Features of an interactive Codex that the triage must not have (as codex-review-loop disables them).
DISABLED_FEATURES = (
    "apps", "browser_use", "browser_use_external", "computer_use", "goals", "hooks", "image_generation",
    "in_app_browser", "memories", "multi_agent", "plugins", "plugin_sharing", "realtime_conversation",
    "remote_plugin", "skill_mcp_dependency_install", "skill_search", "sleep_tool", "tool_suggest",
    "unbounded_connection_retries", "view_image", "workspace_dependencies", "worktrees",
)  # fmt: skip
PROJECT = re.compile(r"[a-z0-9][a-z0-9_.-]{0,40}")  # used with fullmatch
OWN_LABELS = re.compile(r"^(de\.wersdoerfer\.|local\.|eu\.coreso\.|org\.ops-library\.|com\.ollama\.)")


def env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def state_dir() -> Path:
    path = Path(env("OBS_TRIAGE_STATE", str(Path.home() / ".local/state/obs-triage")))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)  # owner only: run reports, days, outbox
    return path


def log(message: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} obs-triage: {message}", flush=True)


# -- macmini over SSH ------------------------------------------------------------------------------


def ctl(action: str, payload: str | None = None, timeout: int = SSH_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """``obs_ctl.py <action>`` on macmini as root (the same command ``ObsDailyConfig.ctl_command`` renders)."""

    remote = env(
        "OBS_TRIAGE_CTL",
        "/usr/bin/python3 -I /usr/local/lib/obs-daily/obs_ctl.py --config /etc/obs-daily/config.json",
    )
    argv = [
        env("OBS_TRIAGE_SSH_BIN", "ssh"), "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
        env("OBS_TRIAGE_HOST", "root@macmini.tailde2ec.ts.net"), f"{remote} {action}",
    ]  # fmt: skip
    try:
        return subprocess.run(
            argv, input=payload, capture_output=True, text=True, errors="backslashreplace", timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        # Timed out: not confirmed, whatever arrived (the result is sent again; a repeat, not a loss).
        return subprocess.CompletedProcess(argv, 124, "", "timed out")


# -- inputs ----------------------------------------------------------------------------------------


def fetch_pack(today: str) -> dict[str, Any]:
    done = ctl("pack")
    if done.returncode != 0:
        raise RuntimeError(f"pack not readable (exit {done.returncode}): {done.stderr.strip()[-160:]}")
    pack = json.loads(done.stdout)
    if pack.get("date") != today:
        raise RuntimeError(f"pack is from {pack.get('date')}, not {today}")
    return dict(pack)


def work_items() -> list[dict[str, Any]]:
    done = subprocess.run(
        [env("OBS_TRIAGE_WORK_BIN", "work"), "items", "--json"],
        capture_output=True,
        text=True,
        timeout=WORK_TIMEOUT,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"work items failed (exit {done.returncode})")
    data = json.loads(done.stdout)
    items = data.get("items")
    complete = (
        isinstance(items, list)
        and not data.get("truncated")
        and data.get("next_cursor") in (None, "")
        and isinstance(data.get("count"), int)
        and data["count"] == len(items)
    )
    if not complete:
        raise RuntimeError("work items answered an incomplete list")
    return list(items)


def known_items(items: list[dict[str, Any]], now: float) -> list[dict[str, str]]:
    """Open items, and items changed in the last ``RECENT_DAYS`` days, compact for the prompt."""

    cutoff = now - RECENT_DAYS * 86400
    compact = []
    for item in items:
        stage = item.get("stage", "")
        try:
            updated = datetime.fromisoformat(str(item.get("updated_at", "")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            updated = 0.0
        if (stage in OPEN_STAGES and stage != "dropped") or updated >= cutoff:
            compact.append(
                {
                    "slug": item["slug"],
                    "stage": stage,
                    "project": item.get("project") or "",
                    "title": (item.get("title") or "")[:160],
                }
            )
    return compact


def launchd_jobs(errors: list[str] | None = None) -> list[dict[str, Any]]:
    """This machine's own launchd jobs (system daemons and the user's agents): state, runs, last exit.

    Labels whose ``launchctl print`` failed are appended to ``errors``.
    """

    jobs = []
    domains = [("system", Path("/Library/LaunchDaemons")), (f"gui/{os.getuid()}", Path.home() / "Library/LaunchAgents")]
    for domain, directory in domains:
        try:
            names = sorted(p.stem for p in directory.glob("*.plist"))
        except OSError:
            continue
        for label in names:
            if not OWN_LABELS.match(label):
                continue
            try:
                done = subprocess.run(
                    [env("OBS_TRIAGE_LAUNCHCTL", "launchctl"), "print", f"{domain}/{label}"],
                    capture_output=True, text=True, timeout=30, check=False,
                )  # fmt: skip
            except (OSError, subprocess.SubprocessError):
                done = None
            if done is None or done.returncode != 0:
                if errors is not None:
                    errors.append(label)
                continue
            fields = dict(re.findall(r"^\t(state|runs|last exit code) = (.+)$", done.stdout, re.MULTILINE))
            runs = fields.get("runs", "0")
            jobs.append(
                {
                    "label": label,
                    "state": fields.get("state", "?"),
                    "runs": int(runs) if runs.isdigit() else 0,
                    "last_exit": fields.get("last exit code", "?"),
                }
            )
    return jobs


def launchd_changes(jobs: list[dict[str, Any]], previous: dict[str, int]) -> list[dict[str, Any]]:
    """Jobs whose runs rose since ``previous`` and whose last exit was not 0."""

    changes = []
    for job in jobs:
        before = previous.get(job["label"])
        if before is None:
            continue
        delta = job["runs"] - before
        failing = job["last_exit"] not in ("0", "(never exited)")
        if delta >= LOOP_RUNS and failing:
            changes.append({**job, "runs_since_last_sample": delta})
    return changes


# -- the Codex run ---------------------------------------------------------------------------------


def prompt(pack: dict[str, Any], items: list[dict[str, str]], launchd: dict[str, Any]) -> str:
    """The part of every round's prompt that stays the same (first, so the provider can cache it)."""

    return (
        BRIEF.read_text().replace("__MAX_ROUNDS__", str(MAX_ROUNDS)).replace("__MAX_QUERIES__", str(MAX_ROUND_QUERIES))
        + "\n\n## Evidence pack (macmini, deterministic)\n\n```json\n"
        + json.dumps(pack, ensure_ascii=False, sort_keys=True)
        + "\n```\n\n## Studio launchd jobs (runs in the last 24 h, last exit)\n\n```json\n"
        + json.dumps(launchd, ensure_ascii=False, sort_keys=True)
        + "\n```\n\n## Known ledger items (open, or changed in the last three weeks)\n\n```json\n"
        + json.dumps(items, ensure_ascii=False)
        + "\n```\n"
    )


def round_prompt(base: str, rounds: list[dict[str, Any]], number: int, final: bool) -> str:
    parts = [base, "\n## Your investigation so far\n"]
    if not rounds:
        parts.append("\nNothing yet: this is the first round.\n")
    for done in rounds:
        parts.append(
            f"\n### Round {done['round']}\n\nYour notes:\n\n{done['notes']}\n\nYour queries and their results:\n\n```json\n"
            + done["results"]
            + "\n```\n"
        )
    if final:
        parts.append(
            f"\n## Round {number} of {MAX_ROUNDS}: the last one\n\nNo more queries will run: leave `queries` empty "
            "and give your final `findings`, `known` and `note` now.\n"
        )
    else:
        parts.append(
            f"\n## Round {number} of {MAX_ROUNDS}\n\nEither ask for up to {MAX_ROUND_QUERIES} more queries (they run, "
            "and you see the results in the next round; findings of this round are ignored), or leave `queries` "
            "empty and give your final answer.\n"
        )
    return "".join(parts)


def utf8(text: str) -> str:
    """``text`` with lone surrogates as visible escapes, so it always encodes."""

    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def drill_down(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The model's queries run read-only on macmini (``obs_ctl.py query``); errors come back as results."""

    specs = []
    for query in queries[:MAX_ROUND_QUERIES]:
        spec = {key: query.get(key) for key in ("kind", "query", "start", "end", "limit", "step", "fn")}
        spec["limit"] = spec["limit"] or 200
        for unused in ("step", "fn"):
            if not spec[unused]:
                del spec[unused]
        specs.append(spec)
    done = ctl("query", json.dumps({"queries": specs}, ensure_ascii=False), timeout=QUERY_TIMEOUT)
    try:
        results = json.loads(done.stdout)["results"] if done.returncode == 0 else None
    except (ValueError, KeyError, TypeError):
        results = None
    if not isinstance(results, list):
        error = f"queries did not run (exit {done.returncode}: {done.stderr.strip()[-200:]})"
        results = [{"id": n, "error": error} for n in range(1, len(specs) + 1)]
    return [{"query": spec, **(result if isinstance(result, dict) else {})} for spec, result in zip(specs, results)]


def investigate(base: str, report: dict[str, Any]) -> dict[str, Any]:
    """Rounds of Codex with drill-down queries in between, within ``TRIAGE_BUDGET``; the final answer."""

    started = time.monotonic()
    rounds: list[dict[str, Any]] = []
    report["rounds"] = []
    for number in range(1, MAX_ROUNDS + 1):
        # One budget for everything (quota guard, rounds, queries). A round that may still ask for
        # queries must leave room for them and for a final round of FINAL_RESERVE.
        left = TRIAGE_BUDGET - (time.monotonic() - started)
        room = left - FINAL_RESERVE - QUERY_TIMEOUT
        final = number == MAX_ROUNDS or room < 5 * 60
        timeout = int(min(CODEX_TIMEOUT, left if final else room))
        if timeout < 60:
            raise Skipped("das Zeitbudget der Untersuchung ist aufgebraucht")
        answer = run_codex(round_prompt(base, rounds, number, final), timeout=timeout)
        queries = [q for q in answer.get("queries", []) if isinstance(q, dict)]
        summary = {"round": number, "seconds": round(time.monotonic() - started), "queries": len(queries)}
        report["rounds"].append(summary)
        if final and queries:
            # The last round must answer; one that still asks for queries left the review unfinished.
            answer["incomplete"] = True
        if final or not queries:
            return answer
        results = drill_down(queries)
        summary["query_texts"] = [r["query"] for r in results]
        summary["errors"] = sum(1 for r in results if "error" in r)
        rounds.append({"round": number, "notes": utf8(str(answer.get("notes", ""))[:8000]),
                       "results": utf8(json.dumps(results, ensure_ascii=False))})  # fmt: skip
        # Older results give way first when the carried results grow too large; the notes stay.
        while sum(len(r["results"].encode()) for r in rounds) > MAX_DRILL_BYTES and len(rounds) > 1:
            oldest = next(r for r in rounds if not r["results"].startswith('"dropped'))
            if oldest is rounds[-1]:
                break
            oldest["results"] = '"dropped for space; your notes of that round remain"'
        log(f"round {number}: {len(results)} queries ({summary['errors']} failed)")
    return answer  # not reached: the last round is final


_RUNNING: list[subprocess.Popen[str]] = []


def _stop_codex(signum: int, _frame: Any) -> None:
    """SIGTERM/SIGINT (launchd stopping the job): take the Codex process group down too, then exit."""

    for process in _RUNNING:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)  # the group this tool's Popen created
    raise SystemExit(128 + signum)


ENV_ALLOW = ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "TMPDIR", "TERM", "LANG", "LC_ALL", "LC_CTYPE",
             "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")  # fmt: skip


def codex_env() -> dict[str, str]:
    """An allowlisted environment (no OPENAI_BASE_URL or other overrides) with a pinned CODEX_HOME,
    the same one the quota guard reads."""

    pinned = {key: os.environ[key] for key in ENV_ALLOW if key in os.environ}
    pinned["CODEX_HOME"] = env("OBS_TRIAGE_CODEX_HOME", str(Path.home() / ".codex"))
    return pinned


def toml_string(value: str) -> str:
    return json.dumps(value)


def codex_argv(work: Path, schema: Path, out: Path) -> list[str]:
    """A locked-down, tool-poor Codex: no user config, MCP servers, plugins, apps, agents or web
    search; commands see only ``work`` (writable) and the minimal system paths, without network."""

    profile = "obs_triage"
    entries = [(":minimal", "read"), ("/tmp", "deny"), ("/private/tmp", "deny"), ("/private/var/folders", "deny")]
    entries.append((str(work.resolve()), "write"))
    filesystem = "{" + ",".join(f"{toml_string(k)}={toml_string(v)}" for k, v in entries) + "}"
    argv = [
        env("OBS_TRIAGE_CODEX_BIN", "codex"), "-a", "never", "exec",
        "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--ephemeral",
        "-C", str(work.resolve()), "-m", MODEL,
        "-c", f"model_reasoning_effort={toml_string(EFFORT)}",
        "-c", f"default_permissions={toml_string(profile)}",
        "-c", f"permissions.{profile}.filesystem={filesystem}",
        "-c", f"permissions.{profile}.network.enabled=false",
        "-c", 'web_search="disabled"', "-c", "agents.enabled=false",
        "-c", 'shell_environment_policy.inherit="core"',
        "-c", f'projects={{{toml_string(str(work.resolve()))}={{trust_level="untrusted"}}}}',
        "-c", "project_doc_max_bytes=0", "-c", "skills.include_instructions=false",
        "-c", "include_apps_instructions=false", "-c", "include_collaboration_mode_instructions=false",
    ]  # fmt: skip
    for feature in DISABLED_FEATURES:
        argv += ["--disable", feature]
    return argv + ["--output-schema", str(schema), "-o", str(out), "-"]


def run_codex(text: str, timeout: int = CODEX_TIMEOUT) -> dict[str, Any]:
    """One bounded, locked-down Codex run with structured output; Skipped on any failure to run.
    ``timeout`` covers the quota guard too."""

    deadline = time.monotonic() + timeout
    guard = env("OBS_TRIAGE_QUOTA_GUARD", str(Path.home() / "projects/agent-stuff/tools/codex-quota-guard/bin/codex-quota-guard"))
    try:
        checked = subprocess.run(
            [guard, "--quiet"], capture_output=True, text=True, timeout=60, check=False, env=codex_env()
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise Skipped(f"codex-quota-guard lief nicht ({type(error).__name__})") from None
    if checked.returncode == 3:
        raise Skipped("Codex-Kontingent ist aufgebraucht (codex-quota-guard)")
    if checked.returncode != 0:
        raise Skipped(f"codex-quota-guard lief nicht (exit {checked.returncode})")
    timeout = int(deadline - time.monotonic())
    if timeout < 60:
        raise Skipped("das Zeitbudget der Untersuchung ist aufgebraucht")
    root = state_dir() / "work"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=root) as tmp:
        work = Path(tmp)
        out = work / "answer.json"
        # Start and registration happen with SIGTERM/SIGINT held back, so a stop signal always finds
        # the process group in _RUNNING.
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        try:
            process = subprocess.Popen(
                codex_argv(work, SCHEMA, out),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                errors="backslashreplace",
                start_new_session=True,
                env=codex_env(),
            )
            _RUNNING.append(process)
        except OSError as error:
            raise Skipped(f"Codex startete nicht ({type(error).__name__})") from None
        finally:
            signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM, signal.SIGINT})
        try:
            _, stderr = process.communicate(text, timeout=timeout)
        except subprocess.TimeoutExpired:
            # The group was created by this Popen (start_new_session): only Codex and its children are in it.
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise Skipped(f"Codex brauchte für eine Runde länger als {timeout // 60} Minuten") from None
        finally:
            _RUNNING.remove(process)
        if process.returncode != 0 or not out.exists():
            # Codex's own diagnostics stay in the log; the message carries only the exit code.
            last = (stderr or "").strip().splitlines()[-1:] or [""]
            log(f"codex exit {process.returncode}: {last[0][:300]}")
            raise Skipped(f"Codex endete mit exit {process.returncode}")
        try:
            answer = json.loads(out.read_text())
        except ValueError:
            answer = None
        valid = (
            isinstance(answer, dict)
            and isinstance(answer.get("findings"), list)
            and all(isinstance(f, dict) for f in answer["findings"])
            and isinstance(answer.get("known"), list)
            and all(isinstance(k, dict) for k in answer["known"])
            and isinstance(answer.get("queries", []), list)
        )
        if not valid:
            raise Skipped("Codex lieferte keine gültige Antwort")
        return dict(answer)


class Skipped(Exception):
    """The triage did not run; the reason goes into the digest."""


GERMAN_LETTERS = "äöüÄÖÜéèêàâçÉÈ"  # no "ß": its two foldings (dropped or "ss") could hide a word
TYPOGRAPHIC_SIGNS = "…–—„“”‚‘’«»°€×→←↔≤≥≈±"
# The characters model text may use: printable ASCII, line breaks and tabs, and a closed list of
# German and typographic characters. Anything else (invisible, combining, filler, look-alike) makes
# the field withheld, so no character outside this list can hide or split a credential word.
ALLOWED_TEXT = frozenset(
    {chr(c) for c in range(0x20, 0x7F)} | set("\n\r\t" + GERMAN_LETTERS + TYPOGRAPHIC_SIGNS)
)


def clean_text(value: Any, withheld: str) -> str:
    """Model text for the ledger and Telegram: ``withheld`` instead when it holds a character
    outside ``ALLOWED_TEXT``, names a credential outside a marker or holds a token-like run;
    otherwise mail addresses masked and whitespace collapsed."""

    text = str(value or "")[:4000]  # bounded work; the stored fields are shorter still
    if not set(text) <= ALLOWED_TEXT:
        return withheld
    # Credential words on the text as written and once mail addresses are replaced (a replacement
    # could take a label with it); token-like runs once they are replaced (a mail address is not a
    # token, and its replacement takes no run apart).
    masked = mask_secrets(text)
    if names_credential(text) or names_credential(masked) or looks_like_token(masked):
        return withheld
    text = masked
    return re.sub(r"\s+", " ", text).strip()


def valid_findings(
    answer: dict[str, Any], existing: set[str], report: str = "the run report"
) -> tuple[list[dict[str, str]], list[str]]:
    """Findings fit for a new ledger item (slug gets the ``obs-`` prefix), and why the others were dropped.
    ``report`` names the local run report, where a withheld text can be read in full."""

    accepted, dropped = [], []
    seen: set[str] = set()
    short_report = "/".join(report.split("/")[-2:])  # runs/<file>, short enough for a title
    for finding in answer.get("findings", []):
        raw_slug = str(finding.get("slug", ""))
        slug = SLUG_PREFIX + raw_slug.removeprefix(SLUG_PREFIX)
        title = clean_text(finding.get("title"), f"Befund-Text zurückgehalten ({short_report})")
        summary = clean_text(
            finding.get("summary"),
            f"Der Text wurde zurückgehalten (Zugangsdaten-Begriff, token-artiger Wert oder nicht zugelassenes Zeichen); vollständig im Lauf-Bericht {report}.",
        )
        project = str(finding.get("project", "")).strip() or "ops-control"
        next_action = clean_text(finding.get("next_action"), f"Lauf-Bericht {report} lesen")[:300]
        evidence = clean_text(finding.get("evidence"), f"zurückgehalten, siehe Lauf-Bericht {report}")[:1200]
        if not slug_ok(raw_slug):
            dropped.append(f"{raw_slug[:60]!r}: bad slug")
        elif slug in existing or raw_slug in existing or slug in seen:
            dropped.append(f"{slug}: slug exists (an item the model should have counted as known)")
        elif not title or len(title) > 120 or not summary or len(summary) > MAX_SUMMARY:
            dropped.append(f"{slug}: title or summary empty or too long")
        elif not PROJECT.fullmatch(project) or names_credential(project) or looks_like_token(project):
            dropped.append(f"{slug}: bad project")
        elif str(finding.get("severity", "")) not in ("high", "medium", "low"):
            dropped.append(f"{slug}: bad severity")
        else:
            seen.add(slug)
            accepted.append(
                {
                    "slug": slug,
                    "title": title,
                    "summary": summary,
                    "project": project,
                    "severity": str(finding.get("severity", "")),
                    "evidence": evidence,
                    "next_action": next_action,
                }
            )
    return accepted, dropped


def item_exists(slug: str) -> bool | None:
    """True/False from ``work show``; None when that could not be decided. The ledger has no
    create-only write, so this check right before ``create_item`` narrows a concurrent creation to
    seconds (slugs carry the ``obs-`` prefix)."""

    try:
        done = subprocess.run(
            [env("OBS_TRIAGE_WORK_BIN", "work"), "show", slug, "--json"],
            capture_output=True, text=True, timeout=WORK_TIMEOUT, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode == 0:
        return True
    # Only the ledger's own answer for a missing item (its JSON error "not found"); a 404 from
    # anything in between, or any other failure, is undecided.
    return False if "work: HTTP 404: not found" in done.stderr.splitlines() else None


def create_item(finding: dict[str, str], today: str) -> bool | None:
    """True created, False refused, None undecided (timeout: the item may exist; the digest says so)."""

    argv = [
        env("OBS_TRIAGE_WORK_BIN", "work"), "upsert", finding["slug"],
        "--title", finding["title"], "--summary", finding["summary"], "--stage", "idea", "--horizon", "next",
        "--project", finding["project"], "--owner", "claude", "--campaign", "obs-triage",
        "--next-action", finding["next_action"] or "Befund prüfen",
        "--notes", f"obs-triage {today} ({finding['severity']}): {finding['evidence']}", "--checked-at", "now",
    ]  # fmt: skip
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=WORK_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.returncode == 0


def german_date(day: str) -> str:
    return datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m.%Y")


def digest(
    today: str, created: list[dict[str, str]], unsure: list[dict[str, str]] | None = None, over_limit: int = 0
) -> str:
    """The Telegram text: new items, and findings whose ledger write failed or is undecided.

    Telegram is a service outside the estate, so the digest carries no model text at all: only the
    item slugs (``obs-<date>-<n>``), the severity and fixed words.
    Titles and evidence are in the ledger and the local run report."""

    unsure = unsure or []
    if not created and not unsure and not over_limit:
        return ""
    noun = "neue Auffälligkeit" if len(created) == 1 else "neue Auffälligkeiten"
    lines = [f"🔎 Obs-Triage {german_date(today)}: {len(created)} {noun}"]
    marks = {"high": "‼️ ", "medium": "", "low": ""}
    lines += [f"• {marks.get(f['severity'], '')}{f['slug']} [{f['severity']}]" for f in created]
    lines += [f"⚠️ nicht (sicher) angelegt: {f['slug']} [{f['severity']}]" for f in unsure]
    if over_limit:
        lines.append(f"⚠️ {over_limit} weitere Befunde nicht angelegt (Tageslimit), nur im Lauf-Bericht")
    return "\n".join(lines)


# -- subcommands -----------------------------------------------------------------------------------


@contextlib.contextmanager
def locked(name: str) -> Iterator[None]:
    """One holder at a time of ``state_dir()/<name>.lock`` (runs and outbox updates)."""

    with open(state_dir() / f"{name}.lock", "a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def write_atomic(path: Path, text: str) -> None:
    """Owner-only (0600; run reports can hold the model's full answer), synced, renamed into place.
    Characters UTF-8 cannot carry (lone surrogates) are written as escapes."""

    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with open(fd, "w", encoding="utf-8", errors="backslashreplace") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def read_json(path: Path, default: Any) -> Any:
    """``default`` when the file is missing; a broken file is kept aside, never silently treated as empty."""

    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        aside = path.with_name(f"{path.name}.broken-{int(time.time())}")
        with contextlib.suppress(OSError):
            path.rename(aside)
        log(f"{path.name} was unreadable; kept as {aside.name}")
        raise RuntimeError(f"{path.name} was unreadable (kept as {aside.name})") from None


MAX_OUTBOX = 30
MAX_SLUG_NUMBER = 999
OUTBOX_FORMAT = 2  # results whose item lines name tool-assigned slugs
DAY_FORMAT = 2
# What a digest may say (``digest`` and the fixed notices of ``cmd_run``): anything else in a waiting
# result, e.g. one written by another version, is replaced before it reaches Telegram.
_DATE = r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}"
_EXC = r"[A-Za-z]{2,40}(?:Error|Exception|Expired)"
_SKIP_REASONS = (
    rf"codex-quota-guard lief nicht \((?:{_EXC}|exit -?[0-9]{{1,3}})\)",
    r"Codex-Kontingent ist aufgebraucht \(codex-quota-guard\)",
    rf"Codex startete nicht \({_EXC}\)",
    r"Codex brauchte für eine Runde länger als [0-9]{1,3} Minuten",
    r"Codex endete mit exit -?[0-9]{1,3}",
    r"Codex lieferte keine gültige Antwort",
    r"das Zeitbudget der Untersuchung ist aufgebraucht",
)
# Item slugs are ``obs-<date>-<n>`` (assigned by ``cmd_run``, never taken from model text).
_SLUG_LINE = re.compile(
    r"(?:• (?:‼️ )?|⚠️ nicht \(sicher\) angelegt: )obs-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{1,3} \[(?:high|medium|low)\]"
)
_FIXED_LINES = re.compile(
    rf"🔎 Obs-Triage {_DATE}: [0-5] neue Auffälligkeit(?:en)?"
    rf"|⚠️ Obs-Triage {_DATE} übersprungen: (?:{'|'.join(_SKIP_REASONS)})"
    rf"|⚠️ Obs-Triage {_DATE} fehlgeschlagen \({_EXC}, siehe Log\)"
    rf"|⚠️ Obs-Triage {_DATE}: Untersuchung nicht abgeschlossen"
    r"|⚠️ [0-9]{1,3} weitere Befunde nicht angelegt \(Tageslimit\), nur im Lauf-Bericht"
    r"|⚠️ Tageslimit erreicht: [0-9]{1,3} weitere Befunde nur im Lauf-Bericht"  # its earlier wording
)


def slug_ok(slug: str) -> bool:
    """The model's slug (a hint for deduplication, kept in the run report only): syntax, and neither
    the bare nor the ``obs-`` form names a credential or looks like a token."""

    bare = slug.removeprefix(SLUG_PREFIX)
    forms = (bare, SLUG_PREFIX + bare)
    return bool(SLUG.fullmatch(bare)) and not any(names_credential(f) or looks_like_token(f) for f in forms)


def digest_safe(item: dict[str, Any]) -> dict[str, Any]:
    """``item`` with a message made only of digest lines (separated by ``\\n``; item lines name an
    ``obs-<date>-<n>`` slug), or with a fixed notice instead."""

    def line_ok(line: str) -> bool:
        if _FIXED_LINES.fullmatch(line):
            return True
        return _SLUG_LINE.fullmatch(line) is not None

    message = str(item.get("message") or "")
    lines = message.split("\n")
    # Item lines only from this format: another one may have named items by model-chosen slugs.
    current = item.get("format") == OUTBOX_FORMAT
    if not message or all(_FIXED_LINES.fullmatch(line) or (current and line_ok(line)) for line in lines):
        return item
    date = re.sub(r"[^0-9-]", "", str(item.get("date", "")))[:10]
    return {**item, "message": f"⚠️ Obs-Triage {date}: Nachricht verworfen (nicht im Digest-Format)"}


def outbox_put(result: dict[str, Any]) -> None:
    """Keep ``result`` durably in the outbox (replacing an earlier version with the same ``id``);
    the outbox keeps the newest ``MAX_OUTBOX``."""

    keep = state_dir() / "undelivered.json"
    with locked("outbox"):
        waiting = [item for item in read_json(keep, []) if isinstance(item, dict) and item.get("id") != result["id"]]
        waiting.append({**result, "format": OUTBOX_FORMAT})
        if len(waiting) > MAX_OUTBOX:
            log(f"outbox over {MAX_OUTBOX}: the oldest {len(waiting) - MAX_OUTBOX} results are given up")
            waiting = waiting[-MAX_OUTBOX:]
        write_atomic(keep, json.dumps(waiting, ensure_ascii=False))


def deliver() -> bool:
    """Hand every waiting result to macmini, which sends its digest at once; a result whose delivery
    macmini did not confirm (exit 0 and ``obs-ctl: delivered``) stays and goes out with the next run.
    Each waiting result is tried on its own, so one Telegram keeps refusing does not hold the others."""

    keep = state_dir() / "undelivered.json"
    with locked("outbox"):
        waiting = [item for item in read_json(keep, []) if isinstance(item, dict)]
        ok, unconfirmed = True, []
        for item in waiting:
            done = ctl("deliver", json.dumps(digest_safe(item), ensure_ascii=False), timeout=DELIVER_TIMEOUT)
            # Exit 0 and the receipt as a whole line; diagnostics arrive on stderr.
            if done.returncode == 0 and "obs-ctl: delivered" in (done.stdout or "").splitlines():
                log(f"{item.get('date')}: delivered")
                continue
            ok = False
            log(f"delivery of {item.get('date')} failed (exit {done.returncode}: {done.stderr.strip()[-200:]}); kept here")
            unconfirmed.append(item)
        if unconfirmed:
            write_atomic(keep, json.dumps(unconfirmed, ensure_ascii=False))
        else:
            keep.unlink(missing_ok=True)
    return ok


def launchd_window(jobs: list[dict[str, Any]], state: Path, now: float, *, keep: bool = True) -> dict[str, Any]:
    """Runs per job since the last daily run (stored in ``launchd-daily.json``)."""

    path = state / "launchd-daily.json"
    try:
        previous = json.loads(path.read_text())
    except (OSError, ValueError):
        previous = {}
    runs = previous.get("runs", {})
    window = [
        {**job, "runs_since_last_day": job["runs"] - runs[job["label"]]}
        for job in jobs
        if job["label"] in runs and (job["runs"] - runs[job["label"]] > 0 or job["last_exit"] not in ("0", "(never exited)"))
    ]
    if keep:
        # Jobs that could not be sampled keep their last good counter.
        merged = {**runs, **{job["label"]: job["runs"] for job in jobs}}
        write_atomic(path, json.dumps({"epoch": int(now), "runs": merged}))
    return {"since": previous.get("epoch"), "jobs": window}


def cmd_run(args: argparse.Namespace) -> int:
    now = time.time()
    today = args.date or datetime.now().strftime("%Y-%m-%d")
    state = state_dir()
    (state / "runs").mkdir(exist_ok=True)
    (state / "days").mkdir(exist_ok=True)
    signal.signal(signal.SIGTERM, _stop_codex)
    signal.signal(signal.SIGINT, _stop_codex)
    result: dict[str, Any] = {
        "date": today, "status": "ok", "detail": "", "message": "", "new_items": [], "ran_at": int(now),
        "id": f"{today}-{time.time_ns()}-{os.getpid()}",
    }  # fmt: skip
    report: dict[str, Any] = {"date": today}
    day_path = state / "days" / f"{today}.json"
    stamp = datetime.fromtimestamp(now).strftime("%H%M%S")
    run_id = f"{today}-{stamp}-{os.getpid()}"
    report_name = f"{run_id}.dry.json" if args.dry_run else f"{run_id}.json"
    with locked("run"):
        # Items this day already created (reruns count against the daily limit and are not repeated).
        day = read_json(day_path, {})
        # Every write this day attempted counts (one whose acknowledgement was lost may have landed).
        done_today = [entry if isinstance(entry, str) else str(entry.get("slug", ""))
                      for entry in day.get("attempted", []) + day.get("created", [])]  # fmt: skip
        # The model's own slugs of those findings (for deduplication within the day only); a day file
        # of another format names model slugs directly.
        hints = [str(h) for h in day.get("hints", []) if isinstance(h, str)]
        if day.get("format") != DAY_FORMAT:
            hints += [form for slug in done_today for form in (slug, slug.removeprefix(SLUG_PREFIX))]
        try:
            pack = fetch_pack(today)
            items = work_items()
            launchd = launchd_window(launchd_jobs(), state, now, keep=not args.dry_run)
            answer = investigate(prompt(pack, known_items(items, now), launchd), report)
        except Skipped as reason:
            result.update(status="skipped", detail=str(reason))
            result["message"] = f"⚠️ Obs-Triage {german_date(today)} übersprungen: {reason}"
            answer = None
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
            result.update(status="failed", detail=f"{type(error).__name__}: {str(error)[:200]}")
            result["message"] = f"⚠️ Obs-Triage {german_date(today)} fehlgeschlagen ({type(error).__name__}, siehe Log)"
            log(f"{today}: {result['detail']}")
            answer = None
        if answer is not None:
            findings, dropped = valid_findings(
                answer, {item["slug"] for item in items} | set(hints), f"studio:{state / 'runs' / report_name}"
            )
            room = max(0, MAX_NEW_ITEMS - len(done_today))
            over_limit = len(findings[room:])
            dropped += [f"{f['slug']}: daily limit of {MAX_NEW_ITEMS} reached" for f in findings[room:]]
            findings = findings[:room]
            # Item slugs come from the date and a number, never from model text: the slug is the one
            # identifier the Telegram digest names. The model's slug stays a hint in the run report.
            taken = {item["slug"] for item in items} | set(done_today)
            number = 0
            for finding in findings:
                number += 1
                while f"{SLUG_PREFIX}{today}-{number}" in taken:  # taken today or by an existing item
                    number += 1
                if number > MAX_SLUG_NUMBER:
                    break
                finding["hint"] = finding["slug"]
                finding["slug"] = f"{SLUG_PREFIX}{today}-{number}"
                taken.add(finding["slug"])
            numbered = [f for f in findings if "hint" in f]
            dropped += [f"{f['slug']}: no slug number left (1..{MAX_SLUG_NUMBER} all taken)"
                        for f in findings if "hint" not in f]  # fmt: skip
            over_limit += len(findings) - len(numbered)
            findings = numbered
            report.update(answer=answer, dropped=dropped)
            # The full answer is on disk before any ledger item or digest refers to it.
            write_atomic(state / "runs" / report_name, json.dumps(report, ensure_ascii=False, indent=1))
            if not args.dry_run and findings:
                # Durable before the first ledger write: the day's quota, and the digest in the outbox
                # (as if every write lands), so a stop in between loses neither.
                # Planned as undecided (a failed day naming every finding): only the final result,
                # which replaces it, says what was created.
                # The slugs are reserved first (they count for the daily limit): a stop before the outbox
                # write leaves only unused numbers, never one slug for two findings. The hints, which
                # keep a finding from being filed twice, are recorded per finding right before its
                # write, after the outbox entry, so such a stop never suppresses a finding silently.
                done_today += [f["slug"] for f in findings]
                write_atomic(day_path, json.dumps({"format": DAY_FORMAT, "attempted": done_today, "hints": hints},
                                                  ensure_ascii=False))  # fmt: skip
                outbox_put({**result, "status": "failed", "message": digest(today, [], findings, over_limit),
                            "detail": "interrupted before the ledger writes were confirmed"})  # fmt: skip
            created: list[dict[str, str]] = []
            unsure: list[dict[str, str]] = []
            for finding in findings:
                if args.dry_run:
                    created.append(finding)
                    continue
                # Recorded before the write (which may land even if this run stops): after the outbox
                # entry, which names the finding as undecided, so a stop here is never silent.
                hints.append(finding["hint"])
                write_atomic(day_path, json.dumps({"format": DAY_FORMAT, "attempted": done_today, "hints": hints},
                                                  ensure_ascii=False))  # fmt: skip
                exists = item_exists(finding["slug"])
                if exists is False and create_item(finding, today):
                    created.append(finding)
                elif exists is True:
                    # Created by someone else since the run read the ledger: theirs stays untouched.
                    dropped.append(f"{finding['slug']}: created meanwhile by another writer; not overwritten")
                else:
                    unsure.append(finding)
            report["unsure"] = [f["slug"] for f in unsure]
            result.update(
                detail=f"{len(created)} new, {len(answer.get('known', []))} known, {len(dropped)} dropped, "
                f"{len(unsure)} ledger writes failed or undecided",
                message=digest(today, created, unsure, over_limit),
                new_items=[{"slug": f["slug"], "title": f["title"]} for f in created],
            )
            if unsure:
                result["status"] = "failed"
            if answer.get("incomplete"):
                # The last round still asked for queries: the review did not finish.
                result["status"] = "failed"
                result["message"] = "\n".join(
                    m for m in (result["message"], f"⚠️ Obs-Triage {german_date(today)}: Untersuchung nicht abgeschlossen")
                    if m
                )
        report["result"] = result
        write_atomic(state / "runs" / report_name, json.dumps(report, ensure_ascii=False, indent=1))
        log(f"{today}: {result['status']}: {result['detail']}")
        if args.dry_run:
            print(result["message"] or "(no message)")
            return 0
        outbox_put(result)
        return 0 if deliver() else 1


def cmd_launchd_check(args: argparse.Namespace) -> int:
    state = state_dir()
    path = state / "launchd-sample.json"
    try:
        previous = json.loads(path.read_text()).get("runs", {})
    except (OSError, ValueError):
        previous = {}
    errors: list[str] = []
    jobs = launchd_jobs(errors)
    loops = launchd_changes(jobs, previous)
    # Jobs that could not be sampled keep their last good counter.
    sample = json.dumps({"epoch": int(time.time()), "runs": {**previous, **{job["label"]: job["runs"] for job in jobs}}})
    payload = {"host": os.uname().nodename.split(".")[0], "checked": len(jobs), "errors": len(errors), "loops": loops}
    if args.dry_run:
        print(json.dumps(payload, indent=1))
        return 0
    try:
        done = ctl("launchd", json.dumps(payload))
    except subprocess.TimeoutExpired:
        done = None
    if done is None or done.returncode != 0:
        # The sample is kept only once macmini has the report, so the next run still sees these runs.
        detail = "timed out" if done is None else f"exit {done.returncode}: {done.stderr.strip()[-200:]}"
        log(f"launchd report failed ({detail})")
        return 1
    write_atomic(path, sample)
    if loops:
        log(f"launchd loops: {', '.join(loop['label'] for loop in loops)}")
    return 0


def cmd_weekly(args: argparse.Namespace) -> int:
    coordination = Path(env("OBS_TRIAGE_KATHARINA", str(Path.home() / "workspaces/ws-work-planning/coordination/katharina")))
    today = datetime.now().strftime("%Y-%m-%d")
    name = "obs-weekly"
    (coordination / f"{name}.md").write_text(WEEKLY_BRIEF.read_text().replace("__DATE__", today))
    if args.dry_run:
        print(coordination / f"{name}.md")
        return 0
    log(f"weekly review {today} starts on the main account")
    done = subprocess.run(
        [str(coordination / "run.sh"), name], env={**os.environ, "ACCOUNT": "main"}, check=False, timeout=6 * 3600
    )
    log(f"weekly review {today} ended with exit {done.returncode}")
    return 0 if done.returncode == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="obs-triage", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="daily LLM triage of macmini's evidence pack")
    run.add_argument("--date", help="the pack's date (default today)")
    run.add_argument("--dry-run", action="store_true", help="no ledger items, no delivery; print the digest")
    run.set_defaults(func=cmd_run)
    check = sub.add_parser("launchd-check", help="report launchd crash loops to macmini")
    check.add_argument("--dry-run", action="store_true")
    check.set_defaults(func=cmd_launchd_check)
    weekly = sub.add_parser("weekly", help="start the weekly review worker")
    weekly.add_argument("--dry-run", action="store_true", help="write the brief only")
    weekly.set_defaults(func=cmd_weekly)
    args = parser.parse_args(argv)
    return int(args.func(args))
