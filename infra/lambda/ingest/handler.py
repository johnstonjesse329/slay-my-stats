"""Ingest: verifies a Steam sign-in, takes the upload straight into S3, and
merges its runs into the user's stored blob. Two Lambda entry points share
this file (plus failure_handler, below):

lambda_handler -- the Function URL (POST from the browser upload page):
    query string  every openid.* parameter Steam appended to our return_to
                  URL, passed through untouched -- the proof of who is
                  uploading. Re-verified with Steam on every upload; there
                  are no sessions.
    Flow: per-IP limit -> verify the OpenID assertion -> refuse if this
    Steam account asked less than COOLDOWN_SECONDS ago (a cost
    circuit-breaker, not a feature) -> answer with a presigned POST for one
    new raw/ object, capped at UPLOAD_MAX_BYTES, plus the upload's id. A
    sign-in works again (after the cooldown) until it expires.

process_handler -- S3 "object created" events under raw/:
    The uploaded object is gzip'd NDJSON: one raw .run file's JSON per line
    (the browser re-serializes each file onto a single line), in any order.
    Stream-decompress it, parsing each run with run.py's parse_run_data ->
    reject anything outside a strict shape/charset allowlist -> park the
    runs on local disk by month (Spool) -> merge each month into its file
    by ts (runs already on the profile are re-parsed in place), with a
    conditional PutObject per month -> the profile summary last -> update
    the player list and site stats -> write the upload's result, which the
    browser polls for. Only the months an upload touches are read or
    written, so an upload costs the same however big the profile is. The
    raw object is kept so profiles can be rebuilt after a parser fix
    (rebuild_profile); only uploads with no run in them at all are deleted.

failure_handler -- the process function's on-failure destination:
    Lambda calls it (directly; no queue) once an upload has failed every
    try, by error or timeout. It writes a failed result for that upload, so
    the page that sent it says so instead of waiting, logs the key, and
    emails the site owner through SNS.

Storage (the data bucket; CloudFront serves users/* only):
    users/<slug>.json.gz    public profile summary: {"v":2, "name", "parser",
                            "months":{"YYYY-MM":[ts...]}, "noRaw":[ts...]}.
                            noRaw lists runs uploaded before raw uploads
                            were kept; the page sends those again so they
                            get a raw copy. A v1 profile ({"v":1, "name",
                            "runs":[...]}, from before month files) is split
                            into month files by its next upload
                            (migrate_profile).
    users/<slug>/<YYYY-MM>.json.gz
                            public: {"v":2, "runs":[...]}, the month's
                            parsed runs (UTC start time), sorted by ts.
                            Written before the summary lists them.
    users/_index.json.gz    public player list: {"v":1, "players":[{slug,
                            name, runs, updated}]}, for search
    users/_uploads/<id>.json.gz
                            public result of one upload, polled by the page
                            that made it. Counts and the slug only; the id
                            is random, so nobody else knows where it is.
    ids/<steamid>.json.gz   private: {"slug"}. The only place a Steam ID is
                            kept, so nothing public links a profile to a
                            Steam account.
    raw/<steamid>/<time>-<id>.ndjson.gz
                            private: every upload exactly as sent.
    limits/steam/<steamid>.json.gz, limits/ip/<hash>.json.gz
                            private: when upload URLs were last handed out.
A profile's slug is its Steam display name at first upload, lowercased with
everything but a-z0-9 dropped ("Mr. Bean!" -> "mrbean"; "player" if nothing
is left), plus "-2", "-3"... if taken. It never changes after that, so
shared links keep working; a rename only updates the shown name.

The cores (authorize(), process_upload()) take a storage object rather than
calling S3 themselves, so tools/serve_site.py can run the same code against
local_data/.
"""
import gzip
import hashlib
import ipaddress
import json
import math
import os
import re
import secrets
import tempfile
import time
import unicodedata
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
# Upload URLs per IP address (per /64 for IPv6, which hands out whole
# blocks) per hour: roomy for a household sharing one address, a wall for
# one machine spamming uploads.
IP_UPLOADS_PER_HOUR = 5
IP_WINDOW_SECONDS = 3600

# Upload limits. A real run is 28-63 KB raw and ~2.7 KB once a whole history
# is gzip'd together, so 100 MB holds ~35,000 runs: any real history in one
# go. Decompressed, 20,000 runs is ~1.3 GB; the cap bounds memory against a
# decompression bomb, and parsing streams, so it never all sits in memory.
# Runs per upload are capped so the biggest one is processed well inside
# the Lambda's timeout (20,000 took ~50 s locally); a profile itself has no
# cap, since it's stored a month at a time. Months per upload are capped
# because each one is an open spool file and an S3 write.
UPLOAD_MAX_BYTES = 100 * 1024 * 1024
UPLOAD_URL_SECONDS = 10 * 60
MAX_DECOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024
MAX_RUNS_PER_UPLOAD = 20000
MAX_MONTHS_PER_UPLOAD = 240
MAX_PARSED_RUN_BYTES = 1024 * 1024
MERGE_RETRIES = 5

