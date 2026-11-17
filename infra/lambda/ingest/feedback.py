"""The feedback inbox, kept in the shared DynamoDB table (docs/prod-feedback-plan.md).

Gamma's auth Lambda serves it at /auth/feedback, checking the signed gamma session itself so
the direct Function URL is no way around it. Which environment a note belongs to is fixed by
the Lambda's own FEEDBACK_ENV, never by the request; FEEDBACK_READ_ENVS lists the ones it may
read (gamma reads prod too, prod never reads gamma), and IAM holds each role to those.

Items, all keyed by env (partition) and sk:
    note      sk = the note id; the note's JSON in `body`, plus plus_count and the index keys
    +1        sk = vote#<note id>#<steam id>
    throttle  sk = rate#<steam id>#<UTC hour>, deleted by TTL
    FB-n      env = counter, sk = seq
"""
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
READ_LIMIT = 400  # items one request may read for a page view, which filters what it reads
COMMIT = re.compile(r"[0-9a-f]{7,40}")
CATEGORIES = {"bug": "Bug", "feature": "Feature request", "improvement": "Improvement idea"}
NOTE_ID = re.compile(r"feedback/\d{10}-[a-f0-9]{32}\.json")
OUTCOMES = ("done", "declined", "duplicate")
STATUSES = ("open", "backlog", "resolved", "all")
RESOLUTION = ("resolved_by", "resolved_at", "close_note", "resolved_in", "outcome", "duplicate_of")
ENVS = ("gamma", "prod")
RATE_WRITES = 60  # writes one player may make in a UTC hour...
RATE_NOTES = 10   # ...of which new notes
# Index name -> its sort key. Every index is partitioned on env, like the table, so the IAM
# rule on env (dynamodb:LeadingKeys) covers the indexes too.
INDEXES = {"base": "sk", "ByState": "st", "ByStateCategory": "stcat", "ByCategory": "cat", "ByPage": "pg"}


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


class Refused(Exception):
    """A request the inbox turns down: the HTTP status and the message the panel shows."""
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def _code(error):
    """The DynamoDB error code of a botocore ClientError, or "" for anything else."""
    return getattr(error, "response", {}).get("Error", {}).get("Code", "")


def _page_hash(path):
    """A page's key in the ByPage index: a raw path can pass the 1 KB key limit."""
    return hashlib.sha256(path.encode()).hexdigest()[:20]


def _index_keys(note):
    """The index sort keys a note is filed under. A note without a type stays out of the type indexes."""
    state, nid, category = _state(note), note["id"], note.get("category")
    keys = {"st": f"{state}#{nid}", "pg": f"{_page_hash(note.get('path', ''))}#{nid}"}
    if category:
        keys.update(stcat=f"{state}#{category}#{nid}", cat=f"{category}#{nid}")
    return keys


def note_item(env, note, plus_count):
    """A note as a table item. The note's own JSON goes in `body` (its target holds fractional pixel
    sizes, which DynamoDB numbers would turn into Decimals); seq and created sit beside it."""
    item = {"env": {"S": env}, "sk": {"S": note["id"]}, "body": {"S": json.dumps(note)},
            "created": {"N": str(int(note.get("created", 0)))}, "plus_count": {"N": str(int(plus_count))}}
    if isinstance(note.get("seq"), int):
        item["seq"] = {"N": str(note["seq"])}
    item.update({name: {"S": value} for name, value in _index_keys(note).items()})
    return item


def vote_key(env, note_id, steam):
    return {"env": {"S": env}, "sk": {"S": f"vote#{note_id}#{steam}"}}


def vote_item(env, note_id, steam, at):
    return {**vote_key(env, note_id, steam), "at": {"N": str(int(at))}}


def _from_item(item):
    """The note as the page sees it: its stored fields, its env and its +1 count."""
    note = json.loads(item["body"]["S"])
    note["env"] = item["env"]["S"]
    note["plus_count"] = int(item.get("plus_count", {}).get("N", "0"))
    return note


