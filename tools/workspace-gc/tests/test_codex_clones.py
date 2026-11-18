"""Codex job clones (ws-cx-<job>/<repo>) and scout clones (ws-cx-scoutN/<repo>).

Codex jobs commit on a local codex-q/ branch and never push it; merge clerks
record finished jobs in merged.txt or dropped.txt of the coordination
directory. Legacy jobs pushed the branch, and the clerk deleted it after
merging a rebased copy.
"""

import os
import time
from unittest import mock

from workspace_gc import inventory, remove

from tests.helpers import GitFixture, ok_signals, sh

JOB = "cx-r1-proj"
BRANCH = "codex-q/r1-proj"


class CodexCloneFixture(GitFixture):
    def setUp(self):
        super().setUp()
        self.url = self.network_repo()
        self.codex = os.path.join(self.tmp, "codex")
        os.makedirs(self.codex)
        env = mock.patch.dict(os.environ, {"WORKSPACE_GC_CODEX_DIR": self.codex})
        env.start()
        self.addCleanup(env.stop)
        # Fixtures are seconds old; the 48 h rule gets its own test.
        idle = mock.patch.object(inventory, "CODEX_MIN_IDLE_HOURS", 0.0)
        idle.start()
        self.addCleanup(idle.stop)

    def job_clone(self, job=JOB, branch=BRANCH, repo="proj"):
        cl = self.clone(self.url, f"ws-cx-{job}", repo)
        sh("git", "checkout", "-q", "-b", branch, cwd=cl)
        self.commit(cl, name="fix.txt", text="fix\n", msg="fix something")
        return cl

    def record(self, name, line):
        with open(os.path.join(self.codex, name), "a") as fh:
            fh.write(line + "\n")

    def on_main(self, name="fix.txt", text="fix\n", msg="fix something (rebased)",
                branch="main"):
        """Push a commit with the same patch to `branch` of the network repo."""
        other = os.path.join(self.tmp, f"other-{branch}")
        if not os.path.isdir(other):
            sh("git", "clone", "-q", self.url, other)
        sh("git", "checkout", "-q", "-B", branch, cwd=other)
        self.commit(other, name="unrelated.txt", text=f"{branch}\n", msg="unrelated")
        self.commit(other, name=name, text=text, msg=msg)
        sh("git", "push", "-q", "origin", branch, cwd=other)

    def co(self, path, **kw):
        return self.by_path(self.build(**kw))[path]