# Every string in a parsed run is a game id, type, seed or build -- in 666
# real runs all match [A-Za-z0-9_.] and are at most 39 chars. Anything else
# is rejected, because these strings end up rendered in other people's
# browsers when they view a profile.
SAFE_STRING_RE = re.compile(r"^[A-Za-z0-9_.\-]{0,80}$")
MAX_DEPTH = 12
MAX_ABS_INT = 2 ** 53
# Plausible run start times: 2020-01-01 .. 2100-01-01.
TS_MIN, TS_MAX = 1577836800, 4102444800

PLAYER_SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
PROFILE_XML_URL = "https://steamcommunity.com/profiles/{}?xml=1"
MAX_NAME_CHARS = 64
MAX_SLUG_CHARS = 32
MAX_SLUG_TRIES = 50
INDEX_KEY = "users/_index.json.gz"
INDEX_RETRIES = 5
STATS_KEY = "users/_stats.json.gz"
UPLOAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16}$")
RAW_KEY_RE = re.compile(r"^raw/(\d{17})/(\d{8}T\d{6}Z)-([A-Za-z0-9_-]{16})\.ndjson\.gz$")


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
# Steam display name
# ---------------------------------------------------------------------------

_api_key = None  # cached per Lambda container once read


def _steam_api_key() -> str:
    """The Steam Web API key: $STEAM_API_KEY if set (dev), else the SSM
    parameter named by $STEAM_API_KEY_PARAM_NAME (Lambda), else ""."""
    global _api_key
    if _api_key is None:
        key = os.environ.get("STEAM_API_KEY", "")
        param = os.environ.get("STEAM_API_KEY_PARAM_NAME")
        if not key and param:
            try:
                import boto3
                key = boto3.client("ssm").get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
            except Exception:
                return ""  # not cached: try again on the next upload
        _api_key = key
    return _api_key


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "slay-my-stats"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read(65536).decode("utf-8", "replace")


def lookup_steam_name(steam_id: str) -> str | None:
    """
    The player's current Steam display name, or None if Steam couldn't be
    asked. Tries the Web API (needs the key), then the public profile XML
    (no key; what the dev server uses). Errors are swallowed without being
    logged -- the API URL carries the key.
    """
    key = _steam_api_key()
    if key:
        try:
            q = urllib.parse.urlencode({"key": key, "steamids": steam_id})
            players = json.loads(_http_get(f"{PLAYER_SUMMARIES_URL}?{q}"))["response"]["players"]
            if players and players[0].get("personaname"):
                return players[0]["personaname"]
        except Exception:
            pass
    try:
        m = re.search(r"<steamID><!\[CDATA\[(.*?)\]\]></steamID>", _http_get(PROFILE_XML_URL.format(steam_id)), re.S)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def clean_name(name) -> str | None:
    """A display name fit to store: no control/format characters (which
    includes bidi overrides), whitespace collapsed, length capped. The page
    only ever shows it via textContent."""
    if not isinstance(name, str):
        return None
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = " ".join(name.split())[:MAX_NAME_CHARS]
    return name or None


def slugify(name: str) -> str:
    """A name's URL form: lowercase a-z0-9 only, so easy to type. Dashes are
    reserved for the "-2" suffix, which keeps "bob-2" from ever clashing
    with a player actually named "bob2". Accents fold ("Zoë" -> "zoe")."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name.lower())[:MAX_SLUG_CHARS] or "player"


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
            raise IngestError(413, "too_large", "Upload is too large.")
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


def month_of(ts: int) -> str:
    """The UTC month a run started in, "YYYY-MM": which month file it's in."""
    return time.strftime("%Y-%m", time.gmtime(ts))


class Spool:
    """
    Parsed runs parked on local disk (/tmp on Lambda), one gzip file per
    month, so an upload of any size is never held in memory at once: it's
    read through once, run by run, and then each month is merged on its
    own. Uploads can be in any order. Also remembers every ts it was given.
    """
    def __init__(self):
        self._dir = tempfile.TemporaryDirectory()
        self._files = {}
        self.ts = set()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for f in self._files.values():
            f.close()
        self._dir.cleanup()

    def add(self, parsed: dict) -> None:
        m = month_of(parsed["ts"])
        f = self._files.get(m)
        if f is None:
            if len(self._files) >= MAX_MONTHS_PER_UPLOAD:
                raise IngestError(413, "too_many_months", f"An upload can span at most {MAX_MONTHS_PER_UPLOAD} months.")
            f = self._files[m] = gzip.open(os.path.join(self._dir.name, m), "wb", compresslevel=1)
        f.write(json.dumps(parsed, separators=(",", ":")).encode("utf-8") + b"\n")
        self.ts.add(parsed["ts"])

    def months(self) -> list[str]:
        for f in self._files.values():
            f.close()  # flushes; reading starts once adding is done
        return sorted(self._files)

    def runs(self, month: str) -> list[dict]:
        if month not in self._files:
            return []
        with gzip.open(os.path.join(self._dir.name, month), "rb") as f:
            return [json.loads(line) for line in f]


