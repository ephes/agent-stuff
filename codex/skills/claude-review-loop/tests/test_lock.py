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

    def test_metadata_update_reports_changed_ownership_as_runtime_error(self):
        held = lock.Lock(self.lock_dir, {"harness_pid": os.getpid()})
        held.__enter__()
        try:
            meta = lock.read_meta(self.lock_dir)
            meta["owner_token"] = "replacement-owner"
            lock.write_meta(self.lock_dir, meta)
            with self.assertRaisesRegex(RuntimeError, "ownership changed"):
                held.update_meta({"claude_pgid": 12345})
        finally:
            held.__exit__(None, None, None)

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

    def test_pool_uses_next_slot_when_first_slot_is_held(self):
        pool_dir = os.path.join(self.tmp.name, "pool")
        first = lock.LockPool(
            pool_dir,
            {"harness_pid": os.getpid()},
            max_concurrent=2,
        )
        first.__enter__()
        try:
            with lock.LockPool(
                pool_dir,
                {"harness_pid": os.getpid()},
                max_concurrent=2,
            ) as second:
                self.assertEqual(first.slot, 0)
                self.assertEqual(second.slot, 1)
                self.assertNotEqual(first.lock_dir, second.lock_dir)
        finally:
            first.__exit__(None, None, None)

    def test_pool_skips_live_guard_with_displaced_slot_directory(self):
        pool_dir = os.path.join(self.tmp.name, "displaced-slot-pool")
        first = lock.LockPool(
            pool_dir,
            {"harness_pid": os.getpid()},
            max_concurrent=2,
        )
        first.__enter__()
        displaced = first.lock_dir + ".displaced-by-test"
        os.rename(first.lock_dir, displaced)
        try:
            with lock.LockPool(
                pool_dir,
                {"harness_pid": os.getpid()},
                max_concurrent=2,
            ) as second:
                self.assertEqual(second.slot, 1)
        finally:
            first.__exit__(None, None, None)

    def test_pool_raises_only_when_all_slots_are_held(self):
        pool_dir = os.path.join(self.tmp.name, "full-pool")
        first = lock.LockPool(
            pool_dir,
            {"harness_pid": os.getpid()},
            max_concurrent=1,
        )
        first.__enter__()
        try:
            with self.assertRaisesRegex(
                lock.LockHeld, r"1 review slot\(s\) held, active limit 1"
            ):
                with lock.LockPool(
                    pool_dir,
                    {"harness_pid": os.getpid()},
                    max_concurrent=1,
                ):
                    pass
        finally:
            first.__exit__(None, None, None)

    def test_restrictive_live_holder_limits_other_invocations(self):
        pool_dir = os.path.join(self.tmp.name, "restrictive-holder-pool")
        with lock.LockPool(
            pool_dir,
            {"harness_pid": os.getpid()},
            max_concurrent=1,
        ):
            with self.assertRaisesRegex(
                lock.LockHeld, r"1 review slot\(s\) held, active limit 1"
            ):
                with lock.LockPool(
                    pool_dir,
                    {"harness_pid": os.getpid()},
                    max_concurrent=3,
                ):
                    pass

    def test_live_legacy_or_malformed_slot_falls_back_to_limit_one(self):
        for index, recorded_limit in enumerate((None, "invalid", 0)):
            with self.subTest(recorded_limit=recorded_limit):
                pool_dir = os.path.join(self.tmp.name, f"legacy-pool-{index}")
                slot_dir = os.path.join(pool_dir, "slot-0")
                os.makedirs(slot_dir)
                meta = {"harness_pid": os.getpid()}
                if recorded_limit is not None:
                    meta["max_concurrent"] = recorded_limit
                lock.write_meta(slot_dir, meta)
                with self.assertRaisesRegex(
                    lock.LockHeld, r"1 review slot\(s\) held, active limit 1"
                ):
                    with lock.LockPool(
                        pool_dir,
                        {"harness_pid": os.getpid()},
                        max_concurrent=3,
                    ):
                        pass

    def test_restrictive_incoming_limit_does_not_join_larger_pool(self):
        pool_dir = os.path.join(self.tmp.name, "restrictive-incoming-pool")
        first = lock.LockPool(
            pool_dir,
            {"harness_pid": os.getpid()},
            max_concurrent=3,
        )
        second = lock.LockPool(
            pool_dir,
            {"harness_pid": os.getpid()},
            max_concurrent=3,
        )
        first.__enter__()
        second.__enter__()
        try:
            with self.assertRaisesRegex(
                lock.LockHeld, r"2 review slot\(s\) held, active limit 1"
            ):
                with lock.LockPool(
                    pool_dir,
                    {"harness_pid": os.getpid()},
                    max_concurrent=1,
                ):
                    pass
        finally:
            second.__exit__(None, None, None)
            first.__exit__(None, None, None)

    def test_pool_selection_guard_timeout_fails_as_contention(self):
        pool_dir = os.path.join(self.tmp.name, "busy-selection-pool")
        held = lock.LockPool(
            pool_dir,
            {"harness_pid": os.getpid()},
            max_concurrent=3,
            selection_timeout=0,
        )

        def busy_selection(_fd, operation):
            if operation == lock.fcntl.LOCK_EX | lock.fcntl.LOCK_NB:
                raise BlockingIOError

        with mock.patch.object(lock.fcntl, "flock", side_effect=busy_selection):
            with self.assertRaisesRegex(lock.LockHeld, "slot selection busy"):
                held.__enter__()

    def test_pool_metadata_update_preserves_slot_metadata(self):
        pool_dir = os.path.join(self.tmp.name, "metadata-pool")
        with lock.LockPool(
            pool_dir,
            {"harness_pid": os.getpid()},
            max_concurrent=3,
        ) as held:
            held.update_meta({"claude_pgid": 12345})
            meta = lock.read_meta(held.lock_dir)
            self.assertEqual(meta["lock_slot"], 0)
            self.assertEqual(meta["max_concurrent"], 3)
            self.assertEqual(meta["claude_pgid"], 12345)

    def test_pool_exit_clears_local_ownership_state(self):
        pool_dir = os.path.join(self.tmp.name, "cleared-state-pool")
        held = lock.LockPool(
            pool_dir,
            {"harness_pid": os.getpid()},
            max_concurrent=3,
        )
        held.__enter__()
        held.__exit__(None, None, None)
        self.assertIsNone(held._lock)
        self.assertIsNone(held.lock_dir)
        self.assertIsNone(held.slot)

    def test_unowned_pool_metadata_update_is_not_reported_as_contention(self):
        pool_dir = os.path.join(self.tmp.name, "unowned-pool")
        held = lock.LockPool(
            pool_dir,
            {"harness_pid": os.getpid()},
            max_concurrent=3,
        )
        with self.assertRaisesRegex(RuntimeError, "unowned review slot"):
            held.update_meta({"claude_pgid": 12345})


if __name__ == "__main__":
    unittest.main()
