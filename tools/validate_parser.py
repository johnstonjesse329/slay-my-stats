"""
tools/validate_parser.py — Check run.py's parser against the data's own labels.

The ingest round-trip test compares the Lambda's output to run.py's local
parse -- the same function on both sides -- so it can only catch plumbing
drift, never a wrong interpretation. This tool checks the parse against
fields the GAME provides, which are independent of how run.py picks a player
or reads a node:

    real Steam ID  -> players[].id, and every map node's player_stats[].player_id
    character      -> the uploader's players[] entry
    deck / relics  -> the uploader's players[] entry
    per-floor HP   -> the player_stats entry the game labels with that ID
    gold per floor -> that same entry
    shop purchases -> that entry's cards_gained
    elite/boss     -> that entry's hp/damage/heal and the room's turns_taken

The expected values never come from run.py's own logic, so selecting the
wrong player or reading the wrong field makes a check fail. `--mutate`
proves the checks still have teeth: it parses every run as if the uploader
were players[0] (the original multiplayer bug) and requires at least one
check to fail. If nothing fails under --mutate, the validator is broken,
not the parser.

Usage:
    python tools/validate_parser.py --history "C:\\path\\to\\history"
        A local STS2 save folder; the Steam ID comes from the path.

    python tools/validate_parser.py --raw upload.ndjson.gz --steam-id 7656119...
        One raw upload as stored in the bucket (gzipped NDJSON).

    python tools/validate_parser.py --bucket slay-my-stats-data
        Every player's raw uploads in the live data bucket (needs AWS creds).

    python tools/validate_parser.py --bucket slay-my-stats-data --mutate
        Same, but parse with the uploader forced to index 0 and require the
        checks to fail.

Exit status is 0 when every check passes (or, under --mutate, when at least
one run fails), 1 otherwise, so it can gate a deploy.
"""

import gzip
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_REPO), str(_REPO / "infra" / "lambda" / "ingest")]

import run  # noqa: E402


def same_id(a, b) -> bool:
    """Exact match first, then numeric: some builds write Steam IDs as float64."""
    if a is None or b is None or a == "" or b == "":
        return False
    if str(a) == str(b):
        return True
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def uploader_index(data: dict, steam_id: str):
    """The uploader's index, taken only from the game's players[].id."""
    players = data.get("players") or []
    if len(players) <= 1:
        return 0
    for i, p in enumerate(players):
        if same_id(p.get("id"), steam_id):
            return i
    return None


def labelled_stats(node: dict, steam_id: str, idx: int):
    """The node's player_stats entry the game labels with the uploader's id.

    Returns (entry, error). Errors here mean the game's own labels disagree
    with the index we used -- i.e. the player selection is wrong.
    """
    stats = node.get("player_stats") or []
    if len(stats) <= 1:
        return (stats[0] if stats else {}), None
    hits = [k for k, s in enumerate(stats) if same_id(s.get("player_id"), steam_id)]
    if len(hits) != 1:
        return None, f"expected one player_stats labelled {steam_id}, found {len(hits)}"
    if hits[0] != idx:
        return None, f"player_stats labelled {steam_id} is at index {hits[0]}, players[] says {idx}"
    return stats[hits[0]], None


def validate_run(data: dict, steam_id: str) -> list[str]:
    """Every way the parse disagrees with the game's own labels; empty is good."""
    problems: list[str] = []
    idx = uploader_index(data, steam_id)
    if idx is None:
        return [f"uploader {steam_id} is not in players[]"]
    players = data.get("players") or [{}]
    p = players[idx]
    parsed = run.parse_run_data(data, steam_id=steam_id)
    tag = data.get("seed") or data.get("start_time")

    char = run.strip_prefix(p.get("character", ""), "CHARACTER.")
    if parsed["char"] != char:
        problems.append(f"[{tag}] char: parsed {parsed['char']}, players[] says {char}")
    deck = [(c["id"], c.get("current_upgrade_level", 0)) for c in p.get("deck", []) if c.get("id")]
    if parsed["finalDeck"] != [{"id": a, "upgrade": b} for a, b in deck]:
        problems.append(f"[{tag}] finalDeck does not match the uploader's own deck")
    relics = [r["id"] for r in p.get("relics", []) if r.get("id")]
    if parsed["finalRelics"] != [{"id": r} for r in relics]:
        problems.append(f"[{tag}] finalRelics does not match the uploader's own relics")

    nodes = [n for act in data.get("map_point_history", []) if isinstance(act, list) for n in act]
    if len(parsed["timeline"]) != len(nodes):
        problems.append(f"[{tag}] timeline has {len(parsed['timeline'])} floors for {len(nodes)} nodes")
        return problems

    for t, node in zip(parsed["timeline"], nodes):
        ps, err = labelled_stats(node, steam_id, idx)
        if err:
            problems.append(f"[{tag}] floor {t['floor']}: {err}")
            break
        if (t["hpAfter"], t["maxHp"], t["goldGained"]) != (ps.get("current_hp", 0), ps.get("max_hp", 0),
                                                           ps.get("gold_gained", 0)):
            problems.append(f"[{tag}] floor {t['floor']} ({t['type']}): HP/gold are not the uploader's")
            break
        if node.get("map_point_type") == "shop":
            expected = [c["id"] for c in (ps.get("cards_gained") or []) if c.get("id")]
            if t["cardsBought"] != expected:
                problems.append(f"[{tag}] floor {t['floor']} (shop): bought {t['cardsBought']}, "
                                f"cards_gained says {expected}")
                break

    fights = [n for n in nodes if n.get("map_point_type") in ("elite", "boss")]
    if len(parsed["fights"]) != len(fights):
        problems.append(f"[{tag}] {len(parsed['fights'])} fights parsed for {len(fights)} elite/boss nodes")
    else:
        for f, node in zip(parsed["fights"], fights):
            ps, err = labelled_stats(node, steam_id, idx)
            if err:
                problems.append(f"[{tag}] fight {f['enc']}: {err}")
                break
            hp_before = ps.get("current_hp", 0) + ps.get("damage_taken", 0) - ps.get("hp_healed", 0)
            turns = (node.get("rooms") or [{}])[0].get("turns_taken", 0)
            if f["hp"] != hp_before or f["turns"] != turns:
                problems.append(f"[{tag}] fight {f['enc']}: hp/turns are not the uploader's")
                break
    return problems


