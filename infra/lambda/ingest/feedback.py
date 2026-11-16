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
RESOLUTION = ("resolved_by", "resolved_at", "close_note", "resolved_in")


def _resolve(note, steam, resolved, close_note, commit):
    """Resolve or reopen a note in place, keeping who did it, when, why and in which commit.

    Reopening moves the resolution into the note's history rather than erasing it, so a note
    that was closed, reopened and closed again still shows every step. Resolving a note that is
    already resolved changes nothing, so a second click cannot overwrite the first resolution.
    """
    now = int(time.time())
    if resolved:
        if note.get("resolved"):
            return
        note.update(resolved=True, resolved_by=steam, resolved_at=now,
                    close_note=close_note, resolved_in=commit)
    elif note.get("resolved"):
        entry = {k: note.pop(k, None) for k in RESOLUTION}
        entry.update(reopened_by=steam, reopened_at=now)
        note.setdefault("history", []).append(entry)
        note["resolved"] = False


def _valid_path(path) -> bool:
    return isinstance(path, str) and path.startswith("/") and not path.startswith("//") and len(path) <= 3000


def _read_notes(store, bucket, scope, path, cursor):
    """A page of notes, newest first; scope "page" keeps only that path.

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
        if cursor and not CURSOR.fullmatch(cursor):
            return reply(400, {"message": "Invalid page cursor."})
        notes, following = _read_notes(store, bucket, scope, params.get("path", ""), cursor)
        return reply(200, {"notes": notes, "next": following, "scope": scope})
    try:
        raw = event.get("body") or ""
        if len(raw) > 40000:
            raise ValueError()
        data = json.loads(base64.b64decode(raw) if event.get("isBase64Encoded") else raw)
        action = data.get("action", "create")
        if action == "resolve":
            key = data.get("id", "")
            if not re.fullmatch(r"feedback/\d{10}-[a-f0-9]{32}\.json", key):
                raise ValueError()
            note = json.loads(store.get_object(Bucket=bucket, Key=key)["Body"].read())
            close_note, commit = data.get("close_note", ""), str(data.get("resolved_in", "")).strip().lower()
            if not isinstance(close_note, str) or len(close_note.strip()) > 2000 or (commit and not COMMIT.fullmatch(commit)):
                raise ValueError()
            _resolve(note, steam, bool(data.get("resolved")), close_note.strip(), commit)
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
            note = {"id": key, "created": int(time.time()), "author": steam,
                    "comment": comment.strip(), "path": path, "url": url, "target": target, "resolved": False}
            if category:
                note["category"] = category
        else:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return reply(400, {"message": "Invalid feedback. Use a comment of 1–4000 characters."})
    store.put_object(Bucket=bucket, Key=key, Body=json.dumps(note).encode(), ContentType="application/json")
    return reply(200, {"note": note})


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
    return f"…{str(note.get('author', '?'))[-4:]}: {text}\n  {note.get('url') or origin + note.get('path', '')}"


def build_report(notes, now, period, origin):
    """The owner's feedback email, or None when there is nothing worth sending.

    "daily" lists what came in over the last day and sends nothing on a quiet day. "weekly"
    always sends: how many notes are open, how many came in and how many were resolved over
    the week, and the open ones. Notes resolved before resolutions were timestamped have no
    date, so they are not counted as resolved this week.
    """
    window = 86400 if period == "daily" else 7 * 86400
    since = now - window
    opened = [n for n in notes if not n.get("resolved")]
    new = sorted((n for n in notes if n.get("created", 0) >= since), key=lambda n: n["created"])
    closed = [n for n in notes if n.get("resolved") and n.get("resolved_at", 0) >= since]
    if period == "daily":
        if not new:
            return None
        head = f"New feedback in the last day: {len(new)}. Open in total: {len(opened)}.\n\n"
        return (f"Gamma feedback: {len(new)} new, {len(opened)} open",
                head + "\n".join(_line(n, origin) for n in new))
    body = (f"Open in total: {len(opened)}\nCame in this week: {len(new)}\n"
            f"Resolved this week: {len(closed)}\n")
    if opened:
        oldest_first = sorted(opened, key=lambda n: n.get("created", 0))
        body += "\nStill open:\n" + "\n".join(_line(n, origin) for n in oldest_first)
    return f"Gamma feedback, this week: {len(opened)} open, {len(new)} in, {len(closed)} resolved", body
