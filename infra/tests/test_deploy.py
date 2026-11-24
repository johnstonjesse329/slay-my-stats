"""The deploy's own guards: the ingest smoke check and the gamma-before-prod gate.

    infra\\.venv\\Scripts\\python.exe -m unittest discover infra/tests

tools/deploy.py answers an empty POST to the ingest URL (any status under 500 passes, a 5xx or
silence fails the deploy) and lets production take only the commit gamma last passed.
"""
import os
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "tools")]

import deploy  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402


def serve(status):
    """A local server that answers every POST with this status; returns (url, stop)."""
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}/", srv.shutdown


class SmokeTest(unittest.TestCase):
    def check(self, status):
        url, stop = serve(status)
        self.addCleanup(stop)
        return lambda: deploy.smoke_test_ingest(url)

    def test_passes_when_the_function_rejects_the_empty_request(self):
        for status in (200, 400, 401, 403, 429):
            with self.subTest(status=status):
                self.check(status)()

    def test_fails_on_a_server_error(self):
        # A Lambda that crashes on import answers 502 to everything.
        for status in (500, 502, 503):
            with self.subTest(status=status), self.assertRaisesRegex(deploy.DeployError, str(status)):
                self.check(status)()

    def test_fails_when_nothing_answers(self):
        url, stop = serve(401)
        stop()  # the port is closed by the time it is asked
        with self.assertRaises(deploy.DeployError):
            deploy.smoke_test_ingest(url)


class GammaGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "slay-my-stats-gamma-ok"
        for target, new in (("_gamma_ok_file", lambda: self.file),):
            p = mock.patch.object(deploy, target, new)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {}, clear=False)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("DEPLOY_SKIP_GAMMA", None)

    def head(self, sha, dirty=False):
        def fake_git(*args):
            if args[:1] == ("status",):
                return " M x" if dirty else ""
            return sha
        p = mock.patch.object(deploy, "git", fake_git)
        p.start()
        self.addCleanup(p.stop)

    def test_prod_stops_without_a_gamma_pass(self):
        self.head("a" * 40)
        with self.assertRaisesRegex(deploy.DeployError, "no pass recorded"):
            deploy.require_gamma_ok(None)

    def test_prod_takes_the_commit_gamma_passed(self):
        self.head("a" * 40)
        deploy.record_gamma_ok("a" * 40)
        deploy.require_gamma_ok(None)

    def test_prod_stops_on_a_newer_commit(self):
        self.head("a" * 40)
        deploy.record_gamma_ok("a" * 40)
        self.head("b" * 40)
        with self.assertRaisesRegex(deploy.DeployError, "last passed aaaaaaa"):
            deploy.require_gamma_ok(None)

    def test_a_dirty_tree_records_nothing(self):
        self.head("a" * 40, dirty=True)
        deploy.record_gamma_ok(None)  # a dirty tree has no commit to pass
        self.assertFalse(self.file.exists())

    def test_the_hotfix_override(self):
        self.head("a" * 40)
        os.environ["DEPLOY_SKIP_GAMMA"] = "1"
        deploy.require_gamma_ok(None)


