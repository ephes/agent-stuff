"""obs-triage: hermetic tests with stub ssh, work and claude programs."""

from __future__ import annotations

import json
import os
import shlex
import stat
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import obs_triage as ot

TODAY = datetime.now().strftime("%Y-%m-%d")


def script(path: Path, body: str) -> str:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


class Stubs:
    """Stub programs in a temporary directory, wired through the OBS_TRIAGE_* variables."""

    def __init__(self, root: Path, *, pack_date: str = TODAY, answer: dict | None = None) -> None:
        self.root = root
        (root / "pack.json").write_text(json.dumps({"date": pack_date, "logs": {}, "metrics": {}}))
        (root / "items.json").write_text(
            json.dumps(
                {
                    "items": [
                        {"slug": "old-thing", "stage": "idea", "title": "Alt", "summary": "s", "updated_at": "2020-01-01T00:00:00Z"},
                        {"slug": "done-long-ago", "stage": "accepted", "title": "x", "updated_at": "2020-01-01T00:00:00Z"},
                    ],
                    "truncated": False,
                    "count": 2,
                    "next_cursor": None,
                }
            )
        )
        (root / "answer.json").write_text(json.dumps(answer or {"findings": [], "known": [], "note": "quiet"}))
        (root / "query-out.json").write_text(json.dumps({"results": [{"id": 1, "lines": ["10:00:00Z web/app info hello"]}]}))
        self.env = {
            "OBS_TRIAGE_STATE": str(root / "state"),
            "OBS_TRIAGE_SSH_BIN": script(
                root / "ssh",
                f'echo "$@" >> {root}/ssh.log\n'
                'case "${@: -1}" in\n'
                f"  *' pack') cat {root}/pack.json ;;\n"
                f"  *' deliver') cat > {root}/delivered.json; cat {root}/delivered.json >> {root}/all-delivered.jsonl;"
                f" echo >> {root}/all-delivered.jsonl; [ \"${{QUEUED:-1}}\" = 1 ] && echo 'obs-ctl: delivered';"
                " exit ${DELIVER_EXIT:-0} ;;\n"
                f"  *' launchd') cat > {root}/launchd.json ;;\n"
                f"  *' query') cat > {root}/query-in.json; cat {root}/query-in.json >> {root}/all-queries.jsonl;"
                f" echo >> {root}/all-queries.jsonl; cat {root}/query-out.json; exit ${{QUERY_EXIT:-0}} ;;\n"
                "esac\n",
            ),
            "OBS_TRIAGE_WORK_BIN": script(
                root / "work",
                f'case "$1" in\n'
                f'  items) cat {root}/items.json ;;\n'
                f'  show) grep -qx "$2" {root}/created.log 2>/dev/null && exit 0; echo "work: HTTP 404: not found" >&2; exit 1 ;;\n'
                f'  upsert) printf "%s\\n" "$@" >> {root}/upserts.log; [ -n "$UPSERT_FAIL" ] && exit 1; echo "$2" >> {root}/created.log ;;\n'
                f"esac\n",
            ),
            # Prints what ``claude -p --output-format json --json-schema`` prints: one result event
            # whose ``structured_output`` is the answer (``model.txt`` overrides the reported model).
            "OBS_TRIAGE_CLAUDE_BIN": script(
                root / "claude",
                f'printf "%s\\n" "$@" > {root}/claude-args.log\nenv > {root}/claude-env.log; pwd > {root}/claude-cwd.log\n'
                f'cat > {root}/prompt.txt\n'
                f'n=$(( $(cat {root}/rounds 2>/dev/null || echo 0) + 1 )); echo $n > {root}/rounds\n'
                f'cp {root}/prompt.txt {root}/prompt-$n.txt\n'
                f'a={root}/answer.json; [ -f {root}/answer-$n.json ] && a={root}/answer-$n.json\n'
                f'm=$(cat {root}/model.txt 2>/dev/null || echo {ot.MODEL})\n'
                'printf \'{"type":"result","subtype":"success","is_error":false,"modelUsage":{"%s":{}},"structured_output":%s}\' "$m" "$(cat "$a")"\n',
            ),
        }

    def delivered(self) -> dict:
        return dict(json.loads((self.root / "delivered.json").read_text()))


