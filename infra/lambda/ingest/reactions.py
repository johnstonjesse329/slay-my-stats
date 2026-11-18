"""Reactions on the What's new posts (site/whats-new/), kept in the feedback table.

Served at /auth/reactions (session.py): the ingest Lambda on prod, gamma's auth Lambda on gamma.
Anyone may read the counts; reacting takes a Steam sign-in, one of each reaction per player and
post. Like feedback, the env a reaction is stored under is the Lambda's own FEEDBACK_ENV.

    GET  /auth/reactions?posts=a,b&fixes=a:12.31,b:5
        -> {"signedIn": bool, "posts": {"a": {"counts": {"flame": 3}, "mine": ["flame"],
                                              "asked": {"count": 7, "mine": true}}}}
    POST /auth/reactions {"post": "a", "kind": "flame", "on": true}
        -> {"signedIn": true, "posts": {"a": {...}}}

`fixes` names the feedback notes a post closes (its FB numbers). `asked` is how many players
filed or +1'd any of them, each counted once, and whether you are one; a note's author always
holds its first +1 (feedback._create). Post ids are not checked against the site's posts: the
Lambda can't see the site bucket, and an unknown id only ever holds the reactions sent to it.

Items, in the env's partition beside the notes (whose keys all start feedback/, so no note
query reads these):
    reaction  sk = react#<steam id>#<post>#<kind>, at
    counts    sk = rcount#<post>, one number attribute per kind (n_flame, n_elite, ...)
    throttle  sk = rrate#<steam id>#<UTC hour>, deleted by TTL
"""
import base64
import json
import os
import re
import time

# The reactions a post offers, in the order site/whats-new.js shows them.
KINDS = ("flame", "elite", "skull", "eye", "huh", "flower")
POST_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
POST_ID_MAX = 60   # build_site.POST_ID_MAX
MAX_POSTS = 100    # posts one read may ask about
MAX_FIXES = 10     # feedback notes one post may name
RATE_WRITES = 120  # reactions one player may change in a UTC hour
NOTES_TTL = 600    # seconds a warm Lambda keeps its FB-number -> note map

_notes = {}  # tuple(envs) -> (read at, {seq: (env, note id)})


