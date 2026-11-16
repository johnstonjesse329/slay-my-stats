"""Gamma boundary tests: Steam verification, session integrity, and direct uploads."""
import ast
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "infra/lambda/ingest")]
import handler

SID = "76561198000000001"
OTHER = "76561198000000002"
ORIGIN = "https://gamma.slay-my-stats.com"
SECRET = "a" * 64


class GammaAuthTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"GAMMA_ORIGIN": ORIGIN, "GAMMA_SESSION_SECRET": SECRET,
                                          "ALLOWED_STEAM_IDS": SID})
        self.env.start()
        self.addCleanup(self.env.stop)

    def event(self, path, query="", cookies=()):
        return {"rawPath": path, "rawQueryString": query, "cookies": list(cookies),
                "requestContext": {"http": {"method": "GET"}}}

    def callback(self, sid=SID):
        login = handler.gamma_auth_handler(self.event("/auth/login"), None)
        self.assertEqual(login["statusCode"], 302)
        self.assertEqual(login["headers"]["cache-control"], "no-store")
        params = parse_qs(urlsplit(login["headers"]["location"]).query)
        back = params["openid.return_to"][0]
        state = parse_qs(urlsplit(back).query)["state"][0]
        event = self.event("/auth/callback", urlencode({"state": state, "openid.return_to": back}),
                           ["__Host-gamma-state=" + state])
        return event

    def test_login_and_signed_session(self):
        event = self.callback()
        with patch.object(handler, "verify_openid", return_value=SID) as verify:
            response = handler.gamma_auth_handler(event, None)
        verify.assert_called_once()
        self.assertEqual(response["headers"]["location"], "/")
        cookie = response["cookies"][0]
        self.assertIn("Secure; HttpOnly; SameSite=Lax; Max-Age=43200", cookie)
        token = cookie.split(";", 1)[0].split("=", 1)[1]
        sid, expiry, signature = token.split(".")
        self.assertEqual(sid, SID)
        self.assertGreater(int(expiry), time.time())
        self.assertEqual(signature, hmac.new(SECRET.encode(), (sid + "." + expiry).encode(), hashlib.sha256).hexdigest())
        self.assertIn("Max-Age=0", response["cookies"][1])

    def test_state_and_exact_callback_required(self):
        for event in [self.event("/auth/callback"), self.callback()]:
            if event["cookies"]:
                event["rawQueryString"] += "x"
            with patch.object(handler, "verify_openid") as verify:
                self.assertEqual(handler.gamma_auth_handler(event, None)["statusCode"], 401)
                verify.assert_not_called()

    def test_denied_account_and_unverified_assertion(self):
        with patch.object(handler, "verify_openid", return_value=OTHER):
            response = handler.gamma_auth_handler(self.callback(), None)
            self.assertEqual(response["statusCode"], 403)
            self.assertEqual(len(response["cookies"]), 1)
        with patch.object(handler, "verify_openid", side_effect=handler.IngestError(401, "bad_openid", "Bad")):
            self.assertEqual(handler.gamma_auth_handler(self.callback(), None)["statusCode"], 401)

    def test_upload_authorization_uses_verified_account(self):
        with patch.object(handler, "verify_ticket", return_value=OTHER):
            with self.assertRaises(handler.IngestError) as error:
                handler._mod_player({"steamId": OTHER, "ticket": "ticket"})
            self.assertEqual(error.exception.status, 403)
        with patch.object(handler, "verify_openid", return_value=OTHER):
            # An unauthorized browser account is refused before reading account data or signing S3 forms.
            from unittest.mock import Mock
            store = Mock()
            store.get.return_value = None
            with self.assertRaises(handler.IngestError) as error:
                handler.authorize({}, "127.0.0.1", store, [ORIGIN], Mock())
            self.assertEqual(error.exception.status, 403)

    @unittest.skipUnless(shutil.which("node"), "Node required for CloudFront runtime checks")
    def test_edge_rejects_forgery_expiry_and_removed_accounts(self):
        tree = ast.parse((ROOT / "infra/slay_my_stats/slay_my_stats_stack.py").read_text())
        template = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "STEAM_GATE_CODE" for t in n.targets))
        expires = str(int(time.time()) + 3600)
        def token(sid, expiry):
            payload = sid + "." + expiry
            return payload + "." + hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        good = token(SID, expires)
        tokens = ["", "junk", good, good[:-1] + ("0" if good[-1] != "0" else "1"),
                  token(SID, "1000000000"), token(OTHER, expires)]
        for rewrite in ["", '    request.uri = "/index.html";\n']:
            code = template % (json.dumps([SID]), json.dumps(SECRET), rewrite)
            script = code + "\nprocess.stdout.write(JSON.stringify(" + json.dumps(tokens) + """.map(value => handler({request: {
                uri: '/u/test', cookies: {'__Host-gamma': {value: value}}
            }}))));"""
            result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
            responses = json.loads(result.stdout)
            self.assertEqual(responses[2]["uri"], "/index.html" if rewrite else "/u/test")
            for i in [0, 1, 3, 4, 5]:
                self.assertEqual(responses[i]["statusCode"], 302)
                self.assertEqual(responses[i]["headers"]["location"]["value"], "/auth/login")