def finding(slug: str, **extra: str) -> dict[str, str]:
    return {
        "slug": slug,
        "title": "fractal: vault-Messwerte fehlen",
        "summary": "Seit zehn Stunden kommen keine Werte.",
        "evidence": "metrics.silent fractal {mountpoint=/vault} 10 h",
        "severity": "medium",
        "project": "graphyard",
        "next_action": "Collector prüfen",
        **extra,
    }


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        patcher = mock.patch.object(ot, "launchd_jobs", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_with(self, stubs: Stubs, *args: str, deliver_exit: int = 0, queued: bool = True) -> int:
        env = {**stubs.env, "DELIVER_EXIT": str(deliver_exit), "QUEUED": "1" if queued else "0",
               # Never handed on: they would replace the claude-katharina login.
               "ANTHROPIC_API_KEY": "sk-test", "CLAUDE_CODE_OAUTH_TOKEN": "test"}  # fmt: skip
        with mock.patch.dict(os.environ, env):
            return ot.main(["run", *args])

    def test_a_quiet_day_sends_nothing_but_records_the_triage(self) -> None:
        stubs = Stubs(self.root)

        self.assertEqual(self.run_with(stubs), 0)

        result = stubs.delivered()
        self.assertEqual((result["status"], result["message"], result["new_items"]), ("ok", "", []))
        args = (self.root / "claude-args.log").read_text().split("\n")
        self.assertEqual(args[:5], ["-p", "--model", "claude-opus-5-5", "--effort", "medium"])
        for flag in ("--restricted", "--safe-mode", "--disable-slash-commands", "--strict-mcp-config",
                     "--no-session-persistence"):  # fmt: skip
            self.assertIn(flag, args)
        for flag, value in (("--tools", ""), ("--setting-sources", ""), ("--output-format", "json"),
                            ("--permission-mode", "dontAsk"), ("--mcp-config", '{"mcpServers":{}}')):  # fmt: skip
            self.assertEqual(args[args.index(flag) + 1], value, flag)
        self.assertEqual(json.loads(args[args.index("--json-schema") + 1]), json.loads(ot.SCHEMA.read_text()))
        for absent in ("--fallback-model", "--dangerously-skip-permissions", "--allowedTools", "--add-dir"):
            self.assertNotIn(absent, args)
        environment = dict(line.split("=", 1) for line in (self.root / "claude-env.log").read_text().splitlines()
                           if "=" in line)  # fmt: skip
        self.assertEqual(environment["CLAUDE_CONFIG_DIR"], str(Path.home() / ".claude-katharina"))
        self.assertNotIn("ANTHROPIC_API_KEY", environment)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", environment)
        cwd = Path((self.root / "claude-cwd.log").read_text().strip()).resolve()
        self.assertEqual(cwd.parent, (self.root / "state/work").resolve())
        self.assertEqual(environment["CLAUDE_CODE_TMPDIR"], str(cwd))
        self.assertFalse(cwd.exists())  # the fresh work directory is gone after the round
        prompt = (self.root / "prompt.txt").read_text()
        self.assertIn("Daily observability review", prompt)
        self.assertIn('"old-thing"', prompt)
        self.assertNotIn("done-long-ago", prompt)
        self.assertTrue(list((self.root / "state/runs").glob(f"{TODAY}-*.json")))

    def test_new_findings_become_items_and_one_digest(self) -> None:
        answer = {
            "findings": [finding("fractal-vault-silent"), finding("old-thing"), finding("Bad Slug"),
                         finding("leaky-one", summary="Kontakt bob@example.org")],
            "known": [{"slug": "old-thing", "observation": "same"}],
            "note": "",
        }
        stubs = Stubs(self.root, answer=answer)

        self.assertEqual(self.run_with(stubs), 0)

        upserts = (self.root / "upserts.log").read_text().split("\n")
        self.assertEqual(upserts[:2], ["upsert", f"obs-{TODAY}-1"])
        for flag, value in (("--stage", "idea"), ("--project", "graphyard"), ("--campaign", "obs-triage")):
            self.assertEqual(upserts[upserts.index(flag) + 1], value)
        self.assertEqual(upserts.count("upsert"), 2)
        self.assertIn("Kontakt <mail>", upserts)  # masked, not dropped
        result = stubs.delivered()
        self.assertEqual([i["slug"] for i in result["new_items"]], [f"obs-{TODAY}-1", f"obs-{TODAY}-2"])
        self.assertIn("2 neue Auffälligkeiten", result["message"])
        self.assertIn(f"• obs-{TODAY}-1 [medium]", result["message"])
        self.assertEqual(result["detail"], "2 new, 1 known, 2 dropped, 0 ledger writes failed or undecided")

        # A rerun the same day neither creates nor announces them again.
        self.assertEqual(self.run_with(stubs), 0)
        self.assertEqual((self.root / "upserts.log").read_text().split("\n").count("upsert"), 2)
        self.assertEqual(stubs.delivered()["new_items"], [])

    def test_dry_run_creates_and_delivers_nothing(self) -> None:
        stubs = Stubs(self.root, answer={"findings": [finding("brand-new-thing")], "known": [], "note": ""})

        self.assertEqual(self.run_with(stubs, "--dry-run"), 0)

        self.assertFalse((self.root / "upserts.log").exists())
        self.assertFalse((self.root / "delivered.json").exists())

    def test_a_used_up_limit_skips_without_any_other_model(self) -> None:
        stubs = Stubs(self.root)
        script(self.root / "claude", f"cat >/dev/null; echo x >> {self.root}/rounds\n"
               "echo '{\"type\":\"result\",\"is_error\":true,\"api_error_status\":429,\"result\":\"limit\"}'; exit 1\n")

        self.assertEqual(self.run_with(stubs), 0)

        result = stubs.delivered()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["detail"], "Claude-Kontingent ist aufgebraucht (HTTP 429)")
        self.assertIn("übersprungen", result["message"])
        self.assertEqual((self.root / "rounds").read_text().split(), ["x"])  # one call, no retry elsewhere

    def test_another_api_error_is_a_skip_with_its_status(self) -> None:
        stubs = Stubs(self.root)
        script(self.root / "claude", "cat >/dev/null\n"
               "echo '{\"type\":\"result\",\"is_error\":true,\"api_error_status\":529,\"result\":\"overloaded hunter2\"}'; exit 1\n")
        self.assertEqual(self.run_with(stubs), 0)
        self.assertEqual(stubs.delivered()["detail"], "Claude meldete einen API-Fehler (HTTP 529)")
        self.assertNotIn("hunter2", stubs.delivered()["message"])

    def test_an_answer_from_another_model_is_a_skip(self) -> None:
        for model in ("claude-sonnet-5-5", f"{ot.MODEL}\":{{}},\"claude-haiku-5-5"):
            with self.subTest(model=model):
                (self.root / "model.txt").write_text(model)
                stubs = Stubs(self.root, answer={"findings": [finding("brand-new-thing")], "known": [], "note": ""})
                self.assertEqual(self.run_with(stubs), 0)
                self.assertEqual(stubs.delivered()["detail"], "Claude antwortete nicht mit dem verlangten Modell")
                self.assertFalse((self.root / "upserts.log").exists())

    def test_a_stale_pack_fails_the_day_with_a_message(self) -> None:
        stubs = Stubs(self.root, pack_date="2020-01-01")

        self.assertEqual(self.run_with(stubs), 0)

        result = stubs.delivered()
        self.assertEqual(result["status"], "failed")
        self.assertIn("2020-01-01", result["detail"])

    def test_a_failed_delivery_exits_1_and_is_kept(self) -> None:
        self.assertEqual(self.run_with(Stubs(self.root), deliver_exit=1, queued=False), 1)
        self.assertTrue((self.root / "state/undelivered.json").exists())

    def test_an_unconfirmed_result_is_kept_and_sent_first_next_time(self) -> None:
        stubs = Stubs(self.root)
        self.assertEqual(self.run_with(stubs, deliver_exit=3, queued=False), 1)
        self.assertTrue((self.root / "state/undelivered.json").exists())

        self.assertEqual(self.run_with(stubs, deliver_exit=3, queued=False), 1)
        self.assertEqual(len(json.loads((self.root / "state/undelivered.json").read_text())), 2)

        self.assertEqual(self.run_with(stubs), 0)

        lines = [l for l in (self.root / "all-delivered.jsonl").read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1 + 2 + 3)
        self.assertFalse((self.root / "state/undelivered.json").exists())

    def test_a_failed_ledger_write_is_reported_with_its_title(self) -> None:
        stubs = Stubs(self.root, answer={"findings": [finding("one-thing")], "known": [], "note": ""})
        with mock.patch.dict(os.environ, {"UPSERT_FAIL": "1"}):
            self.assertEqual(self.run_with(stubs), 0)
        self.assertEqual(stubs.delivered()["status"], "failed")
        self.assertIn(f"nicht (sicher) angelegt: obs-{TODAY}-1 [medium]", stubs.delivered()["message"])
        self.assertNotIn("vault-Messwerte", stubs.delivered()["message"])  # no model text in Telegram

    def test_a_used_up_budget_is_a_skip(self) -> None:
        stubs = Stubs(self.root)
        with mock.patch.object(ot, "TRIAGE_BUDGET", 30):
            self.assertEqual(self.run_with(stubs), 0)
        self.assertEqual(stubs.delivered()["status"], "skipped")
        self.assertFalse((self.root / "rounds").exists())

    def test_a_missing_claude_binary_is_a_skip(self) -> None:
        stubs = Stubs(self.root)
        stubs.env["OBS_TRIAGE_CLAUDE_BIN"] = str(self.root / "no-such-claude")
        self.assertEqual(self.run_with(stubs), 0)
        self.assertEqual(stubs.delivered()["status"], "skipped")
        self.assertEqual(stubs.delivered()["detail"], "Claude startete nicht (FileNotFoundError)")

    def test_an_incomplete_ledger_list_fails_closed(self) -> None:
        stubs = Stubs(self.root)
        data = json.loads((self.root / "items.json").read_text())
        data["next_cursor"] = "abc"
        (self.root / "items.json").write_text(json.dumps(data))
        self.assertEqual(self.run_with(stubs), 0)
        self.assertEqual(stubs.delivered()["status"], "failed")
        self.assertFalse((self.root / "claude-args.log").exists())

    def test_claude_failure_is_a_skip(self) -> None:
        stubs = Stubs(self.root)
        script(self.root / "claude", "cat >/dev/null; echo boom >&2; exit 4\n")

        self.assertEqual(self.run_with(stubs), 0)

        self.assertEqual(stubs.delivered()["status"], "skipped")
        self.assertEqual(stubs.delivered()["detail"], "Claude endete mit exit 4")
        self.assertNotIn("boom", stubs.delivered()["message"])

    def test_a_round_over_its_time_is_a_skip_and_its_process_group_is_killed(self) -> None:
        stubs = Stubs(self.root)
        script(self.root / "claude", f"cat >/dev/null; sleep 30 & echo $! > {self.root}/child.pid; wait\n")
        started = time.monotonic()
        with mock.patch.dict(os.environ, stubs.env), mock.patch.object(ot, "MIN_ROUND", 0), \
                self.assertRaises(ot.Skipped) as raised:  # fmt: skip
            ot.run_model("x", timeout=1)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(str(raised.exception), "Claude brauchte für eine Runde länger als 0 Minuten")
        child = int((self.root / "child.pid").read_text())
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)


    def query(self, text: str, **extra: object) -> dict[str, object]:
        return {"kind": "loki", "query": text, "start": "-2h", "end": "", "limit": 0, "step": 0, "why": "look", **extra}

    def test_queries_run_on_macmini_and_their_results_reach_the_next_round(self) -> None:
        stubs = Stubs(self.root)
        first = {"notes": "rustfs looks odd", "queries": [self.query('{host="fractal"}')], "findings": [finding("ignored")],
                 "known": [], "note": ""}  # fmt: skip
        (self.root / "answer-1.json").write_text(json.dumps(first))
        (self.root / "answer-2.json").write_text(
            json.dumps({"notes": "", "queries": [], "findings": [finding("vault-silent")], "known": [], "note": "ok"})
        )

        self.assertEqual(self.run_with(stubs), 0)

        sent = json.loads((self.root / "query-in.json").read_text())
        self.assertEqual(sent, {"queries": [{"kind": "loki", "query": '{host="fractal"}', "start": "-2h", "end": "",
                                             "limit": 200}]})  # fmt: skip
        second = (self.root / "prompt-2.txt").read_text()
        self.assertIn("rustfs looks odd", second)
        self.assertIn("web/app info hello", second)
        self.assertTrue(second.startswith((self.root / "prompt-1.txt").read_text().split("## Your investigation")[0]))
        self.assertEqual([i["slug"] for i in stubs.delivered()["new_items"]], [f"obs-{TODAY}-1"])
        report = json.loads(next((self.root / "state/runs").glob("*.json")).read_text())
        self.assertEqual([r["queries"] for r in report["rounds"]], [1, 0])

    def test_the_last_round_must_answer(self) -> None:
        stubs = Stubs(self.root)
        always = {"notes": "more", "queries": [self.query("{}")], "findings": [finding("late-one")], "known": [],
                  "note": ""}  # fmt: skip
        (self.root / "answer.json").write_text(json.dumps(always))

        with mock.patch.object(ot, "MAX_ROUNDS", 3):
            self.assertEqual(self.run_with(stubs), 0)

        self.assertEqual((self.root / "rounds").read_text().strip(), "3")
        self.assertIn("Round 3 of 3: the last one", (self.root / "prompt-3.txt").read_text())
        self.assertEqual(len([l for l in (self.root / "all-queries.jsonl").read_text().splitlines() if l]), 2)
        self.assertEqual([i["slug"] for i in stubs.delivered()["new_items"]], [f"obs-{TODAY}-1"])
        self.assertEqual(stubs.delivered()["status"], "failed")
        self.assertIn("Untersuchung nicht abgeschlossen", stubs.delivered()["message"])

    def test_a_round_is_final_when_the_budget_runs_low(self) -> None:
        stubs = Stubs(self.root)
        (self.root / "answer.json").write_text(
            json.dumps({"notes": "", "queries": [self.query("{}")], "findings": [], "known": [], "note": ""})
        )
        with mock.patch.object(ot, "TRIAGE_BUDGET", ot.FINAL_RESERVE - 1):
            self.assertEqual(self.run_with(stubs), 0)
        self.assertEqual((self.root / "rounds").read_text().strip(), "1")
        self.assertFalse((self.root / "all-queries.jsonl").exists())

    def test_failed_queries_come_back_as_errors_and_the_review_goes_on(self) -> None:
        stubs = Stubs(self.root)
        first = {"notes": "n", "queries": [self.query("{}"), self.query("{a}")], "findings": [], "known": [], "note": ""}
        (self.root / "answer-1.json").write_text(json.dumps(first))
        with mock.patch.dict(os.environ, {"QUERY_EXIT": "2"}):
            self.assertEqual(self.run_with(stubs), 0)
        second = (self.root / "prompt-2.txt").read_text()
        self.assertEqual(second.count("queries did not run (exit 2"), 2)

    def test_a_lone_surrogate_in_a_query_does_not_end_the_review(self) -> None:
        stubs = Stubs(self.root)
        first = {"notes": "n\udc80", "queries": [self.query("{x=\"\udc80\"}")], "findings": [], "known": [], "note": ""}
        (self.root / "answer-1.json").write_text(json.dumps(first))
        self.assertEqual(self.run_with(stubs), 0)
        self.assertEqual((self.root / "rounds").read_text().strip(), "2")

    def test_old_results_give_way_when_they_grow_too_large(self) -> None:
        stubs = Stubs(self.root)
        (self.root / "query-out.json").write_text(json.dumps({"results": [{"id": 1, "lines": ["x" * 4000]}]}))
        (self.root / "answer.json").write_text(
            json.dumps({"notes": "keep me", "queries": [self.query("{}")], "findings": [], "known": [], "note": ""})
        )
        with mock.patch.object(ot, "MAX_DRILL_BYTES", 6000), mock.patch.object(ot, "MAX_ROUNDS", 4):
            self.assertEqual(self.run_with(stubs), 0)
        last = (self.root / "prompt-4.txt").read_text()
        self.assertEqual(last.count("dropped for space"), 2)
        self.assertEqual(last.count("keep me"), 3)