# ---------------------------------------------------------------------------
# Run sources
# ---------------------------------------------------------------------------

def from_history(directory: str) -> list[tuple[str, str, dict]]:
    """(<steam id>, label, run) for every .run in a local history folder."""
    d = Path(directory)
    steam_id = d.parts[-4]  # .../steam/<steamID>/profile1/saves/history
    return [(steam_id, f.name, json.loads(f.read_text(encoding="utf-8")))
            for f in sorted(d.glob("*.run"), key=lambda p: int(p.stem))]


def from_raw(path: str, steam_id: str) -> list[tuple[str, str, dict]]:
    """(<steam id>, label, run) for one raw upload (gzipped NDJSON)."""
    body = gzip.decompress(Path(path).read_bytes())
    return [(steam_id, f"{Path(path).name}#{i}", json.loads(line))
            for i, line in enumerate(body.splitlines()) if line.strip()]


def from_bucket(bucket: str) -> list[tuple[str, str, dict]]:
    """(<steam id>, label, run) for every player's raw uploads in the bucket."""
    import handler
    store = handler.S3Store(bucket)
    runs: list[tuple[str, str, dict]] = []
    for key in store.list("ids/"):
        steam_id = key[len("ids/"):-len(".json.gz")]
        for raw_key in sorted(store.list(f"raw/{steam_id}/")):
            got = store.get(raw_key)
            if not got:
                continue
            for i, line in enumerate(gzip.decompress(got[0]).splitlines()):
                if line.strip():
                    runs.append((steam_id, f"{raw_key}#{i}", json.loads(line)))
    return runs


def force_index0(data: dict, steam_id: str) -> int:
    """The old multiplayer bug, for --mutate."""
    return 0


def main() -> int:
    args = sys.argv[1:]

    def arg(name):
        return args[args.index(name) + 1] if name in args else None

    if arg("--history"):
        runs = from_history(arg("--history"))
    elif arg("--raw"):
        if not arg("--steam-id"):
            sys.exit("--raw needs --steam-id")
        runs = from_raw(arg("--raw"), arg("--steam-id"))
    elif arg("--bucket"):
        runs = from_bucket(arg("--bucket"))
    else:
        sys.exit(__doc__)

    mutate = "--mutate" in args
    checked = skipped = failed = 0
    original = run.local_player_index
    if mutate:
        run.local_player_index = force_index0
    try:
        for steam_id, label, data in runs:
            if uploader_index(data, steam_id) is None:
                skipped += 1
                continue
            checked += 1
            problems = validate_run(data, steam_id)
            if problems:
                failed += 1
                if failed <= 5:
                    print(f"  {label}: {problems[0]}")
    finally:
        run.local_player_index = original

    mode = "mutated (uploader forced to index 0)" if mutate else "as parsed"
    print(f"\n{mode}: {checked} runs checked, {failed} failed, {skipped} skipped (uploader not labelled)")
    if mutate:
        if checked == 0:
            print("No runs to mutate -- cannot prove the checks have teeth.")
            return 1
        if failed == 0:
            print("FAIL: a knowingly-wrong parse passed every check -- the validator is broken.")
            return 1
        print("OK: the checks reject a knowingly-wrong parse.")
        return 0
    if failed:
        print("FAIL: the parser disagrees with the game's own labels.")
        return 1
    print("OK: every run matches the game's own labels.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
