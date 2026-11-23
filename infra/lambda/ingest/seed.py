"""Gamma only: copy production's run data into gamma's bucket every night.

The scheduled twin of tools/seed_gamma.py (copy only, no rebuild): users/, ids/,
coop/, raw/ and telemetry/ are copied server-side, only the objects that are
missing or changed, nothing is deleted. S3 copies don't fire the process
Lambda's upload trigger, so copied raw/ files aren't processed a second time.
Prod's player list replaces gamma's, so players with only a gamma profile are
put back on it afterwards.
"""

import os

from handler import INDEX_KEY, S3Store, _pack, _read_index, blob_key

PROD_BUCKET = "slay-my-stats-data"
PREFIXES = ("users", "ids", "coop", "raw", "telemetry")


def _listing(s3, bucket, prefix):
    out = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix + "/"):
        for obj in page.get("Contents", ()):
            out[obj["Key"]] = (obj["ETag"], obj["Size"])
    return out


def keep_gamma_players(store, before):
    """Put back players who only have a gamma profile, as they were listed."""
    players, etag = _read_index(store)
    listed = {p["slug"] for p in players}
    kept = [p for p in before if p["slug"] not in listed and store.get(blob_key(p["slug"]))]
    if not kept:
        return []
    players = sorted(players + kept, key=lambda p: p["slug"])
    store.put(INDEX_KEY, _pack({"v": 1, "players": players}), {}, etag)
    return [p["slug"] for p in kept]


def copy_prod(event=None, context=None, s3=None, store=None, gamma=None):
    import boto3
    s3 = s3 or boto3.client("s3")
    gamma = gamma or os.environ["DATA_BUCKET"]
    if gamma == PROD_BUCKET:
        raise RuntimeError("Refusing to copy a bucket onto itself")
    store = store or S3Store(gamma)
    before, _ = _read_index(store)
    copied = 0
    for prefix in PREFIXES:
        have = _listing(s3, gamma, prefix)
        for key, sig in _listing(s3, PROD_BUCKET, prefix).items():
            if have.get(key) != sig:
                s3.copy_object(Bucket=gamma, Key=key, CopySource={"Bucket": PROD_BUCKET, "Key": key})
                copied += 1
    kept = keep_gamma_players(store, before)
    print(f"Seeded {gamma} from {PROD_BUCKET}: {copied} objects copied; kept gamma-only players: {kept}")
    return {"copied": copied, "kept": kept}