class UnitTests(unittest.TestCase):
    def test_a_text_naming_a_credential_is_withheld_whole(self) -> None:
        for text in (
            "app logged password=hunter2secret",
            'token "synthetic value"',
            "Authorization: ApiKey\r\n\tsample-secret",
            "failed\x00Authorization: Bearer abc",
            "pass word: x",
            "PASS\u200bWORD=x",
            "pass\x9bword=x",
            'Cookie: a=1; sid=x',
            "ＰＡＳＳＷＯＲＤ=x",  # full-width: not in the allowed characters
            "password=" + "ab12cd34ef56gh78ij90kl12mn34 quiet phrase",
            "Basic dXNlcjpwYXNz",
            "key=abc",
            "auth=hunter2 accepted",
            "session abc123 reused",
            "x\x00auth=hunter2",
            "x\x00au\x00th=demo42",
            "harmless\x00text",
            "au\u200bth=demo42",
            "au\u0301th=demo42",
            "au\u3164th=demo42",
            "au\u1160th=demo42",
            "аuth=demo42",  # Cyrillic a
            "auth²=demo42",
            "se²cret=demo42",
            "auéth=demo42",
            "redis-password@prod.example=demo42",
            "ＰＡＳＳ=x",
            "Paßwort=x",
            "außth=demo42",
            "seßcret=demo42",
            "paßßword=x",
            "auäth=demo42",
        ):
            answer = {"findings": [finding("cred-one", evidence=text, title=text)]}
            accepted, _dropped = ot.valid_findings(answer, set(), "studio:/r.json")
            report = "studio:/x/runs/r.json"
            accepted, _dropped = ot.valid_findings(answer, set(), report)
            self.assertEqual(accepted[0]["title"], "Befund-Text zurückgehalten (runs/r.json)", text)
            self.assertEqual(accepted[0]["evidence"], f"zurückgehalten, siehe Lauf-Bericht {report}", text)

    def test_markers_carry_a_fingerprint_and_nothing_else(self) -> None:
        evidence = "heis ssh.service 03:12Z: [secret:password hun…(12)] in a debug line"
        accepted, _dropped = ot.valid_findings({"findings": [finding("marker-one", evidence=evidence)]}, set())
        self.assertEqual(accepted[0]["evidence"], evidence)
        for loose in (
            "[secret:password hunter2] leaked",
            "[secret:password quiet phrase …(12)]",
            "[secret:password demo…(4)]",
            "[secret:mystery hunt…(12)]",
        ):
            accepted, _dropped = ot.valid_findings({"findings": [finding("marker-two", evidence=loose)]}, set())
            self.assertTrue(accepted[0]["evidence"].startswith("zurückgehalten"), loose)

    def test_german_text_passes(self) -> None:
        text = "fractal: Plattenfüllstand „/vault“ steigt – Prüfung nötig (≥ 92 %, 3× täglich, Grösse) …"
        accepted, _dropped = ot.valid_findings({"findings": [finding("de-one", title=text[:120])]}, set())
        self.assertEqual(accepted[0]["title"], text[:120])

    def test_token_like_runs_withhold_and_mail_is_masked(self) -> None:
        for text in (
            "Wert ab12cd34ef56gh78ij90kl12",
            "https://x.example/invite/Ab12Cd34Ef56Gh78Ij90",
            "key Ab12Cd34/Ef56Gh78Ij90Kl12Mn34Op56Q=",
            "https://x.example/r/6f4f3103-81fb-4854-af98-d8a23209491f.Ab12Cd34Ef56Gh78Ij90Kl12Mn34",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc",
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b",
            "Ab12Cd34Ef56/Gh78Ij90KlM",
            "glpat-Ab12Cd34Ef-56Gh78Ij90",
            "opaqueValueWithOneDigit7xyzw",
            "ab12--cd34--ef56--gh78--ij90",
        ):
            accepted, _dropped = ot.valid_findings({"findings": [finding("tok-one", evidence=text)]}, set())
            self.assertTrue(accepted[0]["evidence"].startswith("zurückgehalten"), text)
        for text in (
            "/var/lib/obs-daily/packs/2026-11-19.json",
            "unit traefik-tx-6f4f3103-81fb-4854-af98-d8a23209491f",
            "rustfs-replication-errors-v2-2026 at 2026-11-19T03:12:00Z",
            "Router 2001:db8::10 und 192.0.2.4",
            "Datenbankverbindungsfehler auf staging",
            "traefik-tx-6f4f3103-81fb-4854-af98-d8a23209491f.service failed",
        ):
            accepted, _dropped = ot.valid_findings({"findings": [finding("tok-two", evidence=text)]}, set())
            self.assertEqual(accepted[0]["evidence"], text)
        accepted, _dropped = ot.valid_findings(
            {"findings": [finding("mail-one", summary="Kontakt ab12cd34ef56gh78ij90kl12mn@example.org x\ny")]}, set()
        )
        self.assertEqual(accepted[0]["summary"], "Kontakt <mail> x y")

    def test_secret_shaped_slugs_and_projects_are_dropped(self) -> None:
        answer = {"findings": [finding("ab12cd34ef56gh78ij90kl12mn34"), finding("ok-slug", project="ab12cd34ef56gh78ij90kl12mn"),
                               finding("leaked-password-hunter2")]}  # fmt: skip
        accepted, dropped = ot.valid_findings(answer, set())
        self.assertEqual(accepted, [])
        self.assertEqual(len(dropped), 3)

    def test_valid_findings_rules(self) -> None:
        answer = {"findings": [finding("thing-1"), finding("x" * 60), finding("ok-one", title=""), finding("nl\n")]}

        accepted, dropped = ot.valid_findings(answer, set())

        self.assertEqual([f["slug"] for f in accepted], ["obs-thing-1"])
        self.assertEqual(len(dropped), 3)

    def test_known_items_keep_open_and_recent(self) -> None:
        now = time.time()
        recent = datetime.fromtimestamp(now - 86400).isoformat()
        items = [
            {"slug": "a", "stage": "idea", "updated_at": "2020-01-01T00:00:00Z"},
            {"slug": "b", "stage": "merged", "updated_at": recent},
            {"slug": "c", "stage": "merged", "updated_at": "2020-01-01T00:00:00Z"},
            {"slug": "d", "stage": "dropped", "updated_at": recent},
        ]

        # Recently dropped items count as known too; old closed ones do not.
        self.assertEqual([i["slug"] for i in ot.known_items(items, now)], ["a", "b", "d"])

    def test_launchd_loops_need_runs_and_a_failing_exit(self) -> None:
        jobs = [
            {"label": "loop", "runs": 120, "last_exit": "1", "state": "spawn scheduled"},
            {"label": "busy-but-fine", "runs": 120, "last_exit": "0", "state": "running"},
            {"label": "one-failure", "runs": 101, "last_exit": "1", "state": "not running"},
            {"label": "new", "runs": 500, "last_exit": "1", "state": "x"},
        ]
        previous = {"loop": 100, "busy-but-fine": 100, "one-failure": 100}

        self.assertEqual([j["label"] for j in ot.launchd_changes(jobs, previous)], ["loop"])

    def test_launchd_jobs_skip_unloaded_plists_and_count_failed_prints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            agents = home / "Library/LaunchAgents"
            agents.mkdir(parents=True)
            daemons = home / "LaunchDaemons"
            daemons.mkdir()
            (daemons / "de.wersdoerfer.daemon-off.plist").write_text("")
            for label in ("de.wersdoerfer.ok", "de.wersdoerfer.unloaded", "de.wersdoerfer.broken", "com.other.x"):
                (agents / f"{label}.plist").write_text("")
            launchctl = home / "launchctl"
            calls = home / "calls"
            script(
                launchctl,
                f'echo "$2" >> {shlex.quote(str(calls))}\n'
                'case "$2" in\n'
                '  */de.wersdoerfer.ok) printf "\\tstate = running\\n\\truns = 4\\n\\tlast exit code = 0\\n";;\n'
                '  */de.wersdoerfer.unloaded) echo "Could not find service" >&2; exit 113;;\n'
                '  */de.wersdoerfer.broken) exit 5;;\n'
                '  *) exit 113;;\n'
                "esac\n",
            )
            errors: list[str] = []
            with (
                mock.patch.dict(os.environ, {"OBS_TRIAGE_LAUNCHCTL": str(launchctl)}),
                mock.patch.object(ot.Path, "home", return_value=home),
                mock.patch.object(ot, "SYSTEM_DAEMONS", daemons),
            ):
                jobs = ot.launchd_jobs(errors)
            self.assertEqual(jobs, [{"label": "de.wersdoerfer.ok", "state": "running", "runs": 4, "last_exit": "0"}])
            self.assertEqual(errors, ["de.wersdoerfer.broken"])
            # Foreign labels are never asked about; only the fixture plists are.
            uid = os.getuid()
            self.assertEqual(
                calls.read_text().split(),
                ["system/de.wersdoerfer.daemon-off"]
                + [f"gui/{uid}/de.wersdoerfer.{name}" for name in ("broken", "ok", "unloaded")],
            )

    def test_launchd_check_reports_to_macmini(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stubs = Stubs(root)
            jobs = [{"label": "de.x", "runs": 10, "last_exit": "1", "state": "spawn scheduled"}]
            with mock.patch.dict(os.environ, stubs.env), mock.patch.object(ot, "launchd_jobs", return_value=jobs):
                self.assertEqual(ot.main(["launchd-check"]), 0)
                jobs[0]["runs"] = 30
                self.assertEqual(ot.main(["launchd-check"]), 0)
            report = json.loads((root / "launchd.json").read_text())
            self.assertEqual(report["loops"][0]["label"], "de.x")
            self.assertEqual(report["loops"][0]["runs_since_last_sample"], 20)

    def test_weekly_writes_the_dated_brief_and_runs_on_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script(root / "run.sh", f'echo "$ACCOUNT $1" > {root}/ran\n')
            with mock.patch.dict(os.environ, {"OBS_TRIAGE_KATHARINA": str(root)}):
                self.assertEqual(ot.main(["weekly"]), 0)
            brief = (root / "obs-weekly.md").read_text()
            self.assertIn(f"seven days up to {TODAY}", brief)
            self.assertNotIn("__DATE__", brief)
            self.assertEqual((root / "ran").read_text().strip(), "main obs-weekly")




    def test_a_malformed_answer_is_a_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stubs = Stubs(root, answer={"findings": None, "known": [], "note": ""})
            with mock.patch.dict(os.environ, {**stubs.env, "DELIVER_EXIT": "0", "QUEUED": "1"}), mock.patch.object(
                ot, "launchd_jobs", return_value=[]
            ):
                self.assertEqual(ot.main(["run"]), 0)
            self.assertEqual(stubs.delivered()["status"], "skipped")

    def test_the_schema_is_strict(self) -> None:
        schema = json.loads(ot.SCHEMA.read_text())
        self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]))
        for name in ("findings", "known", "queries"):
            item = schema["properties"][name]["items"]
            self.assertFalse(item["additionalProperties"], name)
            self.assertEqual(sorted(item["required"]), sorted(item["properties"]), name)
        self.assertEqual(schema["properties"]["queries"]["maxItems"], ot.MAX_ROUND_QUERIES)


