import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import pane_watchdog as pw

FIXTURES = Path(__file__).parent / "fixtures"
E = "\x1b"
RULE = "─" * 40


def fixture(name):
    return (FIXTURES / f"{name}.ansi").read_text(encoding="utf-8")


class AnsiParsingTest(unittest.TestCase):
    def test_dim_text_is_dropped_from_plain(self):
        [line] = pw.parse_ansi(f"❯ {E}[0m{E}[2mghost{E}[0m real{E}[2m more{E}[22m end\r\n")
        self.assertEqual(line.text, "❯ ghost real more end")
        self.assertEqual(line.plain, "❯  real end")

    def test_extended_colour_arguments_are_not_sgr_codes(self):
        # 38;2;2;2;2 is a colour, not "dim"; 38;5;2 likewise
        [line] = pw.parse_ansi(f"{E}[38;2;2;2;2mA{E}[38;5;2mB{E}[2;38;5;2mC{E}[0mD")
        self.assertEqual(line.plain, "ABD")

    def test_osc_hyperlinks_and_other_escapes_are_removed(self):
        [line] = pw.parse_ansi(f"{E}]8;id=x;https://example.org{E}\\Guide{E}]8;;{E}\\ {E}[?25l{E}(Bok\x07")
        self.assertEqual(line.text, "Guide ok")

    def test_reset_variants(self):
        [line] = pw.parse_ansi(f"{E}[2mdim{E}[mplain{E}[2mdim{E}[0;1mbold")
        self.assertEqual(line.plain, "plainbold")

    def test_snippet_limit(self):
        self.assertEqual(len(pw.snippet("x" * 500)), pw.SNIPPET_MAX)
        self.assertEqual(pw.snippet("  a \xa0 b\t c "), "a b c")


class AnalyzeFixturesTest(unittest.TestCase):
    """Fixtures: tmux captures of Claude Code 2.1.318 (trust, usage, permission,
    question, typed input) and herdr-format captures with neutral text."""

    def kinds(self, name, status="idle"):
        return pw.analyze(fixture(name), status)

    def test_usage_dialog(self):
        [(kind, text)] = self.kinds("usage-dialog")
        self.assertEqual(kind, "usage-dialog")
        self.assertEqual(text, "Current week (all models) ██ 4% used")

    def test_trust_dialog_hides_generic_esc_to_cancel(self):
        [(kind, text)] = self.kinds("trust-dialog")
        self.assertEqual(kind, "trust-dialog")
        self.assertIn("one you trust", text)
        self.assertLessEqual(len(text), pw.SNIPPET_MAX)

    def test_permission_prompt(self):
        self.assertEqual(self.kinds("permission-prompt"), [("permission-prompt", "Do you want to proceed?")])

    def test_owner_question(self):
        self.assertEqual(self.kinds("owner-question"),
                         [("owner-question", "Shall I delete the probe branch now?")])

    def test_owner_question_ignored_while_working(self):
        self.assertEqual(self.kinds("owner-question", status="working"), [])

    def test_question_followed_by_recap(self):
        self.assertEqual(self.kinds("question-with-recap"),
                         [("owner-question", "Soll ich nach main mergen, oder erst die Doku ergänzen?")])

    def test_ghost_text_is_not_input(self):
        self.assertEqual(self.kinds("ghost-text"), [])

    def test_idle_report_quoting_dialog_phrases_is_clean(self):
        self.assertEqual(self.kinds("idle-clean"), [])

    def test_typed_input(self):
        self.assertIn(("input-text", "half typed owner text"), self.kinds("typed-input"))

    def test_multiline_input_keeps_non_dim_part(self):
        self.assertEqual(self.kinds("typed-multiline"), [("input-text", "please stop after the current slice")])


