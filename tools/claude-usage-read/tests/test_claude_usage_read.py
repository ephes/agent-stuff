import io
import json
import os
import stat
import sys
import tempfile
import threading
import time
import fcntl
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import claude_usage_read as cur

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class ParseResetTest(unittest.TestCase):
    def test_month_day_time_with_zone(self):
        value = cur.parse_reset("Nov 12 at 7:59pm (Europe/Berlin)", NOW)
        self.assertEqual(value.astimezone(timezone.utc), datetime(2026, 11, 12, 18, 59, tzinfo=timezone.utc))

    def test_hour_only(self):
        value = cur.parse_reset("Nov 12 at 8pm (Europe/Berlin)", NOW)
        self.assertEqual(value.astimezone(timezone.utc), datetime(2026, 11, 12, 19, 0, tzinfo=timezone.utc))

    def test_noon_and_midnight(self):
        self.assertEqual(cur.parse_reset("Nov 12 at 12pm (UTC)", NOW).hour, 12)
        self.assertEqual(cur.parse_reset("Nov 12 at 12am (UTC)", NOW).hour, 0)

    def test_year_wraps_to_next_year(self):
        value = cur.parse_reset("Jan 2 at 8am (Europe/Berlin)", NOW)
        self.assertEqual((value.year, value.month, value.day, value.hour), (2027, 1, 2, 8))

    def test_reset_just_passed_stays_in_this_year(self):
        value = cur.parse_reset("Nov 6 at 8am (UTC)", NOW)
        self.assertEqual(value.year, 2026)

    def test_explicit_year(self):
        self.assertEqual(cur.parse_reset("Mar 1, 2028 at 9:30am (UTC)", NOW).year, 2028)

    def test_time_only_today_or_tomorrow(self):
        later = cur.parse_reset("9pm (UTC)", NOW)
        self.assertEqual((later.day, later.hour), (6, 21))
        earlier = cur.parse_reset("9am (UTC)", NOW)
        self.assertEqual((earlier.day, earlier.hour), (7, 9))

    def test_24_hour_clock(self):
        self.assertEqual(cur.parse_reset("Nov 12 at 20:00 (UTC)", NOW).hour, 20)

    def test_rejects_garbage(self):
        for text in ("soon", "Nov 12 at 13pm (UTC)", "Foo 12 at 8pm (UTC)", "Nov 31 at 8pm (UTC)",
                     "Nov 12 at 8pm (Mars/Base)", "Nov 12 at 20 (UTC)"):
            with self.subTest(text=text), self.assertRaises(cur.UsageError):
                cur.parse_reset(text, NOW)