class OutboxTests(unittest.TestCase):
    def test_a_refused_result_does_not_hold_the_others_and_the_outbox_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stubs = Stubs(root)
            script(root / "ssh", f'cat > {root}/in.json; grep -q poison {root}/in.json && exit 1; echo "obs-ctl: delivered"\n')
            env = {**stubs.env, "OBS_TRIAGE_SSH_BIN": str(root / "ssh")}
            state = root / "state"
            with mock.patch.dict(os.environ, env):
                for n in range(ot.MAX_OUTBOX + 3):
                    ot.outbox_put({"id": f"i{n}", "date": "poison" if n == 0 else f"d{n}", "message": f"m{n}"})
                self.assertTrue(ot.deliver())
            self.assertFalse((state / "undelivered.json").exists())  # the poison one was given up as oldest

            with mock.patch.dict(os.environ, env):
                ot.outbox_put({"id": "p", "date": "poison", "message": ""})
                ot.outbox_put({"id": "f", "date": "f", "message": ""})
                self.assertFalse(ot.deliver())
            self.assertEqual(json.loads((state / "undelivered.json").read_text()), [{"id": "p", "date": "poison", "message": "", "format": 2}])

    def test_a_replaced_result_keeps_one_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"OBS_TRIAGE_STATE": tmp}):
                ot.outbox_put({"id": "a", "message": "planned"})
                ot.outbox_put({"id": "a", "message": "final"})
            self.assertEqual(json.loads((Path(tmp) / "undelivered.json").read_text()), [{"id": "a", "message": "final", "format": 2}])


