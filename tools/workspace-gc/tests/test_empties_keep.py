import os
import shutil
import tempfile
import time
import unittest

from workspace_gc import empties
from workspace_gc.signals import Signals


class EmptiesKeepGlobTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="wsgc-empties-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        old = time.time() - 48 * 3600
        for name in ("ws-x-on-device-ad-y", "ws-archive-media-finish", "ws-plain"):
            p = os.path.join(self.root, name)
            os.makedirs(p)
            os.utime(p, (old, old))

    def reasons(self, keep):
        orig = empties._now
        empties._now = lambda: time.time() + 48 * 3600
        self.addCleanup(setattr, empties, "_now", orig)
        found = empties.scan([self.root], keep, Signals())
        return {os.path.basename(e.path): e.reason for e in found}

    def test_broad_prefix_glob_does_not_protect_everything(self):
        r = self.reasons([os.path.join(self.root, "*on-device-ad*")])
        self.assertEqual(r["ws-x-on-device-ad-y"], "keep-listed")
        self.assertEqual(r["ws-archive-media-finish"], "")
        self.assertEqual(r["ws-plain"], "")

    def test_segment_glob_below_directory_protects(self):
        r = self.reasons([os.path.join(self.root, "ws-pl*", "repo")])
        self.assertEqual(r["ws-plain"], "keep-listed")
        self.assertEqual(r["ws-archive-media-finish"], "")

    def test_plain_path_below_directory_still_protects(self):
        r = self.reasons([os.path.join(self.root, "ws-plain", "sub")])
        self.assertEqual(r["ws-plain"], "keep-listed")
        self.assertEqual(r["ws-archive-media-finish"], "")


if __name__ == "__main__":
    unittest.main()