def spool_upload(body: bytes, steam_id: str, spool: Spool) -> tuple[int, int, int]:
    """Parse every run in the upload into the spool; returns (count good,
    count rejected, count that looked like .run files at all -- rejected ones
    included, since a run the parser can't handle yet may be the parser's
    fault)."""
    good, rejected, run_shaped = 0, 0, 0
    for line in iter_upload_lines(body):
        if good + rejected >= MAX_RUNS_PER_UPLOAD:
            raise IngestError(413, "too_many_runs", f"At most {MAX_RUNS_PER_UPLOAD} runs per upload.")
        try:
            data = json.loads(line, parse_constant=lambda c: None)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            if "start_time" in data and "players" in data:
                run_shaped += 1
            parsed = run.parse_run_data(data, steam_id=steam_id)
            ts = parsed.get("ts")
            ok = (isinstance(ts, int) and not isinstance(ts, bool) and TS_MIN <= ts <= TS_MAX
                  and check_safe(parsed)
                  and len(json.dumps(parsed, separators=(",", ":"))) <= MAX_PARSED_RUN_BYTES)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError):
            ok = False
        if ok:
            spool.add(parsed)
            good += 1
        else:
            rejected += 1
    return good, rejected, run_shaped


# ---------------------------------------------------------------------------
# Storage + merge
# ---------------------------------------------------------------------------

def blob_key(slug: str) -> str:
    return f"users/{slug}.json.gz"


def month_key(slug: str, month: str) -> str:
    return f"users/{slug}/{month}.json.gz"


def id_key(steam_id: str) -> str:
    return f"ids/{steam_id}.json.gz"


def raw_key(steam_id: str, upload_id: str, now: float) -> str:
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"raw/{steam_id}/{stamp}-{upload_id}.ndjson.gz"


def result_key(upload_id: str) -> str:
    return f"users/_uploads/{upload_id}.json.gz"


def steam_limit_key(steam_id: str) -> str:
    return f"limits/steam/{steam_id}.json.gz"


def ip_limit_key(ip: str) -> str:
    """Keyed by a hash, not the address itself. Bare IPv4 hashes can be
    brute-forced, so this only keeps addresses out of plain sight in a
    private bucket."""
    try:
        addr = ipaddress.ip_address(ip)
        if addr.version == 6:
            addr = ipaddress.ip_network(f"{ip}/64", strict=False)
        ip = str(addr)
    except ValueError:
        pass
    return f"limits/ip/{hashlib.sha256(ip.encode()).hexdigest()[:32]}.json.gz"


def _pack(obj) -> bytes:
    return gzip.compress(json.dumps(obj, separators=(",", ":")).encode("utf-8"), compresslevel=6, mtime=0)


def _unpack(raw: bytes):
    return json.loads(gzip.decompress(raw))


def _read_index(store) -> tuple[list[dict], str | None]:
    got = store.get(INDEX_KEY)
    return (_unpack(got[0]).get("players", []), got[2]) if got else ([], None)


def _claim_slug(store, steam_id: str, name: str, data: bytes, meta: dict) -> str:
    """
    Create a first-time player's profile under the first free slug for their
    name and record it against their Steam ID. Creating the profile with a
    must-not-exist write is what reserves the slug, so two new players with
    the same name can't both get it.
    """
    taken = {p["slug"] for p in _read_index(store)[0]}
    base, n, tries = slugify(name), 1, 0
    while True:
        slug = base if n == 1 else f"{base}-{n}"
        n += 1
        if slug in taken:
            continue
        try:
            store.put(blob_key(slug), data, meta, None)
            break
        except StoreConflict:  # created since the index was written
            tries += 1
            if tries >= MAX_SLUG_TRIES:
                raise IngestError(503, "busy", "Couldn't set up your profile. Try again shortly.")
    try:
        store.put(id_key(steam_id), _pack({"slug": slug}), {}, None)
    except StoreConflict:
        # This player's first upload from another tab won the race; give the
        # slug back rather than leave a second, orphaned copy.
        store.delete(blob_key(slug))
        raise IngestError(409, "conflict", "Another upload for this profile landed at the same time. Try again.")
    return slug


def _update_index(store, slug: str, name: str, runs: int, now: float) -> None:
    """Upsert this player into the public list. Best effort: the profile is
    already saved, and the next upload rewrites this entry anyway."""
    for _ in range(INDEX_RETRIES):
        players, etag = _read_index(store)
        players = [p for p in players if p["slug"] != slug]
        players.append({"slug": slug, "name": name, "runs": runs, "updated": int(now)})
        players.sort(key=lambda p: p["slug"])
        try:
            store.put(INDEX_KEY, _pack({"v": 1, "players": players}), {}, etag)
            return
        except StoreConflict:
            continue
    print(json.dumps({"warning": "index_update_failed", "slug": slug}))