class StateTests(unittest.TestCase):
    def test_state_is_owner_only_and_a_lone_surrogate_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            answer = {"findings": [finding("sur-one", title="a\udc80b")], "known": [], "note": "x\udc81"}
            stubs = Stubs(root, answer=answer)
            env = {**stubs.env, "QUEUED": "1", "DELIVER_EXIT": "0"}
            with mock.patch.dict(os.environ, env), mock.patch.object(ot, "launchd_jobs", return_value=[]):
                self.assertEqual(ot.main(["run"]), 0)
            report = next((root / "state/runs").glob("*.json"))
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / "state").stat().st_mode & 0o777, 0o700)
            self.assertIn("\\udc81", report.read_text())
            self.assertTrue(stubs.delivered()["new_items"][0]["title"].startswith("Befund-Text zurückgehalten"))


class LimitTests(unittest.TestCase):
    def test_findings_over_the_limit_are_announced(self) -> None:
        message = ot.digest("2026-11-19", [finding("obs-2026-11-19-1")], [], 2)
        self.assertTrue(message.endswith("⚠️ 2 weitere Befunde nicht angelegt (Tageslimit), nur im Lauf-Bericht"))
        earlier = message.rsplit("\n", 1)[0] + "\n⚠️ Tageslimit erreicht: 2 weitere Befunde nur im Lauf-Bericht"
        self.assertEqual(ot.digest_safe({"date": "d", "format": 2, "message": earlier})["message"], earlier)
        self.assertEqual(ot.digest_safe({"date": "d", "format": 2, "message": message})["message"], message)
        self.assertEqual(
            ot.digest_safe({"date": "d", "format": 2, "message": "• obs-2026-11-19-100 [low]"})["message"],
            "• obs-2026-11-19-100 [low]",
        )


