"""Publish a daily fight benchmark from the production run uploads."""

from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json

from handler import (RAW_KEY_RE, IngestError, _get_store, _pack, _unpack, blob_key, id_key,
                     iter_upload_lines)
from tools.power_curve.fight_demand import cuts_of, run_fights, table


BENCHMARK_KEY = "users/_fight-demand.json.gz"


def published_starts(store, steam_id):
    player = store.get(id_key(steam_id))
    if player is None:
        return set()
    profile = store.get(blob_key(_unpack(player[0])["slug"]))
    if profile is None:
        return set()
    doc = _unpack(profile[0])
    if "months" in doc:
        return {ts for month in doc["months"].values() for ts in month}
    return {run["ts"] for run in doc.get("runs", [])}


def upload_fights(store, published, key):
    """Fights of one upload; None when the upload can't be read (logged, counted by refresh)."""
    steam_id = RAW_KEY_RE.fullmatch(key)[1]
    body = store.get(key)
    if body is None:
        raise RuntimeError("An upload disappeared during the benchmark refresh")
    fights = {}
    try:
        for line in iter_upload_lines(body[0]):
            try:
                raw = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if (isinstance(raw, dict) and isinstance(raw.get("start_time"), int)
                    and raw["start_time"] in published[steam_id]
                    and raw.get("map_point_history") and raw.get("players")):
                run_id = (steam_id, raw["start_time"])
                parsed = run_fights({run_id: raw})
                fights[run_id] = parsed[0] if parsed else []
    except IngestError as e:
        print(json.dumps({"benchmark_skipped_upload": key, "error": f"{e.code}: {e}"}))
        return None
    return fights


def refresh(event, context):
    store = _get_store()
    previous = store.get(BENCHMARK_KEY)
    keys = sorted(key for key in store.list("raw/") if RAW_KEY_RE.fullmatch(key))
    by_run = {}
    skipped = 0
    # Read uploads concurrently, but apply them in key order so newer copies win.
    with ThreadPoolExecutor(max_workers=8) as pool:
        players = sorted({RAW_KEY_RE.fullmatch(key)[1] for key in keys})
        published = dict(zip(players, pool.map(partial(published_starts, store), players)))
        active_keys = [key for key in keys if published[RAW_KEY_RE.fullmatch(key)[1]]]
        for fights in pool.map(partial(upload_fights, store, published), active_keys):
            if fights is None:
                skipped += 1
            else:
                by_run.update(fights)
    runs = [fights for fights in by_run.values() if fights]
    encounters = table(runs)
    benchmark = {"encounters": encounters, "cuts": cuts_of(runs, encounters)}
    store.put(BENCHMARK_KEY, _pack(benchmark), {}, previous[2] if previous else None)
    print(json.dumps({"benchmark_runs": len(runs), "encounters": len(encounters),
                      "skipped_uploads": skipped}))
