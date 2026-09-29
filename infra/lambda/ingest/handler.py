"""Ingest Lambda: verifies a Steam sign-in and merges uploaded runs into the
user's stored blob.

Request (POST to the Function URL, sent by the browser upload page):
    query string  every openid.* parameter Steam appended to our return_to
                  URL, passed through untouched -- the proof of who is
                  uploading. Re-verified with Steam on every upload; there
                  are no sessions.
    body          gzip'd NDJSON: one raw .run file's JSON per line (the
                  browser re-serializes each file onto a single line).

Flow: verify the OpenID assertion -> read the user's blob and refuse if it
was written less than COOLDOWN_SECONDS ago (a cost circuit-breaker, not a
feature) or by this same sign-in -> stream-decompress the body, parsing
each run with run.py's parse_run_data -> reject anything outside a strict
shape/charset allowlist -> dedupe by ts -> merge -> conditional PutObject.
Responds with counts only, never the blob (a big history is larger than the
6 MB response limit); the page re-fetches it through CloudFront.

The core (ingest()) takes a storage object rather than calling S3 itself, so
tools/serve_site.py can run the same code against local_data/users/.
"""
import base64
import gzip
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone

# Bundled next to this file in the Lambda asset (see the stack's bundling);
# on the dev server the repo root is on sys.path instead.
import run

STEAM_OPENID_ENDPOINT = "https://steamcommunity.com/openid/login"
CLAIMED_ID_RE = re.compile(r"^https://steamcommunity\.com/openid/id/(\d{17})$")

# A sign-in is good for this long after Steam issued it: long enough to pick
# the history folder and upload, short enough that a leaked return URL
# (browser history, a screenshot) goes stale quickly.
NONCE_MAX_AGE_SECONDS = 30 * 60
NONCE_MAX_SKEW_SECONDS = 5 * 60
COOLDOWN_SECONDS = 60

# Upload limits. A real run is ~63 KB raw on average; 1,700 of them is about
# what fits the 6 MB request once gzip'd, so these leave generous headroom
# while still bounding memory against a decompression bomb.
MAX_DECOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024
MAX_RUNS_PER_UPLOAD = 3000
MAX_RUNS_TOTAL = 20000
MAX_PARSED_RUN_BYTES = 1024 * 1024

# Every string in a parsed run is a game id, type, seed or build -- in 666
# real runs all match [A-Za-z0-9_.] and are at most 39 chars. Anything else
# is rejected, because these strings end up rendered in other people's
# browsers when they view a profile.
SAFE_STRING_RE = re.compile(r"^[A-Za-z0-9_.\-]{0,80}$")
MAX_DEPTH = 12
MAX_ABS_INT = 2 ** 53
# Plausible run start times: 2020-01-01 .. 2100-01-01.
TS_MIN, TS_MAX = 1577836800, 4102444800


class StoreConflict(Exception):
    """The blob changed between our read and our conditional write."""


class IngestError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Steam OpenID
# ---------------------------------------------------------------------------

def _post_to_steam(params: dict) -> str:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(STEAM_OPENID_ENDPOINT, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=8) as resp:
        return resp.read(4096).decode("utf-8", "replace")


def _origin(url: str):
    """(scheme, host, port) of a URL, compared exactly -- never a string
    prefix, which "https://slay-my-stats.com.evil.example" would pass."""
    try:
        u = urllib.parse.urlsplit(url)
        return (u.scheme, u.hostname, u.port) if u.scheme in ("http", "https") and u.hostname and not u.username else None
    except ValueError:
        return None