class DigestTests(unittest.TestCase):
    def test_only_digest_lines_reach_telegram(self) -> None:
        good = {"date": "2026-11-19", "format": 2,
                "message": "🔎 Obs-Triage 19.11.2026: 1 neue Auffälligkeit\n• ‼️ obs-2026-11-19-1 [high]"}  # fmt: skip
        self.assertEqual(ot.digest_safe(good), good)
        legacy = {k: v for k, v in good.items() if k != "format"}  # item lines of another format
        self.assertIn("verworfen", ot.digest_safe(legacy)["message"])
        bad = {"date": "2026-11-19", "message": "🔎 Obs-Triage 19.11.2026: 1 neue Auffälligkeit\n• heis: Wert hunter2 [high]"}
        self.assertEqual(ot.digest_safe(bad)["message"], "⚠️ Obs-Triage 2026-11-19: Nachricht verworfen (nicht im Digest-Format)")
        for message in (ot.digest("2026-11-19", [finding("obs-2026-11-19-1")], [finding("obs-2026-11-19-2")]),
                        "⚠️ Obs-Triage 19.11.2026 übersprungen: Codex endete mit exit 4",
                        "⚠️ Obs-Triage 23.11.2026 übersprungen: Claude endete mit exit 1",
                        "⚠️ Obs-Triage 23.11.2026 übersprungen: Claude-Kontingent ist aufgebraucht (HTTP 429)",
                        "⚠️ Obs-Triage 23.11.2026 übersprungen: Claude meldete einen API-Fehler (HTTP 529)",
                        "⚠️ Obs-Triage 23.11.2026 übersprungen: Claude antwortete nicht mit dem verlangten Modell",
                        "⚠️ Obs-Triage 23.11.2026 übersprungen: Claude brauchte für eine Runde länger als 25 Minuten",
                        "⚠️ Obs-Triage 23.11.2026 übersprungen: Claude startete nicht (FileNotFoundError)",
                        "⚠️ Obs-Triage 19.11.2026 fehlgeschlagen (RuntimeError, siehe Log)",
                        "⚠️ Obs-Triage 19.11.2026 übersprungen: codex-quota-guard lief nicht (exit -15)"):  # fmt: skip
            self.assertEqual(ot.digest_safe({"date": "d", "format": 2, "message": message})["message"], message)
        for message in ("⚠️ Obs-Triage 19.11.2026 übersprungen: Kennwort Beispielwert 123",
                        "• obs-password-example [high]", "• obs-ab12--cd34--ef56--gh78--ij90 [high]",
                        "🔎 Obs-Triage 19.11.2026: 1 neue Auffälligkeit\x1c• obs-2026-11-19-1 [high]",
                        "• obs-heis-x [high]",
                        "• obs-agent12-check-backend [low]",
                        "🔎 Obs-Triage 19.11.2026: ٣ neue Auffälligkeiten"):  # fmt: skip
            self.assertIn("verworfen", ot.digest_safe({"date": "d", "format": 2, "message": message})["message"], message)

    def test_a_huge_field_is_checked_quickly(self) -> None:
        started = time.monotonic()
        ot.valid_findings({"findings": [finding("big-one", evidence="x" * 40000)]}, set())
        self.assertLess(time.monotonic() - started, 1)