class FeedbackTableGuard(unittest.TestCase):
    """The table's stack deploys only by --feedback-table; a push stops while its file differs."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "slay-my-stats-feedback-ok"
        self.calls, self.diff, self.dirty, self.head = [], "", "", "a" * 40
        def fake_git(*args):
            self.calls.append(("git", *args))
            return {"diff": self.diff, "status": self.dirty}.get(args[0], self.head)
        def fake_run(args, **kw):
            self.calls.append(tuple(args))
            out = self.cdk_diff if args[1] == "diff" else ""
            return deploy.subprocess.CompletedProcess(args, 0, out, "")
        self.cdk_diff = "There were no differences"
        for target, new in (("_feedback_ok_file", lambda: self.file), ("git", fake_git), ("run", fake_run)):
            p = mock.patch.object(deploy, target, new)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {}, clear=False)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("DEPLOY_YES", None)

    def test_a_push_stops_with_no_table_deploy_recorded(self):
        with self.assertRaisesRegex(deploy.DeployError, "--feedback-table"):
            deploy.require_feedback_table(None)

    def test_a_push_goes_ahead_while_the_file_matches(self):
        self.file.write_text("c" * 40)
        deploy.require_feedback_table(None)
        self.assertIn(("git", "diff", "--name-only", "c" * 40, "--", deploy.FEEDBACK_STACK_FILE), self.calls)

    def test_a_push_stops_once_the_file_changed(self):
        self.file.write_text("c" * 40)
        self.diff = deploy.FEEDBACK_STACK_FILE
        with self.assertRaisesRegex(deploy.DeployError, r"changed since .*(ccccccc)"):
            deploy.require_feedback_table(None)

    def test_an_unchanged_table_records_the_commit_without_deploying(self):
        deploy.deploy_feedback_table()
        self.assertEqual(self.file.read_text(), "a" * 40)
        self.assertFalse([c for c in self.calls if c[:2] == ("cdk", "deploy")])

    def test_a_change_is_asked_about_and_deploys_only_the_table(self):
        self.cdk_diff = "[+] AWS::DynamoDB::GlobalTable"
        with mock.patch.object(deploy, "ask", return_value=True):
            deploy.deploy_feedback_table()
        self.assertIn(("cdk", "deploy", deploy.FEEDBACK_STACK, "--exclusively", "--require-approval", "never"), self.calls)
        self.assertEqual(self.file.read_text(), "a" * 40)

    def test_a_declined_change_deploys_and_records_nothing(self):
        self.cdk_diff = "[+] AWS::DynamoDB::GlobalTable"
        os.environ["DEPLOY_YES"] = "1"  # gamma's skip does not reach the table
        with mock.patch.object(deploy, "ask", return_value=False), self.assertRaises(deploy.DeployError):
            deploy.deploy_feedback_table()
        self.assertFalse(self.file.exists())

    def test_an_uncommitted_file_records_nothing(self):
        self.dirty = " M " + deploy.FEEDBACK_STACK_FILE
        deploy.deploy_feedback_table()
        self.assertFalse(self.file.exists())


class ProfileRebuildGuard(unittest.TestCase):
    def setUp(self):
        self.inputs = {"parser_version": 7, "known_ids_sha256": "new"}
        self.s3 = mock.Mock()
        mocks = (
            mock.patch("boto3.client", return_value=self.s3),
            mock.patch.object(deploy, "profile_rebuild_inputs", return_value=self.inputs),
            mock.patch.object(deploy, "run"),
        )
        for patcher in mocks:
            patcher.start()
            self.addCleanup(patcher.stop)

    def marker(self, previous):
        self.s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(previous).encode()), "ETag": '"old"'}

    def test_matches_skip_this_stage(self):
        self.marker(self.inputs)
        deploy.rebuild_held_runs("gamma")
        deploy.run.assert_not_called()
        self.s3.get_object.assert_called_once_with(Bucket=deploy.DATA_BUCKETS["gamma"], Key=deploy.PROFILE_REBUILD_KEY)
        self.s3.put_object.assert_not_called()

    def test_each_input_change_rebuilds_before_recording(self):
        for changed in ({"parser_version": 6}, {"known_ids_sha256": "old"}):
            with self.subTest(changed=changed):
                self.marker({**self.inputs, **changed})
                deploy.run.reset_mock()
                deploy.rebuild_held_runs("prod")
                args = [call.args[0] for call in deploy.run.call_args_list]
                self.assertEqual([Path(arg[1]).name for arg in args], ["rebuild_profiles.py", "rebuild_stats.py"])
                self.assertIn("--strict", args[0])
                self.assertTrue(all(arg[-1] == deploy.DATA_BUCKETS["prod"] for arg in args))
                self.s3.put_object.assert_called_with(Bucket=deploy.DATA_BUCKETS["prod"], Key=deploy.PROFILE_REBUILD_KEY,
                                                        Body=json.dumps(self.inputs).encode(), ContentType="application/json",
                                                        IfMatch='"old"')

    def test_missing_marker_initializes_after_success(self):
        self.s3.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        deploy.rebuild_held_runs("gamma")
        self.assertEqual(deploy.run.call_count, 2)
        self.assertEqual(self.s3.put_object.call_args.kwargs["IfNoneMatch"], "*")

    def test_failed_rebuild_saves_no_marker(self):
        self.marker({**self.inputs, "parser_version": 6})
        deploy.run.side_effect = [None, deploy.DeployError("stats recount failed")]
        deploy.rebuild_held_runs("gamma")
        self.s3.put_object.assert_not_called()


class ArtDeploy(unittest.TestCase):
    def setUp(self):
        self.s3 = mock.Mock()
        self.bucket = deploy.DATA_BUCKETS["gamma"]
        self.key = "card_final/example.webp"
        self.art = {self.key: "abc"}
        self.real_check_art = deploy.check_art
        patcher = mock.patch.object(deploy, "check_art")  # tested on its own below
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_art_differing_from_the_manifest_stops_the_deploy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            (root / "tools" / "art_manifest.json").write_text(
                json.dumps({"files": {"ui_icons/map/marked_x.png": "0" * 64}}))
            with mock.patch.object(deploy, "LOCAL", root), mock.patch.object(deploy, "SRC", root):
                with self.assertRaisesRegex(deploy.DeployError, "missing: ui_icons/map/marked_x.png"):
                    self.real_check_art()

    def test_first_deploy_seeds_from_existing_s3_objects(self):
        self.s3.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        self.s3.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": self.key, "ETag": '"abc"'}, {"Key": "index.html", "ETag": '"extra"'}]},
        ]
        self.s3.put_object.return_value = {"ETag": '"baseline"'}
        self.assertEqual(deploy.read_art_manifest(self.s3, self.bucket, self.art), (self.art, '"baseline"'))
        self.assertEqual(json.loads(self.s3.put_object.call_args.kwargs["Body"]), self.art)
        self.assertEqual(self.s3.put_object.call_args.kwargs["IfNoneMatch"], "*")

    def test_existing_manifest_skips_remote_art_listing(self):
        self.s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(self.art).encode()), "ETag": '"art"'}
        self.assertEqual(deploy.read_art_manifest(self.s3, self.bucket, self.art), (self.art, '"art"'))
        self.s3.get_paginator.assert_not_called()
        self.s3.put_object.assert_not_called()

    def test_same_size_art_edit_changes_digest(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(deploy, "LOCAL", Path(tmp)), \
                mock.patch.object(deploy, "ART_DIRS", ["card_final"]):
            path = Path(tmp) / self.key
            path.parent.mkdir()
            path.write_bytes(b"one")
            first = deploy.art_digests()
            path.write_bytes(b"two")
            self.assertNotEqual(first[self.key], deploy.art_digests()[self.key])

    def test_art_manifest_advances_after_invalidation(self):
        self.s3.get_object.return_value = {"Body": io.BytesIO(b'{}'), "ETag": '"old"'}
        self.s3.put_object.return_value = {"ETag": '"new"'}
        calls = mock.Mock()
        with mock.patch("boto3.client", return_value=self.s3), mock.patch.object(deploy, "run"), \
                mock.patch.object(deploy, "art_digests", return_value=self.art), \
                mock.patch.object(deploy, "upload_changed_dist", return_value=[]), \
                mock.patch.object(deploy, "upload_art_object", calls.upload), \
                mock.patch.object(deploy, "invalidate", calls.invalidate):
            self.s3.attach_mock(calls, "deploy")
            deploy.deploy_site("prod")
        self.assertEqual([entry[0] for entry in self.s3.mock_calls],
                         ["get_object", "deploy.upload", "deploy.invalidate", "put_object"])
        calls.invalidate.assert_called_once_with(["/" + self.key])
        self.assertEqual(self.s3.put_object.call_args.kwargs["IfMatch"], '"old"')

    def _deploy_site(self, stage, dist):
        self.s3.get_object.return_value = {"Body": io.BytesIO(b'{}'), "ETag": '"old"'}
        self.s3.put_object.return_value = {"ETag": '"new"'}
        invalidate = mock.Mock()
        with mock.patch("boto3.client", return_value=self.s3), mock.patch.object(deploy, "run"),                 mock.patch.object(deploy, "art_digests", return_value=self.art),                 mock.patch.object(deploy, "upload_changed_dist", return_value=dist),                 mock.patch.object(deploy, "upload_art_object"),                 mock.patch.object(deploy, "invalidate", invalidate):
            deploy.deploy_site(stage)
        return invalidate

    def test_gamma_never_invalidates_but_records_art(self):
        invalidate = self._deploy_site("gamma", ["index.html"])
        invalidate.assert_not_called()
        self.assertEqual(self.s3.put_object.call_args.kwargs["IfMatch"], '"old"')

    def test_hashed_files_are_not_invalidated(self):
        invalidate = self._deploy_site("prod", ["app.3fa91c20ab.js", "dashboard.0123456789.css", "index.html"])
        invalidate.assert_called_once_with(["/" + self.key, "/index.html"])


if __name__ == "__main__":
    unittest.main()