class ParseOutputTest(unittest.TestCase):
    def test_subscription_fixture(self):
        windows = cur.parse_claude_output(fixture("usage-subscription.json"), NOW)
        self.assertEqual([w.label for w in windows], ["week (all models)", "week (Fable)"])
        weekly = cur.weekly_all_models(windows)
        self.assertEqual(weekly.used_percent, 3.0)
        self.assertEqual(cur._iso(weekly.resets_at), "2026-11-12T18:59:00Z")

    def test_session_window_and_fraction(self):
        windows = cur.parse_claude_output(fixture("usage-session-and-year-wrap.json"), NOW)
        self.assertEqual(windows[0].label, "session")
        weekly = cur.weekly_all_models(windows)
        self.assertEqual(weekly.used_percent, 97.5)
        self.assertEqual(cur._iso(weekly.resets_at), "2027-01-02T07:00:00Z")

    def test_no_usage_lines(self):
        with self.assertRaisesRegex(cur.UsageError, "no 'Current"):
            cur.parse_claude_output(fixture("usage-api-key.json"), NOW)

    def test_cost_summary_names_the_missing_login(self):
        # ~/.claude read with an explicit CLAUDE_CONFIG_DIR: no login found, the cost summary instead.
        with self.assertRaisesRegex(cur.UsageError, "API-cost summary.*no subscription login"):
            cur.parse_claude_output(fixture("usage-cost-summary.json"), NOW)

    def test_main_account_fixture(self):
        now = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)
        windows = cur.parse_claude_output(fixture("usage-main-account.json"), now)
        self.assertEqual([(w.work_label, w.used_percent, cur._iso(w.resets_at)) for w in windows], [
            ("Weekly · all models", 76.0, "2026-11-18T02:00:00Z"),
            ("Weekly · Fable", 10.0, "2026-11-18T01:59:00Z"),
        ])

    def test_work_labels(self):
        cases = {"week (all models)": "Weekly · all models", "Week (All Models)": "Weekly · all models",
                 "week (Fable)": "Weekly · Fable", "week (Opus 5)": "Weekly · Opus 5",
                 "session": None, "week": None, "month (all models)": None}
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(cur.Window(label, 1.0, None).work_label, expected)

    def test_not_json(self):
        with self.assertRaisesRegex(cur.UsageError, "JSON"):
            cur.parse_claude_output("Welcome to Claude\n", NOW)

    def test_error_result(self):
        raw = json.dumps({"type": "result", "is_error": True, "result": "Not logged in\nmore"})
        with self.assertRaisesRegex(cur.UsageError, "Not logged in$"):
            cur.parse_claude_output(raw, NOW)

    def test_model_answer_is_rejected(self):
        raw = json.dumps({"type": "result", "is_error": False, "local_command": None,
                          "result": "Current week (all models): 3% used"})
        # local_command None is accepted (older versions omit it); a different command is not
        cur.parse_claude_output(raw, NOW)
        raw = json.dumps({"type": "result", "is_error": False, "local_command": "status",
                          "result": "Current week (all models): 3% used"})
        with self.assertRaisesRegex(cur.UsageError, "local command"):
            cur.parse_claude_output(raw, NOW)

    def test_missing_weekly(self):
        windows = cur.parse_usage_text("Current session: 4% used · resets 9pm (UTC)", NOW)
        with self.assertRaises(cur.UsageError):
            cur.weekly_all_models(windows)

    def test_report_payload(self):
        reset = datetime(2026, 11, 12, 18, 59, tzinfo=timezone.utc)
        windows = [cur.Window("session", 40.0, reset), cur.Window("week (Fable)", 0.5, reset),
                   cur.Window("week (Opus)", 7.0, None), cur.Window("week (all models)", 3.0, reset)]
        payload = cur.report_payload(windows, NOW, pool="claude-katharina")
        self.assertEqual(payload, {"windows": [
            {"provider": "claude", "window_label": "Weekly · all models", "percent_used": 3.0,
             "resets_at": "2026-11-12T18:59:00Z", "observed_at": "2026-11-06T15:00:00Z",
             "source": "claude-usage-read", "pool": "claude-katharina"},
            {"provider": "claude", "window_label": "Weekly · Fable", "percent_used": 0.5,
             "resets_at": "2026-11-12T18:59:00Z", "observed_at": "2026-11-06T15:00:00Z",
             "source": "claude-usage-read", "pool": "claude-katharina"},
            # No reset of its own (unused this week): the all-models reset keeps the reading fresh.
            {"provider": "claude", "window_label": "Weekly · Opus", "percent_used": 7.0,
             "resets_at": "2026-11-12T18:59:00Z", "observed_at": "2026-11-06T15:00:00Z",
             "source": "claude-usage-read", "pool": "claude-katharina"},
        ]})
        # Without an all-models window there is no cycle to fall back on: such a window is left out.
        lone = cur.report_payload([cur.Window("week (Opus)", 0.0, None)], NOW)
        self.assertEqual(lone, {"windows": []})
        main = cur.report_payload(windows, NOW, account="main")["windows"]
        self.assertTrue(all(w["account"] == "main" and "pool" not in w for w in main))
        self.assertTrue(all("account" not in w for w in cur.report_payload(windows, NOW)["windows"]))


RATE_LIMITED_LOG = (
    "2026-11-19T19:05:50.244Z [DEBUG] fetchUtilization: GET /api/oauth/usage (attempt 1)\n"
    "2026-11-19T19:05:50.261Z [DEBUG] fetchUtilization: 429 remembered for this bearer; not asking again for 2973s\n"
    "2026-11-19T19:05:50.261Z [ERROR] Failed to load usage data: Request failed with status code 429\n")
FORBIDDEN_LOG = (
    "x [DEBUG] fetchUtilization: GET /api/oauth/usage (attempt 1)\n"
    "x [ERROR] Failed to load usage data: Request failed with status code 403\n")