class InterruptionTests(unittest.TestCase):
    def test_a_stop_after_the_ledger_write_keeps_quota_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stubs = Stubs(root, answer={"findings": [finding("one-thing"), finding("two-thing")], "known": [], "note": ""})
            calls = {"n": 0}

            def stop_after_first(finding_: dict[str, str], today: str) -> bool:
                calls["n"] += 1
                if calls["n"] == 2:
                    raise KeyboardInterrupt
                return True

            env = {**stubs.env, "QUEUED": "1", "DELIVER_EXIT": "0"}
            with mock.patch.dict(os.environ, env), mock.patch.object(ot, "launchd_jobs", return_value=[]), \
                    mock.patch.object(ot, "create_item", stop_after_first), self.assertRaises(KeyboardInterrupt):  # fmt: skip
                ot.main(["run"])
            outbox = json.loads((root / "state/undelivered.json").read_text())
            self.assertEqual(outbox[0]["status"], "failed")  # never claims what it did not confirm
            self.assertEqual(outbox[0]["message"].count("nicht (sicher) angelegt"), 2)
            day = json.loads((root / f"state/days/{TODAY}.json").read_text())
            self.assertEqual(day["attempted"], [f"obs-{TODAY}-1", f"obs-{TODAY}-2"])
            self.assertEqual(day["hints"], ["obs-one-thing", "obs-two-thing"])

    def test_slugs_skip_existing_items_and_old_day_files_still_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stubs = Stubs(root, answer={"findings": [finding("old-one"), finding("new-one")], "known": [], "note": ""})
            items = json.loads((root / "items.json").read_text())
            items["items"].append({"slug": f"obs-{TODAY}-2", "stage": "idea", "title": "t", "updated_at": "2020-01-01T00:00:00Z"})
            items["count"] = len(items["items"])
            (root / "items.json").write_text(json.dumps(items))
            (root / "state/days").mkdir(parents=True)
            (root / f"state/days/{TODAY}.json").write_text(json.dumps({"created": ["obs-old-one"]}))
            env = {**stubs.env, "QUEUED": "1", "DELIVER_EXIT": "0"}
            with mock.patch.dict(os.environ, env), mock.patch.object(ot, "launchd_jobs", return_value=[]):
                self.assertEqual(ot.main(["run"]), 0)
            self.assertEqual([i["slug"] for i in stubs.delivered()["new_items"]], [f"obs-{TODAY}-1"])  # 2 is taken

    def test_an_item_created_meanwhile_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stubs = Stubs(root, answer={"findings": [finding("race-thing")], "known": [], "note": ""})
            (root / "created.log").write_text(f"obs-{TODAY}-1\n")
            env = {**stubs.env, "QUEUED": "1", "DELIVER_EXIT": "0"}
            with mock.patch.dict(os.environ, env), mock.patch.object(ot, "launchd_jobs", return_value=[]):
                self.assertEqual(ot.main(["run"]), 0)
            self.assertFalse((root / "upserts.log").exists())


if __name__ == "__main__":
    unittest.main()
