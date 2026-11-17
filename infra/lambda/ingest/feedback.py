"""Private gamma feedback inbox, authenticated even at the direct Function URL."""
import base64
import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse
import uuid
from http.cookies import CookieError, SimpleCookie

PAGE_SIZE = 25
SCAN_LIMIT = 400  # objects read in one request; a page-scoped view may skip most
CURSOR = re.compile(r"feedback/\d{10}-[a-f0-9]{32}\.json")
COMMIT = re.compile(r"[0-9a-f]{7,40}")
CATEGORIES = {"bug": "Bug", "feature": "Feature request", "improvement": "Improvement idea"}
NOTE_ID = re.compile(r"feedback/\d{10}-[a-f0-9]{32}\.json")
OUTCOMES = ("done", "declined", "duplicate")
STATUSES = ("open", "backlog", "resolved", "all")
RESOLUTION = ("resolved_by", "resolved_at", "close_note", "resolved_in", "outcome", "duplicate_of")


def _outcome(data):
    """The validated close fields of a resolve request; ValueError when they do not fit.

    done needs a commit and a close note, declined needs a close note saying why, and
    duplicate needs the id of the note it repeats. Every user can read these, so an
    unexplained decline is refused here rather than left to the person closing it.
    """
    outcome = data.get("outcome")
    close_note = data.get("close_note", "")
    commit = str(data.get("resolved_in", "")).strip().lower()
    duplicate_of = data.get("duplicate_of", "")
    if (outcome not in OUTCOMES or not isinstance(close_note, str) or len(close_note.strip()) > 2000
            or (commit and not COMMIT.fullmatch(commit)) or not isinstance(duplicate_of, str)):
        raise ValueError()
    close_note = close_note.strip()
    if outcome == "done" and not (commit and close_note):
        raise ValueError()
    if outcome == "declined" and not close_note:
        raise ValueError()
    if outcome == "duplicate" and not NOTE_ID.fullmatch(duplicate_of):
        raise ValueError()
    return {"outcome": outcome, "close_note": close_note, "resolved_in": commit if outcome == "done" else "",
            "duplicate_of": duplicate_of if outcome == "duplicate" else ""}


def _state(note):
    """open, backlog or resolved: backlog is an open note we will take on, but not now."""
    if note.get("resolved"):
        return "resolved"
    return "backlog" if note.get("backlog") else "open"


def _backlog(note, steam, on, reason):
    """Put an open note in the backlog, or take it back out. Resolved notes are left alone."""
    if note.get("resolved"):
        return False
    if on:
        note["backlog"] = {"by": steam, "at": int(time.time()), "reason": reason}
    elif "backlog" in note:
        del note["backlog"]
    else:
        return False
    return True


def _number_all(store, bucket):
    """Give every note a stable sequence number (shown as FB-n), oldest first, and return them all.

    Notes already numbered keep theirs; any without one are numbered after the highest in creation
    order. Gamma's inbox is small, so reading it all on a create or a first view is fine.
    """
    notes = sorted(_all_notes(store, bucket), key=lambda n: (n.get("created", 0), n.get("id", "")))
    top = max([n["seq"] for n in notes if isinstance(n.get("seq"), int)] or [0])
    for note in notes:
        if not isinstance(note.get("seq"), int):
            top += 1
            note["seq"] = top
            store.put_object(Bucket=bucket, Key=note["id"], Body=json.dumps(note).encode(),
                             ContentType="application/json")
    return notes


def _resolve(note, steam, resolved, fields):
    """Resolve or reopen a note in place, keeping who did it, when, why and in which commit.

    Reopening moves the resolution into the note's history rather than erasing it, so a note
    that was closed, reopened and closed again still shows every step. Resolving a note that is
    already resolved changes nothing, so a second click cannot overwrite the first resolution.
    """
    now = int(time.time())
    if resolved:
        if note.get("resolved"):
            return
        note.pop("backlog", None)
        note.update(resolved=True, resolved_by=steam, resolved_at=now, **fields)
    elif note.get("resolved"):
        entry = {k: note.pop(k, None) for k in RESOLUTION}
        entry.update(reopened_by=steam, reopened_at=now)
        note.setdefault("history", []).append(entry)
        note["resolved"] = False

_NAMES = {}          # steam id -> (looked up at, display name); warm Lambdas reuse it
NAME_TTL = 6 * 3600


def _steam_name(steam):
    """A player's current Steam display name, or None if Steam could not be asked."""
    cached = _NAMES.get(steam)
    if cached and time.time() - cached[0] < NAME_TTL:
        return cached[1]
    try:
        from handler import lookup_steam_name
        name = lookup_steam_name(steam)
    except Exception:
        name = None
    if name:
        _NAMES[steam] = (time.time(), name)
    return name


def _named(note):
    """The note as sent to the page: who wrote and who resolved it, by Steam name. Names are looked
    up per response, never stored on the note, so a rename shows up and nothing extra is kept."""
    out = dict(note)
    for field in ("author", "resolved_by"):
        name = note.get(field) and _steam_name(str(note[field]))
        if name:
            out[field + "_name"] = name
    return out