class MissingWindowsTest(unittest.TestCase):
    def test_debug_log_rate_limit(self):
        diag = cur.parse_debug_log(RATE_LIMITED_LOG)
        self.assertEqual((diag.attempted, diag.failed, diag.status, diag.retry_after_s), (True, True, 429, 2973))

    def test_debug_log_without_fetch(self):
        self.assertEqual(cur.parse_debug_log("x [DEBUG] Bootstrap ok\n"), cur.FetchDiagnostics())

    def test_rate_limited_reason(self):
        with self.assertRaisesRegex(cur.WindowsMissing, r"windows section missing - usage fetch rate-limited "
                                    r"\(HTTP 429.*~50 min\)"):
            cur.parse_claude_output(fixture("usage-windows-missing.json"), NOW,
                                    cur.parse_debug_log(RATE_LIMITED_LOG))

    def test_scope_reason_names_the_login_command(self):
        with self.assertRaisesRegex(cur.WindowsMissing, r"login lacks usage scope or was revoked \(HTTP 403\); "
                                    r"log in again: CLAUDE_CONFIG_DIR=/x/.claude-k claude, then /login"):
            cur.parse_claude_output(fixture("usage-windows-missing.json"), NOW, cur.parse_debug_log(FORBIDDEN_LOG),
                                    Path("/x/.claude-k"))

    def test_other_failure_and_unknown(self):
        diag = cur.parse_debug_log("x [ERROR] Failed to load usage data: socket hang up\n")
        with self.assertRaisesRegex(cur.WindowsMissing, r"usage fetch failed$"):
            cur.parse_claude_output(fixture("usage-windows-missing.json"), NOW, diag)
        with self.assertRaisesRegex(cur.WindowsMissing, "no usage fetch in claude's debug log"):
            cur.parse_claude_output(fixture("usage-windows-missing.json"), NOW, None)

    def test_api_key_output_is_not_windows_missing(self):
        # "/usage is only available for subscription plans." is not a subscription login.
        with self.assertRaises(cur.UsageError) as ctx:
            cur.parse_claude_output(fixture("usage-api-key.json"), NOW, cur.FetchDiagnostics())
        self.assertNotIsInstance(ctx.exception, cur.WindowsMissing)


