"""
Steam sign-in for the site: one signed cookie that uploads and feedback both trust.

Routes, all under /auth/ on the site's own origin (CloudFront sends them here):

    GET  /auth/login?next=/path   -> Steam's OpenID login, returning to /auth/callback
    GET  /auth/callback           -> checks Steam's answer, sets the session, goes back to `next`
    GET  /auth/me                 -> {"steamId"} while signed in, else 401
    POST /auth/logout             -> clears the session
    GET/POST /auth/feedback       -> feedback.handle
    POST /auth/upload             -> an upload URL (handler.authorize), only where `upload` is given

The cookie is `<steam id>.<expiry>.<HMAC-SHA256 of both>`, host-only, Secure, HttpOnly and
SameSite=Lax, so other sites can neither read it nor send it on a cross-site POST.

Prod: `__Host-session`, 30 days, signed with the key in Parameter Store
(SESSION_SECRET_PARAM_NAME), any Steam account. Gamma: `__Host-gamma`, 12 hours, signed with
GAMMA_SESSION_SECRET (CloudFront's gate checks the same cookie and can't reach Parameter Store),
and only the ALLOWED_STEAM_IDS reviewers. SESSION_SECRET (dev server only) overrides the key.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.parse
from http.cookies import CookieError, SimpleCookie

PROD_SECONDS = 30 * 24 * 3600
GAMMA_SECONDS = 12 * 3600
STATE_SECONDS = 600
# Where a sign-in may return to: a path on this site, never another host ("//evil.example").
NEXT_RE = re.compile(r"/(?![/\\])[A-Za-z0-9\-._~/%?=&+]{0,500}")


def _gamma() -> bool:
    return "GAMMA_SESSION_SECRET" in os.environ


def cookie_name() -> str:
    return "__Host-gamma" if _gamma() else "__Host-session"


def lifetime() -> int:
    return GAMMA_SECONDS if _gamma() else PROD_SECONDS


def origin() -> str:
    """The site's own origin, e.g. https://slay-my-stats.com."""
    return os.environ.get("GAMMA_ORIGIN") or os.environ["SITE_ORIGIN"]


_secret = None  # read once per Lambda container


def _key() -> bytes:
    global _secret
    if _secret is None:
        if os.environ.get("SESSION_SECRET") or _gamma():
            _secret = os.environ.get("SESSION_SECRET") or os.environ["GAMMA_SESSION_SECRET"]
        else:
            import boto3  # only on Lambda
            _secret = boto3.client("ssm").get_parameter(
                Name=os.environ["SESSION_SECRET_PARAM_NAME"], WithDecryption=True)["Parameter"]["Value"]
    return _secret.encode()


def _sign(payload: str) -> str:
    return hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()


def _cookies(event) -> SimpleCookie:
    jar = SimpleCookie()
    try:
        jar.load("; ".join(event.get("cookies", [])))
    except CookieError:
        return SimpleCookie()
    return jar


def steam_id(event, now: float | None = None) -> str | None:
    """The signed-in Steam ID, or None (no cookie, expired, forged, or off gamma's list)."""
    now = time.time() if now is None else now
    try:
        steam, expiry, signature = _cookies(event)[cookie_name()].value.split(".")
        if not re.fullmatch(r"\d{17}", steam) or int(expiry) <= now:
            return None
        if not hmac.compare_digest(signature, _sign(f"{steam}.{expiry}")):
            return None
    except (KeyError, ValueError):
        return None
    allowed = os.environ.get("ALLOWED_STEAM_IDS")
    if allowed is not None and steam not in allowed.split(","):
        return None
    return steam


def session_cookie(steam: str, now: float | None = None) -> str:
    payload = f"{steam}.{int(time.time() if now is None else now) + lifetime()}"
    return _set(cookie_name(), payload + "." + _sign(payload), lifetime())


def _set(name: str, value: str, age: int) -> str:
    return f"{name}={value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={age}"


def _json(status: int, body: dict, set_cookies=()) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "cookies": list(set_cookies), "body": json.dumps(body)}


def _redirect(location: str, set_cookies=()) -> dict:
    return {"statusCode": 302, "headers": {"location": location, "cache-control": "no-store",
            "referrer-policy": "no-referrer"}, "cookies": list(set_cookies), "body": ""}


def _safe_next(value) -> str:
    return value if isinstance(value, str) and NEXT_RE.fullmatch(value) else "/"


def _callback_url(state: str, next_path: str) -> str:
    return origin() + "/auth/callback?" + urllib.parse.urlencode({"state": state, "next": next_path})


def same_origin(event) -> bool:
    """A POST from one of the site's own pages (browsers send Origin on every POST)."""
    return (event.get("headers") or {}).get("origin") == origin()


def handle(event, upload=None) -> dict:
    """Answer one /auth/ request. `upload(event, steam)` serves /auth/upload where given."""
    import handler  # the OpenID check and IngestError live there
    path = event.get("rawPath", "").rstrip("/")
    method = event.get("requestContext", {}).get("http", {}).get("method")
    state_name = cookie_name() + "-state"

    if path == "/auth/feedback":
        from feedback import handle as feedback
        return feedback(event)
    if path == "/auth/upload" and upload:
        if method != "POST":
            return _json(405, {"error": "method_not_allowed", "message": "POST only."})
        steam = steam_id(event)
        if not steam:
            return _json(401, {"error": "signed_out", "message": "Sign in through Steam to upload."})
        if not same_origin(event):
            return _json(403, {"error": "forbidden", "message": "Uploads must start from the site."})
        return upload(event, steam)
    if path == "/auth/logout":
        if method != "POST" or not same_origin(event):
            return _json(405, {"error": "method_not_allowed"})
        return _json(200, {}, [_set(cookie_name(), "", 0)])
    if method != "GET":
        return _json(405, {"error": "method_not_allowed"})
    if path == "/auth/me":
        steam = steam_id(event)
        return _json(200, {"steamId": steam}) if steam else _json(401, {"error": "signed_out"})
    query = dict(urllib.parse.parse_qsl(event.get("rawQueryString", "")))
    if path == "/auth/login":
        state = secrets.token_hex(32)
        params = {"openid.ns": "http://specs.openid.net/auth/2.0", "openid.mode": "checkid_setup",
                  "openid.return_to": _callback_url(state, _safe_next(query.get("next"))),
                  "openid.realm": origin() + "/",
                  "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
                  "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select"}
        return _redirect(handler.STEAM_OPENID_ENDPOINT + "?" + urllib.parse.urlencode(params),
                         [_set(state_name, state, STATE_SECONDS)])
    if path != "/auth/callback":
        return _json(404, {"error": "not_found"})

    next_path = _safe_next(query.get("next"))
    clear_state = _set(state_name, "", 0)
    if query.get("openid.mode") == "cancel":  # backed out on Steam's page: just go back
        return _redirect(next_path, [clear_state])
    state = _cookies(event).get(state_name)
    try:
        if not state or not re.fullmatch(r"[a-f0-9]{64}", state.value) or not hmac.compare_digest(
                state.value.encode(), query.get("state", "").encode()):
            raise handler.IngestError(401, "bad_state", "That sign-in has expired. Start it again.")
        if query.get("openid.return_to") != _callback_url(state.value, next_path):
            raise handler.IngestError(401, "bad_openid", "Sign-in was for a different callback.")
        steam = handler.verify_openid(query, [origin()])
        handler.require_allowed_steam_id(steam)
    except handler.IngestError as e:
        return _json(e.status, {"error": e.code, "message": e.message}, [clear_state])
    return _redirect(next_path, [session_cookie(steam), clear_state])
