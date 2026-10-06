"""read_work_items against stubbed `work` CLI output.

The work API used to cap every list at 500 rows silently; newer servers page
and report `count`/`truncated`/`next_cursor`. An incomplete list must never
read as complete, because a missing active item would leave its worktree
removable.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from workspace_gc import inventory as inv_mod
from workspace_gc import signals as sig_mod
from workspace_gc.signals import Signals, SourceStatus, WorkRef


def item(slug, stage="implementing", worktree=None):
    return {"slug": slug, "stage": stage, "worktree": worktree or f"/w/{slug}"}


class StubWork:
    """Answers `work items --json` with `listing` and `work show --json` from `items`."""

    def __init__(self, listing, items):
        self.listing = listing
        self.items = {i["slug"]: i for i in items}
        self.calls = []

    def __call__(self, env_file, ledger_dir, args):
        self.calls.append(args)
        if args[:2] == ["items", "--json"]:
            return 0, json.dumps(self.listing), ""
        if args[:2] == ["show", "--json"]:
            return 0, json.dumps({"item": self.items[args[2]]}), ""
        return 2, "", "unexpected"


class ReadWorkItemsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = os.path.join(tmp.name, "env")
        with open(self.env, "w") as fh:
            fh.write("WORK_TOKEN=x\n")
        self.ledger = tmp.name

    def read(self, listing, items):
        stub = StubWork(listing, items)
        with mock.patch.object(sig_mod, "run_work", stub):
            refs, status = sig_mod.read_work_items(self.env, self.ledger)
        return refs, status, stub

    def rows(self, n, **kw):
        return [item(f"item-{i:04d}", **kw) for i in range(n)]

    def test_complete_list_is_ok(self):
        rows = [item("a"), item("b", stage="merged"), {"slug": "c", "stage": "parked", "worktree": ""}]
        listing = {"items": [{"slug": r["slug"], "stage": r["stage"]} for r in rows]}
        refs, status, _ = self.read(listing, rows)
        self.assertEqual(status.status, "ok")
        self.assertEqual(status.detail, "3 items, 2 with worktree")
        self.assertEqual(sorted(refs, key=lambda r: r.slug),
                         [WorkRef("a", "implementing", "/w/a"), WorkRef("b", "merged", "/w/b")])

    def test_complete_paged_list_is_ok(self):
        # what a paging-aware CLI prints after following every page
        rows = self.rows(600)
        listing = {"items": rows, "count": 600, "truncated": False, "next_cursor": None}
        refs, status, _ = self.read(listing, rows)
        self.assertEqual(status.status, "ok")
        self.assertEqual(len(refs), 600)

    def test_legacy_server_at_cap_is_incomplete(self):
        # an old server caps silently at 500 and reports no count
        rows = self.rows(500)
        refs, status, _ = self.read({"items": rows}, rows)
        self.assertEqual(status.status, "error")
        self.assertIn("500", status.detail)
        self.assertIn("may be incomplete", status.detail)
        # the rows that did arrive still protect their worktrees
        self.assertEqual(len(refs), 500)

    def test_legacy_server_below_cap_is_ok(self):
        rows = self.rows(499)
        _, status, _ = self.read({"items": rows}, rows)
        self.assertEqual(status.status, "ok")

    def test_truncated_flag_is_incomplete(self):
        rows = self.rows(10)
        listing = {"items": rows, "count": 600, "truncated": True, "next_cursor": None}
        refs, status, _ = self.read(listing, rows)
        self.assertEqual(status.status, "error")
        self.assertIn("10 of 600", status.detail)
        self.assertEqual(len(refs), 10)

    def test_next_cursor_is_incomplete(self):
        # an old CLI against a paging server prints the first page as-is
        rows = self.rows(500)
        listing = {"items": rows, "count": 500, "truncated": False, "next_cursor": "abc"}
        _, status, _ = self.read(listing, rows)
        self.assertEqual(status.status, "error")

    def test_count_above_rows_is_incomplete(self):
        rows = self.rows(10)
        listing = {"items": rows, "count": 12, "truncated": False, "next_cursor": None}
        _, status, _ = self.read(listing, rows)
        self.assertEqual(status.status, "error")
        self.assertIn("10 of 12", status.detail)

    def test_malformed_paging_fields_are_incomplete(self):
        rows = self.rows(3)
        for extra in ({"count": "3"}, {"count": True}, {"truncated": "false"}, {"count": None},
                      {"count": -1}):
            with self.subTest(extra=extra):
                _, status, _ = self.read({"items": rows, **extra}, rows)
                self.assertEqual(status.status, "error")

    def test_negative_count_at_cap_is_incomplete(self):
        rows = self.rows(500)
        listing = {"items": rows, "count": -1, "truncated": False, "next_cursor": None}
        _, status, _ = self.read(listing, rows)
        self.assertEqual(status.status, "error")

    def test_items_must_be_a_list(self):
        _, status, stub = self.read({"items": {"slug": "a"}}, [])
        self.assertEqual(status.status, "error")
        self.assertEqual(stub.calls, [["items", "--json"]])


class IncompleteListKeepsCheckoutsTest(unittest.TestCase):
    """A clean, pushed, idle worktree is class D while the work list is incomplete."""

    def checkout(self, path="/ws/ws-x/repo"):
        co = inv_mod.Checkout(path=path, root="/ws", workspace="/ws/ws-x", kind="worktree")
        co.network_remotes = ["origin"]
        co.unpushed = 0
        co.idle_hours = 100
        return co

    def classify(self, status, refs=()):
        sig = Signals(work_refs=list(refs))
        sig.status = {"herdr": SourceStatus("ok"), "processes": SourceStatus("ok"), "work": status}
        co = self.checkout()
        inv_mod.apply_signals(co, sig)
        inv_mod.classify(co, 48)
        return co

    def test_complete_list_leaves_class_a(self):
        co = self.classify(SourceStatus("ok", "3 items, 0 with worktree"))
        self.assertEqual(co.cls, "A")

    def test_incomplete_list_keeps(self):
        co = self.classify(SourceStatus("error", "work items: showing 500 of 600"))
        self.assertEqual(co.cls, "D")
        self.assertTrue(any("work item list incomplete" in r for r in co.reasons), co.reasons)

    def test_failed_work_source_keeps(self):
        co = self.classify(SourceStatus("error", "work items exit 1: HTTP 500"))
        self.assertEqual(co.cls, "D")

    def test_absent_or_skipped_source_does_not_keep(self):
        for st in ("absent", "skipped"):
            with self.subTest(st=st):
                self.assertEqual(self.classify(SourceStatus(st)).cls, "A")

    def test_listed_active_item_still_named(self):
        ref = WorkRef("x", "implementing", "/ws/ws-x/repo")
        co = self.classify(SourceStatus("error", "showing 1 of 2"), [ref])
        self.assertEqual(co.cls, "D")
        self.assertIn("active work item: x", co.reasons)
        self.assertFalse(any("work item list incomplete" in r for r in co.reasons))


if __name__ == "__main__":
    unittest.main()