def write_claude_json(path, *, fetched_at, percent=88, fable=10, resets_at="2026-11-12T19:00:00.058023+00:00",
                      cache_account="acct-1", account="acct-1", limits=True):
    utilization = {"seven_day": {"utilization": percent, "resets_at": resets_at}, "five_hour": None}
    if limits:
        utilization["limits"] = [
            {"kind": "weekly_all", "group": "weekly", "percent": percent, "resets_at": resets_at, "scope": None},
            {"kind": "weekly_scoped", "group": "weekly", "percent": fable, "resets_at": resets_at,
             "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None}},
            {"kind": "five_hour", "group": "session", "percent": 50, "resets_at": resets_at, "scope": None},
        ]
    data = {"oauthAccount": {"accountUuid": account, "emailAddress": "someone@example.invalid"},
            "cachedUsageUtilization": {"accountUuid": cache_account,
                                       "fetchedAtMs": int(fetched_at.timestamp() * 1000),
                                       "utilization": utilization}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class CachedUsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / ".claude-k"
        self.fetched = datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_weekly_windows_and_fetch_time(self):
        write_claude_json(self.cfg / ".claude.json", fetched_at=self.fetched)
        windows, fetched, login = cur.read_cached_usage(self.cfg, NOW)
        self.assertEqual(login, "acct-1")
        self.assertEqual(fetched, self.fetched)
        self.assertEqual([(w.work_label, w.used_percent, cur._iso(w.resets_at)) for w in windows], [
            ("Weekly · all models", 88.0, "2026-11-12T19:00:00Z"), ("Weekly · Fable", 10.0, "2026-11-12T19:00:00Z")])

    def test_scoped_window_past_its_own_reset_is_dropped(self):
        write_claude_json(self.cfg / ".claude.json", fetched_at=self.fetched)
        data = json.loads((self.cfg / ".claude.json").read_text())
        data["cachedUsageUtilization"]["utilization"]["limits"][1]["resets_at"] = "2026-11-06T14:00:00+00:00"
        (self.cfg / ".claude.json").write_text(json.dumps(data))
        windows, _, _ = cur.read_cached_usage(self.cfg, NOW)
        self.assertEqual([w.label for w in windows], ["week (all models)"])

    def test_seven_day_without_limits(self):
        write_claude_json(self.cfg / ".claude.json", fetched_at=self.fetched, limits=False)
        windows, _, _ = cur.read_cached_usage(self.cfg, NOW)
        self.assertEqual([(w.label, w.used_percent) for w in windows], [("week (all models)", 88.0)])

    def test_default_dir_uses_home_claude_json(self):
        home = Path(self.tmp.name) / "home"
        (home / ".claude").mkdir(parents=True)
        write_claude_json(home / ".claude.json", fetched_at=self.fetched, percent=44)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            windows, _, _ = cur.read_cached_usage(home / ".claude", NOW)
        self.assertEqual(windows[0].used_percent, 44.0)

    def test_unusable_caches(self):
        cases = {
            "predates the weekly reset": dict(resets_at="2026-11-06T14:00:00+00:00"),
            "another account": dict(cache_account="acct-2"),
            "in the future": dict(fetched_at=datetime(2026, 11, 6, 16, 0, tzinfo=timezone.utc)),
        }
        for message, kwargs in cases.items():
            with self.subTest(message=message):
                write_claude_json(self.cfg / ".claude.json", **{"fetched_at": self.fetched, **kwargs})
                with self.assertRaisesRegex(cur.UsageError, message):
                    cur.read_cached_usage(self.cfg, NOW)
        with self.assertRaisesRegex(cur.UsageError, "no .claude.json"):
            cur.read_cached_usage(Path(self.tmp.name) / "missing", NOW)
        data = json.loads((self.cfg / ".claude.json").read_text())
        data["cachedUsageUtilization"]["fetchedAtMs"] = 10 ** 25
        (self.cfg / ".claude.json").write_text(json.dumps(data))
        with self.assertRaisesRegex(cur.UsageError, "invalid fetch time"):
            cur.read_cached_usage(self.cfg, NOW)
        (self.cfg / ".claude.json").write_text("{}")
        with self.assertRaisesRegex(cur.UsageError, "no cached usage reading"):
            cur.read_cached_usage(self.cfg, NOW)


class ChildEnvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / ".claude").mkdir()
        self.base = {"HOME": str(self.home), "PATH": "/usr/bin", "CLAUDE_CONFIG_DIR": "/elsewhere",
                     "ANTHROPIC_API_KEY": "x", "ANTHROPIC_BASE_URL": "x", "CLAUDE_CODE_OAUTH_TOKEN": "x",
                     "CLAUDECODE": "1", "HERDR_PANE_ID": "p1", "CLAUDE_USAGE_READ_WORK": "work"}

    def tearDown(self):
        self.tmp.cleanup()

    def env_for(self, config_dir):
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            return cur.child_env(config_dir, self.base)

    def test_default_dir_runs_without_config_dir(self):
        for config_dir in (self.home / ".claude", self.home / ".claude" / ".." / ".claude"):
            with self.subTest(config_dir=config_dir):
                self.assertNotIn("CLAUDE_CONFIG_DIR", self.env_for(config_dir))

    def test_default_dir_is_recognized_lexically_like_claude_code(self):
        (self.home / "x").mkdir()
        (self.home / "p" / ".claude").mkdir(parents=True)
        (self.home / "p" / "link").symlink_to(self.home / "x")
        # The filesystem would walk link/.. to ~/.claude; Claude Code's lexical join gives ~/p/.claude.
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            self.assertFalse(cur._is_default_dir(self.home / "p" / "link" / ".." / ".claude"))
            self.assertTrue(cur._is_default_dir(self.home / "p" / ".." / ".claude"))

    def test_case_variant_of_default_dir_on_a_case_insensitive_volume(self):
        if not (self.home / ".CLAUDE").exists():
            self.skipTest("case-sensitive volume")
        self.assertNotIn("CLAUDE_CONFIG_DIR", self.env_for(self.home / ".CLAUDE"))

    def test_other_dir_is_passed(self):
        env = self.env_for(self.home / ".claude-katharina")
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(self.home / ".claude-katharina"))

    def test_scrubs_other_logins_and_session_context(self):
        env = self.env_for(self.home / ".claude-katharina")
        self.assertEqual(sorted(env), ["CLAUDE_CONFIG_DIR", "CLAUDE_USAGE_READ_WORK", "HOME", "PATH"])


