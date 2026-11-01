import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import codex_quota_guard as guard

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
FUTURE = int((NOW + timedelta(days=3)).timestamp())
PAST = int((NOW - timedelta(hours=1)).timestamp())


def event(used, resets=FUTURE, minutes=10080, stamp="2026-11-01T11:00:00Z", key="primary", nested=True):
    limits = {key: {"used_percent": used, "window_minutes": minutes, "resets_at": resets},
              "credits": {"balance": "123.4"}}
    body = {"rate_limits": limits}
    return {"timestamp": stamp, "type": "event_msg", "payload": body} if nested else {"timestamp": stamp, **body}


class QuotaGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "sessions" / "2026" / "11" / "01").mkdir(parents=True)
        self.counter = 0

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *lines, mtime=None):
        self.counter += 1
        path = self.home / "sessions" / "2026" / "11" / "01" / f"rollout-{self.counter:03}.jsonl"
        path.write_text("".join((l if isinstance(l, str) else json.dumps(l)) + "\n" for l in lines))
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def check(self, env=None):
        return guard.check(home=self.home, now=NOW, env=env or {})

    def test_blocks_when_weekly_window_is_full_and_not_reset(self):
        self.write(event(100))
        status = self.check()
        self.assertTrue(status.blocked)
        self.assertIn("weekly limit is at 100%", status.message)
        self.assertIn(guard.ALLOW_ENV, status.message)
        self.assertNotIn("123.4", status.message)

    def test_allows_below_limit(self):
        self.write(event(99.5))
        self.assertFalse(self.check().blocked)

    def test_allows_when_full_window_has_already_reset(self):
        self.write(event(100, resets=PAST))
        self.assertFalse(self.check().blocked)

    def test_allows_without_any_reading(self):
        status = self.check()
        self.assertFalse(status.blocked)
        self.assertIn("not checked", status.message)

    def test_override_env_allows_and_says_so(self):
        self.write(event(100))
        status = self.check({guard.ALLOW_ENV: "1"})
        self.assertFalse(status.blocked)
        self.assertIn("Allowed by", status.message)

    def test_override_needs_exact_value(self):
        self.write(event(100))
        self.assertTrue(self.check({guard.ALLOW_ENV: "yes"}).blocked)

    def test_configurable_threshold(self):
        self.write(event(96))
        self.assertTrue(self.check({guard.MAX_PERCENT_ENV: "95"}).blocked)
        self.assertFalse(self.check({guard.MAX_PERCENT_ENV: "97"}).blocked)

    def test_invalid_threshold_is_an_error(self):
        self.write(event(50))
        for bad in ("abc", "0", "101"):
            with self.assertRaises(ValueError):
                self.check({guard.MAX_PERCENT_ENV: bad})

    def test_secondary_window_counts(self):
        self.write(event(100, minutes=300, key="secondary"))
        status = self.check()
        self.assertTrue(status.blocked)
        self.assertIn("5-hour", status.message)

    def test_last_event_in_a_file_wins(self):
        self.write(event(100, stamp="2026-11-01T10:00:00Z"), event(20, stamp="2026-11-01T11:00:00Z"))
        self.assertFalse(self.check().blocked)

    def test_freshest_reading_across_files_wins(self):
        self.write(event(10, stamp="2026-11-01T09:00:00Z"), mtime=2_000_000_000)
        self.write(event(100, stamp="2026-11-01T11:00:00Z"), mtime=1_900_000_000)
        self.assertTrue(self.check().blocked)

    def test_newest_file_without_reading_falls_back_to_older_file(self):
        self.write(event(100), mtime=1_900_000_000)
        self.write({"timestamp": "2026-11-01T11:30:00Z", "type": "session_meta"}, mtime=2_000_000_000)
        self.assertTrue(self.check().blocked)

    def test_top_level_rate_limits_and_garbage_lines(self):
        self.write("not json rate_limits", json.dumps([1, "rate_limits"]),
                   {"timestamp": "no-time", "rate_limits": {}}, event(100, nested=False))
        self.assertTrue(self.check().blocked)

    def test_invalid_windows_are_ignored(self):
        self.write(event(True), event(150), event(100, minutes=0), event("100"))
        self.assertFalse(self.check().blocked)

    def test_cli_exit_codes(self):
        self.write(event(100))
        env = {"CODEX_HOME": str(self.home)}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(guard, "datetime", wraps=datetime) as dt:
            dt.now.return_value = NOW
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(guard.main([]), guard.EXIT_BLOCKED)
            self.assertIn("paid credits", err.getvalue())
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(guard.main(["--json"]), guard.EXIT_BLOCKED)
            self.assertTrue(json.loads(out.getvalue())["blocked"])
        with mock.patch.dict(os.environ, {**env, guard.MAX_PERCENT_ENV: "x"}, clear=True), redirect_stderr(io.StringIO()):
            self.assertEqual(guard.main([]), guard.EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
