import io
import json
import os
import stat
import sys
import tempfile
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

    def test_report_args(self):
        weekly = cur.Window("week (all models)", 3.0, datetime(2026, 11, 12, 18, 59, tzinfo=timezone.utc))
        self.assertEqual(cur.report_args(weekly, "claude-katharina"), [
            "usage", "report", "--provider", "claude", "--pool", "claude-katharina",
            "--window", "Weekly · all models", "--used", "3", "--resets-at", "2026-11-12T18:59:00Z",
            "--observed-at", "now", "--source", "claude-usage-read"])
        self.assertNotIn("--pool", cur.report_args(weekly, None))


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

    def fake_claude(self, fixture_name, exit_code=0):
        return self.fake("claude", (
            "import json, os, sys\n"
            f"open({str(self.log)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], "
            "'config': os.environ.get('CLAUDE_CONFIG_DIR'), 'cwd': os.getcwd()}) + '\\n')\n"
            f"sys.stdout.write(open({str(FIXTURES / fixture_name)!r}, encoding='utf-8').read())\n"
            f"sys.exit({exit_code})\n"))

    def fake_work(self, exit_code=0):
        return self.fake("work", (
            "import json, sys\n"
            f"open({str(self.log)!r}, 'a').write(json.dumps({{'work': sys.argv[1:]}}) + '\\n')\n"
            f"sys.exit({exit_code})\n"))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def run_main(self, argv, env):
        out, err = io.StringIO(), io.StringIO()
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
        self.assertEqual(call["argv"], ["-p", "/usage", "--output-format", "json", "--no-session-persistence"])
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
        work = [c["work"] for c in self.calls() if "work" in c]
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0][:6], ["usage", "report", "--provider", "claude", "--pool", "claude-katharina"])
        self.assertIn("claude-usage-read", work[0])

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

    def test_pool_without_report_is_usage_error(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            cur.main(["--pool", "x"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
