"""Exercise local feedback checkpoints against an isolated Git repository."""

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import feedback_batch as batch


class FeedbackBatchTest(unittest.TestCase):
    def setUp(self):
        scratch = batch.ROOT / "local_data"
        scratch.mkdir(exist_ok=True)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir=scratch))).resolve()
        self.handoffs = self.root / "local_data" / "feedback" / "handoffs"
        self.handoffs.mkdir(parents=True)
        self.enterContext(patch.multiple(batch, ROOT=self.root, BATCH=self.handoffs.parent / "batch.json"))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.git("init", "-q")
        self.base = self.commit("base")
        self.initial = self.commit("candidate")
        self.revised = self.commit("revision")
        batch._save({"entries": [
            {"seq": 1, "env": "prod", "group": "charts", "status": "planned"},
            {"seq": 2, "env": "gamma", "group": "inbox", "status": "planned"},
        ]})

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.com",
                 "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def handoff(self, name):
        path = self.handoffs / f"{name}.md"
        path.touch()
        return path

    def record_candidate(self, commit):
        batch.record_candidate(["FB-1"], self.base, commit, "Syntax check passed", self.handoff(commit))

    def test_queue_scopes_production_and_shows_pending_verification(self):
        self.record_candidate(self.initial)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            batch.queue(source="prod", show_ids=True)
        self.assertIn("verification pending: FB-1 [prod]", output.getvalue())
        self.assertNotIn("FB-2", output.getvalue())

    def test_two_failures_across_revisions_defer_only_affected_report(self):
        self.record_candidate(self.initial)
        first = self.handoff("first-review")
        for _ in range(2):
            batch.record_review(["FB-1"], self.initial, "changes-requested", first, "Keyboard check failed")
        entry = batch._load()["entries"][0]
        self.assertEqual(batch._queue_checkpoint(entry), "validation failed")
        self.assertEqual(len(entry["validation_failures"]), 1)

        self.record_candidate(self.revised)
        entry = batch._load()["entries"][0]
        self.assertNotIn("agent_review", entry)
        batch.record_review(["FB-1"], self.revised, "inconclusive", self.handoff("second-review"), "Fixture unavailable")
        blocked, other = batch._load()["entries"]
        self.assertEqual(batch._queue_checkpoint(blocked), "blocked")
        self.assertEqual(blocked["blocker"], "Fixture unavailable")
        self.assertEqual(len(blocked["validation_failures"]), 2)
        self.assertEqual(batch._queue_checkpoint(other), "queued")
        with self.assertRaises(SystemExit):
            self.record_candidate(self.initial)

    def test_review_must_match_every_recorded_candidate(self):
        self.record_candidate(self.initial)
        handoff = self.handoff("passing-review")
        with self.assertRaises(SystemExit):
            batch.record_review(["FB-1", "FB-2"], self.initial, "pass", handoff)
        with self.assertRaises(SystemExit):
            batch.record_review(["FB-1"], self.revised, "pass", handoff)
        self.assertNotIn("agent_review", batch._load()["entries"][0])

        batch.record_review(["FB-1"], self.initial, "pass", handoff)
        entry = batch._load()["entries"][0]
        self.assertEqual(batch._queue_checkpoint(entry), "candidate")
        self.assertEqual(entry["status"], "built")


if __name__ == "__main__":
    unittest.main()
