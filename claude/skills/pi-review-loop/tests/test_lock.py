import os
import tempfile
import unittest
from pi_review_loop import lock


class TestLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lock_dir = os.path.join(self.tmp.name, "pi-review.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def test_acquire_and_release(self):
        with lock.Lock(self.lock_dir, {"pi_pgid": -1}):
            self.assertTrue(os.path.isdir(self.lock_dir))
        self.assertFalse(os.path.exists(self.lock_dir))

    def test_second_acquire_raises_when_held_by_live_group(self):
        # Use our own pgid as a stand-in for a "live" Pi group.
        meta = {"pi_pgid": os.getpgrp(), "command": "pi", "cwd": os.getcwd()}
        with lock.Lock(self.lock_dir, meta):
            with self.assertRaises(lock.LockHeld):
                with lock.Lock(self.lock_dir, {"pi_pgid": -1}):
                    pass

    def test_reclaims_stale_lock_when_group_dead(self):
        # Pre-create a lock whose recorded pgid is dead (no such group).
        os.mkdir(self.lock_dir)
        lock.write_meta(self.lock_dir, {
            "pi_pgid": 2_000_000_000,  # not a live group
            "command": "pi", "cwd": os.getcwd(),
        })
        # A fresh acquire should reclaim it rather than raise.
        with lock.Lock(self.lock_dir, {"pi_pgid": -1}):
            self.assertTrue(os.path.isdir(self.lock_dir))

    def test_does_not_reclaim_live_harness_pid(self):
        os.mkdir(self.lock_dir)
        lock.write_meta(self.lock_dir, {"harness_pid": os.getpid(),
                                        "command": "pi-review-loop"})
        with self.assertRaises(lock.LockHeld):
            with lock.Lock(self.lock_dir, {"harness_pid": os.getpid()}):
                pass

    def test_reclaims_dead_harness_pid(self):
        os.mkdir(self.lock_dir)
        lock.write_meta(self.lock_dir, {"harness_pid": 2_000_000_000,
                                        "command": "pi-review-loop"})
        with lock.Lock(self.lock_dir, {"harness_pid": os.getpid()}):
            self.assertTrue(os.path.isdir(self.lock_dir))

    def test_does_not_reclaim_lock_with_missing_meta(self):
        # No meta.json => treat as held (fail closed), do not reclaim.
        os.mkdir(self.lock_dir)
        with self.assertRaises(lock.LockHeld):
            with lock.Lock(self.lock_dir, {"pi_pgid": -1}):
                pass

    def test_read_meta_returns_empty_on_corrupt_json(self):
        os.mkdir(self.lock_dir)
        with open(os.path.join(self.lock_dir, lock.META_NAME), "w") as fh:
            fh.write("{not json")
        self.assertEqual(lock.read_meta(self.lock_dir), {})

    def test_exit_tolerates_externally_removed_dir(self):
        import shutil
        with lock.Lock(self.lock_dir, {"pi_pgid": -1}):
            shutil.rmtree(self.lock_dir)  # vanished mid-context
        # __exit__ must not raise

    def test_pgid_is_pi_false_for_non_pi_group(self):
        # The test runner is python, not pi -> guard must refuse to kill it.
        self.assertFalse(lock._pgid_is_pi(os.getpgrp()))

    def test_pgid_is_pi_false_for_dead_pgid(self):
        self.assertFalse(lock._pgid_is_pi(2_000_000_000))

    def test_reclaims_dead_harness_even_when_pgid_not_pi(self):
        # harness dead + a pi_pgid that is NOT pi: reclaim still removes the lock,
        # but must not kill the unrelated group (guarded by _pgid_is_pi).
        os.mkdir(self.lock_dir)
        lock.write_meta(self.lock_dir, {"harness_pid": 2_000_000_000,
                                        "pi_pgid": os.getpgrp(),
                                        "command": "pi-review-loop"})
        with lock.Lock(self.lock_dir, {"harness_pid": os.getpid()}):
            self.assertTrue(os.path.isdir(self.lock_dir))


if __name__ == "__main__":
    unittest.main()
