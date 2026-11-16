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
            note["resolved"] = bool(data.get("resolved"))
        elif action == "create":
            comment = data.get("comment", "")
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
        else:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return reply(400, {"message": "Invalid feedback. Use a comment of 1–4000 characters."})
    store.put_object(Bucket=bucket, Key=key, Body=json.dumps(note).encode(), ContentType="application/json")
    return reply(200, {"note": note})
