"""Publish a daily fight benchmark, the home page showcase and the mod's snapshot from the
production run uploads."""

from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json

import time

from run import local_player_index
from handler import (RAW_KEY_RE, STATS_KEY, IngestError, _get_store, _norm_steam_id, _pack, _unpack,
                     blob_key, id_key, iter_upload_lines, telemetry_key)
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


def upload_fights(store, published, key, facts=None, showcase_since=0):
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
                if facts is not None and raw.get("win") and raw["start_time"] >= showcase_since:
                    multiplayer = len(raw["players"]) > 1
                    slot = local_player_index(raw, steam_id) if multiplayer else None
                    player = raw["players"][slot or 0]
                    facts[run_id] = {"ts": raw["start_time"], "char": player.get("character"),
                                     "asc": raw.get("ascension") or 0, "deck": sum(1 for c in player.get("deck") or [] if c.get("id")),
                                     "slot": slot,
                                     "standard": raw.get("game_mode", "standard") == "standard"}
                    # The normal co-op profile can fall back to seat 0 if the uploader ID
                    # is absent. A player-specific achievement requires a confirmed seat.
                    damage_slot = slot or 0
                    if multiplayer and _norm_steam_id(player.get("id")) != _norm_steam_id(steam_id):
                        damage_slot = None
                    facts[run_id]["boss_no_damage"] = showcase.final_boss_no_damage(raw, damage_slot)
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
    showcase_since = time.time() - showcase.WINDOW_DAYS * 86400

    def read_upload(key):
        upload_facts = {}
        fights = upload_fights(store, published, key, facts=upload_facts, showcase_since=showcase_since)
        return fights, upload_facts

    # Read uploads concurrently, but apply them in key order so newer copies win.
    with ThreadPoolExecutor(max_workers=8) as pool:
        players = sorted({RAW_KEY_RE.fullmatch(key)[1] for key in keys})
        published = dict(zip(players, pool.map(partial(published_starts, store), players)))
        active_keys = [key for key in keys if published[RAW_KEY_RE.fullmatch(key)[1]]]
        for fights, upload_facts in pool.map(read_upload, active_keys):
            if fights is None:
                skipped += 1
            else:
                by_run.update(fights)
                for run_id in fights.keys() - upload_facts.keys():
                    facts.pop(run_id, None)
                facts.update(upload_facts)
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
            if not f or f["ts"] < since:
                continue
            steam_id = run_id[0]
            if steam_id not in names:
                names[steam_id] = profile_name(store, steam_id)
            if not names[steam_id]:
                continue
            slot = f["slot"]
            c = {"slug": names[steam_id][0], "name": names[steam_id][1], "ts": f["ts"], "char": f["char"],
                 "asc": f["asc"], "deck": f["deck"], "syn": f.get("syn"), "multiplayer": slot is not None,
                 "op": f["standard"] and showcase.is_op(fights, benchmark["encounters"], benchmark["cuts"], slot),
                 "boss_no_damage": f["boss_no_damage"]}
            got = store.get(telemetry_key(steam_id, f["ts"]))
            if got:
                c.update(showcase.turn_peaks(_unpack(got[0]), slot))
            candidates.append(c)
        previous = store.get(SHOWCASE_KEY)
        store.put(SHOWCASE_KEY, _pack(showcase.build(candidates, now)), {}, previous[2] if previous else None)
        print(json.dumps({"showcase_candidates": len(candidates)}))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"showcase_failed": f"{type(e).__name__}: {e}"}))