# ---------------------------------------------------------------------------
# Site-wide stats: running totals, updated from each upload's new runs only
# ---------------------------------------------------------------------------
#
# Every figure is a sum ([runs, wins] pairs, counts, minutes) or a best-so-far
# record, so an upload's new runs make a small tally that's added onto the
# totals without rereading anyone's history. Solo and multiplayer runs are
# counted apart, since their win rates aren't comparable; solo follows the
# dashboard's Solo filter, which leaves out daily runs (they only count in
# allRuns). Card and relic counts are kept raw for every id, and the home
# page ranks them. Adding a new figure means recounting once with
# tools/rebuild_stats.py.

MODES = ("solo", "multi")
PAIR_KEYS = ("chars", "cards", "relics")


def _empty_mode() -> dict:
    return {"runs": 0, "wins": 0, "minutes": 0, "chars": {}, "cards": {}, "relics": {},
            "killers": {}, "records": {}}


def empty_stats() -> dict:
    return {"v": 1, "allRuns": 0, **{m: _empty_mode() for m in MODES}}


def _bump(pairs: dict, key, won: bool) -> None:
    pair = pairs.setdefault(key, [0, 0])
    pair[0] += 1
    pair[1] += won


def _offer_fastest(records: dict, rec: dict) -> None:
    old = records.get("fastestWin")
    if old is None or rec["mins"] < old["mins"]:
        records["fastestWin"] = rec


def tally(runs: list[dict], slug: str) -> dict:
    stats = empty_stats()
    for r in runs:
        stats["allRuns"] += 1
        if r.get("mp"):
            m = stats["multi"]
        elif r.get("mode") == "daily":
            continue
        else:
            m = stats["solo"]
        won = bool(r.get("won"))
        mins = r.get("mins") or 0
        m["runs"] += 1
        m["wins"] += won
        m["minutes"] += mins
        _bump(m["chars"], r.get("char") or "UNKNOWN", won)
        for cid in {c.get("id") for c in r.get("finalDeck") or []} - {None}:
            _bump(m["cards"], cid, won)
        for rid in {c.get("id") for c in r.get("finalRelics") or []} - {None}:
            _bump(m["relics"], rid, won)
        fights = r.get("fights") or []
        if not won and fights and fights[-1].get("won") is False and fights[-1].get("enc"):
            enc = fights[-1]["enc"]
            m["killers"][enc] = m["killers"].get(enc, 0) + 1
        if won and mins > 0:
            _offer_fastest(m["records"], {"slug": slug, "char": r.get("char"), "mins": mins, "ts": r.get("ts")})
    return stats


def merge_stats(total: dict, delta: dict) -> dict:
    total["allRuns"] = total.get("allRuns", 0) + delta.get("allRuns", 0)
    for mode in MODES:
        t, d = total.setdefault(mode, _empty_mode()), delta.get(mode, {})
        for k in ("runs", "wins", "minutes"):
            t[k] = t.get(k, 0) + d.get(k, 0)
        t["minutes"] = round(t["minutes"], 1)
        for k in PAIR_KEYS:
            pairs = t.setdefault(k, {})
            for key, (n, w) in d.get(k, {}).items():
                pair = pairs.setdefault(key, [0, 0])
                pair[0] += n
                pair[1] += w
        killers = t.setdefault("killers", {})
        for enc, n in d.get("killers", {}).items():
            killers[enc] = killers.get(enc, 0) + n
        rec = d.get("records", {}).get("fastestWin")
        if rec:
            _offer_fastest(t.setdefault("records", {}), rec)
    return total


def _update_stats(store, delta: dict) -> None:
    """Add an upload's tally onto the public totals. Best effort, like the
    index: the profile is already saved, and a missed tally only leaves the
    totals a little short until the next rebuild."""
    for _ in range(INDEX_RETRIES):
        got = store.get(STATS_KEY)
        total = _unpack(got[0]) if got else empty_stats()
        try:
            store.put(STATS_KEY, _pack(merge_stats(total, delta)), {}, got[2] if got else None)
            return
        except StoreConflict:
            continue
    print(json.dumps({"warning": "stats_update_failed", "runs": delta.get("allRuns")}))


# ---------------------------------------------------------------------------
# Handing out upload URLs
# ---------------------------------------------------------------------------

