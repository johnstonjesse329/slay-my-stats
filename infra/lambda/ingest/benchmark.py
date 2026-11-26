"""Publish a daily fight benchmark, the home page showcase and the mod's snapshot from the
production run uploads."""

from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json

import time

from handler import (RAW_KEY_RE, STATS_KEY, IngestError, _get_store, _pack, _unpack, blob_key, id_key,
                     iter_upload_lines, telemetry_key)
import mod_pack
import showcase
from tools.power_curve.fight_demand import cuts_of, rating_mix, run_fights, table


BENCHMARK_KEY = "users/_fight-demand.json.gz"
SHOWCASE_KEY = "users/_showcase.json.gz"


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


def profile_name(store, steam_id):
    """(slug, display name) of a player's published profile, or None."""
    player = store.get(id_key(steam_id))
    profile = player and store.get(blob_key(_unpack(player[0])["slug"]))
    return profile and (_unpack(player[0])["slug"], _unpack(profile[0]).get("name") or "")


def upload_fights(store, published, key, facts=None):
    """Fights of one upload; None when the upload can't be read (logged, counted by refresh).
    `facts`, when given, gets each run's showcase facts by run id."""
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
                if facts is not None:
                    player = (raw.get("players") or [{}])[0]
                    facts[run_id] = {"ts": raw["start_time"], "char": player.get("character"),
                                     "asc": raw.get("ascension") or 0, "deck": sum(1 for c in player.get("deck") or [] if c.get("id")),
                                     "won": bool(raw.get("win")), "solo": len(raw["players"]) == 1,
                                     "standard": raw.get("game_mode", "standard") == "standard"}
                    if raw.get("win") and len(raw["players"]) == 1:  # only a showcase candidate needs them
                        try:
                            facts[run_id]["syn"] = showcase.deck_synergies(
                                player.get("character"), player.get("deck"), player.get("relics"))
                        except Exception as e:  # noqa: BLE001 -- the names are extra; never cost the refresh
                            print(json.dumps({"showcase_synergy_failed": f"{type(e).__name__}: {e}"}))
    except IngestError as e:
        print(json.dumps({"benchmark_skipped_upload": key, "error": f"{e.code}: {e}"}))
        return None
    return fights


def refresh(event, context):
    store = _get_store()
    previous = store.get(BENCHMARK_KEY)
    keys = sorted(key for key in store.list("raw/") if RAW_KEY_RE.fullmatch(key))
    by_run, facts = {}, {}
    skipped = 0
    # Read uploads concurrently, but apply them in key order so newer copies win.
    with ThreadPoolExecutor(max_workers=8) as pool:
        players = sorted({RAW_KEY_RE.fullmatch(key)[1] for key in keys})
        published = dict(zip(players, pool.map(partial(published_starts, store), players)))
        active_keys = [key for key in keys if published[RAW_KEY_RE.fullmatch(key)[1]]]
        for fights in pool.map(partial(upload_fights, store, published, facts=facts), active_keys):
            if fights is None:
                skipped += 1
            else:
                by_run.update(fights)
    runs = [fights for fights in by_run.values() if fights]
    encounters = table(runs)
    cuts = cuts_of(runs, encounters)
    benchmark = {"encounters": encounters, "cuts": cuts, "ratings": rating_mix(runs, encounters, cuts)}
    store.put(BENCHMARK_KEY, _pack(benchmark), {}, previous[2] if previous else None)
    publish_showcase(store, by_run, facts, benchmark, time.time())
    publish_mod_pack(store, benchmark, time.time())
    print(json.dumps({"benchmark_runs": len(runs), "encounters": len(encounters),
                      "skipped_uploads": skipped}))


def publish_mod_pack(store, benchmark, now):
    """The mod's snapshot (mod_pack.py). Best effort, like the showcase."""
    try:
        stats = store.get(STATS_KEY)
        if stats is None:
            raise RuntimeError("no totals to publish")
        mod_pack.publish(store, benchmark, _unpack(stats[0]), now)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"mod_pack_failed": f"{type(e).__name__}: {e}"}))


def publish_showcase(store, by_run, facts, benchmark, now):
    """The home page's showcase from the same runs. Best effort: a failure here is logged and
    never costs the benchmark above."""
    try:
        since = now - showcase.WINDOW_DAYS * 86400
        names, candidates = {}, []
        for run_id, fights in by_run.items():
            f = facts.get(run_id)
            if not f or not f["won"] or not f["solo"] or f["ts"] < since:
                continue
            steam_id = run_id[0]
            if steam_id not in names:
                names[steam_id] = profile_name(store, steam_id)
            if not names[steam_id]:
                continue
            c = {"slug": names[steam_id][0], "name": names[steam_id][1], "ts": f["ts"], "char": f["char"],
                 "asc": f["asc"], "deck": f["deck"], "syn": f.get("syn"),
                 "op": f["standard"] and showcase.is_op(fights, benchmark["encounters"], benchmark["cuts"])}
            got = store.get(telemetry_key(steam_id, f["ts"]))
            if got:
                c.update(showcase.turn_peaks(_unpack(got[0])))
            candidates.append(c)
        previous = store.get(SHOWCASE_KEY)
        store.put(SHOWCASE_KEY, _pack(showcase.build(candidates, now)), {}, previous[2] if previous else None)
        print(json.dumps({"showcase_candidates": len(candidates)}))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"showcase_failed": f"{type(e).__name__}: {e}"}))