class Refused(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def _code(error):
    return getattr(error, "response", {}).get("Error", {}).get("Code", "")


def _post_id(value):
    if not isinstance(value, str) or len(value) > POST_ID_MAX or not POST_ID.fullmatch(value):
        raise Refused(400, "That isn't a post on this site.")
    return value


def _query_all(db, args):
    items = []
    while True:
        page = db.query(**args)
        items += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return items
        args = {**args, "ExclusiveStartKey": page["LastEvaluatedKey"]}


def _prefixed(db, table, env, prefix, projection=None):
    args = {"TableName": table, "KeyConditionExpression": "#e = :e AND begins_with(sk, :p)",
            "ExpressionAttributeNames": {"#e": "env"},
            "ExpressionAttributeValues": {":e": {"S": env}, ":p": {"S": prefix}}}
    if projection:
        args["ProjectionExpression"] = projection
    return _query_all(db, args)


def _counts(db, table, env, posts):
    """{post: {kind: n}} for the posts asked about, from their count items."""
    wanted, out = set(posts), {p: {} for p in posts}
    for item in _prefixed(db, table, env, "rcount#"):
        post = item["sk"]["S"][len("rcount#"):]
        if post in wanted:
            out[post] = {k: int(item[f"n_{k}"]["N"]) for k in KINDS
                         if f"n_{k}" in item and int(item[f"n_{k}"]["N"]) > 0}
    return out


def total_reactions(db, table, env):
    """Count reactions currently on posts using the transactionally maintained totals."""
    return sum(int(item[f"n_{kind}"]["N"])
               for item in _prefixed(db, table, env, "rcount#")
               for kind in KINDS if f"n_{kind}" in item)


def _mine(db, table, env, steam, posts):
    """{post: [kinds]} this player has given, in KINDS order."""
    wanted, out = set(posts), {p: [] for p in posts}
    prefix = f"react#{steam}#"
    for item in _prefixed(db, table, env, prefix, projection="sk"):
        post, _, kind = item["sk"]["S"][len(prefix):].rpartition("#")
        if post in wanted and kind in KINDS:
            out[post].append(kind)
    return {p: sorted(kinds, key=KINDS.index) for p, kinds in out.items()}


def _note_map(db, table, envs):
    """FB number -> (env, note id) across the envs this Lambda reads, kept NOTES_TTL seconds."""
    key = tuple(envs)
    cached = _notes.get(key)
    if cached and time.time() - cached[0] < NOTES_TTL:
        return cached[1]
    found = {}
    for env in envs:
        for item in _prefixed(db, table, env, "feedback/", projection="sk, seq"):
            if "seq" in item:
                found[int(item["seq"]["N"])] = (env, item["sk"]["S"])
    _notes[key] = (time.time(), found)
    return found


def _asked(db, table, envs, steam, fixes):
    """{post: {"count", "mine"}}: the distinct players who filed or +1'd each post's notes."""
    if not fixes:
        return {}
    notes = _note_map(db, table, envs)
    voters = {}  # FB number -> set of Steam IDs
    out = {}
    for post, numbers in fixes.items():
        players = set()
        for n in numbers:
            if n not in notes:
                continue
            if n not in voters:
                env, note_id = notes[n]
                prefix = f"vote#{note_id}#"
                voters[n] = {item["sk"]["S"][len(prefix):]
                             for item in _prefixed(db, table, env, prefix, projection="sk")}
            players |= voters[n]
        out[post] = {"count": len(players), "mine": bool(steam) and steam in players}
    return out


def _parse_get(event):
    import urllib.parse
    params = dict(urllib.parse.parse_qsl(event.get("rawQueryString", "")))
    posts = [p for p in params.get("posts", "").split(",") if p]
    if not posts or len(posts) > MAX_POSTS:
        raise Refused(400, "Name between 1 and 100 posts.")
    posts = list(dict.fromkeys(_post_id(p) for p in posts))
    fixes = {}
    for part in [p for p in params.get("fixes", "").split(",") if p]:
        post, _, numbers = part.partition(":")
        numbers = numbers.split(".")
        if post not in posts or not (1 <= len(numbers) <= MAX_FIXES) or not all(
                n.isdigit() and len(n) <= 7 for n in numbers):
            raise Refused(400, "fixes is <post>:<FB number>[.<FB number>...], for posts asked about.")
        fixes[post] = [int(n) for n in numbers]
    return posts, fixes


def _throttle(db, table, env, steam):
    """Count this change against the player's hour, as feedback._throttle does (one conditional ADD)."""
    hour = int(time.time() // 3600)
    try:
        db.update_item(TableName=table, Key={"env": {"S": env}, "sk": {"S": f"rrate#{steam}#{hour}"}},
                       UpdateExpression="SET #x = if_not_exists(#x, :exp) ADD #n :one",
                       ConditionExpression="attribute_not_exists(#n) OR #n < :max",
                       ExpressionAttributeNames={"#n": "n", "#x": "expires"},
                       ExpressionAttributeValues={":one": {"N": "1"}, ":max": {"N": str(RATE_WRITES)},
                                                  ":exp": {"N": str((hour + 25) * 3600)}})
    except Exception as error:
        if _code(error) != "ConditionalCheckFailedException":
            raise
        raise Refused(429, "That's a lot of reactions for one hour. Try again later.")


def _react(db, table, env, steam, post, kind, on):
    """Give or take back one reaction: the reaction item and its count move together in one
    transaction. The item is put only if absent and deleted only if present, so a repeat (a
    double click, two tabs) fails its condition and the count stays exact."""
    key = {"env": {"S": env}, "sk": {"S": f"react#{steam}#{post}#{kind}"}}
    mark = ({"Put": {"TableName": table, "Item": {**key, "at": {"N": str(int(time.time()))}},
                     "ConditionExpression": "attribute_not_exists(sk)"}} if on else
            {"Delete": {"TableName": table, "Key": key, "ConditionExpression": "attribute_exists(sk)"}})
    count = {"Update": {"TableName": table, "Key": {"env": {"S": env}, "sk": {"S": f"rcount#{post}"}},
                        "UpdateExpression": "ADD #k :d", "ExpressionAttributeNames": {"#k": f"n_{kind}"},
                        "ExpressionAttributeValues": {":d": {"N": "1" if on else "-1"}}}}
    try:
        db.transact_write_items(TransactItems=[mark, count])
    except Exception as error:
        if _code(error) != "TransactionCanceledException":
            raise


def _parse_post(event):
    try:
        raw = event.get("body") or ""
        if len(raw) > 2000:
            raise ValueError()
        data = json.loads(base64.b64decode(raw) if event.get("isBase64Encoded") else raw)
        kind = data["kind"]
        if kind not in KINDS:
            raise ValueError()
        return _post_id(data["post"]), kind, bool(data.get("on"))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise Refused(400, "That reaction could not be saved. Refresh and try again.") from None


def handle(event):
    def reply(status, body):
        return {"statusCode": status, "headers": {"content-type": "application/json",
                "cache-control": "no-store"}, "body": json.dumps(body)}

    import session
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if method not in ("GET", "POST"):
        return reply(405, {"message": "Method not allowed."})
    steam = session.steam_id(event)
    table, env = os.environ["FEEDBACK_TABLE"], os.environ["FEEDBACK_ENV"]
    readable = [e for e in os.environ.get("FEEDBACK_READ_ENVS", env).split(",") if e in ("gamma", "prod")] or [env]
    import boto3
    db = boto3.client("dynamodb")
    try:
        if method == "GET":
            posts, fixes = _parse_get(event)
        else:
            if not steam:
                raise Refused(401, "Sign in through Steam to react.")
            if not session.same_origin(event):
                raise Refused(403, "Reactions must be sent from the site.")
            post, kind, on = _parse_post(event)
            _throttle(db, table, env, steam)
            _react(db, table, env, steam, post, kind, on)
            posts, fixes = [post], {}
        counts = _counts(db, table, env, posts)
        mine = _mine(db, table, env, steam, posts) if steam else {}
        asked = _asked(db, table, readable, steam, fixes)
    except Refused as refused:
        return reply(refused.status, {"message": refused.message})
    view = {p: {"counts": counts[p], "mine": mine.get(p, [])} for p in posts}
    for p, a in asked.items():
        view[p]["asked"] = a
    return reply(200, {"signedIn": bool(steam), "posts": view})