def verify_openid(params: dict, allowed_return_to: list[str], now: float | None = None,
                  post=_post_to_steam) -> str:
    """
    Check an OpenID 2.0 positive assertion from Steam and return the verified
    SteamID64. Local checks come first so junk never costs a round trip:
    mode, endpoint, claimed/identity id shape, return_to on one of our own
    origins (an assertion minted for some other site must not work here),
    and nonce age. Then Steam itself confirms the signature.
    """
    now = time.time() if now is None else now
    if params.get("openid.mode") != "id_res":
        raise IngestError(401, "bad_openid", "Not a Steam sign-in response.")
    if params.get("openid.op_endpoint") != STEAM_OPENID_ENDPOINT:
        raise IngestError(401, "bad_openid", "Sign-in did not come from Steam.")
    claimed = params.get("openid.claimed_id", "")
    m = CLAIMED_ID_RE.match(claimed)
    if not m or params.get("openid.identity") != claimed:
        raise IngestError(401, "bad_openid", "Unrecognized Steam identity.")
    if _origin(params.get("openid.return_to", "")) not in {_origin(p) for p in allowed_return_to} - {None}:
        raise IngestError(401, "bad_openid", "Sign-in was for a different site.")
    signed = params.get("openid.signed", "").split(",")
    for field in ("return_to", "claimed_id", "identity", "response_nonce"):
        if field not in signed:
            raise IngestError(401, "bad_openid", "Sign-in response is missing signed fields.")

    nonce = params.get("openid.response_nonce", "")
    try:
        issued = datetime.strptime(nonce[:20], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        raise IngestError(401, "bad_openid", "Sign-in response has no valid timestamp.")
    if now - issued > NONCE_MAX_AGE_SECONDS:
        raise IngestError(401, "signin_expired", "Steam sign-in expired. Sign in again to upload.")
    if issued - now > NONCE_MAX_SKEW_SECONDS:
        raise IngestError(401, "bad_openid", "Sign-in timestamp is in the future.")

    check = {k: v for k, v in params.items() if k.startswith("openid.")}
    check["openid.mode"] = "check_authentication"
    try:
        answer = post(check)
    except Exception:
        raise IngestError(502, "steam_unreachable", "Couldn't reach Steam to verify the sign-in. Try again shortly.")
    if "is_valid:true" not in answer.splitlines():
        raise IngestError(401, "bad_openid", "Steam did not confirm the sign-in.")
    return m.group(1)


# ---------------------------------------------------------------------------
# Upload body
# ---------------------------------------------------------------------------

def iter_upload_lines(body: bytes):
    """
    Yield each NDJSON line of a gzip'd body, decompressing incrementally so a
    small body that inflates enormously is cut off at MAX_DECOMPRESSED_BYTES
    instead of being expanded in full first.
    """
    d = zlib.decompressobj(wbits=31)  # gzip container
    total = 0
    buf = b""
    pending = body
    while True:
        try:
            chunk = d.decompress(pending, 1024 * 1024)
        except zlib.error:
            raise IngestError(400, "bad_body", "Upload isn't valid gzip.")
        pending = d.unconsumed_tail
        total += len(chunk)
        if total > MAX_DECOMPRESSED_BYTES:
            raise IngestError(413, "too_large", "Upload is too large. Upload in smaller batches.")
        buf += chunk
        *lines, buf = buf.split(b"\n")
        for line in lines:
            if line.strip():
                yield line
        if len(buf) > MAX_LINE_BYTES:
            raise IngestError(400, "bad_body", "A run in the upload is implausibly large.")
        if d.eof and d.unused_data:
            # Concatenated gzip members are one valid gzip stream; carry on
            # rather than silently dropping everything after the first.
            pending = d.unused_data
            d = zlib.decompressobj(wbits=31)
            continue
        if not chunk and not pending:
            break
    if not d.eof:
        raise IngestError(400, "bad_body", "Upload was cut off.")
    if buf.strip():
        yield buf


def check_safe(value, depth: int = 0) -> bool:
    """True if a parsed run only holds the kinds of values real runs hold."""
    if depth > MAX_DEPTH:
        return False
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return abs(value) <= MAX_ABS_INT
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return SAFE_STRING_RE.match(value) is not None
    if isinstance(value, list):
        return all(check_safe(v, depth + 1) for v in value)
    if isinstance(value, dict):
        return all(
            (isinstance(k, int) and not isinstance(k, bool) and abs(k) <= MAX_ABS_INT
             or isinstance(k, str) and SAFE_STRING_RE.match(k) is not None)
            and check_safe(v, depth + 1)
            for k, v in value.items()
        )
    return False


def parse_upload(body: bytes, steam_id: str) -> tuple[list[dict], int]:
    """Parse every run in the upload; returns (good runs, count rejected)."""
    runs, rejected = [], 0
    for line in iter_upload_lines(body):
        if len(runs) + rejected >= MAX_RUNS_PER_UPLOAD:
            raise IngestError(413, "too_many_runs",
                              f"At most {MAX_RUNS_PER_UPLOAD} runs per upload. Upload in smaller batches.")
        try:
            data = json.loads(line, parse_constant=lambda c: None)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            parsed = run.parse_run_data(data, steam_id=steam_id)
            ts = parsed.get("ts")
            ok = (isinstance(ts, int) and not isinstance(ts, bool) and TS_MIN <= ts <= TS_MAX
                  and check_safe(parsed)
                  and len(json.dumps(parsed, separators=(",", ":"))) <= MAX_PARSED_RUN_BYTES)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError):
            ok = False
        if ok:
            runs.append(parsed)
        else:
            rejected += 1
    return runs, rejected


# ---------------------------------------------------------------------------
# Storage + merge
# ---------------------------------------------------------------------------

def blob_key(steam_id: str) -> str:
    return f"users/steam-{steam_id}.json.gz"