def authorize(params: dict, ip: str, store, allowed_return_to: list[str], presign,
              now: float | None = None, post=_post_to_steam) -> dict:
    """
    Check the limits and the sign-in, then hand out a presigned POST for one
    new raw/ object. Storage-agnostic, like the rest: `store` provides
        get(key) -> (bytes, last_modified_epoch, etag, metadata) or None
        put(key, bytes, metadata, if_match_etag or None for "must not exist")
            raising StoreConflict if that precondition fails
        delete(key), list(prefix) -> [key, ...]
    and `presign(key, max_bytes, expires_seconds)` returns {"url", "fields"}.
    """
    now = time.time() if now is None else now
    # The IP limit comes first, so a flood from one address never reaches Steam.
    got_ip = store.get(ip_limit_key(ip))
    ip_times = [t for t in (_unpack(got_ip[0]).get("times", []) if got_ip else []) if now - t < IP_WINDOW_SECONDS]
    if len(ip_times) >= IP_UPLOADS_PER_HOUR:
        raise IngestError(429, "rate_limited", "Too many uploads from your network. Try again in an hour.")

    # A sign-in can be used again until it expires; whether Steam accepts the
    # same one twice is up to Steam. The cooldown and IP limit still apply.
    steam_id = verify_openid(params, allowed_return_to, now=now, post=post)
    got = store.get(steam_limit_key(steam_id))
    if got and now - _unpack(got[0]).get("at", 0) < COOLDOWN_SECONDS:
        raise IngestError(429, "cooldown", "You just uploaded. Wait a minute and try again.")
    try:
        store.put(steam_limit_key(steam_id), _pack({"at": now}), {}, got[2] if got else None)
        store.put(ip_limit_key(ip), _pack({"times": ip_times + [now]}), {}, got_ip[2] if got_ip else None)
    except StoreConflict:
        raise IngestError(409, "conflict", "Another upload started at the same time. Try again.")

    # The slug lets the page skip runs the profile already has, on any device.
    record = store.get(id_key(steam_id))
    upload_id = secrets.token_urlsafe(12)
    return {"uploadId": upload_id, "maxBytes": UPLOAD_MAX_BYTES,
            "slug": _unpack(record[0])["slug"] if record else None,
            **presign(raw_key(steam_id, upload_id, now), UPLOAD_MAX_BYTES, UPLOAD_URL_SECONDS)}


# ---------------------------------------------------------------------------
# Processing an upload
# ---------------------------------------------------------------------------

def _read_profile(store, steam_id: str) -> tuple[str | None, str | None, dict | None]:
    """(slug, etag, profile summary) for a player; the summary is None if
    they have no profile."""
    record = store.get(id_key(steam_id))
    slug = _unpack(record[0])["slug"] if record else None
    existing = store.get(blob_key(slug)) if slug else None
    return (slug, existing[2], _unpack(existing[0])) if existing else (slug, None, None)


def _no_raw(doc: dict | None) -> set:
    """ts of the runs on a profile with no raw copy: every run, on a profile
    from before raw uploads were kept."""
    if doc is None:
        return set()
    if "noRaw" in doc:
        return set(doc["noRaw"])
    return {r["ts"] for r in doc.get("runs", [])}


def _total(doc: dict) -> int:
    return sum(len(ts) for ts in doc.get("months", {}).values())


def _summary(name: str, months: dict, no_raw, parser: int) -> dict:
    return {"v": 2, "name": name, "parser": parser, "months": dict(sorted(months.items())),
            "noRaw": sorted(no_raw)}


def stored_months(store, slug: str, doc: dict):
    """Yield (month, runs) for every month on a profile, oldest first, one
    month in memory at a time. Reads a profile from before month files
    (v1, every run in the one file) too."""
    if doc.get("v", 1) < 2:
        by_month = {}
        for r in doc.get("runs", []):
            by_month.setdefault(month_of(r["ts"]), []).append(r)
        yield from sorted(by_month.items())
        return
    for m in sorted(doc.get("months", {})):
        got = store.get(month_key(slug, m))
        yield m, _unpack(got[0])["runs"] if got else []


def merge_runs(old_runs: list[dict], new_runs: list[dict]) -> tuple[list[dict], list[dict], int]:
    """
    An upload's runs merged into a profile's by ts. A run the profile already
    has is replaced by the upload's fresh parse, so a parser fix reaches it
    the next time it's sent. Returns (merged, added, count already there).
    """
    by_ts = {r["ts"]: r for r in old_runs}
    added, already = [], 0
    for r in {r["ts"]: r for r in new_runs}.values():
        if r["ts"] in by_ts:
            already += 1
        else:
            added.append(r)
        by_ts[r["ts"]] = r
    return sorted(by_ts.values(), key=lambda r: r["ts"]), added, already


def _merge_month(store, slug: str, month: str, new_runs: list[dict]) -> tuple[list[int], list[dict], int, bool]:
    """Merge runs into one month file. Returns (every ts now in the month,
    runs added, count already there, whether the file changed)."""
    key = month_key(slug, month)
    for _ in range(MERGE_RETRIES):
        got = store.get(key)
        old = _unpack(got[0])["runs"] if got else []
        merged, added, already = merge_runs(old, new_runs)
        ts = [r["ts"] for r in merged]
        if merged == old:
            return ts, added, already, False
        try:
            store.put(key, _pack({"v": 2, "runs": merged}), {}, got[2] if got else None)
            return ts, added, already, True
        except StoreConflict:  # another upload wrote this month first: merge onto that
            continue
    raise IngestError(503, "busy", "Your profile is busy. Try again shortly.")


def migrate_profile(store, slug: str) -> bool:
    """Split a profile from before month files (v1: every run in
    users/<slug>.json.gz) into month files plus the summary. Month files go
    first, so the summary never lists one that isn't there. Returns whether
    there was anything to do; raises IngestError "conflict" if the profile
    changed meanwhile."""
    got = store.get(blob_key(slug))
    if got is None:
        return False
    doc = _unpack(got[0])
    if doc.get("v", 1) >= 2:
        return False
    months = {}
    for m, runs in stored_months(store, slug, doc):
        runs.sort(key=lambda r: r["ts"])
        _put_over(store, month_key(slug, m), _pack({"v": 2, "runs": runs}))
        months[m] = [r["ts"] for r in runs]
    summary = _summary(doc["name"], months, _no_raw(doc), doc.get("parser", 0))
    try:
        store.put(blob_key(slug), _pack(summary), {}, got[2])
    except StoreConflict:
        raise IngestError(409, "conflict", "The profile changed while it was being migrated. Try again.")
    return True


