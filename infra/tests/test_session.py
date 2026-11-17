"""Prod sign-in (session.py): the 30-day cookie, its key from Parameter Store, and where sign-in returns to."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "infra/lambda/ingest")]
import handler  # noqa: E402
import session  # noqa: E402

SID = "76561198000000001"
ORIGIN = "https://slay-my-stats.test"
PARAM = "/slay-my-stats/session-key"


class ProdSessionTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"SITE_ORIGIN": ORIGIN, "SESSION_SECRET_PARAM_NAME": PARAM})
        env.start()
        self.addCleanup(env.stop)
        for name in ("GAMMA_SESSION_SECRET", "GAMMA_ORIGIN", "SESSION_SECRET", "ALLOWED_STEAM_IDS"):
            os.environ.pop(name, None)
        self.ssm = MagicMock()
        self.ssm.get_parameter.return_value = {"Parameter": {"Value": "k" * 64}}
        client = patch("boto3.client", return_value=self.ssm)
        client.start()
        self.addCleanup(client.stop)
        session._secret = None
        self.addCleanup(setattr, session, "_secret", None)

    def event(self, path, query="", cookies=(), method="GET", origin=None):
        return {"rawPath": path, "rawQueryString": query, "cookies": list(cookies),
                "headers": {"origin": origin} if origin else {},
                "requestContext": {"http": {"method": method}}}

    def signed_in(self, now=None):
        return session.session_cookie(SID, now).split(";", 1)[0]

    def test_key_is_read_once_from_parameter_store(self):
        cookie = self.signed_in()
        self.assertEqual(session.steam_id(self.event("/auth/me", cookies=[cookie])), SID)
        self.ssm.get_parameter.assert_called_once_with(Name=PARAM, WithDecryption=True)

    def test_cookie_lasts_30_days_and_any_account_may_sign_in(self):
        set_cookie = session.session_cookie("76561198000000002")
        self.assertTrue(set_cookie.startswith("__Host-session="))
        self.assertIn("Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=2592000", set_cookie)
        cookie = self.signed_in(now=time.time() - 30 * 24 * 3600 + 60)
        self.assertEqual(session.steam_id(self.event("/", cookies=[cookie])), SID)
        expired = self.signed_in(now=time.time() - 30 * 24 * 3600 - 1)
        self.assertIsNone(session.steam_id(self.event("/", cookies=[expired])))

    def test_forged_or_mangled_cookies(self):
        good = self.signed_in()
        name, value = good.split("=", 1)
        steam, expiry, sig = value.split(".")
        for bad in [f"{name}={steam}.{int(expiry) + 1}.{sig}", f"{name}=76561198000000002.{expiry}.{sig}",
                    f"{name}={value}x", f"{name}=junk", f"__Host-gamma={value}", 'x="unterminated']:
            self.assertIsNone(session.steam_id(self.event("/", cookies=[bad])), bad)

    def test_me(self):
        self.assertEqual(session.handle(self.event("/auth/me"))["statusCode"], 401)
        response = session.handle(self.event("/auth/me", cookies=[self.signed_in()]))
        self.assertEqual(json.loads(response["body"]), {"steamId": SID})
        self.assertEqual(response["headers"]["cache-control"], "no-store")

    def login(self, next_path=None):
        query = urlencode({"next": next_path}) if next_path is not None else ""
        response = session.handle(self.event("/auth/login", query))
        self.assertEqual(response["statusCode"], 302)
        steam = parse_qs(urlsplit(response["headers"]["location"]).query)
        self.assertEqual(steam["openid.realm"], [ORIGIN + "/"])
        back = steam["openid.return_to"][0]
        state = response["cookies"][0].split(";", 1)[0]
        self.assertTrue(state.startswith("__Host-session-state="))
        return back, state

    def test_sign_in_returns_to_the_page_it_started_on(self):
        back, state = self.login("/upload")
        self.assertTrue(back.startswith(ORIGIN + "/auth/callback?"))
        query = urlsplit(back).query + "&" + urlencode({"openid.return_to": back})
        with patch.object(handler, "verify_openid", return_value=SID) as verify:
            response = session.handle(self.event("/auth/callback", query, [state]))
        verify.assert_called_once()
        self.assertEqual(verify.call_args.args[1], [ORIGIN])
        self.assertEqual(response["headers"]["location"], "/upload")
        self.assertTrue(response["cookies"][0].startswith("__Host-session="))
        self.assertIn("Max-Age=0", response["cookies"][1])

    def test_next_never_leaves_the_site(self):
        for bad in ["//evil.example/", "https://evil.example/", "/\\evil.example", "evil", "/a b", "/" + "a" * 600]:
            back, _ = self.login(bad)
            self.assertEqual(parse_qs(urlsplit(back).query)["next"], ["/"], bad)
        back, _ = self.login("/u/someone?tab=runs")
        self.assertEqual(parse_qs(urlsplit(back).query)["next"], ["/u/someone?tab=runs"])

    def test_callback_for_another_page_is_refused(self):
        back, state = self.login("/upload")
        other = back.replace("next=%2Fupload", "next=%2Fabout")
        query = urlsplit(other).query + "&" + urlencode({"openid.return_to": back})
        with patch.object(handler, "verify_openid") as verify:
            self.assertEqual(session.handle(self.event("/auth/callback", query, [state]))["statusCode"], 401)
            verify.assert_not_called()

    def test_backing_out_on_steam_goes_back(self):
        response = session.handle(self.event("/auth/callback", urlencode({"next": "/upload", "openid.mode": "cancel"})))
        self.assertEqual((response["statusCode"], response["headers"]["location"]), (302, "/upload"))
        self.assertFalse(any(c.startswith("__Host-session=") and "Max-Age=0" not in c for c in response["cookies"]))

    def test_logout_only_from_the_site(self):
        cookie = self.signed_in()
        for method, origin in [("GET", ORIGIN), ("POST", None), ("POST", "https://evil.example")]:
            response = session.handle(self.event("/auth/logout", cookies=[cookie], method=method, origin=origin))
            self.assertEqual((response["statusCode"], response["cookies"]), (405, []))
        response = session.handle(self.event("/auth/logout", cookies=[cookie], method="POST", origin=ORIGIN))
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("__Host-session=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0", response["cookies"])

    def test_upload_needs_session_and_origin(self):
        upload = MagicMock(return_value={"statusCode": 200})
        cookie = self.signed_in()
        cases = [(dict(method="GET", cookies=[cookie], origin=ORIGIN), 405),
                 (dict(method="POST", origin=ORIGIN), 401),
                 (dict(method="POST", cookies=[cookie], origin="https://evil.example"), 403)]
        for kw, status in cases:
            self.assertEqual(session.handle(self.event("/auth/upload", **kw), upload)["statusCode"], status)
        upload.assert_not_called()
        session.handle(self.event("/auth/upload", method="POST", cookies=[cookie], origin=ORIGIN), upload)
        self.assertEqual(upload.call_args.args[1], SID)
        # Without an upload handler (gamma's auth Lambda), there is no upload route.
        self.assertEqual(session.handle(self.event("/auth/upload", method="POST", cookies=[cookie],
                                                   origin=ORIGIN))["statusCode"], 405)


if __name__ == "__main__":
    unittest.main()