class AnalyzeInlineTest(unittest.TestCase):
    def box(self, body, above=""):
        return f"{above}{RULE}\r\n{body}\r\n{RULE}\r\n  status line\r\n"

    def test_interrupted_turn_is_not_a_question(self):
        raw = self.box("❯ ", above="⏺ Running it\r\n  ⎿  Interrupted · What should Claude do instead?\r\n")
        self.assertEqual(pw.analyze(raw, "idle"), [])

    def test_question_phrase_without_question_mark(self):
        raw = self.box("❯ ", above="⏺ Tests pass. Want me to merge it to main.\r\n")
        self.assertEqual(pw.analyze(raw, "done"), [("owner-question", "Tests pass. Want me to merge it to main.")])

    def test_question_far_above_end_is_ignored(self):
        body = "⏺ Is this right? Here is the report.\r\n" + "".join(f"  - point {i}\r\n" for i in range(12))
        self.assertEqual(pw.analyze(self.box("❯ ", above=body), "idle"), [])

    def test_option_cursor_without_rule_is_not_input_line(self):
        raw = f"{RULE}\r\n Bash command\r\n Do you want to proceed?\r\n ❯ 1. Yes\r\n   2. No\r\n Esc to cancel\r\n"
        self.assertEqual(pw.analyze(raw), [("permission-prompt", "Do you want to proceed?")])

    def test_esc_to_cancel_alone_counts_as_prompt(self):
        raw = f"{RULE}\r\n Edit file\r\n ❯ 1. Yes\r\n Esc to cancel · Tab to amend\r\n"
        self.assertEqual(pw.analyze(raw), [("permission-prompt", "Esc to cancel · Tab to amend")])

    def test_dialog_words_in_transcript_do_not_count_while_input_box_shows(self):
        raw = self.box("❯ ", above="  Do you want to proceed?\r\n  Esc to cancel\r\n  Current week (all models)\r\n"
                       "⏺ Done, nothing open.\r\n\r\n")
        self.assertEqual(pw.analyze(raw), [])

    def test_input_box_in_scrollback_does_not_hide_dialog(self):
        raw = (f"{RULE}\r\n❯ \r\n{RULE}\r\n  status\r\n⏺ Running\r\n{RULE}\r\n Bash command\r\n"
               " Do you want to proceed?\r\n ❯ 1. Yes\r\n Esc to cancel\r\n")
        self.assertEqual(pw.analyze(raw), [("permission-prompt", "Do you want to proceed?")])

    def test_no_assistant_message_means_no_question(self):
        raw = self.box("❯ ", above="❯ What does this do?\r\n  more\r\n")
        self.assertEqual(pw.analyze(raw, "idle"), [])

    def test_plain_shell_pane(self):
        self.assertEqual(pw.analyze("$ ls\r\nREADME.md\r\n$ \r\n"), [])


class CliTest(unittest.TestCase):
    """main() against a fake herdr that logs every call."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = self.dir / "calls.jsonl"
        self.panes = {}  # machine -> {pane_id: (status, fixture name)}
        self.fail = set()
        self.agentless = set()

    def tearDown(self):
        self.tmp.cleanup()

    def fake_herdr(self):
        config = self.dir / "config.json"
        config.write_text(json.dumps({
            "panes": {m: {p: [s, str(FIXTURES / f"{f}.ansi")] for p, (s, f) in panes.items()}
                      for m, panes in self.panes.items()},
            "fail": sorted(self.fail), "agentless": sorted(self.agentless)}))
        path = self.dir / "herdr"
        path.write_text(f"#!{sys.executable}\n" + f"""
import json, sys
args = sys.argv[1:]
open({str(self.log)!r}, "a").write(json.dumps(args) + "\\n")
cfg = json.load(open({str(config)!r}))
machine = "local"
if args[:1] == ["--machine"]:
    machine, args = args[1], args[2:]
if machine in cfg["fail"]:
    sys.stderr.write("ssh: connect to host " + machine + ": timed out\\n")
    sys.exit(1)
panes = cfg["panes"].get(machine, {{}})
if args[:2] == ["pane", "list"]:
    print(json.dumps({{"id": "cli:pane:list", "result": {{"panes": [
        {{"pane_id": p, "agent": None if p in cfg["agentless"] else "claude", "agent_status": s}}
        for p, (s, _) in panes.items()]}}}}))