def _plan(scope, path, status, category):
    """Which index answers a view, the prefix its keys start with, and the filter a page view applies.

    Each index key ends in the note id, so ascending order is newest first. A page has few notes,
    so This page reads ByPage and checks status and type itself.
    """
    if scope == "page":
        def keep(note):
            return (note.get("path") == path and (status == "all" or _state(note) == status)
                    and (not category or note.get("category") == category))
        return "ByPage", _page_hash(path) + "#", keep
    if status != "all" and category:
        return "ByStateCategory", f"{status}#{category}#", None
    if status != "all":
        return "ByState", f"{status}#", None
    if category:
        return "ByCategory", f"{category}#", None
    return "base", "feedback/", None


def _key(env, note_id, index, prefix):
    """The key to resume a query after this note, as DynamoDB's LastEvaluatedKey would give it."""
    key = {"env": {"S": env}, "sk": {"S": note_id}}
    if index != "base":
        key[INDEXES[index]] = {"S": prefix + note_id}
    return key


def _query(db, table, env, plan, start, want):
    """Up to `want` notes of one env from `start`, newest first, and the key to go on from (None at the end)."""
    index, prefix, keep = plan
    args = {"TableName": table, "KeyConditionExpression": "#e = :e AND begins_with(#s, :p)",
            "ExpressionAttributeNames": {"#e": "env", "#s": INDEXES[index]},
            "ExpressionAttributeValues": {":e": {"S": env}, ":p": {"S": prefix}}}
    if index != "base":
        args["IndexName"] = index
    notes, read = [], 0
    while True:
        args["Limit"] = 100 if keep else want - len(notes)
        if start:
            args["ExclusiveStartKey"] = start
        page = db.query(**args)
        items = page.get("Items", [])
        for i, item in enumerate(items):
            read += 1
            note = _from_item(item)
            if keep and not keep(note):
                continue
            notes.append(note)
            if len(notes) >= want:
                more = i + 1 < len(items) or "LastEvaluatedKey" in page
                return notes, (_key(env, note["id"], index, prefix) if more else None)
        start = page.get("LastEvaluatedKey")
        if not start:
            return notes, None
        if read >= READ_LIMIT:
            return notes, start


def _encode_cursor(cursor):
    """{env: key or None (from the start)} -> the opaque string the page sends back; envs read to the end are left out."""
    plain = {env: key and {name: value["S"] for name, value in key.items()} for env, key in cursor.items()}
    return base64.urlsafe_b64encode(json.dumps(plain, separators=(",", ":")).encode()).decode()


def _decode_cursor(raw, envs, plan):
    """The cursor the page sent, checked strictly: only the envs being read, and keys of exactly the
    shape this view's index gives, for a real note id. Anything else is a 400."""
    index, prefix, _ = plan
    try:
        plain = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except ValueError:
        raise Refused(400, "Invalid page cursor.")
    names = {"env", "sk"} | ({INDEXES[index]} if index != "base" else set())
    if not isinstance(plain, dict) or not plain or not set(plain) <= set(envs):
        raise Refused(400, "Invalid page cursor.")
    cursor = {}
    for env, key in plain.items():
        if key is not None:
            if (not isinstance(key, dict) or set(key) != names or key["env"] != env
                    or not isinstance(key["sk"], str) or not NOTE_ID.fullmatch(key["sk"])
                    or (index == "base" and not key["sk"].startswith(prefix))
                    or (index != "base" and key[INDEXES[index]] != prefix + key["sk"])):
                raise Refused(400, "Invalid page cursor.")
            key = {name: {"S": value} for name, value in key.items()}
        cursor[env] = key
    return cursor


def _read(db, table, plan, cursor):
    """A page of notes across the envs in the cursor, merged newest first, and the cursor for the next page.

    Each env is read for a full page; what is not shown is read again next time from the last note
    shown of that env, so Both never skips or repeats a note.
    """
    index, prefix, _ = plan
    found, read = [], {}
    for env, start in cursor.items():
        notes, end = _query(db, table, env, plan, start, PAGE_SIZE)
        found += notes
        read[env] = (notes, end, start)
    page = sorted(found, key=lambda n: n["id"])[:PAGE_SIZE]
    following = {}
    for env, (notes, end, start) in read.items():
        shown = [n for n in page if n["env"] == env]
        if len(shown) < len(notes):
            following[env] = _key(env, shown[-1]["id"], index, prefix) if shown else start
        elif end is not None:
            following[env] = end
    return page, (_encode_cursor(following) if following else None)