class CliTest(unittest.TestCase):
    """Drive main() against fake claude and work executables."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = self.dir / "calls.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def fake(self, name, body):
        path = self.dir / name
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return str(path)

    def fake_claude(self, fixture_name, exit_code=0, debug=""):
        return self.fake("claude", (
            "import json, os, sys\n"
            f"open({str(self.log)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], "
            "'config': os.environ.get('CLAUDE_CONFIG_DIR'), 'cwd': os.getcwd()}) + '\\n')\n"
            "if '--debug-file' in sys.argv:\n"
            f"    open(sys.argv[sys.argv.index('--debug-file') + 1], 'w').write({debug!r})\n"
            f"sys.stdout.write(open({str(FIXTURES / fixture_name)!r}, encoding='utf-8').read())\n"
            f"sys.exit({exit_code})\n"))

    def fake_work(self, exit_code=0):
        return self.fake("work", (
            "import json, sys\n"
            f"open({str(self.log)!r}, 'a').write(json.dumps({{'work': sys.argv[1:], "
            "'stdin': sys.stdin.read()}) + '\\n')\n"
            f"sys.exit({exit_code})\n"))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def run_main(self, argv, env):
        out, err = io.StringIO(), io.StringIO()
        env = {"CLAUDE_USAGE_READ_STATE": str(self.dir / "state"), **env}
        with mock.patch.dict(os.environ, env), redirect_stdout(out), redirect_stderr(err):
            code = cur.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_prints_parseable_line(self):
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-subscription.json"),
               "CLAUDE_CONFIG_DIR": str(self.dir / "cfg")}
        code, out, err = self.run_main([], env)
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"^used=3 resets_at=20\d\d-11-12T18:59:00Z observed_at=\S+Z config_dir=\S+cfg\n$")
        call = self.calls()[0]
        self.assertEqual(call["argv"][:6], ["-p", "/usage", "--output-format", "json", "--no-session-persistence",
                                            "--debug-file"])
        self.assertEqual(len(call["argv"]), 7)
        # The debug log lives in a private temp dir that is gone afterwards.
        self.assertFalse(Path(call["argv"][6]).exists())
        self.assertEqual(call["config"], str(self.dir / "cfg"))
        self.assertNotIn("credential", out + err)

    def test_positional_config_dir_wins(self):
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-subscription.json"),
               "CLAUDE_CONFIG_DIR": "/nonexistent-env"}
        code, _, _ = self.run_main([str(self.dir / "other")], env)
        self.assertEqual(code, 0)
        self.assertEqual(self.calls()[0]["config"], str(self.dir / "other"))

    def test_json_output(self):
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-subscription.json")}
        code, out, _ = self.run_main(["--json", str(self.dir)], env)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["used_percent"], 3.0)
        self.assertEqual(len(data["windows"]), 2)
        self.assertNotIn("credential", out)

    def test_report_calls_work(self):
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-subscription.json"),
               "CLAUDE_USAGE_READ_WORK": self.fake_work()}
        code, _, err = self.run_main(["--report", "--pool", "claude-katharina", str(self.dir)], env)
        self.assertEqual(code, 0, err)
        work = [c for c in self.calls() if "work" in c]
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["work"], ["usage", "report", "--json", "-"])
        windows = json.loads(work[0]["stdin"])["windows"]
        self.assertEqual([(w["window_label"], w["percent_used"], w["pool"]) for w in windows], [
            ("Weekly · all models", 3.0, "claude-katharina"), ("Weekly · Fable", 0.0, "claude-katharina")])
        self.assertTrue(all(w["source"] == "claude-usage-read" for w in windows))
        self.assertNotIn("credential", work[0]["stdin"])

    def test_default_dir_reads_without_config_dir(self):
        home = self.dir / "home"
        (home / ".claude").mkdir(parents=True)
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-main-account.json"), "HOME": str(home),
               "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_CODE_OAUTH_TOKEN": "x"}
        code, out, err = self.run_main([], env)
        self.assertEqual(code, 0, err)
        self.assertIn("used=76 ", out)
        self.assertIsNone(self.calls()[0]["config"])

    def test_cost_summary_is_a_read_failure(self):
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-cost-summary.json"),
               "CLAUDE_USAGE_READ_WORK": self.fake_work()}
        code, out, err = self.run_main(["--report", str(self.dir)], env)
        self.assertEqual(code, cur.EXIT_READ_FAILED)
        self.assertIn("no subscription login", err)
        self.assertFalse(any("work" in c for c in self.calls()))

    def test_report_failure_exit_code(self):
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-subscription.json"),
               "CLAUDE_USAGE_READ_WORK": self.fake_work(exit_code=2)}
        code, _, err = self.run_main(["--report", str(self.dir)], env)
        self.assertEqual(code, cur.EXIT_REPORT_FAILED)
        self.assertIn("exited 2", err)

    def test_unparseable_output_does_not_report(self):
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-api-key.json"),
               "CLAUDE_USAGE_READ_WORK": self.fake_work()}
        code, out, err = self.run_main(["--report", str(self.dir)], env)
        self.assertEqual(code, cur.EXIT_READ_FAILED)
        self.assertEqual(out, "")
        self.assertFalse(any("work" in c for c in self.calls()))

    def test_claude_failure(self):
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-subscription.json", exit_code=3)}
        code, out, err = self.run_main([str(self.dir)], env)
        self.assertEqual(code, cur.EXIT_READ_FAILED)
        self.assertIn("claude exited 3", err)

    def test_missing_claude(self):
        env = {"CLAUDE_USAGE_READ_CLAUDE": str(self.dir / "nope")}
        code, _, err = self.run_main([str(self.dir)], env)
        self.assertEqual(code, cur.EXIT_READ_FAILED)
        self.assertIn("not found", err)

    def test_windows_missing_falls_back_to_cache_and_reports_once(self):
        cfg = self.dir / "cfg"
        fetched = datetime.now(timezone.utc).replace(microsecond=0) - cur.timedelta(minutes=40)
        reset = (datetime.now(timezone.utc) + cur.timedelta(days=2)).isoformat()
        write_claude_json(cfg / ".claude.json", fetched_at=fetched, resets_at=reset)
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-windows-missing.json", debug=RATE_LIMITED_LOG),
               "CLAUDE_USAGE_READ_WORK": self.fake_work()}
        code, out, err = self.run_main(["--report", "--pool", "claude-katharina", str(cfg)], env)
        self.assertEqual(code, cur.EXIT_STALE, err)
        self.assertIn(f"observed_at={cur._iso(fetched)} ", out)
        self.assertTrue(out.rstrip().endswith("stale=cached"))
        self.assertIn("windows section missing - usage fetch rate-limited (HTTP 429", err)
        self.assertIn("using Claude Code's cached reading", err)
        self.assertNotIn("example.invalid", out + err)
        work = [c for c in self.calls() if "work" in c]
        self.assertEqual(len(work), 1)
        windows = json.loads(work[0]["stdin"])["windows"]
        self.assertEqual([(w["window_label"], w["percent_used"], w["observed_at"], w["source"]) for w in windows], [
            ("Weekly · all models", 88.0, cur._iso(fetched), "claude-usage-read:cache"),
            ("Weekly · Fable", 10.0, cur._iso(fetched), "claude-usage-read:cache")])
        self.assertNotIn("example.invalid", work[0]["stdin"])
        # The same cached reading is not sent again.
        code, _, err = self.run_main(["--report", "--pool", "claude-katharina", str(cfg)], env)
        self.assertEqual(code, cur.EXIT_STALE)
        self.assertIn("not newer than the last cached reading reported", err)
        self.assertEqual(len([c for c in self.calls() if "work" in c]), 1)

    def test_live_reports_record_nothing(self):
        cfg = self.dir / "cfg"
        fetched = datetime.now(timezone.utc).replace(microsecond=0) - cur.timedelta(hours=1)
        resets = (datetime.now(timezone.utc) + cur.timedelta(days=2)).isoformat()
        write_claude_json(cfg / ".claude.json", fetched_at=fetched, resets_at=resets)
        live = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-subscription.json"),
                "CLAUDE_USAGE_READ_WORK": self.fake_work()}
        self.assertEqual(self.run_main(["--report", str(cfg)], live)[0], 0)
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-windows-missing.json", debug=RATE_LIMITED_LOG),
               "CLAUDE_USAGE_READ_WORK": live["CLAUDE_USAGE_READ_WORK"]}
        code, _, err = self.run_main(["--report", str(cfg)], env)
        self.assertEqual(code, cur.EXIT_STALE, err)
        # The live run recorded nothing, so the (older) cached reading is sent once, then held back.
        self.assertEqual(len([c for c in self.calls() if "work" in c]), 2)
        self.run_main(["--report", str(cfg)], env)
        self.assertEqual(len([c for c in self.calls() if "work" in c]), 2)
        # Another login in the same dir (re-login, or a dir swapped in): the record does not suppress it.
        write_claude_json(cfg / ".claude.json", fetched_at=fetched, resets_at=resets,
                          account="acct-2", cache_account="acct-2")
        code, _, err = self.run_main(["--report", str(cfg)], env)
        self.assertEqual(code, cur.EXIT_STALE, err)
        self.assertEqual(len([c for c in self.calls() if "work" in c]), 3)

    def test_relative_config_dir_is_the_same_for_claude_and_cache(self):
        cfg = self.dir / "cfg"
        write_claude_json(cfg / ".claude.json", fetched_at=datetime.now(timezone.utc) - cur.timedelta(minutes=5),
                          resets_at=(datetime.now(timezone.utc) + cur.timedelta(days=1)).isoformat())
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-windows-missing.json", debug=RATE_LIMITED_LOG)}
        old = os.getcwd()
        os.chdir(self.dir)
        try:
            code, out, err = self.run_main(["cfg"], env)
        finally:
            os.chdir(old)
        self.assertEqual(code, cur.EXIT_STALE, err)
        self.assertEqual(Path(self.calls()[0]["config"]).resolve(), cfg.resolve())
        printed = out.split("config_dir=", 1)[1].split()[0]
        self.assertTrue(os.path.isabs(printed))
        self.assertEqual(Path(printed).resolve(), cfg.resolve())

    def test_cache_path_is_joined_like_claude_code(self):
        real = self.dir / "profiles" / "real"
        (real / "cfg").mkdir(parents=True)
        (real / "sub").mkdir()
        (self.dir / "link").symlink_to(real / "sub")
        # Claude Code joins with node's path.join, which collapses "link/.." lexically: its
        # .claude.json for "link/../cfg" is <cwd>/cfg/.claude.json, not real/cfg's.
        fetched = datetime.now(timezone.utc) - cur.timedelta(minutes=5)
        resets = (datetime.now(timezone.utc) + cur.timedelta(days=1)).isoformat()
        write_claude_json(real / "cfg" / ".claude.json", fetched_at=fetched, resets_at=resets, percent=11)
        write_claude_json(self.dir / "cfg" / ".claude.json", fetched_at=fetched, resets_at=resets, percent=22)
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-windows-missing.json", debug=RATE_LIMITED_LOG)}
        old = os.getcwd()
        os.chdir(self.dir)
        try:
            code, out, err = self.run_main(["link/../cfg"], env)
        finally:
            os.chdir(old)
        self.assertEqual(code, cur.EXIT_STALE, err)
        # claude gets the spelling unchanged (its keychain item depends on it) ...
        self.assertTrue(self.calls()[0]["config"].endswith("/link/../cfg"))
        # ... and the fallback reads the .claude.json claude itself would.
        self.assertTrue(out.startswith("used=22 "), out)

    def test_live_report_during_a_login_switch_records_nothing(self):
        cfg = self.dir / "cfg"
        fetched = datetime.now(timezone.utc).replace(microsecond=0) - cur.timedelta(hours=1)
        resets = (datetime.now(timezone.utc) + cur.timedelta(days=2)).isoformat()
        write_claude_json(cfg / ".claude.json", fetched_at=fetched, resets_at=resets)
        switched = self.dir / "switched.json"
        write_claude_json(switched, fetched_at=fetched, resets_at=resets, account="acct-2", cache_account="acct-2")
        # claude runs while the dir's login changes from acct-1 to acct-2.
        claude = self.fake("claude-switch", (
            "import shutil, sys\n"
            f"shutil.copy({str(switched)!r}, {str(cfg / '.claude.json')!r})\n"
            f"sys.stdout.write(open({str(FIXTURES / 'usage-subscription.json')!r}, encoding='utf-8').read())\n"))
        env = {"CLAUDE_USAGE_READ_CLAUDE": claude, "CLAUDE_USAGE_READ_WORK": self.fake_work()}
        self.assertEqual(self.run_main(["--report", str(cfg)], env)[0], 0)
        record = cur.state_file(cfg, env={"CLAUDE_USAGE_READ_STATE": str(self.dir / "state")})
        self.assertFalse(record.exists())
        # acct-2's older cached reading is still sent.
        env["CLAUDE_USAGE_READ_CLAUDE"] = self.fake_claude("usage-windows-missing.json", debug=RATE_LIMITED_LOG)
        code, _, err = self.run_main(["--report", str(cfg)], env)
        self.assertEqual(code, cur.EXIT_STALE, err)
        self.assertEqual(len([c for c in self.calls() if "work" in c]), 2)

    def test_report_record_is_per_profile_and_target(self):
        real = self.dir / "profiles" / "real"
        (real / "sub").mkdir(parents=True)
        (self.dir / "link").symlink_to(real / "sub")
        base = {"CLAUDE_USAGE_READ_STATE": str(self.dir / "state")}
        lexical = cur.state_file(self.dir / "link" / ".." / "cfg", "p1", env=base)
        self.assertEqual(lexical, cur.state_file(self.dir / "cfg", "p1", env=base))
        self.assertNotEqual(lexical, cur.state_file(real / "cfg", "p1", env=base))
        loop = self.dir / "loop"
        loop.symlink_to(loop)
        self.assertTrue(cur.state_file(loop, "p1", env=base).name.endswith(".json"))
        self.assertFalse(cur._is_default_dir(loop))
        self.assertNotEqual(lexical, cur.state_file(self.dir / "cfg", "p2", env=base))
        self.assertNotEqual(lexical, cur.state_file(self.dir / "cfg", "p1", "main", env=base))

    def test_reading_that_expires_while_waiting_for_the_lock_is_not_sent(self):
        cfg = self.dir / "cfg"
        windows = [cur.Window("week (all models)", 5.0, datetime.now(timezone.utc) - cur.timedelta(seconds=1))]
        args = mock.Mock(pool=None, account=None)
        err = io.StringIO()
        with redirect_stderr(err):
            code = cur._report(windows, NOW, True, self.dir / "state.json", args, self.fake_work())
        self.assertEqual(code, cur.EXIT_READ_FAILED)
        self.assertIn("expired at the weekly reset", err.getvalue())
        self.assertFalse(self.log.exists() and any("work" in c for c in self.calls()))

    def test_overlapping_reports_wait_for_the_lock(self):
        cfg = self.dir / "cfg"
        write_claude_json(cfg / ".claude.json", fetched_at=datetime.now(timezone.utc) - cur.timedelta(minutes=5),
                          resets_at=(datetime.now(timezone.utc) + cur.timedelta(days=1)).isoformat())
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-windows-missing.json", debug=RATE_LIMITED_LOG),
               "CLAUDE_USAGE_READ_WORK": self.fake_work(), "CLAUDE_USAGE_READ_STATE": str(self.dir / "state")}
        with mock.patch.dict(os.environ, {"CLAUDE_USAGE_READ_STATE": str(self.dir / "state")}):
            lock_path = cur.state_file(Path(os.path.abspath(cfg))).with_suffix(".lock")
        lock_path.parent.mkdir(parents=True)
        held = open(lock_path, "a")
        fcntl.flock(held, fcntl.LOCK_EX)
        waiting = threading.Event()

        def flock(handle, op):
            waiting.set()
            return fcntl.flock(handle, op)

        result = {}
        fake_fcntl = mock.Mock(LOCK_EX=fcntl.LOCK_EX, flock=flock)
        thread = threading.Thread(target=lambda: result.update(code=self.run_main(["--report", str(cfg)], env)[0]))
        try:
            with mock.patch.object(cur, "fcntl", fake_fcntl):
                thread.start()
                self.assertTrue(waiting.wait(30), "the run never tried to take the lock")
                time.sleep(0.5)
                self.assertFalse(any("work" in c for c in self.calls()), "reported while another run held the lock")
                held.close()
                thread.join(30)
        finally:
            held.close()
            thread.join(30)
        self.assertEqual(result.get("code"), cur.EXIT_STALE)
        self.assertEqual(len([c for c in self.calls() if "work" in c]), 1)

    def test_windows_missing_without_cache_is_a_read_failure(self):
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-windows-missing.json", debug=FORBIDDEN_LOG),
               "CLAUDE_USAGE_READ_WORK": self.fake_work()}
        code, out, err = self.run_main(["--report", str(self.dir / "cfg")], env)
        self.assertEqual(code, cur.EXIT_READ_FAILED)
        self.assertEqual(out, "")
        self.assertRegex(err, r"login lacks usage scope or was revoked \(HTTP 403\).*; no usable cached reading: "
                              r"no .claude.json")
        self.assertFalse(any("work" in c for c in self.calls()))

    def test_json_marks_stale(self):
        cfg = self.dir / "cfg"
        fetched = datetime.now(timezone.utc).replace(microsecond=0) - cur.timedelta(minutes=5)
        write_claude_json(cfg / ".claude.json", fetched_at=fetched,
                          resets_at=(datetime.now(timezone.utc) + cur.timedelta(days=1)).isoformat())
        env = {"CLAUDE_USAGE_READ_CLAUDE": self.fake_claude("usage-windows-missing.json", debug=RATE_LIMITED_LOG)}
        code, out, _ = self.run_main(["--json", str(cfg)], env)
        self.assertEqual(code, cur.EXIT_STALE)
        data = json.loads(out)
        self.assertTrue(data["stale"])
        self.assertIn("HTTP 429", data["reason"])
        self.assertEqual(data["observed_at"], cur._iso(fetched))

    def test_pool_without_report_is_usage_error(self):
        for argv in (["--pool", "x"], ["--account", "main"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                cur.main(argv)
            self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