elif args[:2] == ["pane", "read"]:
    sys.stdout.write(open(panes[args[2]][1], encoding="utf-8").read())
else:
    sys.exit(9)
""")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return str(path)

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"PANE_WATCHDOG_HERDR": self.fake_herdr()}), \
                redirect_stdout(out), redirect_stderr(err):
            code = pw.main(argv)
        return code, out.getvalue(), err.getvalue()

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_no_findings_exit_zero(self):
        self.panes = {"local": {"w1:p1": ("idle", "ghost-text"), "w2:p1": ("idle", "idle-clean")}}
        code, out, err = self.run_main(["--local-name", "atlas"])
        self.assertEqual((code, out, err), (0, "", ""))

    def test_findings_one_line_each_exit_one(self):
        self.panes = {"local": {"w1:p1": ("idle", "usage-dialog")},
                      "claascraft": {"w2:p3": ("idle", "question-with-recap"), "w2:p4": ("idle", "typed-input")}}
        code, out, err = self.run_main(["local", "claascraft", "--local-name", "atlas"])
        self.assertEqual(code, 1, err)
        lines = out.splitlines()
        self.assertEqual(lines[0], "atlas\tw1:p1\tusage-dialog\tCurrent week (all models) ██ 4% used")
        self.assertIn("claascraft\tw2:p3\towner-question\tSoll ich nach main mergen, oder erst die Doku ergänzen?",
                      lines)
        self.assertIn("claascraft\tw2:p4\tinput-text\thalf typed owner text", lines)
        for line in lines:
            machine, pane, kind, text = line.split("\t")
            self.assertLessEqual(len(text), pw.SNIPPET_MAX)

    def test_only_read_only_commands_are_run(self):
        self.panes = {"local": {"w1:p1": ("idle", "permission-prompt")}, "studio": {"w3:p1": ("idle", "trust-dialog")}}
        self.run_main(["local", "studio"])
        for call in self.calls():
            if call[:1] == ["--machine"]:
                call = call[2:]
            self.assertIn(tuple(call[:2]), pw.READ_ONLY_COMMANDS)
        self.assertIn(["pane", "read", "w1:p1", "--format", "ansi", "--lines", "80"], self.calls())
        self.assertIn(["--machine", "studio", "pane", "list"], self.calls())

    def test_panes_without_agent_are_skipped(self):
        self.panes = {"local": {"w1:p1": (None, "permission-prompt"), "w1:p2": ("idle", "trust-dialog")}}
        self.agentless = {"w1:p1"}
        code, out, _ = self.run_main(["--local-name", "atlas"])
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), [
            "atlas\tw1:p2\ttrust-dialog\tQuick safety check: Is this a project you created or one you trust? "
            "(Like your own code, a well-known open source"])
        self.assertNotIn(["pane", "read", "w1:p1", "--format", "ansi", "--lines", "80"], self.calls())

    def test_herdr_refuses_other_commands(self):
        with self.assertRaises(ValueError):
            pw.Herdr("herdr")._run(pw.LOCAL, ["pane", "send-keys", "w1:p1", "Enter"])

    def test_unreachable_machine_exit_two(self):
        self.panes = {"local": {"w1:p1": ("idle", "owner-question")}}
        self.fail = {"claascraft"}
        code, out, err = self.run_main(["local", "claascraft", "--local-name", "atlas"])
        self.assertEqual(code, 2)
        self.assertIn("atlas\tw1:p1\towner-question", out)
        self.assertIn("claascraft\t-\terror\therdr pane list exited 1: ssh: connect to host claascraft: timed out",
                      err)

    def test_json_output(self):
        self.panes = {"local": {"w1:p1": ("idle", "permission-prompt")}}
        code, out, _ = self.run_main(["--json", "--local-name", "atlas"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out), [{"machine": "atlas", "pane": "w1:p1", "kind": "permission-prompt",
                                            "snippet": "Do you want to proceed?"}])


if __name__ == "__main__":
    unittest.main()