def _merge_upload(store, steam_id: str, body: bytes, now: float, lookup_name) -> dict:
    with Spool() as spool:
        good, rejected, run_shaped = spool_upload(body, steam_id, spool)
        if not run_shaped:
            raise IngestError(400, "no_runs", "None of those files could be read as runs.")
        slug, etag, doc = _read_profile(store, steam_id)
        if doc is not None and doc.get("v", 1) < 2:
            migrate_profile(store, slug)
            slug, etag, doc = _read_profile(store, steam_id)
        result = {"status": "done", "slug": slug, "name": doc.get("name") if doc else None, "added": 0,
                  "duplicates": 0, "rejected": rejected, "total": _total(doc) if doc else 0}
        if not good:
            return result

        # A player's name is only asked once there's something to save, so
        # junk uploads never reach Steam. A returning player keeps their old
        # name if Steam can't be asked; a new one can't be given an address
        # without one, so their slug is claimed (with an empty profile)
        # before any month is written under it.
        name = None
        if doc is None:
            name = clean_name(lookup_name(steam_id))
            if name is None:
                raise IngestError(502, "steam_unreachable", "Couldn't get your Steam name from Steam.")
            empty = _pack(_summary(name, {}, [], run.PARSER_VERSION))
            claimed = False
            if slug is None:
                try:
                    slug, claimed = _claim_slug(store, steam_id, name, empty, {}), True
                except IngestError as e:
                    if e.code != "conflict":
                        raise
                    # Their first upload from another tab claimed a slug first: use that one.
                    slug = _unpack(store.get(id_key(steam_id))[0])["slug"]
            if not claimed:  # a record whose profile isn't there (yet): create it in place
                try:
                    store.put(blob_key(slug), empty, {}, None)
                except StoreConflict:
                    pass

        # One month at a time: merged into its file, written, then dropped.
        months, delta, changed = {}, empty_stats(), False
        for m in spool.months():
            ts, added, already, wrote = _merge_month(store, slug, m, spool.runs(m))
            months[m] = ts
            result["added"] += len(added)
            result["duplicates"] += already
            changed |= wrote
            # Only the runs this upload added: the rest are already in the totals.
            merge_stats(delta, tally(added, slug))

        if not changed and doc is not None and not (_no_raw(doc) & spool.ts):
            return result
        name = name or clean_name(lookup_name(steam_id)) or doc["name"]

        # The summary last. Another upload may have added to the same months
        # meanwhile; runs are never taken away here, so the ts lists are
        # unioned rather than replaced.
        for _ in range(MERGE_RETRIES):
            got = store.get(blob_key(slug))
            cur = _unpack(got[0])
            merged = dict(cur.get("months", {}))
            for m, ts in months.items():
                merged[m] = sorted(set(merged.get(m, [])) | set(ts))
            new = _summary(name, merged, _no_raw(cur) - spool.ts, cur.get("parser", run.PARSER_VERSION))
            try:
                store.put(blob_key(slug), _pack(new), {}, got[2])
                break
            except StoreConflict:
                continue
        else:
            raise IngestError(503, "busy", "Your profile is busy. Try again shortly.")
    _update_index(store, slug, name, _total(new), now)
    if delta["allRuns"]:
        _update_stats(store, delta)
    result.update(slug=slug, name=name, total=_total(new))
    return result


def _put_over(store, key: str, data: bytes) -> None:
    """Write whether or not the key exists (S3 event deliveries can repeat)."""
    for _ in range(INDEX_RETRIES):
        got = store.get(key)
        try:
            store.put(key, data, {}, got[2] if got else None)
            return
        except StoreConflict:
            continue


def process_upload(key: str, store, now: float | None = None, lookup_name=None) -> dict | None:
    """
    Merge one uploaded raw/ object into its player's profile and publish the
    upload's result for the page to poll. The Steam ID comes from the key,
    which authorize() chose, never from the upload. Returns the result, or
    None for a key that isn't an upload or is already gone. Raises
    IngestError (status >= 500) when trying again later may work; the Lambda
    then retries, and the raw object stays either way.
    """
    m = RAW_KEY_RE.match(key)
    got = store.get(key) if m else None
    if got is None:
        return None
    steam_id, _, upload_id = m.groups()
    now = time.time() if now is None else now
    try:
        result = _merge_upload(store, steam_id, got[0], now, lookup_name or lookup_steam_name)
    except IngestError as e:
        if e.status >= 500:
            raise
        # Not a run history at all: spam, not a parser problem, so not kept.
        if e.code in ("no_runs", "bad_body", "too_large"):
            store.delete(key)
        result = {"status": "failed", "error": e.code, "message": e.message}
    _put_over(store, result_key(upload_id), _pack(result))
    return result


