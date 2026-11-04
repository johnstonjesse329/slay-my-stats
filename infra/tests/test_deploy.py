"""The deploy's own guards: the ingest smoke check and the gamma-before-prod gate.

    infra\\.venv\\Scripts\\python.exe -m unittest discover infra/tests

tools/deploy.py answers an empty POST to the ingest URL (any status under 500 passes, a 5xx or
silence fails the deploy) and lets production take only the commit gamma last passed.
"""
import os
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
            deploy.require_gamma_ok()

    def test_prod_takes_the_commit_gamma_passed(self):
        self.head("a" * 40)
        deploy.record_gamma_ok()
        deploy.require_gamma_ok()

    def test_prod_stops_on_a_newer_commit(self):
        self.head("a" * 40)
        deploy.record_gamma_ok()
        self.head("b" * 40)
        with self.assertRaisesRegex(deploy.DeployError, "last passed aaaaaaa"):
            deploy.require_gamma_ok()

    def test_a_dirty_tree_records_nothing(self):
        self.head("a" * 40, dirty=True)
        deploy.record_gamma_ok()
        self.assertFalse(self.file.exists())

    def test_the_hotfix_override(self):
        self.head("a" * 40)
        os.environ["DEPLOY_SKIP_GAMMA"] = "1"
        deploy.require_gamma_ok()


if __name__ == "__main__":
    unittest.main()
