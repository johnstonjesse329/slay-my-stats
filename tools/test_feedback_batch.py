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

    def test_backlog_dry_run_then_apply_on_each_source(self):
        entries = batch._load()
        for e in entries["entries"]:
            e.update(id=f"note-{e['seq']}", author="author-1")
        batch._save(entries)
        notes = {"note-1": {}, "note-2": {}}
        calls = []

        def change(db, table, env, note_id, steam, fn):
            calls.append((env, note_id))
            fn(notes[note_id])

        with patch.object(batch, "_db", return_value=object()), patch.object(batch.feedback, "_change", change):
            batch.backlog(["FB-1", "FB-2"], "  After the chart rework  ")
            self.assertEqual(calls, [])
            batch.backlog(["FB-1", "FB-2"], "  After the chart rework  ", apply=True)
            self.assertEqual(calls, [("prod", "note-1"), ("gamma", "note-2")])
            self.assertEqual(notes["note-1"]["backlog"]["reason"], "After the chart rework")
            self.assertEqual([e["inbox_status"] for e in batch._load()["entries"]], ["backlog", "backlog"])
            with contextlib.redirect_stdout(io.StringIO()) as output:
                batch.queue()
            self.assertIn("0 active", output.getvalue())

            batch.backlog(["FB-1"], apply=True)  # already there: no second write
            self.assertEqual(len(calls), 2)
            batch.backlog(["FB-1"], on=False, apply=True)
            self.assertNotIn("backlog", notes["note-1"])
            self.assertEqual(batch._load()["entries"][0]["inbox_status"], "open")

    def test_backlog_skips_resolved_and_long_reasons(self):
        entries = batch._load()
        entries["entries"][0].update(id="note-1", author="1", inbox_status="resolved")
        batch._save(entries)
        with patch.object(batch, "_db") as db:
            with self.assertRaises(SystemExit):
                batch.backlog(["FB-1"], "x" * 501, apply=True)
            batch.backlog(["FB-1"], apply=True)
        self.assertNotIn("backlog", batch._load()["entries"][0].get("inbox_status", ""))
        db.assert_called_once()


if __name__ == "__main__":
    unittest.main()