def rebuild_profile(store, steam_id: str, now: float | None = None, dry_run: bool = False) -> dict:
    """
    Re-parse every raw upload a player has made with the current parser and
    rewrite their profile from it; runs with no raw copy stay as they are.
    Like an upload, it goes a month at a time. Site stats aren't touched:
    run tools/rebuild_stats.py afterwards.
    """
    slug, etag, doc = _read_profile(store, steam_id)
    if doc is None:
        raise IngestError(404, "no_profile", f"No profile for {steam_id}.")
    unreadable = 0
    with Spool() as spool:
        for key in sorted(store.list(f"raw/{steam_id}/")):  # oldest first: later copies win
            got = store.get(key) if RAW_KEY_RE.match(key) else None
            if got is None:
                continue
            try:
                spool_upload(got[0], steam_id, spool)
            except IngestError:
                unreadable += 1
        no_raw = _no_raw(doc) - spool.ts
        fresh_months = set(spool.months())

        def every_month():
            for m, old in stored_months(store, slug, doc):
                fresh_months.discard(m)
                yield m, old
            for m in sorted(fresh_months):
                yield m, []

        months, dropped = {}, 0
        for m, old in every_month():
            runs = merge_runs([r for r in old if r["ts"] in no_raw], spool.runs(m))[0]
            dropped += len({r["ts"] for r in old} - {r["ts"] for r in runs})
            if runs:
                months[m] = [r["ts"] for r in runs]
            if dry_run:
                continue
            if runs:
                _put_over(store, month_key(slug, m), _pack({"v": 2, "runs": runs}))
            else:
                store.delete(month_key(slug, m))
        summary = {"slug": slug, "runs": sum(len(ts) for ts in months.values()),
                   "fromRaw": len(spool.ts), "noRaw": len(no_raw), "dropped": dropped,
                   "unreadableUploads": unreadable}
        if dry_run:
            return summary
    try:
        store.put(blob_key(slug), _pack(_summary(doc["name"], months, no_raw, run.PARSER_VERSION)), {}, etag)
    except StoreConflict:
        raise IngestError(503, "busy", "The profile changed during the rebuild; run it again.")
    return summary


def save_profile(store, steam_id: str, slug: str | None, etag: str | None, name: str,
                 runs: list[dict], meta: dict, now: float, no_raw: list[int] | None = None) -> str:
    """Write a whole profile from a list of runs, replacing whatever was
    there (claiming a slug if the player has none yet), and list it in the
    public index. For tools and tests; uploads merge month by month instead.
    `etag` is the summary as read, or None. `no_raw` lists the runs with no
    raw copy; None means none of them have one. Returns the slug."""
    by_month = {}
    for r in sorted(runs, key=lambda r: r["ts"]):
        by_month.setdefault(month_of(r["ts"]), []).append(r)
    no_raw = [r["ts"] for r in runs] if no_raw is None else no_raw
    old_months = set()
    if slug:
        got = store.get(blob_key(slug))
        if (got[2] if got else None) != etag:
            raise IngestError(409, "conflict", "Another upload for this profile landed at the same time. Try again.")
        if got:
            old = _unpack(got[0])
            old_months = set(old.get("months", {})) if old.get("v", 1) >= 2 else set()
    else:
        slug = _claim_slug(store, steam_id, name, _pack(_summary(name, {}, [], run.PARSER_VERSION)), meta)
        etag = store.get(blob_key(slug))[2]
    for m, month_runs in by_month.items():
        _put_over(store, month_key(slug, m), _pack({"v": 2, "runs": month_runs}))
    for m in old_months - by_month.keys():
        store.delete(month_key(slug, m))
    months = {m: [r["ts"] for r in month_runs] for m, month_runs in by_month.items()}
    try:
        store.put(blob_key(slug), _pack(_summary(name, months, no_raw, run.PARSER_VERSION)), meta, etag)
    except StoreConflict:
        raise IngestError(409, "conflict", "Another upload for this profile landed at the same time. Try again.")
    _update_index(store, slug, name, len(runs), now)
    return slug


