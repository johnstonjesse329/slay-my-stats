"""The deploy lock and building a commit from an export (tools/deploy.py), against a throwaway repo.

    python tools/test_deploy.py

Touches no AWS: only deploy_lock(), lock_status(), export_commit()/finish_export() and check_pre_push().
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy  # noqa: E402


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class DeployTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "repo"
        root.mkdir()
        sh(root, "git", "init", "-q")
        sh(root, "git", "config", "user.email", "test@example.com")
        sh(root, "git", "config", "user.name", "test")
        (root / ".gitignore").write_text("card_final/\ncard_data.json\ndist/\nlocal_data/\ninfra/cdk.context.json\n")
        (root / "infra").mkdir()
        (root / "infra" / "app.py").write_text("committed\n")
        (root / "build_site.py").write_text("v1\n")
        sh(root, "git", "add", "-A")
        sh(root, "git", "commit", "-qm", "v1")
        self.v1 = sh(root, "git", "rev-parse", "HEAD")
        (root / "build_site.py").write_text("v2, uncommitted\n")  # the checkout is dirty and ahead
        (root / "card_final").mkdir()
        (root / "card_final" / "a.png").write_bytes(b"art")
        (root / "event_images").mkdir()
        (root / "event_images" / "a.webp").write_bytes(b"event art")
        (root / "card_data.json").write_text("{}")
        (root / "dist").mkdir()
        (root / "infra" / "cdk.context.json").write_text('{"secret": "x"}')
        self.root = root
        self._saved = deploy._HERE, deploy.SRC, deploy.LOCAL
        deploy._HERE = deploy.SRC = deploy.LOCAL = root

    def tearDown(self):
        deploy._HERE, deploy.SRC, deploy.LOCAL = self._saved
        self.tmp.cleanup()

    def test_main_checkout_is_found_from_a_worktree(self):
        wt = Path(self.tmp.name) / "wt"
        sh(self.root, "git", "worktree", "add", "-q", "--detach", str(wt))
        deploy._HERE = wt
        self.assertEqual(deploy.main_checkout().resolve(), self.root.resolve())

    def test_second_deploy_is_refused_and_lock_released(self):
        lock = self.root / ".git" / deploy.LOCK_NAME
        with deploy.deploy_lock("gamma deploy", self.v1):
            self.assertEqual(json.loads(lock.read_text())["commit"], self.v1)
            with self.assertRaises(deploy.DeployError) as e:
                with deploy.deploy_lock("prod deploy", self.v1):
                    self.fail("got the lock twice")
            self.assertIn("gamma deploy of " + self.v1[:7], str(e.exception))
            self.assertIn("Wait for it", str(e.exception))
        self.assertFalse(lock.exists())

    def test_lock_released_when_the_deploy_fails(self):
        with self.assertRaises(RuntimeError):
            with deploy.deploy_lock("gamma deploy", None):
                raise RuntimeError("cdk blew up")
        self.assertFalse((self.root / ".git" / deploy.LOCK_NAME).exists())

    def test_stale_lock_points_at_break_lock_and_break_lock_clears_it(self):
        lock = self.root / ".git" / deploy.LOCK_NAME
        lock.write_text(json.dumps({"what": "gamma deploy", "since": time.time() - 3 * 3600, "pid": 1}))
        with self.assertRaises(deploy.DeployError) as e:
            with deploy.deploy_lock("gamma deploy", None):
                pass
        self.assertIn("--break-lock", str(e.exception))
        self.assertTrue(lock.exists(), "a refused deploy must not remove someone else's lock")
        with contextlib.redirect_stdout(io.StringIO()):
            deploy.lock_status(break_it=True)
        self.assertFalse(lock.exists())

    def test_released_lock_does_not_remove_a_newer_holder(self):
        lock = self.root / ".git" / deploy.LOCK_NAME
        with deploy.deploy_lock("gamma deploy", None):
            lock.write_text(json.dumps({"what": "after --break-lock", "since": 1, "pid": 2}))
        self.assertTrue(lock.exists())

    def test_export_builds_the_commit_and_borrows_inputs(self):
        with contextlib.redirect_stdout(io.StringIO()):
            out = deploy.export_commit(self.v1)
        self.assertEqual((out / "build_site.py").read_text(), "v1\n", "built the checkout, not the commit")
        self.assertEqual((out / "card_final" / "a.png").read_bytes(), b"art")
        self.assertTrue(deploy._is_link(out / "card_final"))
        self.assertEqual((out / "event_images" / "a.webp").read_bytes(), b"event art")
        self.assertTrue(deploy._is_link(out / "event_images"))
        self.assertEqual((out / "card_data.json").read_text(), "{}")
        self.assertEqual((out / "infra" / "cdk.context.json").read_text(), '{"secret": "x"}')
        self.assertFalse((out / "dist").exists(), "dist/ is an output, not an input")
        self.assertFalse((out / "local_data").exists())
        (out / "infra" / "cdk.context.json").write_text('{"secret": "x", "lookup": 1}')
        with contextlib.redirect_stdout(io.StringIO()):
            deploy.finish_export(out)
        self.assertFalse(out.exists())
        self.assertTrue((self.root / "card_final" / "a.png").exists(), "deleted through the link")
        self.assertTrue((self.root / "event_images" / "a.webp").exists(), "deleted through the link")
        self.assertIn("lookup", (self.root / "infra" / "cdk.context.json").read_text())

    def test_pre_push_deploys_the_pushed_commit_from_a_dirty_checkout(self):
        line = f"refs/heads/gamma {self.v1} refs/heads/gamma {deploy.ZERO_SHA}"
        self.assertEqual(deploy.check_pre_push([line]), ("gamma", self.v1))
        self.assertIsNone(deploy.check_pre_push([f"refs/heads/x {self.v1} refs/heads/x {deploy.ZERO_SHA}"]))

    def test_ref_resolves_or_says_why_not(self):
        self.assertEqual(deploy.use_ref(["--ref", "HEAD"]), self.v1)
        self.assertIsNone(deploy.use_ref([]))
        with self.assertRaises(deploy.DeployError):
            deploy.use_ref(["--ref", "no-such-branch"])


class RebuildInputsTest(unittest.TestCase):
    def test_stats_layout_is_part_of_what_triggers_a_rebuild(self):
        # A new PICK_SLOTS etc. makes the pages hide "All players" until the stats are recounted.
        inputs = deploy.profile_rebuild_inputs()
        self.assertRegex(inputs["stats_layout"], r"^\d+\.\d+\.\d+\.\d+$")
        self.assertIn("parser_version", inputs)


if __name__ == "__main__":
    unittest.main()