def _with_votes(db, table, notes, steam):
    """Each note as sent: +1 count and whether this player gave one, never who the others are."""
    keys = [vote_key(n["env"], n["id"], steam) for n in notes]
    mine = set()
    while keys:
        batch, keys = keys[:100], keys[100:]
        request = {table: {"Keys": batch, "ProjectionExpression": "sk"}}
        while request:
            got = db.batch_get_item(RequestItems=request)
            mine.update(item["sk"]["S"] for item in got.get("Responses", {}).get(table, []))
            request = got.get("UnprocessedKeys") or None
    return [_named({**n, "plus_mine": f"vote#{n['id']}#{steam}" in mine}) for n in notes]


def _get(db, table, env, note_id):
    item = db.get_item(TableName=table, Key={"env": {"S": env}, "sk": {"S": note_id}}, ConsistentRead=True).get("Item")
    if not item:
        raise Refused(404, "That note no longer exists.")
    return item


def _throttle(db, table, env, steam, creating):
    """Count this write against the player's hour; refuse once the hour is used up (FB-24).

    One conditional ADD, so two writes at once cannot both slip under the cap. The counter
    deletes itself (TTL on `expires`) a day after its hour.
    """
    hour = int(time.time() // 3600)
    names, values = {"#n": "n", "#x": "expires"}, {":one": {"N": "1"}, ":max": {"N": str(RATE_WRITES)},
                                                     ":exp": {"N": str((hour + 25) * 3600)}}
    update, condition = "SET #x = if_not_exists(#x, :exp) ADD #n :one", "(attribute_not_exists(#n) OR #n < :max)"
    if creating:
        names["#c"] = "c"
        values[":cmax"] = {"N": str(RATE_NOTES)}
        update += ", #c :one"
        condition += " AND (attribute_not_exists(#c) OR #c < :cmax)"
    try:
        db.update_item(TableName=table, Key={"env": {"S": env}, "sk": {"S": f"rate#{steam}#{hour}"}},
                       UpdateExpression=update, ConditionExpression=condition,
                       ExpressionAttributeNames=names, ExpressionAttributeValues=values)
    except Exception as error:
        if _code(error) != "ConditionalCheckFailedException":
            raise
        raise Refused(429, "That's a lot of feedback for one hour. Try again later.")


def _change(db, table, env, note_id, steam, change):
    """Apply change(note) -> bool to a stored note, on condition its state is still the one read,
    so two reviewers cannot overwrite each other. Only the body and the state keys are written;
    plus_count is left to the +1 transactions."""
    item = _get(db, table, env, note_id)
    note = json.loads(item["body"]["S"])
    if not change(note):
        return
    names, values = {"#b": "body", "#st": "st"}, {":b": {"S": json.dumps(note)}, ":was": item["st"],
                                                   ":st": {"S": _index_keys(note)["st"]}}
    update = "SET #b = :b, #st = :st"
    if "stcat" in item:
        names["#sc"] = "stcat"
        values[":sc"] = {"S": _index_keys(note)["stcat"]}
        update += ", #sc = :sc"
    try:
        db.update_item(TableName=table, Key={"env": {"S": env}, "sk": {"S": note_id}}, UpdateExpression=update,
                       ConditionExpression="#st = :was", ExpressionAttributeNames=names, ExpressionAttributeValues=values)
    except Exception as error:
        if _code(error) != "ConditionalCheckFailedException":
            raise
        raise Refused(409, "Someone changed this note just now. Refresh and try again.")


def _plus(db, table, env, note_id, steam, on):
    """Give or take back this player's +1: the vote item and the count move together in one transaction.

    The vote is put only if absent and deleted only if present, so a repeat fails its condition
    and changes nothing: one +1 per player, and the count stays exact.
    """
    note_key = {"env": {"S": env}, "sk": {"S": note_id}}
    count = {"Update": {"TableName": table, "Key": note_key, "UpdateExpression": "ADD plus_count :d",
                        "ConditionExpression": "attribute_exists(sk)",
                        "ExpressionAttributeValues": {":d": {"N": "1" if on else "-1"}}}}
    vote = ({"Put": {"TableName": table, "Item": vote_item(env, note_id, steam, time.time()),
                     "ConditionExpression": "attribute_not_exists(sk)"}} if on else
            {"Delete": {"TableName": table, "Key": vote_key(env, note_id, steam),
                        "ConditionExpression": "attribute_exists(sk)"}})
    try:
        db.transact_write_items(TransactItems=[vote, count])
    except Exception as error:
        if _code(error) != "TransactionCanceledException":
            raise
        _get(db, table, env, note_id)  # a missing note is a 404; otherwise it was a repeat


def _create(db, table, env, steam, note):
    """Number the note (one sequence across both envs), then put it and its author's +1 together.
    A failed put leaves a gap in the numbers, never a repeat."""
    got = db.update_item(TableName=table, Key={"env": {"S": "counter"}, "sk": {"S": "seq"}},
                         UpdateExpression="ADD #v :one", ExpressionAttributeNames={"#v": "value"},
                         ExpressionAttributeValues={":one": {"N": "1"}}, ReturnValues="UPDATED_NEW")
    note["seq"] = int(got["Attributes"]["value"]["N"])
    db.transact_write_items(TransactItems=[
        {"Put": {"TableName": table, "Item": note_item(env, note, 1), "ConditionExpression": "attribute_not_exists(sk)"}},
        {"Put": {"TableName": table, "Item": vote_item(env, note["id"], steam, note["created"]),
                 "ConditionExpression": "attribute_not_exists(sk)"}}])


def _session(event):
    """The signed-in gamma reviewer's Steam ID, or None."""
    cookies = SimpleCookie()
    try:
        cookies.load("; ".join(event.get("cookies", [])))
        token = cookies["__Host-gamma"].value
        steam, expiry, signature = token.split(".")
        expected = hmac.new(os.environ["GAMMA_SESSION_SECRET"].encode(),
                            f"{steam}.{expiry}".encode(), hashlib.sha256).hexdigest()
        if (steam not in os.environ["ALLOWED_STEAM_IDS"].split(",")
                or int(expiry) <= time.time() or not hmac.compare_digest(signature, expected)):
            return None
        return steam
    except (KeyError, ValueError, CookieError):
        return None


def handle(event):
    def reply(status, body):
        return {"statusCode": status, "headers": {"content-type": "application/json",
                "cache-control": "no-store"}, "body": json.dumps(body)}

    steam = _session(event)
    if not steam:
        return reply(401, {"message": "Sign in to gamma again to use feedback."})
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if method not in ("GET", "POST"):
        return reply(405, {"message": "Method not allowed."})
    origin = os.environ["GAMMA_ORIGIN"]
    if method == "POST" and event.get("headers", {}).get("origin") != origin:
        return reply(403, {"message": "Feedback must be submitted from gamma."})
    table, env = os.environ["FEEDBACK_TABLE"], os.environ["FEEDBACK_ENV"]
    readable = [e for e in os.environ.get("FEEDBACK_READ_ENVS", env).split(",") if e in ENVS] or [env]
    admin = steam in [s for s in os.environ.get("ADMIN_STEAM_IDS", "").split(",") if s]
    about = {"me": steam, "env": env, "envs": readable, "admin": admin}
    import boto3
    db = boto3.client("dynamodb")
    try:
        if method == "GET":
            return reply(200, {**about, **_get_view(db, table, readable, env, steam, event)})
        return reply(200, {**about, "note": _post(db, table, env, steam, admin, origin, event)})
    except Refused as refused:
        return reply(refused.status, {"message": refused.message})


def _get_view(db, table, readable, env, steam, event):
    params = dict(urllib.parse.parse_qsl(event.get("rawQueryString", "")))
    if "id" in params:  # one note, for a ?feedback= link
        if not NOTE_ID.fullmatch(params["id"]):
            raise Refused(400, "Invalid note id.")
        for e in readable:
            item = db.get_item(TableName=table, Key={"env": {"S": e}, "sk": {"S": params["id"]}}).get("Item")
            if item:
                return {"notes": _with_votes(db, table, [_from_item(item)], steam), "next": None}
        return {"notes": [], "next": None}
    scope = params.get("scope", "site")
    if scope not in ("page", "site"):
        raise Refused(400, "Scope must be page or site.")
    if scope == "page" and not _valid_path(params.get("path")):
        raise Refused(400, "A page view needs a path.")
    status, category = params.get("status", "all"), params.get("category", "")
    if status not in STATUSES or (category and category not in CATEGORIES):
        raise Refused(400, "Status must be open, backlog, resolved or all, and category a known type.")
    which = params.get("env", env)
    envs = readable if which == "both" else [which]
    if not set(envs) <= set(readable):
        raise Refused(400, "Environment must be one this inbox can read.")
    plan = _plan(scope, params.get("path", ""), status, category)
    cursor = _decode_cursor(params["cursor"], envs, plan) if params.get("cursor") else {e: None for e in envs}
    notes, following = _read(db, table, plan, cursor)
    return {"notes": _with_votes(db, table, notes, steam), "next": following, "scope": scope}


def _post(db, table, env, steam, admin, origin, event):
    try:
        raw = event.get("body") or ""
        if len(raw) > 40000:
            raise ValueError()
        data = json.loads(base64.b64decode(raw) if event.get("isBase64Encoded") else raw)
        action = data.get("action", "create")
        if action not in ("create", "plus", "resolve", "backlog"):
            raise ValueError()
        if action != "create":
            note_id = data.get("id", "")
            if not NOTE_ID.fullmatch(note_id):
                raise ValueError()
            if data.get("env", env) != env:
                raise Refused(403, f"Notes from {data.get('env')} can only be changed there.")
            if action in ("resolve", "backlog") and not admin:
                raise Refused(403, "Only the site's admin can resolve or backlog notes.")
        if action == "resolve":
            resolved = bool(data.get("resolved"))
            fields = _outcome(data) if resolved else {}
            change = lambda note: _changed(note, lambda n: _resolve(n, steam, resolved, fields))
        elif action == "backlog":
            reason = data.get("reason", "")
            if not isinstance(reason, str) or len(reason.strip()) > 500:
                raise ValueError()
            on = bool(data.get("on"))
            change = lambda note: _backlog(note, steam, on, reason.strip())
        elif action == "create":
            note = _new_note(data, steam, origin)
    except (ValueError, TypeError, AttributeError):
        raise Refused(400, "Invalid feedback. Use a comment of 1–4000 characters.")
    _throttle(db, table, env, steam, action == "create")
    if action == "create":
        _create(db, table, env, steam, note)
        note_id = note["id"]
    elif action == "plus":
        _plus(db, table, env, note_id, steam, bool(data.get("on")))
    else:
        _change(db, table, env, note_id, steam, change)
    return _with_votes(db, table, [_from_item(_get(db, table, env, note_id))], steam)[0]


def _changed(note, change):
    """Run an in-place change and say whether it changed anything."""
    before = json.dumps(note, sort_keys=True)
    change(note)
    return json.dumps(note, sort_keys=True) != before


def _new_note(data, steam, origin):
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
    now = int(time.time())
    note = {"id": f"feedback/{9999999999 - now:010d}-{uuid.uuid4().hex}.json", "created": now, "author": steam,
            "comment": comment.strip(), "path": path, "url": url, "target": target, "resolved": False}
    if category:
        note["category"] = category
    return note


def all_notes(db, table, env):
    """Every note of one env, newest first, for the digests and the batch tool."""
    args = {"TableName": table, "KeyConditionExpression": "#e = :e AND begins_with(sk, :p)",
            "ExpressionAttributeNames": {"#e": "env"},
            "ExpressionAttributeValues": {":e": {"S": env}, ":p": {"S": "feedback/"}}}
    notes = []
    while True:
        page = db.query(**args)
        notes += [_from_item(item) for item in page.get("Items", [])]
        if "LastEvaluatedKey" not in page:
            return notes
        args["ExclusiveStartKey"] = page["LastEvaluatedKey"]


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