def remove_profile(store, slug: str, raw: bool = False, dry_run: bool = False) -> dict:
    """
    Take a profile off the site: its month files, its summary, its entry in
    the player list and the record tying it to a Steam account, so the
    player's next upload starts a fresh profile (under the same slug, if
    it's still free). With raw=True their kept uploads go too. Site stats
    aren't touched: run tools/rebuild_stats.py afterwards.
    """
    steam_ids = [k[len("ids/"):-len(".json.gz")] for k in store.list("ids/")
                 if (got := store.get(k)) and _unpack(got[0]).get("slug") == slug]
    keys = sorted(store.list(f"users/{slug}/"))
    if store.get(blob_key(slug)):
        keys.append(blob_key(slug))
    keys += [id_key(s) for s in steam_ids]
    if raw:
        keys += [k for s in steam_ids for k in sorted(store.list(f"raw/{s}/"))]
    summary = {"slug": slug, "steamIds": steam_ids, "deleted": keys}
    if dry_run:
        return summary
    for _ in range(INDEX_RETRIES):
        players, etag = _read_index(store)
        if all(p["slug"] != slug for p in players):
            break
        try:
            store.put(INDEX_KEY, _pack({"v": 1, "players": [p for p in players if p["slug"] != slug]}), {}, etag)
            break
        except StoreConflict:
            continue
    else:
        raise IngestError(503, "busy", "The player list kept changing; run it again.")
    for k in keys:
        store.delete(k)
    return summary


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

    def delete(self, key):
        self._s3.delete_object(Bucket=self._bucket, Key=key)

    def list(self, prefix):
        pages = self._s3.get_paginator("list_objects_v2").paginate(Bucket=self._bucket, Prefix=prefix)
        return [o["Key"] for page in pages for o in page.get("Contents", [])]

    def presign_post(self, key, max_bytes, expires):
        """A form POST straight to S3 for exactly this key. The size cap is
        part of the signed policy, so S3 itself refuses anything bigger."""
        import boto3
        from botocore.config import Config
        region = os.environ.get("AWS_REGION", "us-west-2")
        # The regional endpoint: the global one redirects POSTs for buckets
        # outside us-east-1, which a browser form upload can't follow.
        s3 = boto3.client("s3", region_name=region, endpoint_url=f"https://s3.{region}.amazonaws.com",
                          config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))
        return s3.generate_presigned_post(
            Bucket=self._bucket, Key=key,
            Fields={"Content-Type": "application/gzip"},
            Conditions=[{"Content-Type": "application/gzip"}, ["content-length-range", 1, max_bytes]],
            ExpiresIn=expires,
        )


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
        return self._root / key  # "users/x" -> <root>/users/x

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

    def delete(self, key):
        p = self._path(key)
        for f in (p, p.with_name(p.name + ".meta.json")):
            f.unlink(missing_ok=True)

    def list(self, prefix):
        folder = self._path(prefix).parent if not prefix.endswith("/") else self._path(prefix)
        if not folder.is_dir():
            return []
        keys = (f.relative_to(self._root).as_posix() for f in folder.rglob("*") if f.is_file())
        return [k for k in keys if k.startswith(prefix) and not k.endswith(".meta.json")]


# ---------------------------------------------------------------------------
# Lambda entry points
# ---------------------------------------------------------------------------

_store = None


def _get_store():
    global _store
    if _store is None:
        _store = S3Store(os.environ["DATA_BUCKET"])
    return _store


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body)}


def lambda_handler(event, context):
    """The Function URL (payload format 2.0): hands out upload URLs."""
    http = event.get("requestContext", {}).get("http", {})
    if http.get("method") != "POST":
        return _response(405, {"error": "method_not_allowed", "message": "POST only."})
    params = dict(urllib.parse.parse_qsl(event.get("rawQueryString", ""), keep_blank_values=True))
    allowed = [p for p in os.environ.get("ALLOWED_RETURN_TO", "").split(",") if p]
    store = _get_store()
    try:
        result = authorize(params, http.get("sourceIp", ""), store, allowed, store.presign_post)
    except IngestError as e:
        print(json.dumps({"status": e.status, "code": e.code}))
        return _response(e.status, {"error": e.code, "message": e.message})
    print(json.dumps({"status": 200, "uploadId": result["uploadId"]}))
    return _response(200, result)


def process_handler(event, context):
    """S3 "object created" events for raw/. Invoked asynchronously, so an
    exception here makes Lambda retry the event (twice) and then hand it to
    failure_handler; the raw object stays put for a later rebuild."""
    for record in event.get("Records", []):
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        result = process_upload(key, _get_store())
        log = {k: v for k, v in (result or {}).items() if k != "name"}
        print(json.dumps({"key": key, **log}))


def _alert(subject: str, message: str) -> None:
    """Email the site owner, through the SNS topic the stack names (the dev
    server has none)."""
    topic = os.environ.get("ALERT_TOPIC_ARN")
    if topic:
        import boto3  # only on Lambda
        boto3.client("sns").publish(TopicArn=topic, Subject=subject[:100], Message=message)


def failure_handler(event, context):
    """Lambda's on-failure record for a process_handler event that failed
    every try: the original event plus the last error. Tells the page that
    sent the upload (its runs aren't on the profile, so sending them again
    later picks them up) and emails the site owner."""
    error = (event.get("responsePayload") or {}).get("errorMessage")
    keys = []
    for record in (event.get("requestPayload") or {}).get("Records", []):
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        m = RAW_KEY_RE.match(key)
        if m:
            _put_over(_get_store(), result_key(m.group(3)), _pack({
                "status": "failed", "error": "process_failed",
                "message": "Something went wrong adding those runs. Try again later."}))
        print(json.dumps({"failed": key, "error": error}))
        keys.append(key)
    _alert("Slay My Stats: an upload failed",
           "An upload failed every try and wasn't added. Its raw copy is kept.\n\n"
           + "\n".join(keys) + f"\n\nLast error: {error}\n\n"
           + "Details are in the process function's logs (ProcessLogGroup in CloudWatch).")