def _valid_path(path) -> bool:
    return isinstance(path, str) and path.startswith("/") and not path.startswith("//") and len(path) <= 3000


def _read_notes(store, bucket, scope, path, cursor, status="all", category=""):
    """A page of notes, newest first; scope "page" keeps only that path.

    status (open, backlog, resolved or all; open leaves the backlog out) and category narrow the page the same way: a note that
    does not match is read and skipped, so a narrow filter may scan to the limit and hand
    back a cursor with fewer than a full page.

    Keys sort newest first, so the cursor is the last key read (StartAfter) and
    no more keys means the visible inbox is exhausted.
    """
    notes, scanned, after = [], 0, cursor or ""
    while True:
        args = {"Bucket": bucket, "Prefix": "feedback/", "MaxKeys": 100}
        if after:
            args["StartAfter"] = after
        listing = store.list_objects_v2(**args)
        contents = listing.get("Contents", [])
        for index, obj in enumerate(contents):
            after = obj["Key"]
            scanned += 1
            note = json.loads(store.get_object(Bucket=bucket, Key=after)["Body"].read())
            if scope == "page" and note.get("path") != path:
                continue
            if status != "all" and _state(note) != status:
                continue
            if category and note.get("category") != category:
                continue
            notes.append(note)
            if len(notes) >= PAGE_SIZE:
                return notes, (after if index + 1 < len(contents) or listing.get("IsTruncated") else None)
        if not listing.get("IsTruncated"):
            return notes, None
        if scanned >= SCAN_LIMIT:
            return notes, after


def handle(event):
    def reply(status, body):
        return {"statusCode": status, "headers": {"content-type": "application/json",
                "cache-control": "no-store"}, "body": json.dumps(body)}

    cookies = SimpleCookie()
    try:
        cookies.load("; ".join(event.get("cookies", [])))
        token = cookies["__Host-gamma"].value
        steam, expiry, signature = token.split(".")
        expected = hmac.new(os.environ["GAMMA_SESSION_SECRET"].encode(),
                            f"{steam}.{expiry}".encode(), hashlib.sha256).hexdigest()
        if (steam not in os.environ["ALLOWED_STEAM_IDS"].split(",")
                or int(expiry) <= time.time() or not hmac.compare_digest(signature, expected)):
            raise ValueError()
    except (KeyError, ValueError, CookieError):
        return reply(401, {"message": "Sign in to gamma again to use feedback."})
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if method not in ("GET", "POST"):
        return reply(405, {"message": "Method not allowed."})
    origin = os.environ["GAMMA_ORIGIN"]
    if method == "POST" and event.get("headers", {}).get("origin") != origin:
        return reply(403, {"message": "Feedback must be submitted from gamma."})
    import boto3
    store = boto3.client("s3")
    bucket = os.environ["DATA_BUCKET"]
    if method == "GET":
        params = dict(urllib.parse.parse_qsl(event.get("rawQueryString", "")))
        scope = params.get("scope", "site")
        cursor = params.get("cursor", "")
        if scope == "page" and not _valid_path(params.get("path")):
            return reply(400, {"message": "A page view needs a path."})
        if scope not in ("page", "site"):
            return reply(400, {"message": "Scope must be page or site."})
        status, category = params.get("status", "all"), params.get("category", "")
        if status not in STATUSES or (category and category not in CATEGORIES):
            return reply(400, {"message": "Status must be open, backlog, resolved or all, and category a known type."})
        if cursor and not CURSOR.fullmatch(cursor):
            return reply(400, {"message": "Invalid page cursor."})
        notes, following = _read_notes(store, bucket, scope, params.get("path", ""), cursor, status, category)
        if any(not isinstance(n.get("seq"), int) for n in notes):
            _number_all(store, bucket)  # first view after this shipped: number the old notes once
            notes, following = _read_notes(store, bucket, scope, params.get("path", ""), cursor, status, category)
        return reply(200, {"notes": [_named(n) for n in notes], "next": following, "scope": scope, "me": steam})
    try:
        raw = event.get("body") or ""
        if len(raw) > 40000:
            raise ValueError()
        data = json.loads(base64.b64decode(raw) if event.get("isBase64Encoded") else raw)
        action = data.get("action", "create")
        if action == "resolve":
            key = data.get("id", "")
            if not NOTE_ID.fullmatch(key):
                raise ValueError()
            note = json.loads(store.get_object(Bucket=bucket, Key=key)["Body"].read())
            resolved = bool(data.get("resolved"))
            _resolve(note, steam, resolved, _outcome(data) if resolved else {})
        elif action == "backlog":
            key = data.get("id", "")
            reason = data.get("reason", "")
            if not NOTE_ID.fullmatch(key) or not isinstance(reason, str) or len(reason.strip()) > 500:
                raise ValueError()
            note = json.loads(store.get_object(Bucket=bucket, Key=key)["Body"].read())
            if not _backlog(note, steam, bool(data.get("on")), reason.strip()):
                return reply(200, {"note": _named(note), "me": steam})
        elif action == "plus":
            # One +1 per signed-in person, set or taken back. Repeating the same request changes
            # nothing and writes nothing, so a double click or a script cannot pile up writes.
            key = data.get("id", "")
            if not NOTE_ID.fullmatch(key):
                raise ValueError()
            note = json.loads(store.get_object(Bucket=bucket, Key=key)["Body"].read())
            plus = [p for p in note.get("plus", []) if isinstance(p, str)]
            if bool(data.get("on")) == (steam in plus):
                return reply(200, {"note": _named(note), "me": steam})
            plus = [p for p in plus if p != steam] + ([steam] if data.get("on") else [])
            note["plus"] = plus[:50]
        elif action == "create":
            comment = data.get("comment", "")
            category = data.get("category")  # notes from before categories have none
            if category is not None and category not in CATEGORIES:
                raise ValueError()
            path = data.get("path", "")
            target = data.get("target", {})
            if (not isinstance(comment, str) or not 1 <= len(comment.strip()) <= 4000
                    or not _valid_path(path)
                    or not isinstance(target, dict) or len(json.dumps(target)) > 12000):
                raise ValueError()
            # The exact page URL, so a report can be reopened without guessing the host.
            # Older clients send only the path; those notes still get one.
            url = data.get("url") or origin + path
            if (not isinstance(url, str) or len(url) > 3200
                    or not (url == origin or url.startswith(origin + "/"))):
                raise ValueError()
            key = f"feedback/{9999999999 - int(time.time()):010d}-{uuid.uuid4().hex}.json"
            seq = max([n["seq"] for n in _number_all(store, bucket)] or [0]) + 1
            note = {"id": key, "seq": seq, "created": int(time.time()), "author": steam,
                    "comment": comment.strip(), "path": path, "url": url, "target": target, "resolved": False}
            if category:
                note["category"] = category
        else:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return reply(400, {"message": "Invalid feedback. Use a comment of 1–4000 characters."})
    store.put_object(Bucket=bucket, Key=key, Body=json.dumps(note).encode(), ContentType="application/json")
    return reply(200, {"note": _named(note), "me": steam})