def ingest(params: dict, body: bytes, store, allowed_return_to: list[str],
           now: float | None = None, post=_post_to_steam) -> dict:
    """
    The whole upload, storage-agnostic. `store` provides:
        get(key) -> (bytes, last_modified_epoch, etag, metadata) or None
        put(key, bytes, metadata, if_match_etag or None for "must not exist")
            raising StoreConflict if that precondition fails
    """
    now = time.time() if now is None else now
    steam_id = verify_openid(params, allowed_return_to, now=now, post=post)
    nonce = params["openid.response_nonce"]
    key = blob_key(steam_id)

    existing = store.get(key)
    etag = None
    old_runs: list[dict] = []
    if existing is not None:
        raw, last_modified, etag, meta = existing
        if meta.get("last-nonce") == nonce:
            raise IngestError(409, "signin_used", "This sign-in was already used for an upload. Sign in again.")
        if now - last_modified < COOLDOWN_SECONDS:
            raise IngestError(429, "cooldown", "You just uploaded. Wait a minute and try again.")
        old_runs = json.loads(gzip.decompress(raw)).get("runs", [])

    new_runs, rejected = parse_upload(body, steam_id)

    seen = {r["ts"] for r in old_runs}
    added, duplicates = [], 0
    for r in new_runs:
        if r["ts"] in seen:
            duplicates += 1
        else:
            seen.add(r["ts"])
            added.append(r)

    result = {"steamId": steam_id, "added": len(added), "duplicates": duplicates,
              "rejected": rejected, "total": len(old_runs) + len(added)}
    if not added:
        return result
    if result["total"] > MAX_RUNS_TOTAL:
        raise IngestError(413, "too_many_runs", f"Profiles are capped at {MAX_RUNS_TOTAL} runs.")

    merged = sorted(old_runs + added, key=lambda r: r["ts"])
    payload = json.dumps({"v": 1, "runs": merged}, separators=(",", ":")).encode("utf-8")
    try:
        store.put(key, gzip.compress(payload, compresslevel=6, mtime=0), {"last-nonce": nonce}, etag)
    except StoreConflict:
        raise IngestError(409, "conflict", "Another upload for this profile landed at the same time. Try again.")
    return result


class S3Store:
    def __init__(self, bucket: str):
        import boto3  # only on Lambda; the dev server uses a local store
        self._s3 = boto3.client("s3")
        self._bucket = bucket

    def get(self, key):
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=key)
        except self._s3.exceptions.NoSuchKey:
            return None
        return (obj["Body"].read(), obj["LastModified"].timestamp(), obj["ETag"], obj.get("Metadata", {}))

    def put(self, key, data, metadata, if_match):
        # Conditional write: if someone else's upload replaced the blob since
        # we read it (or created it, when we saw none), S3 refuses with 412
        # instead of one upload silently discarding the other's runs.
        cond = {"IfMatch": if_match} if if_match else {"IfNoneMatch": "*"}
        try:
            self._s3.put_object(
                Bucket=self._bucket, Key=key, Body=data,
                ContentType="application/json", ContentEncoding="gzip",
                Metadata=metadata, **cond,
            )
        except self._s3.exceptions.ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("PreconditionFailed", "ConditionalRequestConflict"):
                raise StoreConflict() from e
            raise


class DirStore:
    """
    The same interface over a local folder, for tools/serve_site.py. Keeps
    metadata in a sidecar file and uses the file's mtime as Last-Modified.
    Not concurrency-safe; the dev server is one user.
    """
    def __init__(self, root):
        from pathlib import Path
        self._root = Path(root)

    def _path(self, key):
        return self._root / key.split("/", 1)[1]  # "users/x" -> <root>/x

    def get(self, key):
        p = self._path(key)
        if not p.exists():
            return None
        meta_path = p.with_name(p.name + ".meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        st = p.stat()
        return (p.read_bytes(), st.st_mtime, f"{st.st_mtime_ns}-{st.st_size}", meta)

    def put(self, key, data, metadata, if_match):
        p = self._path(key)
        current = self.get(key)
        if (current[2] if current else None) != if_match:
            raise StoreConflict()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        p.with_name(p.name + ".meta.json").write_text(json.dumps(metadata))


# ---------------------------------------------------------------------------
# Lambda entry point (Function URL, payload format 2.0)
# ---------------------------------------------------------------------------

_store = None


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body)}


def lambda_handler(event, context):
    global _store
    if event.get("requestContext", {}).get("http", {}).get("method") != "POST":
        return _response(405, {"error": "method_not_allowed", "message": "POST only."})
    params = dict(urllib.parse.parse_qsl(event.get("rawQueryString", ""), keep_blank_values=True))
    body = event.get("body") or ""
    body = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode("latin-1")
    allowed = [p for p in os.environ.get("ALLOWED_RETURN_TO", "").split(",") if p]
    if _store is None:
        _store = S3Store(os.environ["DATA_BUCKET"])
    try:
        result = ingest(params, body, _store, allowed)
    except IngestError as e:
        print(json.dumps({"status": e.status, "code": e.code}))
        return _response(e.status, {"error": e.code, "message": e.message})
    print(json.dumps({"status": 200, **result}))
    return _response(200, result)