class LocalJobCloneTest(CodexCloneFixture):
    def test_merged_job_is_A_and_removable(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        co = self.co(cl)
        self.assertEqual(co.cls, "A", co.reasons)
        self.assertIn("closed Codex job clone", co.reasons[0])
        self.assertIn("merged abc1234", co.reasons[0])
        code, out = self.cli("remove", "--apply", cl)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(cl))

    def test_dropped_job_is_A(self):
        cl = self.job_clone()
        self.record("dropped.txt", f"{JOB}\tproj\tsuperseded by r2")
        co = self.co(cl)
        self.assertEqual(co.cls, "A", co.reasons)
        self.assertIn("dropped: superseded by r2", co.reasons[0])

    def test_job_neither_merged_nor_dropped_is_kept(self):
        cl = self.job_clone()
        self.record("merged.txt", "cx-r1-other\tproj\tabc1234")
        co = self.co(cl)
        self.assertEqual(co.cls, "B", co.reasons)
        self.assertTrue(any("neither merged.txt nor dropped.txt" in n for n in co.notes),
                        co.notes)
        code, out = self.cli("remove", "--apply", cl)
        self.assertEqual(code, 1, out)
        self.assertTrue(os.path.isdir(cl))

    def test_never_pushed_job_with_patch_on_main_is_still_kept(self):
        # Without merged.txt/dropped.txt only a pushed (legacy) branch counts.
        cl = self.job_clone()
        self.on_main()
        sh("git", "fetch", "-q", "origin", cwd=cl)
        co = self.co(cl)
        self.assertEqual(co.cls, "B", co.reasons)
        self.assertTrue(any("never pushed" in n for n in co.notes), co.notes)

    def test_repository_mismatch_is_kept(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tother-repo\tabc1234")
        co = self.co(cl)
        self.assertEqual(co.cls, "B", co.reasons)
        self.assertTrue(any("closed for repository other-repo" in n for n in co.notes),
                        co.notes)

    def test_dirty_closed_job_is_C(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        self.write(cl, "README.md", "changed\n")
        self.assertEqual(self.co(cl).cls, "C")

    def test_untracked_work_closed_job_is_C(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        self.write(cl, "notes.md", "unsaved\n")
        self.assertEqual(self.co(cl).cls, "C")

    def test_stash_closed_job_is_C(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        self.write(cl, "README.md", "stashed\n")
        sh("git", "stash", "-q", cwd=cl)
        co = self.co(cl)
        self.assertEqual(co.cls, "C", co.reasons)
        self.assertTrue(any("stash" in r for r in co.reasons), co.reasons)

    def test_in_use_closed_job_is_D(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        sig = ok_signals(process_cwds=[cl])
        co = self.co(cl, signals=sig)
        self.assertEqual(co.cls, "D", co.reasons)

    def test_recently_active_closed_job_is_D(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        with mock.patch.object(inventory, "CODEX_MIN_IDLE_HOURS", 48.0):
            co = self.co(cl)
        self.assertEqual(co.cls, "D", co.reasons)
        self.assertIn("< 48h for a closed Codex job clone", co.reasons[0])

    def test_closed_job_ignores_min_idle_hours(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        co = self.co(cl, min_idle_hours=48, codex_idle_hours=0)
        self.assertEqual(co.cls, "A", co.reasons)

    def test_closed_job_default_codex_idle_is_6h(self):
        self.assertEqual(inventory.CODEX_MIN_IDLE_HOURS, 0.0)  # patched by the fixture
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        later = time.time() + 7 * 3600
        with mock.patch.object(inventory.time, "time", return_value=later):
            co = self.co(cl, min_idle_hours=48, codex_idle_hours=6)
        self.assertEqual(co.cls, "A", co.reasons)
        co = self.co(cl, min_idle_hours=48, codex_idle_hours=6)
        self.assertEqual(co.cls, "D", co.reasons)
        self.assertIn("< 6h for a closed Codex job clone", co.reasons[0])

    def test_idle_closed_job_is_A_with_real_threshold(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        later = time.time() + 72 * 3600
        with mock.patch.object(inventory, "CODEX_MIN_IDLE_HOURS", 48.0), \
                mock.patch.object(inventory.time, "time", return_value=later):
            co = self.co(cl)
        self.assertEqual(co.cls, "A", co.reasons)

    def test_removal_refused_when_job_is_no_longer_closed(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        inv = self.build()
        co = self.by_path(inv)[cl]
        self.assertEqual(co.cls, "A", co.reasons)
        os.remove(os.path.join(self.codex, "merged.txt"))
        with self.assertRaises(remove.Refused) as ctx:
            remove.remove_checkout(co, inv.roots, [self.projects], [], signals=ok_signals())
        self.assertIn("no longer closed", str(ctx.exception))
        self.assertTrue(os.path.isdir(cl))

    def test_closed_job_with_work_outside_head_is_kept(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        sh("git", "branch", "-q", "side", "HEAD~1", cwd=cl)
        sh("git", "checkout", "-q", "side", cwd=cl)
        self.commit(cl, name="side.txt", msg="unmerged side work")
        sh("git", "checkout", "-q", BRANCH, cwd=cl)
        co = self.co(cl)
        self.assertEqual(co.cls, "B", co.reasons)
        self.assertTrue(any("outside HEAD" in n for n in co.notes), co.notes)

    def test_removal_refused_when_work_was_added_after_inventory(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        inv = self.build()
        co = self.by_path(inv)[cl]
        self.assertEqual(co.cls, "A", co.reasons)
        sh("git", "checkout", "-q", "-b", "side", cwd=cl)
        self.commit(cl, name="side.txt", msg="new unmerged work")
        sh("git", "checkout", "-q", BRANCH, cwd=cl)
        with self.assertRaises(remove.Refused) as ctx:
            remove.remove_checkout(co, inv.roots, [self.projects], [], signals=ok_signals())
        self.assertIn("changed since the inventory", str(ctx.exception))
        self.assertTrue(os.path.isdir(cl))

    def test_removal_refused_when_containment_unknown_without_fetch(self):
        cl = self.job_clone()
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        inv = self.build()
        co = self.by_path(inv)[cl]
        self.assertEqual(co.cls, "A", co.reasons)
        self.on_main(name="new.txt", text="new\n", msg="remote moved on")
        with self.assertRaises(remove.Refused) as ctx:
            remove.remove_checkout(co, inv.roots, [self.projects], [], fetch=False,
                                   signals=ok_signals())
        self.assertIn("containment unknown", str(ctx.exception))
        self.assertTrue(os.path.isdir(cl))

    def test_not_a_job_workspace_is_unaffected(self):
        cl = self.clone(self.url, f"ws-other-{JOB}")
        sh("git", "checkout", "-q", "-b", BRANCH, cwd=cl)
        self.commit(cl, name="fix.txt", text="fix\n", msg="fix")
        self.record("merged.txt", f"{JOB}\tproj\tabc1234")
        co = self.co(cl)
        self.assertEqual(co.cls, "B", co.reasons)
        self.assertEqual(co.codex_job, "")

    def test_reader_skips_malformed_lines(self):
        self.record("merged.txt", "only-a-job")
        self.record("merged.txt", f"{JOB}\tproj\tabc")
        self.record("dropped.txt", "\tproj\twhy")
        table = inventory.read_codex_closed(self.codex)
        self.assertEqual(table, {JOB: ("proj", "merged abc")})


class LegacyJobCloneTest(CodexCloneFixture):
    def pushed_clone(self):
        cl = self.job_clone()
        sh("git", "push", "-q", "-u", "origin", BRANCH, cwd=cl)
        return cl

    def delete_remote_branch(self, branch=BRANCH):
        sh("git", "-C", os.path.join(self.net, "proj.git"), "branch", "-q", "-D", branch)

    def test_merged_legacy_branch_is_A(self):
        cl = self.pushed_clone()
        self.on_main()
        self.delete_remote_branch()
        co = self.co(cl)
        self.assertEqual(co.cls, "A", co.reasons)
        self.assertIn("merged legacy Codex job clone", co.reasons[0])
        self.assertIn("every patch is on main", co.reasons[0])
        code, out = self.cli("remove", "--apply", cl)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(cl))

    def test_legacy_branch_merged_into_develop_is_A(self):
        cl = self.pushed_clone()
        self.on_main(branch="develop")
        self.delete_remote_branch()
        co = self.co(cl)
        self.assertEqual(co.cls, "A", co.reasons)
        self.assertEqual(co.codex_patches_on, "develop")

    def test_legacy_branch_gone_but_patch_not_merged_is_kept(self):
        cl = self.pushed_clone()
        self.on_main(name="other.txt", text="different\n", msg="other change")
        self.delete_remote_branch()
        co = self.co(cl)
        self.assertEqual(co.cls, "B", co.reasons)
        self.assertTrue(any("not every patch" in n for n in co.notes), co.notes)

    def test_legacy_branch_with_extra_local_branch_is_kept(self):
        cl = self.pushed_clone()
        self.on_main()
        sh("git", "branch", "-q", "side", "HEAD~1", cwd=cl)
        sh("git", "checkout", "-q", "side", cwd=cl)
        self.commit(cl, name="side.txt", msg="side work")
        sh("git", "checkout", "-q", BRANCH, cwd=cl)
        self.delete_remote_branch()
        co = self.co(cl)
        self.assertEqual(co.cls, "B", co.reasons)
        self.assertTrue(any("outside HEAD" in n for n in co.notes), co.notes)

    def test_removal_refused_when_legacy_branch_returns(self):
        cl = self.pushed_clone()
        self.on_main()
        self.delete_remote_branch()
        inv = self.build()
        co = self.by_path(inv)[cl]
        self.assertEqual(co.cls, "A", co.reasons)
        # Someone pushes a different commit under the branch name again.
        other = os.path.join(self.tmp, "other-main")
        sh("git", "checkout", "-q", "-b", BRANCH, cwd=other)
        sh("git", "push", "-q", "origin", BRANCH, cwd=other)
        with self.assertRaises(remove.Refused) as ctx:
            remove.remove_checkout(co, inv.roots, [self.projects], [], signals=ok_signals())
        self.assertIn("still exists", str(ctx.exception))
        self.assertTrue(os.path.isdir(cl))


class ScoutCloneTest(CodexCloneFixture):
    def test_unfinished_scout_round_is_D(self):
        cl = self.clone(self.url, "ws-cx-scout7")
        co = self.co(cl)
        self.assertEqual(co.cls, "D", co.reasons)
        self.assertIn("scout round 7 not finished", co.reasons[0])

    def test_finished_scout_round_is_A(self):
        cl = self.clone(self.url, "ws-cx-scout7")
        self.record("scout7.out", "report\n\n## Runner closeout\nLEFT x")
        co = self.co(cl)
        self.assertEqual(co.cls, "A", co.reasons)
        self.assertIn("finished scout round 7 clone", co.reasons[0])

    def test_removal_refused_when_scout_closeout_disappears(self):
        cl = self.clone(self.url, "ws-cx-scout7")
        self.record("scout7.out", "## Runner closeout")
        inv = self.build()
        co = self.by_path(inv)[cl]
        self.assertEqual(co.cls, "A", co.reasons)
        os.remove(os.path.join(self.codex, "scout7.out"))
        with self.assertRaises(remove.Refused) as ctx:
            remove.remove_checkout(co, inv.roots, [self.projects], [], signals=ok_signals())
        self.assertIn("no runner closeout now", str(ctx.exception))
        self.assertTrue(os.path.isdir(cl))

    def test_finished_scout_with_local_commit_is_kept(self):
        cl = self.clone(self.url, "ws-cx-scout7")
        self.record("scout7.out", "## Runner closeout")
        self.commit(cl, name="audit.txt", msg="local audit")
        self.assertEqual(self.co(cl).cls, "B")

    def test_finished_scout_dirty_is_C(self):
        cl = self.clone(self.url, "ws-cx-scout7")
        self.record("scout7.out", "## Runner closeout")
        self.write(cl, "README.md", "edited\n")
        self.assertEqual(self.co(cl).cls, "C")

    def test_finished_scout_recently_active_is_D(self):
        cl = self.clone(self.url, "ws-cx-scout7")
        self.record("scout7.out", "## Runner closeout")
        co = self.co(cl, min_idle_hours=0, codex_idle_hours=6)
        self.assertEqual(co.cls, "D", co.reasons)
        self.assertIn("< 6h for a finished scout clone", co.reasons[0])

    def test_finished_scout_uses_codex_idle_not_min_idle(self):
        # A finished round has no further user: --min-idle-hours (48) does not
        # apply, --codex-idle-hours (patched to 0 here) does.
        cl = self.clone(self.url, "ws-cx-scout7")
        self.record("scout7.out", "## Runner closeout")
        co = self.co(cl, min_idle_hours=48)
        self.assertEqual(co.cls, "A", co.reasons)

    def test_unfinished_scout_keeps_min_idle(self):
        cl = self.clone(self.url, "ws-cx-scout7")
        co = self.co(cl, min_idle_hours=48)
        self.assertEqual(co.cls, "D", co.reasons)
        self.assertIn("< 48h)", co.reasons[0])