def _all_notes(store, bucket):
    """Every note, for the digests. Gamma's inbox is small, so this reads them all."""
    notes, token = [], None
    while True:
        args = {"Bucket": bucket, "Prefix": "feedback/"}
        if token:
            args["ContinuationToken"] = token
        listing = store.list_objects_v2(**args)
        for obj in listing.get("Contents", []):
            notes.append(json.loads(store.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()))
        if not listing.get("IsTruncated"):
            return notes
        token = listing.get("NextContinuationToken")


def _line(note, origin):
    text = " ".join(note.get("comment", "").split())
    text = text if len(text) <= 100 else text[:99] + "…"
    kind = CATEGORIES.get(note.get("category"))
    text = f"[{kind}] {text}" if kind else text
    text = f"FB-{note['seq']} {text}" if isinstance(note.get("seq"), int) else text
    who = _named(note).get("author_name") or "…" + str(note.get("author", "?"))[-4:]
    return f"{who}: {text}\n  {note.get('url') or origin + note.get('path', '')}"


def build_report(notes, now, period, origin):
    """The owner's feedback email, or None when there is nothing worth sending.

    "daily" lists what came in over the last day and sends nothing on a quiet day. "weekly"
    always sends: how many notes are open, how many came in and how many were resolved over
    the week, and the open ones. Notes resolved before resolutions were timestamped have no
    date, so they are not counted as resolved this week.
    """
    window = 86400 if period == "daily" else 7 * 86400
    since = now - window
    opened = [n for n in notes if _state(n) == "open"]
    later = [n for n in notes if _state(n) == "backlog"]
    new = sorted((n for n in notes if n.get("created", 0) >= since), key=lambda n: n["created"])
    closed = [n for n in notes if n.get("resolved") and n.get("resolved_at", 0) >= since]
    if period == "daily":
        if not new:
            return None
        head = f"New feedback in the last day: {len(new)}. Open in total: {len(opened)}, backlog: {len(later)}.\n\n"
        return (f"Gamma feedback: {len(new)} new, {len(opened)} open",
                head + "\n".join(_line(n, origin) for n in new))
    body = (f"Open in total: {len(opened)}, backlog: {len(later)}\nCame in this week: {len(new)}\n"
            f"Resolved this week: {len(closed)}\n")
    if opened:
        oldest_first = sorted(opened, key=lambda n: n.get("created", 0))
        body += "\nStill open:\n" + "\n".join(_line(n, origin) for n in oldest_first)
    return f"Gamma feedback, this week: {len(opened)} open, {len(new)} in, {len(closed)} resolved", body
