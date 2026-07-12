import os
import tempfile
import unittest
from unittest import mock
from claude_review_loop import lock


class TestLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lock_dir = os.path.join(self.tmp.name, "opus-review.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def test_acquire_and_release(self):
        with lock.Lock(self.lock_dir, {"claude_pgid": -1}) as held:
            self.assertTrue(os.path.isdir(self.lock_dir))
            self.assertEqual(
                lock.read_meta(self.lock_dir)["owner_token"], held.owner_token
            )
        self.assertFalse(os.path.exists(self.lock_dir))

    def test_metadata_update_preserves_owner_token(self):
        with lock.Lock(self.lock_dir, {"harness_pid": os.getpid()}) as held:
            held.update_meta({"claude_pgid": 12345})
            meta = lock.read_meta(self.lock_dir)
            self.assertEqual(meta["owner_token"], held.owner_token)
            self.assertEqual(meta["claude_pgid"], 12345)

    def test_meta_write_failure_cleans_only_owned_partial_lock(self):
        candidate = lock.Lock(self.lock_dir, {"claude_pgid": -1})
        with mock.patch.object(lock, "write_meta", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                candidate.__enter__()
        self.assertFalse(candidate.acquired)
        self.assertFalse(os.path.exists(self.lock_dir))
        with lock.Lock(self.lock_dir, {"harness_pid": os.getpid()}):
            self.assertTrue(os.path.isdir(self.lock_dir))

    def test_second_acquire_raises_when_held_by_live_group(self):
        # Use our own pgid as a stand-in for a live Claude group.
        meta = {"claude_pgid": os.getpgrp(), "command": "claude", "cwd": os.getcwd()}
        with lock.Lock(self.lock_dir, meta):
            with self.assertRaises(lock.LockHeld):
                with lock.Lock(self.lock_dir, {"claude_pgid": -1}):
                    pass

    def test_guard_blocks_second_owner_even_when_lock_directory_is_displaced(self):
        held = lock.Lock(self.lock_dir, {"harness_pid": os.getpid()})
        held.__enter__()
        displaced = self.lock_dir + ".displaced-by-test"
        os.rename(self.lock_dir, displaced)
        try:
            with self.assertRaises(lock.LockHeld):
                with lock.Lock(self.lock_dir, {"harness_pid": os.getpid()}):
                    pass
        finally:
            held.__exit__(None, None, None)

    def test_reclaims_stale_lock_when_group_dead(self):
        # Pre-create a lock whose recorded pgid is dead (no such group).
        os.mkdir(self.lock_dir)
        lock.write_meta(self.lock_dir, {
            "claude_pgid": 2_000_000_000,  # not a live group
            "command": "claude", "cwd": os.getcwd(),
        })
        # A fresh acquire should reclaim it rather than raise.
        with lock.Lock(self.lock_dir, {"claude_pgid": -1}):
            self.assertTrue(os.path.isdir(self.lock_dir))

    def test_does_not_reclaim_live_harness_pid(self):
        os.mkdir(self.lock_dir)
        lock.write_meta(self.lock_dir, {"harness_pid": os.getpid(),
                                        "command": "claude-review-loop"})
        with self.assertRaises(lock.LockHeld):
            with lock.Lock(self.lock_dir, {"harness_pid": os.getpid()}):
                pass

    def test_reclaims_dead_harness_pid(self):
        os.mkdir(self.lock_dir)
        lock.write_meta(self.lock_dir, {"harness_pid": 2_000_000_000,
                                        "command": "claude-review-loop"})
        with lock.Lock(self.lock_dir, {"harness_pid": os.getpid()}):
            self.assertTrue(os.path.isdir(self.lock_dir))

    def test_atomic_stale_retirement_does_not_remove_replacement_lock(self):
        os.mkdir(self.lock_dir)
        lock.write_meta(self.lock_dir, {"harness_pid": 2_000_000_000})
        real_rename = os.rename
        replacement_token = "owner-b"

        def rename_then_replace(source, tombstone):
            real_rename(source, tombstone)
            os.mkdir(source)
            lock.write_meta(source, {
                "harness_pid": os.getpid(), "owner_token": replacement_token,
            })

        with mock.patch.object(lock.os, "rename", side_effect=rename_then_replace):
            self.assertTrue(lock._reclaim_if_stale(self.lock_dir))
        self.assertTrue(os.path.isdir(self.lock_dir))
        self.assertEqual(
            lock.read_meta(self.lock_dir)["owner_token"], replacement_token
        )

    def test_release_does_not_remove_replacement_owner_lock(self):
        held = lock.Lock(self.lock_dir, {"harness_pid": os.getpid()})
        held.__enter__()
        displaced = self.lock_dir + ".displaced"
        os.rename(self.lock_dir, displaced)
        os.mkdir(self.lock_dir)
        lock.write_meta(self.lock_dir, {
            "harness_pid": os.getpid(), "owner_token": "new-owner",
        })
        held.__exit__(None, None, None)
        self.assertTrue(os.path.isdir(self.lock_dir))
        self.assertEqual(lock.read_meta(self.lock_dir)["owner_token"], "new-owner")

    def test_does_not_reclaim_lock_with_missing_meta(self):
        # No meta.json => treat as held (fail closed), do not reclaim.
        os.mkdir(self.lock_dir)
        with self.assertRaises(lock.LockHeld):
            with lock.Lock(self.lock_dir, {"claude_pgid": -1}):
                pass

    def test_read_meta_returns_empty_on_corrupt_json(self):
        os.mkdir(self.lock_dir)
        with open(os.path.join(self.lock_dir, lock.META_NAME), "w") as fh:
            fh.write("{not json")
        self.assertEqual(lock.read_meta(self.lock_dir), {})

    def test_exit_tolerates_externally_removed_dir(self):
        import shutil
        with lock.Lock(self.lock_dir, {"claude_pgid": -1}):
            shutil.rmtree(self.lock_dir)  # vanished mid-context
        # __exit__ must not raise

    def test_pgid_is_claude_false_for_non_claude_group(self):
        # The test runner is python, not claude -> guard must refuse to kill it.
        self.assertFalse(lock._pgid_is_claude(os.getpgrp()))

    def test_pgid_is_claude_false_for_dead_pgid(self):
        self.assertFalse(lock._pgid_is_claude(2_000_000_000))

    def test_pgid_is_claude_accepts_wrapper_command(self):
        completed = mock.Mock(stdout="/opt/homebrew/bin/node /opt/homebrew/bin/claude -p\n")
        with mock.patch("claude_review_loop.lock.subprocess.run", return_value=completed):
            self.assertTrue(lock._pgid_is_claude(12345))

    def test_pgid_is_claude_accepts_fish_claude_yolo_wrapper(self):
        completed = mock.Mock(stdout="fish -lc claude-yolo -p --model opus\n")
        with mock.patch("claude_review_loop.lock.subprocess.run", return_value=completed):
            self.assertTrue(lock._pgid_is_claude(12345))

    def test_pgid_is_claude_rejects_unrelated_fish(self):
        completed = mock.Mock(stdout="fish -lc echo hi\n")
        with mock.patch("claude_review_loop.lock.subprocess.run", return_value=completed):
            self.assertFalse(lock._pgid_is_claude(12345))

    def test_reclaims_dead_harness_even_when_pgid_not_claude(self):
        # harness dead + a claude_pgid that is NOT claude: reclaim still removes
        # the lock, but must not kill the unrelated group.
        os.mkdir(self.lock_dir)
        lock.write_meta(self.lock_dir, {"harness_pid": 2_000_000_000,
                                        "claude_pgid": os.getpgrp(),
                                        "command": "claude-review-loop"})
        with lock.Lock(self.lock_dir, {"harness_pid": os.getpid()}):
            self.assertTrue(os.path.isdir(self.lock_dir))


if __name__ == "__main__":
    unittest.main()
