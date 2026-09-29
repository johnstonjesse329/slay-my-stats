"""
run.py — Slay the Spire 2 Run History Dashboard Generator

Reads your STS2 save files, extracts run statistics, and produces a
self-contained HTML file you can open in any browser to explore your history.

Usage:
    python run.py
        Auto-detects your save folder and writes sts2_viz.html to your home
        directory, then opens it in your default browser.

    python run.py --history "C:\\path\\to\\history"
        Skip auto-detection and use the folder you specify. Useful if the
        auto-detect fails or you have saves in a non-standard location.

    python run.py --out my_stats.html
        Write the output to a custom file name/path instead of sts2_viz.html.

    python run.py --help
        Show this message and exit.

How it works (high level):
    1. Find the history folder containing .run files (one file per run).
    2. Parse each .run file — they are JSON — and extract the fields we care
       about (character, ascension, win/loss, floor reached, etc.).
    3. Build a single self-contained HTML file that has all the run data
       embedded directly inside it as a JavaScript variable.
    4. Open that HTML file in the browser. The page uses Chart.js (loaded from
       the internet via CDN) to draw charts, and plain JavaScript to let you
       filter and explore the data interactively.

No external Python libraries are needed — only the standard library.
"""

import json        # for reading .run files (they are JSON) and for embedding data in HTML
import platform    # for detecting Windows / Mac / Linux so we know where to look for saves
import sys         # for reading command-line arguments and exiting with an error code
import webbrowser  # for opening the finished HTML file in the default browser
from pathlib import Path             # a modern, cross-platform way to work with file paths


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Where to write the HTML output by default.
# Path.home() gives the user's home directory (e.g. C:\Users\<you> on Windows),
# so the file lands there instead of inside the package repo.
DEFAULT_OUT = Path.home() / "sts2_viz.html"

# Hex colour codes for each character, used in charts and pivot tables.
# These match the character colour palettes in the game.
CHAR_COLORS = {
    "IRONCLAD":    "#e05c5c",  # red
    "SILENT":      "#5cba7d",  # green
    "DEFECT":      "#5b9bd5",  # blue
    "NECROBINDER": "#b07dd4",  # purple
    "REGENT":      "#e8a930",  # gold
}

# Boss encounter IDs grouped by act (0-indexed internally, displayed as Act 1/2/3).
# Encounter groupings for the character detail tables.
# Act 1 has two map variants (Overgrowth / Underdocks) with distinct encounter pools,
# so it is split into two labelled sub-groups. Acts 2 and 3 have a single variant each.
# Each entry is {"label": str, "ids": [encounter_id, ...]}.
ENCOUNTER_GROUPS = [
    # --- Act 1 ---
    {"label": "Act 1: Overgrowth — Elites", "ids": [
        "ENCOUNTER.BYGONE_EFFIGY_ELITE",
        "ENCOUNTER.BYRDONIS_ELITE",
        "ENCOUNTER.PHROG_PARASITE_ELITE",
    ]},
    {"label": "Act 1: Overgrowth — Bosses", "ids": [
        "ENCOUNTER.CEREMONIAL_BEAST_BOSS",
        "ENCOUNTER.THE_KIN_BOSS",
        "ENCOUNTER.VANTOM_BOSS",
    ]},
    {"label": "Act 1: Underdocks — Elites", "ids": [
        "ENCOUNTER.PHANTASMAL_GARDENERS_ELITE",
        "ENCOUNTER.SKULKING_COLONY_ELITE",
        "ENCOUNTER.TERROR_EEL_ELITE",
    ]},
    {"label": "Act 1: Underdocks — Bosses", "ids": [
        "ENCOUNTER.LAGAVULIN_MATRIARCH_BOSS",
        "ENCOUNTER.SOUL_FYSH_BOSS",
        "ENCOUNTER.WATERFALL_GIANT_BOSS",
    ]},
    # --- Act 2 ---
    {"label": "Act 2 — Elites", "ids": [
        "ENCOUNTER.DECIMILLIPEDE_ELITE",
        "ENCOUNTER.ENTOMANCER_ELITE",
        "ENCOUNTER.INFESTED_PRISMS_ELITE",
    ]},
    {"label": "Act 2 — Bosses", "ids": [
        "ENCOUNTER.KAISER_CRAB_BOSS",
        "ENCOUNTER.KNOWLEDGE_DEMON_BOSS",
        "ENCOUNTER.THE_INSATIABLE_BOSS",
    ]},
    # --- Act 3 ---
    {"label": "Act 3 — Elites", "ids": [
        "ENCOUNTER.KNIGHTS_ELITE",
        "ENCOUNTER.MECHA_KNIGHT_ELITE",
        "ENCOUNTER.SOUL_NEXUS_ELITE",
    ]},
    {"label": "Act 3 — Bosses", "ids": [
        "ENCOUNTER.AEONGLASS_BOSS",
        "ENCOUNTER.DOORMAKER_BOSS",
        "ENCOUNTER.QUEEN_BOSS",
        "ENCOUNTER.TEST_SUBJECT_BOSS",
    ]},
]


# ---------------------------------------------------------------------------
# Save file detection
# ---------------------------------------------------------------------------

def find_history_dirs() -> list[Path]:
    """
    Look for STS2 history folders on this machine and return all that exist.

    STS2 stores one folder per Steam account, named by Steam ID (a long number).
    The folder structure is:
        <AppData>/SlayTheSpire2/steam/<steamID>/profile1/saves/history/

    AppData lives in different places depending on the OS:
        Windows : C:\\Users\\<you>\\AppData\\Roaming\\
        Mac     : /Users/<you>/Library/Application Support/
        Linux   : /home/<you>/.local/share/

    Path.home() gives us the user's home directory regardless of OS, so we
    build the path from there.

    Returns a sorted list of Path objects — one per Steam account that has a
    history folder. Returns an empty list if nothing is found.
    """
    system = platform.system()  # "Windows", "Darwin" (Mac), or "Linux"
    home   = Path.home()        # e.g. C:\Users\<you> on Windows

    if system == "Windows":
        base = home / "AppData" / "Roaming" / "SlayTheSpire2" / "steam"
    elif system == "Darwin":  # macOS is called "Darwin" internally
        base = home / "Library" / "Application Support" / "SlayTheSpire2" / "steam"
    else:
        base = home / ".local" / "share" / "SlayTheSpire2" / "steam"

    # If the base folder doesn't exist at all, STS2 probably isn't installed.
    if not base.exists():
        return []

    # Iterate over every subfolder of base (each one is a Steam ID).
    # Only include those that actually have a history folder inside them.
    candidates = sorted(
        p / "profile1" / "saves" / "history"
        for p in base.iterdir()
        if p.is_dir() and (p / "profile1" / "saves" / "history").exists()
    )

    return candidates


def resolve_history_dir() -> Path:
    """
    Find the history folder to use, prompting the user if multiple accounts exist.

    Calls find_history_dirs() and handles the three possible outcomes:
      - Nothing found  → print a helpful error and exit.
      - Exactly one    → use it silently.
      - More than one  → list them and ask the user to pick one.
    """
    candidates = find_history_dirs()

    if not candidates:
        print("Could not find STS2 save data.")
        print("Use --history to specify the path manually. Example:")
        print('  python run.py --history "C:\\Users\\you\\AppData\\Roaming\\SlayTheSpire2\\steam\\<steamID>\\profile1\\saves\\history"')
        sys.exit(1)  # exit with a non-zero code to signal failure

    if len(candidates) == 1:
        # Only one account — no need to ask.
        return candidates[0]

    # Multiple Steam accounts found. Show each one with its Steam ID and run count
    # so the user can identify which account they want.
    print("Multiple Steam accounts found. Which one would you like to use?\n")
    for i, path in enumerate(candidates, start=1):
        steam_id  = path.parts[-4]              # the Steam ID is 4 levels up from history/
        run_count = len(list(path.glob("*.run")))
        print(f"  [{i}] Steam ID {steam_id}  ({run_count} runs)")

    print()
    # Keep asking until the user gives a valid number.
    while True:
        choice = input(f"Enter a number (1–{len(candidates)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            return candidates[int(choice) - 1]
        print("Please enter a number from the list above.")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    """
    Read command-line arguments passed to the script.

    sys.argv is a list of strings. sys.argv[0] is always the script name.
    Everything after it is what the user typed, e.g.:
        python run.py --history "C:\\foo" --out bar.html
    gives sys.argv = ['run.py', '--history', 'C:\\foo', '--out', 'bar.html']

    Returns (history_dir, out_path) where history_dir may be None if the user
    didn't pass --history (we'll auto-detect it later).
    """
    args = sys.argv[1:]  # drop the script name itself

    if "--help" in args or "-h" in args:
        print(__doc__)  # __doc__ is the triple-quoted string at the top of this file
        sys.exit(0)

    # Look for --history followed by a path.
    # list.index() gives the position of the item, so +1 gives the value after it.
    if "--history" in args:
        history_dir = Path(args[args.index("--history") + 1])
    else:
        history_dir = None  # signal to main() that it should auto-detect

    if "--out" in args:
        out_path = Path(args[args.index("--out") + 1])
    else:
        out_path = DEFAULT_OUT

    no_open = "--no-open" in args

    return history_dir, out_path, no_open


# ---------------------------------------------------------------------------
# Parsing .run files
# ---------------------------------------------------------------------------

def strip_prefix(value: str, prefix: str) -> str:
    """
    Remove a leading prefix from a string if it's present.

    STS2 stores identifiers like "CHARACTER.IRONCLAD", "CARD.STRIKE", etc.
    We want just the part after the dot.
    str.removeprefix() is a Python 3.9+ built-in that does exactly this.
    """
    return value.removeprefix(prefix) if value else ""


def fmt_card(card_id: str) -> str:
    """Turn "CARD.TWIN_STRIKE" into "Twin Strike" (human-readable)."""
    return strip_prefix(card_id, "CARD.").replace("_", " ").title()


def fmt_relic(relic_id: str) -> str:
    """Turn "RELIC.BURNING_BLOOD" into "Burning Blood"."""
    return strip_prefix(relic_id, "RELIC.").replace("_", " ").title()


def fmt_encounter(enc_id: str) -> str:
    """Turn "ENCOUNTER.BYRDONIS_ELITE" into "Byrdonis Elite"."""
    return strip_prefix(enc_id, "ENCOUNTER.").replace("_", " ").title()


def extract_fights(data: dict, char: str, asc: int, won: bool) -> list[dict]:
    """
    Walk map_point_history and emit one record per elite or boss node.

    Pre-fight state is recovered from the node's own player_stats:
        hp_before   = current_hp + damage_taken - hp_healed
                      (damage and heals both occur during the fight;
                       backing them out gives entering HP)
        cards_before = cards in the final deck whose floor_added_to_deck
                      is strictly less than the fight's floor index
                      (floor index counted sequentially across all acts)
        relics_before = same logic applied to relics
        potions_before = accumulated potions picked up minus those used,
                         counting only events before this fight's floor

    A fight is won iff hp_after > 0 — the player survived this specific
    node. killed_by_encounter is NOT used: the player may die to a later
    encounter in the same run (see CLAUDE.md "Fight win detection").
    """
    mph      = data.get("map_point_history", [])
    deck     = data.get("players", [{}])[0].get("deck",   [])
    relics   = data.get("players", [{}])[0].get("relics", [])
    killed   = data.get("killed_by_encounter", "")

    # Build a timeline of (floor_index, potion_delta) so we can count
    # potions held at the start of any given floor.
    # potion_delta = +1 per potion_choices picked, -1 per potion_used entry.
    timeline_potions: list[int] = []  # one entry per floor, cumulative delta
    floor_idx = 0
    for act in mph:
        if not isinstance(act, list):
            continue
        for node in act:
            ps = node.get("player_stats", [{}])[0]
            gained = sum(1 for pc in ps.get("potion_choices", []) if pc.get("was_picked"))
            used   = len(ps.get("potion_used", []))
            timeline_potions.append(gained - used)
            floor_idx += 1

    # Convert to cumulative so timeline_potions[i] = net potions after floor i.
    cumulative = 0
    for i in range(len(timeline_potions)):
        cumulative += timeline_potions[i]
        timeline_potions[i] = cumulative

    fights = []
    floor_idx = 0
    for act in mph:
        if not isinstance(act, list):
            continue
        for node in act:
            ntype = node.get("map_point_type")
            if ntype not in ("elite", "boss"):
                floor_idx += 1
                continue

            rooms = node.get("rooms", [])
            enc_id = rooms[0].get("model_id", "") if rooms else ""
            ps     = node.get("player_stats", [{}])[0]

            hp_after  = ps.get("current_hp",    0)
            dmg       = ps.get("damage_taken",  0)
            healed    = ps.get("hp_healed",     0)
            max_hp    = ps.get("max_hp",         0)
            hp_before = hp_after + dmg - healed

            # Cards/relics owned strictly before entering this fight.
            cards_before   = sum(1 for c in deck   if c.get("id") and c.get("floor_added_to_deck", 9999) < floor_idx)
            relics_before  = sum(1 for r in relics  if r.get("id") and r.get("floor_added_to_deck", 9999) < floor_idx)
            strikes_before = sum(1 for c in deck   if c.get("id", "").startswith("CARD.STRIKE_") and c.get("floor_added_to_deck", 9999) < floor_idx)
            defends_before = sum(1 for c in deck   if c.get("id", "").startswith("CARD.DEFEND_") and c.get("floor_added_to_deck", 9999) < floor_idx)

            # Potions held entering this floor = cumulative after the *previous* floor.
            potions_before = timeline_potions[floor_idx - 1] if floor_idx > 0 else 0

            # A fight is won if the player survived it (hp_after > 0).
            # Using hp_after directly is more reliable than cross-referencing
            # killed_by_encounter, which can be a later encounter in the same run.
            fight_won = hp_after > 0

            fights.append({
                "enc":     enc_id,           # e.g. "ENCOUNTER.BYRDONIS_ELITE"
                "type":    ntype,            # "elite" or "boss"
                "char":    char,
                "asc":     asc,
                "won":     fight_won,
                "hp":      hp_before,        # HP entering the fight
                "maxHp":   max_hp,           # max HP at the time
                "cards":   cards_before,
                "relics":  relics_before,
                "potions": potions_before,
                "strikes": strikes_before,
                "defends": defends_before,
                "dmg":     dmg,              # damage taken during the fight
                "turns":   rooms[0].get("turns_taken", 0) if rooms else 0,
            })

            floor_idx += 1

    return fights


def extract_timeline(data: dict) -> list[dict]:
    """
    Walk map_point_history and emit one record per node visited.
    Used by the Run Detail page to show a per-floor event timeline.
    """
    mph = data.get("map_point_history", [])
    nodes = []
    floor_idx = 0
    for act_idx, act in enumerate(mph):
        if not isinstance(act, list):
            continue
        act_num = act_idx + 1
        for node in act:
            ntype = node.get("map_point_type", "unknown")
            rooms = node.get("rooms", [])
            enc_id = rooms[0].get("model_id", "") if rooms else ""
            turns  = rooms[0].get("turns_taken", 0) if rooms else 0
            ps = node.get("player_stats", [{}])[0]

            hp_after = ps.get("current_hp",   0)
            dmg      = ps.get("damage_taken", 0)
            healed   = ps.get("hp_healed",    0)
            max_hp   = ps.get("max_hp",       0)
            hp_before = hp_after + dmg - healed

            gold = ps.get("current_gold", None)

            # card_choices/relic_choices.was_picked can fire multiple times in a single
            # shop visit (buying 2+ items) — keep every pick, not just the last one.
            # Also split shop purchases from fight/treasure/event reward pickups, same
            # reasoning as potions below.
            cards_bought   = []
            cards_rewarded = []
            cards_skipped  = []
            for cc in ps.get("card_choices", []):
                cid = cc.get("card", {}).get("id", "")
                if not cid:
                    continue
                if cc.get("was_picked"):
                    (cards_bought if ntype == "shop" else cards_rewarded).append(cid)
                else:
                    cards_skipped.append(cid)
            card_picked = cards_rewarded[0] if cards_rewarded else (cards_bought[0] if cards_bought else None)

            relics_bought   = []
            relics_rewarded = []
            relics_for_sale = []
            for rc in ps.get("relic_choices", []):
                rid = rc.get("choice", "") or None
                if not rid:
                    continue
                if rc.get("was_picked"):
                    (relics_bought if ntype == "shop" else relics_rewarded).append(rid)
                else:
                    relics_for_sale.append(rid)
            relic_picked = relics_rewarded[0] if relics_rewarded else (relics_bought[0] if relics_bought else None)

            # potion_choices.was_picked fires at shop nodes (a purchase) AND at
            # fight/treasure/event nodes (a reward pickup) — keep these separate so
            # run-level totals don't mislabel reward potions as "bought".
            potions_bought    = []
            potions_for_sale  = []
            potions_rewarded  = []
            for pc in ps.get("potion_choices", []):
                pid = pc.get("choice", "") or None
                if not pid:
                    continue
                if pc.get("was_picked"):
                    if ntype == "shop":
                        potions_bought.append(pid)
                    else:
                        potions_rewarded.append(pid)
                elif ntype == "shop":
                    potions_for_sale.append(pid)

            rest_choices = ps.get("rest_site_choices", [])
            rest_choice = rest_choices[0] if rest_choices else None

            upgraded_cards = ps.get("upgraded_cards", [])
            cards_removed  = [c.get("id", "") for c in ps.get("cards_removed", []) if c.get("id")]
            gold_gained    = ps.get("gold_gained", 0)

            nodes.append({
                "act":            act_num,
                "floor":          floor_idx,
                "type":           ntype,
                "enc":            enc_id,
                "hpBefore":       hp_before,
                "hpAfter":        hp_after,
                "maxHp":          max_hp,
                "dmg":            dmg,
                "healed":         healed,
                "gold":           gold,
                "cardPicked":     card_picked,
                "cardsSkipped":   cards_skipped,
                "cardsBought":    cards_bought,
                "cardsRewarded":  cards_rewarded,
                "relicPicked":    relic_picked,
                "relicsForSale":  relics_for_sale,
                "relicsBought":   relics_bought,
                "relicsRewarded": relics_rewarded,
                "potionsBought":   potions_bought,
                "potionsForSale":  potions_for_sale,
                "potionsRewarded": potions_rewarded,
                "restChoice":     rest_choice,
                "upgradedCards":  upgraded_cards,
                "cardsRemoved":   cards_removed,
                "goldGained":     gold_gained,
                "turns":          turns,
            })
            floor_idx += 1
    return nodes


def parse_run(path: Path) -> dict:
    """
    Parse a single .run file and return a flat dictionary of stats we care about.

    Each .run file is a JSON object saved by the game after a run ends.
    The filename is the Unix timestamp (seconds since 1970-01-01) of when the
    run started, which we use as a sortable unique ID.

    Key fields in the JSON:
        players         — list of players; length > 1 means a multiplayer run
        start_time      — Unix timestamp (also encoded in the filename)
        ascension       — ascension level (0 = no ascension)
        win             — true/false
        game_mode       — "standard" or "daily"
        run_time        — total run duration in seconds
        map_point_history — list of acts, each containing the nodes visited;
                            counting nodes gives a proxy for floors reached
        killed_by_encounter — what killed the player (empty string if they won)
    """
    with path.open(encoding="utf-8") as f:
        data = json.load(f)  # parse the JSON text into a Python dict

    # The Steam ID is embedded in the save path
    # (.../steam/<steamID>/profile1/saves/history/<file>.run — index -5 from the file).
    parts = path.parts
    steam_id = parts[-5] if len(parts) >= 5 else None
    return parse_run_data(data, steam_id=steam_id, fallback_ts=int(path.stem))


def parse_run_data(data: dict, steam_id: str | None = None, fallback_ts: int | None = None) -> dict:
    """
    parse_run() minus the file: takes an already-loaded .run JSON object, the
    local player's Steam ID (to pick them out of a multiplayer run) and the
    timestamp to fall back on if the file lacks start_time. The ingest Lambda
    calls this directly with the Steam ID it verified, since uploads arrive
    as JSON, not files at a save-folder path.
    """
    # In multiplayer, every player has their own entry. Find the local player by
    # matching their Steam ID. Fall back to index 0 for solo runs or no Steam ID.
    players = data.get("players", [{}])
    player = players[0]
    if steam_id and len(players) > 1:
        for p in players:
            if str(p.get("id", "")) == steam_id:
                player = p
                break

    # Use start_time if present; fall back to the filename (they should match).
    ts = data.get("start_time", fallback_ts)

    # Strip the "CHARACTER." prefix so we store just "IRONCLAD", "SILENT", etc.
    character = strip_prefix(player.get("character", ""), "CHARACTER.")

    # map_point_history is a list of acts. Each act is a list of nodes visited.
    # Summing the node counts across all acts gives total floors reached.
    map_history   = data.get("map_point_history", [])
    floor_reached = sum(len(act) for act in map_history if isinstance(act, list))

    # run_time is in seconds; convert to minutes rounded to 1 decimal place.
    run_time_min = round(data.get("run_time", 0) / 60, 1)

    # Count cards and relics by counting list entries that have a non-empty "id".
    cards  = len([c for c in player.get("deck",   []) if c.get("id")])
    relics = len([r for r in player.get("relics", []) if r.get("id")])

    # Count generic starter cards. The starter variants are named CARD.STRIKE_<CHAR>
    # and CARD.DEFEND_<CHAR>, so we match the prefix exactly to exclude cards like
    # Pommel Strike, Meteor Strike, Ultimate Defend, etc.
    strikes = len([c for c in player.get("deck", []) if c.get("id", "").startswith("CARD.STRIKE_")])
    defends = len([c for c in player.get("deck", []) if c.get("id", "").startswith("CARD.DEFEND_")])

    char = character or "UNKNOWN"
    asc  = data.get("ascension", 0)
    run_won = bool(data.get("win", False))

    # Tally every card and relic offered to the local player, recording where each appeared.
    # cardsOffered / relicsOffered: { id: [{floor, type, enc}] }
    # restChoices: { HEAL: n, SMITH: n, ... } — count of each choice made at rest sites.
    cards_offered: dict[str, list] = {}
    relics_offered: dict[str, list] = {}
    # restChoices: { act (1-indexed): { choice: count } }
    rest_choices: dict[int, dict[str, int]] = {}
    floor_idx = 0
    for act_idx, act in enumerate(map_history):
        if not isinstance(act, list):
            continue
        act_num = act_idx + 1
        for node in act:
            ntype = node.get("map_point_type", "")
            rooms = node.get("rooms", [])
            enc   = rooms[0].get("model_id", "") if rooms else ""
            loc   = {"floor": floor_idx, "type": ntype, "enc": enc}
            ps    = node.get("player_stats", [{}])[0]  # local player only
            for cc in ps.get("card_choices", []):
                cid = cc.get("card", {}).get("id", "")
                if cid:
                    cards_offered.setdefault(cid, []).append({**loc, "picked": bool(cc.get("was_picked"))})
            for rc in ps.get("relic_choices", []):
                rid = rc.get("choice", "")
                if rid:
                    relics_offered.setdefault(rid, []).append({**loc, "picked": bool(rc.get("was_picked"))})
            if ntype == "rest_site":
                act_choices = rest_choices.setdefault(act_num, {})
                for choice in ps.get("rest_site_choices", []):
                    if choice:
                        act_choices[choice] = act_choices.get(choice, 0) + 1
            floor_idx += 1

    final_deck = [
        {
            "id":      c["id"],
            "upgrade": c.get("current_upgrade_level", 0),
        }
        for c in player.get("deck", []) if c.get("id")
    ]
    final_relics = [
        {"id": r["id"]}
        for r in player.get("relics", []) if r.get("id")
    ]

    # Total gold earned over the run (shop/event/reward pickups), not the final
    # gold balance — summed from the same per-floor goldGained the timeline
    # already carries, so this doesn't walk map_point_history a second time.
    timeline = extract_timeline(data)
    gold_gained_total = sum(t["goldGained"] for t in timeline)

    return {
        "char":          char,
        "asc":           asc,
        "won":           run_won,
        "floor":         floor_reached,
        "mins":          run_time_min,
        "cards":         cards,
        "relics":        relics,
        "strikes":       strikes,
        "defends":       defends,
        "ts":            ts,
        "mp":            len(players) > 1,
        "mode":          data.get("game_mode", "standard"),
        "build":         data.get("build_id", "UNKNOWN"),
        "seed":          data.get("seed", ""),
        "goldGained":    gold_gained_total,
        "cardsOffered":  cards_offered,
        "relicsOffered": relics_offered,
        "restChoices":   rest_choices,
        "finalDeck":     final_deck,
        "finalRelics":   final_relics,
        "fights":        extract_fights(data, char, asc, run_won),
        "timeline":      timeline,
    }


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

# Resolve paths relative to this script file so run.py works from any cwd.
_HERE = Path(__file__).parent

# The dashboard JS used to be one 5,300-line dashboard.js. It now lives as
# js/*.js, concatenated in exactly this order to produce the same single
# <script>. The order is load-bearing: the emitted script is one global scope
# with ~100 top-level const/let bindings and no module wrapper, so anything
# read at load time must come after its declaration. Listing the files
# explicitly rather than globbing is what makes that order reviewable in one
# place: the filenames deliberately carry no ordering hint, because two
# representations of the same order are one more than can stay in sync.
_JS_DIR = _HERE / "js"
_JS_MODULES = [
    "data.js",
    "tooltip.js",
    "charts.js",
    "aggregation.js",
    "render-helpers.js",
    "overview-tables.js",
    "update.js",
    "page-nav.js",
    "character-detail.js",
    "cards-page.js",
    "seeds.js",
    "run-detail.js",
    "card-face.js",
]


def read_dashboard_js() -> str:
    """Concatenate js/*.js in _JS_MODULES order into one script."""
    unlisted = sorted(
        f.name for f in _JS_DIR.glob("*.js") if f.name not in _JS_MODULES
    )
    if unlisted:
        raise SystemExit(
            f"js/ has files missing from _JS_MODULES (add them in load order): {unlisted}"
        )
    missing = [n for n in _JS_MODULES if not (_JS_DIR / n).exists()]
    if missing:
        raise SystemExit(f"_JS_MODULES lists files that do not exist: {missing}")
    return "".join((_JS_DIR / n).read_text(encoding="utf-8") for n in _JS_MODULES)

_PORTRAIT_ROOT  = _HERE / "card_portraits"  # downscaled 144px-wide PNGs; falls back to full-res if absent
_PORTRAIT_ROOT_FULL = _HERE / "pck_recover_full" / "images" / "packed" / "card_portraits"
# Committed copies (tools/downscale_relics.py); falls back to the gitignored
# extraction so a machine that has only run the recovery still works.
_NODE_ICON_DIR      = _HERE / "node_icons"
_NODE_ICON_DIR_FULL = _HERE / "pck_recover_full" / "images" / "ui" / "run_history"

_NODE_ICON_FILES = {
    "monster":       "monster.png",
    "elite":         "elite.png",
    "rest_site":     "rest_site.png",
    "shop":          "shop.png",
    "treasure":      "treasure.png",
    "unknown":       "unknown_monster.png",
    "unknown_elite": "unknown_elite.png",
    "unknown_shop":  "unknown_shop.png",
    "unknown_treasure": "unknown_treasure.png",
    "ancient":      "ancient.png",
    "event":         "event.png",
    # Per-Ancient portraits, keyed the same way boss encounters are (the
    # node's own "enc" field, e.g. "EVENT.NEOW"). Unlike bosses these source
    # files don't share a distinguishing suffix to glob on, so they're listed
    # explicitly here rather than derived from a directory scan.
    "EVENT.DARV":       "darv.png",
    "EVENT.NEOW":       "neow.png",
    "EVENT.NONUPEIPE":  "nonupeipe.png",
    "EVENT.OROBAS":     "orobas.png",
    "EVENT.PAEL":       "pael.png",
    "EVENT.TANX":       "tanx.png",
    "EVENT.TEZCATARA":  "tezcatara.png",
    "EVENT.VAKUU":      "vakuu.png",
}

_CARD_FINAL_DIR = _HERE / "card_final"


def build_card_final_images(url_for=Path.as_uri) -> dict[str, str]:
    """Fully baked card faces (art + text), keyed by CARD.ID / CARD.ID_UP.

    Produced by tools/bake_finished_cards.py. Empty if the bake hasn't been
    run — card-face.js falls back to the older hand-built CSS tooltip.

    url_for turns a resolved Path into the string embedded in the output;
    it defaults to Path.as_uri (file:// URIs for the local HTML generator)
    but build_site.py passes a root-absolute-URL maker instead.
    """
    if not _CARD_FINAL_DIR.exists():
        return {}
    return {p.stem: url_for(p) for p in sorted(_CARD_FINAL_DIR.glob("*.webp"))}


_UI_ICONS_DIR = _HERE / "ui_icons"


def build_energy_icons(url_for=Path.as_uri) -> dict[str, str]:
    """
    Character pool ("ironclad", "colorless", ...) -> energy orb icon URL, for
    the inline "Gain N Energy" glyph in relic/potion descriptions and the
    non-baked card tooltip fallback (js/run-detail.js's substituteDescVars).
    ui_icons/energy_<pool>.png are copies of the same card_chrome/ sprites
    tools/bake_finished_cards.py pastes onto a baked card's cost badge, so
    which pools have their own colored orb (vs. falling back to "colorless")
    is derived from whichever files actually exist here, not hardcoded --
    stays in sync automatically if a pool's icon is added or removed.
    """
    if not _UI_ICONS_DIR.exists():
        return {}
    return {
        p.stem.removeprefix("energy_"): url_for(p)
        for p in sorted(_UI_ICONS_DIR.glob("energy_*.png"))
    }


def build_node_icons(url_for=Path.as_uri) -> dict[str, str]:
    """
    type -> icon URL for each generic node type, plus one entry per boss
    encounter id (e.g. "ENCOUNTER.QUEEN_BOSS" -> queen_boss.png's URL) and one
    per Ancient event id (e.g. "EVENT.NEOW" -> neow.png's URL) so the Run
    Detail timeline can show the specific boss/Ancient instead of a generic
    node icon. Boss entries are derived from the <name>_boss.png files
    themselves rather than hardcoded, so they stay in sync with whatever's in
    node_icons/; Ancients are listed explicitly in _NODE_ICON_FILES since
    their source files don't share a boss-style suffix to glob on. All three
    (generic types, bosses, Ancients) live in the same flat dict — the keys
    look nothing alike, so there's no collision risk.
    """
    root = _NODE_ICON_DIR if _NODE_ICON_DIR.exists() else _NODE_ICON_DIR_FULL
    if not root.exists():
        return {}
    result = {}
    for key, fname in _NODE_ICON_FILES.items():
        p = root / fname
        if p.exists():
            result[key] = url_for(p)
    for p in sorted(root.glob("*_boss.png")):
        result["ENCOUNTER." + p.stem.upper()] = url_for(p)
    return result
_CARD_DATA_FILE   = _HERE / "card_data.json"
_RELIC_DATA_FILE  = _HERE / "relic_data.json"
_POTION_DATA_FILE = _HERE / "potion_data.json"


def build_card_char(card_data: dict) -> dict[str, str]:
    """
    cid -> owning character pool ("IRONCLAD", "SILENT", ...), derived from
    card_data["pool"] (set by extract_card_data.py, which reads portrait
    directory structure — authoritative game data). Shared by build_html()
    and build_site.py so the derivation lives in exactly one place.
    """
    return {cid: meta["pool"] for cid, meta in card_data.items() if "pool" in meta}

def resolve_image_paths(data: dict, url_for=Path.as_uri) -> dict:
    """
    relic_data.json and potion_data.json store imagePath as a path relative to
    this script (e.g. "relic_images/akabeko.png") so the repo isn't tied to one
    machine's absolute layout. Resolve to a URL here, same as
    build_card_images()/build_node_icons() — file:// URIs by default, or
    root-absolute site paths when build_site.py passes its own url_for.
    """
    for meta in data.values():
        rel = meta.get("imagePath")
        if rel:
            p = _HERE / rel
            meta["imagePath"] = url_for(p) if p.exists() else ""
    return data

# Special-case overrides: card ID stem → portrait filename stem (without .png)
_PORTRAIT_OVERRIDES: dict[str, str] = {
    "stack": "smokestack",
    "mad_science": "mad_science_attack",
}

def build_card_images(url_for=Path.as_uri) -> dict[str, str]:
    """
    Scan the extracted portrait folder and return a dict mapping CARD.ID → URL.
    Prefers non-beta portraits; falls back to beta subfolder if that's all there is.
    Returns an empty dict if the portrait folder doesn't exist.
    """
    root = _PORTRAIT_ROOT if _PORTRAIT_ROOT.exists() else _PORTRAIT_ROOT_FULL
    if not root.exists():
        return {}

    # Index all PNGs: stem → list of paths, non-beta first
    index: dict[str, list[Path]] = {}
    for p in sorted(root.rglob("*.png")):
        stem = p.stem
        index.setdefault(stem, []).append(p)

    def resolve(stem: str) -> str | None:
        candidates = index.get(stem, [])
        if not candidates:
            return None
        # Prefer non-beta path
        non_beta = [c for c in candidates if "beta" not in c.parts]
        chosen = non_beta[0] if non_beta else candidates[0]
        return url_for(chosen)

    result: dict[str, str] = {}

    # Walk all known card stems from the portrait folder itself
    all_stems: set[str] = set(index.keys()) - {"beta", "ancient_beta"}
    # We emit for every stem we find; JS will look up by CARD.X → stem.
    # Iterate sorted, NOT over the raw set: Python set iteration order depends
    # on string hash randomization, so an unsorted walk made the resulting dict
    # (and ~62KB of the embedded JSON) come out in a different key order on
    # every build, which made two builds of identical code undiffable.
    for stem in sorted(all_stems):
        uri = resolve(stem)
        if uri:
            result[stem] = uri
    return result


def dashboard_body_html(subtitle: str) -> str:
    """
    The markup between <body> and the <script> tag: skip link, header, the
    shared filter bar, and all five pages (Overview / Character Detail / Run
    Detail / Card Stats / Seed Data). Shared by build_html() (the local HTML
    generator) and build_site.py (the static site, whose subtitle differs
    since there's no "local save data" on the live site).
    """
    return f"""<a class="skip-link" href="#main-content">Skip to content</a>

<header>
<h1>Slay the Spire 2</h1>
<p class="subtitle">{subtitle}</p>
</header>

<nav class="page-tabs" aria-label="Pages">
  <button class="page-tab active" id="tab-overview" onclick="showPage('overview')">Overview</button>
  <button class="page-tab" id="tab-character" onclick="showPage('character')">Character Detail</button>
  <button class="page-tab" id="tab-detail" onclick="showPage('detail')">Run Detail</button>
  <button class="page-tab" id="tab-cards" onclick="showPage('cards')">Card Stats</button>
  <button class="page-tab" id="tab-seeds" onclick="showPage('seeds')">Seed Data</button>
</nav>

<nav class="filter-bar filter-bar-2row" id="shared-filter-bar" aria-label="Filters">
  <button type="button" class="filter-summary" id="shared-filter-summary" aria-expanded="false">
    <span class="filter-label">Filters</span>
    <span class="filter-summary-text"></span>
    <span class="filter-summary-caret" aria-hidden="true">▾</span>
  </button>
  <div class="filter-row">
    <div class="filter-group">
      <span class="filter-label">Character</span>
      <div id="shared-char-selector"></div>
    </div>
    <div class="filter-group">
      <span class="filter-label">Mode</span>
      <button class="toggle-btn" id="shared-mode-all">All</button>
      <button class="toggle-btn" id="shared-mode-solo">Solo</button>
      <button class="toggle-btn" id="shared-mode-multi">Multi</button>
      <button class="toggle-btn" id="shared-mode-daily">Daily</button>
    </div>
  </div>
  <div class="filter-row">
    <div class="filter-group">
      <span class="filter-label">Ascension</span>
      <button class="toggle-btn" id="shared-asc-granular" aria-pressed="false" title="Pick individual ascension levels, and split the tables into one column per level instead of A0–9 / A10 / All">Show granular</button>
      <div id="shared-asc-checkboxes" style="display:none;gap:0.4rem;flex-wrap:wrap"></div>
      <button class="toggle-btn" id="shared-asc-all" style="display:none">All</button>
      <button class="toggle-btn" id="shared-asc-none" style="display:none">None</button>
    </div>
    <div class="filter-group filter-dropdown-wrap">
      <span class="filter-label">Build</span>
      <button class="toggle-btn" id="shared-build-toggle" aria-expanded="false" aria-controls="shared-build-panel" aria-haspopup="true">All builds ▾</button>
      <div class="filter-dropdown-panel" id="shared-build-panel" style="display:none">
        <div class="filter-dropdown-actions">
          <button class="toggle-btn" id="shared-build-all">All</button>
          <button class="toggle-btn" id="shared-build-none">None</button>
        </div>
        <div class="sep"></div>
        <div id="shared-build-checkboxes" class="filter-dropdown-scroll"></div>
      </div>
    </div>
  </div>
  <div class="filter-row">
    <div class="filter-group">
      <span class="filter-label">Date</span>
      <input type="date" id="shared-date-from" aria-label="Start date">
      <span style="color:#8a8aa0;font-size:0.85rem" aria-hidden="true">→</span>
      <input type="date" id="shared-date-to" aria-label="End date">
      <div class="sep"></div>
      <button class="toggle-btn" id="shared-date-7d">7d</button>
      <button class="toggle-btn" id="shared-date-30d">30d</button>
      <button class="toggle-btn" id="shared-date-90d">90d</button>
      <button class="toggle-btn" id="shared-date-today">Today</button>
      <button class="toggle-btn" id="shared-date-alltime">All time</button>
    </div>
    <div class="filter-group">
      <button class="toggle-btn" id="shared-filters-save" title="Remember the current filters and use them as the default next time you open this dashboard">Save as default</button>
      <button class="toggle-btn" id="shared-filters-reset" title="Revert to the built-in filters. Your saved default is kept unless you click Save as default">Reset filters</button>
      <span id="shared-filters-unsaved" title="You've changed filters since your last save — click Save as default to keep them" style="display:none;align-items:center;justify-content:center;width:1.15rem;height:1.15rem;margin-left:0.4rem;border-radius:50%;background:#e0c468;color:#13132a;font-size:0.75rem;font-weight:700;cursor:default;user-select:none">!</span>
      <span id="shared-filters-status" style="color:#8a8aa0;font-size:0.8rem;margin-left:0.4rem"></span>
    </div>
  </div>
</nav>

<main id="main-content">
<div id="page-overview">
<div class="cards" id="summary-cards"></div>
<div class="cards" id="personal-bests-cards"></div>

<div class="grid-2">
  <div class="chart-box">
    <h2>Win % by Character</h2>
    <div class="chart-wrap"><canvas id="charWinChart"></canvas></div>
  </div>
  <div class="chart-box">
    <h2>Win % by Ascension Level (per Character)</h2>
    <div class="chart-wrap"><canvas id="ascWinChart"></canvas></div>
  </div>
</div>

<div class="grid-1">
  <div class="chart-box">
    <h2>Win % by Month</h2>
    <p class="chart-caption">Dotted lines mark when each game build was first played.</p>
    <div class="chart-wrap"><canvas id="monthlyWinChart"></canvas></div>
  </div>
</div>

<div class="grid-4">
  <div class="chart-box">
    <h2>Median Floor Reached by Character</h2>
    <div class="chart-wrap"><canvas id="charFloorChart"></canvas></div>
  </div>
  <div class="chart-box">
    <h2>Median Run Length (min) by Character</h2>
    <div class="chart-wrap"><canvas id="charTimeChart"></canvas></div>
  </div>
  <div class="chart-box">
    <h2>Total Time Played (hrs) by Character</h2>
    <div class="chart-wrap"><canvas id="charTotalTimeChart"></canvas></div>
  </div>
  <div class="chart-box">
    <h2>Time Played (% Share)</h2>
    <div class="chart-wrap" style="display:flex;align-items:center;justify-content:center;height:100%"><canvas id="charTimeShareChart" style="max-height:220px"></canvas></div>
  </div>
</div>

<div class="grid-2">
  <div class="chart-box">
    <h2>Elite Death Rate</h2>
    <p class="chart-caption">How often a run died on its 1st, 2nd, 3rd… elite, or in the fight right after, by act.</p>
    <div class="chart-wrap"><canvas id="eliteDeathRateChart"></canvas></div>
  </div>
  <div class="chart-box">
    <h2>Elite Win Rate</h2>
    <p class="chart-caption">Share of runs won, by how many elites the run fought in total.</p>
    <div class="chart-wrap"><canvas id="eliteWinRateChart"></canvas></div>
  </div>
</div>

<div class="grid-2">
  <div class="chart-box">
    <h2>Win %</h2>
    <p class="chart-caption">Share of runs won, by character and ascension.</p>
    <div class="pivot-wrap"><table class="pivot" id="pivot-table"></table></div>
  </div>
  <div class="chart-box">
    <h2>Final Boss Win %</h2>
    <p class="chart-caption">Of the runs that reached the final boss, the share that beat it. Ascension 10's two Act 3 bosses are shown separately.</p>
    <div class="pivot-wrap"><table class="pivot" id="final-boss-win-table"></table></div>
  </div>
</div>

<div class="grid-2">
  <div class="chart-box">
    <h2>Cards at Run End</h2>
    <p class="chart-caption">Median deck size when the run ended, in runs you won vs. lost. The small range under Won is the fewest–most in a win.</p>
    <div class="pivot-wrap"><table class="pivot" id="cards-table"></table></div>
  </div>
  <div class="chart-box">
    <h2>Relics at Run End</h2>
    <p class="chart-caption">Median relics held when the run ended, in runs you won vs. lost. The small range under Won is the fewest–most in a win.</p>
    <div class="pivot-wrap"><table class="pivot" id="relics-table"></table></div>
  </div>
</div>

<!-- Starter Cards gets a full row: its Won / Lost pairs per act don't fit
     half the page at 1280px. -->
<div class="grid-1">
  <div class="chart-box">
    <h2>Starter Cards Entering Boss</h2>
    <p class="chart-caption">Average Strikes and Defends still in your deck when you reached each act's boss, in runs you won vs. lost.</p>
    <div class="pivot-wrap"><table class="pivot" id="starter-cards-table"></table></div>
  </div>
</div>

<div class="grid-2">
  <div class="chart-box">
    <h2>Elites Defeated</h2>
    <p class="chart-caption">Median elite fights won per run (all acts), in runs you won vs. lost. The small range under Won is the fewest–most in a win.</p>
    <div class="pivot-wrap"><table class="pivot" id="elites-table"></table></div>
  </div>
  <div class="chart-box">
    <h2>Rest Site Win %</h2>
    <p class="chart-caption">Win % by how many times you picked each rest site option over a run. Only runs that reached Act 3.</p>
    <div class="chart-wrap"><canvas id="restWinChartAll"></canvas></div>
  </div>
</div>

<div class="grid-1">
  <div class="chart-box">
    <h2>Rest Site Choices</h2>
    <p class="chart-caption">How many times per run you picked each option, on average, in runs you won vs. lost. Click a character for each act.</p>
    <div class="pivot-wrap"><table class="pivot" id="rest-choices-table"></table></div>
  </div>
</div>
</div><!-- end #page-overview -->

<!-- ================================================================
     Character Detail page
     ================================================================ -->
<div id="page-character" style="display:none">

<div id="detail-char-fallback-note" class="char-fallback-note" style="display:none;margin-bottom:0.75rem"></div>

<div class="grid-2">
  <div class="chart-box">
    <h2>Boss Win Rate</h2>
    <p class="chart-caption">Share of times you won each boss fight, by ascension.</p>
    <div class="pivot-wrap"><table class="pivot" id="boss-win-table"></table></div>
  </div>
  <div class="chart-box">
    <h2>Elite Win Rate</h2>
    <p class="chart-caption">Share of times you won each elite fight, by ascension.</p>
    <div class="pivot-wrap"><table class="pivot" id="elite-win-table"></table></div>
  </div>
</div>

<div class="grid-1">
  <div class="chart-box">
    <h2>HP Entering Fight</h2>
    <p class="chart-caption">Median HP at the start of elite and boss fights, as % of max HP at the time; green for runs you won, red for runs you lost.</p>
    <div class="pivot-wrap"><table class="pivot" id="hp-table"></table></div>
  </div>
</div>

<div class="grid-1">
  <div class="chart-box">
    <h2>Cards / Relics / Potions Entering Fight</h2>
    <p class="chart-caption">Median cards, relics and potions held at the start of elite and boss fights; green for runs you won, red for runs you lost.</p>
    <div class="pivot-wrap"><table class="pivot" id="loadout-table"></table></div>
  </div>
</div>

<div class="grid-1">
  <div class="chart-box">
    <h2>Damage Taken</h2>
    <p class="chart-caption">Median damage taken per elite and boss fight; green for runs you won, red for runs you lost.</p>
    <div class="pivot-wrap"><table class="pivot" id="dmg-table"></table></div>
  </div>
</div>

<div class="grid-1">
  <div class="chart-box">
    <h2>Deck Size Entering Boss</h2>
    <p class="chart-caption">Median cards in your deck at each act's boss; green for runs you won, red for runs you lost.</p>
    <div class="pivot-wrap"><table class="pivot" id="deck-act-table"></table></div>
  </div>
</div>

</div><!-- end #page-character -->

<!-- ================================================================
     Cards page
     ================================================================ -->
<div id="page-cards" style="display:none">

<div class="filter-bar" id="cards-filter-bar">
  <div class="filter-group">
    <label id="cards-include-colorless-label">
      <input type="checkbox" id="cards-include-colorless" checked>
      Include colorless cards
    </label>
  </div>
  <div class="filter-group" id="cards-other-char-group" style="display:none">
    <label id="cards-include-other-chars-label">
      <input type="checkbox" id="cards-include-other-chars">
      Include other characters' cards
    </label>
  </div>
  <div class="filter-group">
    <span class="filter-label">Type</span>
    <button class="toggle-btn active" id="cards-type-all">All</button>
    <button class="toggle-btn" id="cards-type-attack">Attack</button>
    <button class="toggle-btn" id="cards-type-skill">Skill</button>
    <button class="toggle-btn" id="cards-type-power">Power</button>
  </div>
  <div class="filter-group">
    <span class="filter-label">Rarity</span>
    <button class="toggle-btn active" id="cards-rarity-all">All</button>
    <button class="toggle-btn" id="cards-rarity-common">Common</button>
    <button class="toggle-btn" id="cards-rarity-uncommon">Uncommon</button>
    <button class="toggle-btn" id="cards-rarity-rare">Rare</button>
  </div>
</div>

<div class="chart-box">
  <h2 id="cards-title">Card Offer &amp; Pick Rates</h2>
  <p class="chart-caption" id="cards-caption">Every card offered under the current filters.</p>
  <input type="text" class="seeds-input" id="cards-name-filter" placeholder="Filter by card name…" aria-label="Filter cards by name" style="max-width:260px;margin-bottom:0.75rem">
  <div class="pivot-wrap" style="max-height:420px;overflow-y:auto">
    <table class="pivot" id="cards-table-main" style="table-layout:fixed;min-width:0;width:auto">
      <thead id="cards-thead"></thead>
      <tbody id="cards-tbody"></tbody>
    </table>
  </div>
</div>

</div><!-- end #page-cards -->

<!-- ================================================================
     Seeds page
     ================================================================ -->
<div id="page-seeds" style="display:none">

<div class="chart-box" style="margin-bottom:1.5rem">
  <h2>Search by Cards &amp; Relics Offered</h2>
  <div class="seeds-search-area">
    <div class="seeds-search-col">
      <div class="seeds-search-label">Cards</div>
      <div class="seeds-typeahead-wrap">
        <input type="text" id="seeds-card-input" class="seeds-input" placeholder="Type a card name…" aria-label="Search seeds by card" autocomplete="off">
        <div id="seeds-card-dropdown" class="seeds-dropdown" style="display:none"></div>
      </div>
      <div id="seeds-card-filters" class="seeds-chips"></div>
    </div>
    <div class="seeds-search-col">
      <div class="seeds-search-label">Relics</div>
      <div class="seeds-typeahead-wrap">
        <input type="text" id="seeds-relic-input" class="seeds-input" placeholder="Type a relic name…" aria-label="Search seeds by relic" autocomplete="off">
        <div id="seeds-relic-dropdown" class="seeds-dropdown" style="display:none"></div>
      </div>
      <div id="seeds-relic-filters" class="seeds-chips"></div>
    </div>
    <div style="display:flex;align-items:flex-end;padding-bottom:0.25rem">
      <button class="toggle-btn" id="seeds-clear-btn" style="white-space:nowrap">Clear all</button>
    </div>
  </div>
</div>

<div class="chart-box">
  <h2 id="seeds-title">Matching Seeds</h2>
  <p class="chart-caption" id="seeds-caption">Seeds whose run offered every card and relic you searched for.</p>
  <div class="pivot-wrap">
    <table class="pivot" id="seeds-table">
      <thead><tr id="seeds-thead-row">
        <th style="text-align:left">Seed</th>
        <th style="text-align:left">Character</th>
        <th>Win</th>
        <th style="text-align:left">Date</th>
        <th style="text-align:left">Matched Cards / Relics Offered</th>
      </tr></thead>
      <tbody id="seeds-tbody"></tbody>
    </table>
  </div>
</div>

</div><!-- end #page-seeds -->

<!-- ================================================================
     Run Detail page
     ================================================================ -->
<div id="page-detail" style="display:none">

<div id="detail-layout">
  <div id="detail-run-list"></div>
  <div id="detail-main">
    <div id="detail-placeholder" class="detail-placeholder">Select a run from the list to view its timeline.</div>
    <div id="detail-content" style="display:none">
      <div id="detail-run-header"></div>
      <div id="detail-deck-relics"></div>
      <div id="detail-timeline"></div>
      <div class="chart-box" id="detail-hp-box" style="margin-top:16px">
        <div class="chart-vline-legend">
          <span class="vline-legend-item"><span class="vline-legend-line" style="border-color:#e05c5c99"></span>Elite / Boss</span>
        </div>
        <div class="chart-wrap"><canvas id="detail-hp-chart"></canvas></div>
      </div>
      <div class="chart-box" id="detail-gold-box" style="margin-top:16px">
        <div class="chart-vline-legend">
          <span class="vline-legend-item"><span class="vline-legend-line" style="border-color:#f0c06099"></span>Shop / Event</span>
        </div>
        <div class="chart-wrap"><canvas id="detail-gold-chart"></canvas></div>
      </div>
    </div>
  </div>
</div>

</div><!-- end #page-detail -->

</main>"""


def build_html(runs: list[dict]) -> str:
    """
    Build and return the full HTML dashboard as a string.

    CSS and JS are read from dashboard.css / dashboard.js (sibling files),
    then inlined into the output so it remains self-contained.
    The JS template contains a {chart_data} placeholder that Python replaces
    with the actual JSON before embedding.
    """
    characters  = sorted({run["char"] for run in runs})
    ascensions  = sorted({run["asc"]  for run in runs})
    # Sort builds newest-first by numeric version parts (e.g. "v0.107.1" > "v0.99.1"),
    # not lexicographically — a plain string sort puts "v0.99.1" after "v0.107.1".
    # Non-numeric builds (e.g. "UNKNOWN") always sort last, oldest-to-newest order.
    def build_sort_key(build: str) -> tuple:
        parts = build.lstrip("v").split(".")
        nums = [int(p) for p in parts if p.isdigit()]
        return (1, nums) if nums else (0,)
    builds = sorted({run["build"] for run in runs}, key=build_sort_key, reverse=True)
    char_colors = [CHAR_COLORS.get(c, "#888") for c in characters]

    card_images  = build_card_images()
    node_icons   = build_node_icons()
    card_final   = build_card_final_images()
    energy_icons = build_energy_icons()
    card_data   = json.loads(_CARD_DATA_FILE.read_text(encoding="utf-8"))  if _CARD_DATA_FILE.exists()  else {}
    relic_data  = json.loads(_RELIC_DATA_FILE.read_text(encoding="utf-8")) if _RELIC_DATA_FILE.exists() else {}
    relic_data  = resolve_image_paths(relic_data)
    potion_data = json.loads(_POTION_DATA_FILE.read_text(encoding="utf-8")) if _POTION_DATA_FILE.exists() else {}
    potion_data = resolve_image_paths(potion_data)

    # Build a map of encounter ID → human-readable label for use in the UI.
    #
    # Cards and relics prefer the game's own localized title and fall back to
    # prettifying the id. The fallback alone is wrong for 64 cards and 53
    # relics, because an id has already lost the real name's punctuation and
    # casing: ASCENDERS_BANE -> "Ascenders Bane" (Ascender's Bane), BEGONE ->
    # "Begone" (BEGONE!), BLOOD_SOAKED_ROSE -> "Blood Soaked Rose"
    # (Blood-Soaked Rose), ART_OF_WAR -> "Art Of War" (Art of War).
    enc_labels: dict[str, str] = {}
    card_labels: dict[str, str] = {}
    relic_labels: dict[str, str] = {}
    for run in runs:
        for fight in run.get("fights", []):
            enc = fight["enc"]
            if enc and enc not in enc_labels:
                enc_labels[enc] = fmt_encounter(enc)
        for cid in run.get("cardsOffered", {}):
            if cid and cid not in card_labels:
                card_labels[cid] = card_data.get(cid, {}).get("title") or fmt_card(cid)
        for rid in run.get("relicsOffered", {}):
            if rid and rid not in relic_labels:
                relic_labels[rid] = relic_data.get(rid, {}).get("title") or fmt_relic(rid)

    # Every card/relic the game knows about, not just the ones this player has
    # been offered — node tooltips name cards that were skipped or removed, and
    # those never appear in cardsOffered.
    for cid, meta in card_data.items():
        if meta.get("title"):
            card_labels.setdefault(cid, meta["title"])
    for rid, meta in relic_data.items():
        if meta.get("title"):
            relic_labels.setdefault(rid, meta["title"])

    card_char = build_card_char(card_data)

    chart_data = json.dumps({
        "characters":      characters,
        "charColors":      char_colors,
        "ascensions":      ascensions,
        "builds":          builds,
        "encLabels":       enc_labels,
        "encGroups":       ENCOUNTER_GROUPS,
        "cardLabels":      card_labels,
        "relicLabels":     relic_labels,
        "cardImages":         card_images,
        "cardImageOverrides": _PORTRAIT_OVERRIDES,
        "cardData":           card_data,
        "cardChar":           card_char,
        "relicData":          relic_data,
        "potionData":         potion_data,
        "nodeIcons":          node_icons,
        "cardFinal":          card_final,
        "energyIcons":        energy_icons,
        "runsData":           runs,
    })

    css = (_HERE / "dashboard.css").read_text(encoding="utf-8")
    # data.js no longer declares DATA itself (it's a global provided before the
    # bundle runs — see js/data.js's header comment), so emit the declaration
    # here, ahead of the concatenated js/*.js.
    js = f"const DATA = {chart_data};\n" + read_dashboard_js()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Slay the Spire 2 — Run History</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
  <style>
{css}
  </style>
</head>
<body>
{dashboard_body_html("Run history dashboard. Generated from local save data.")}

<script>
{js}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    history_dir, out_path, no_open = parse_args()

    # If the user didn't pass --history, auto-detect (may prompt for Steam ID).
    if history_dir is None:
        history_dir = resolve_history_dir()

    if not history_dir.exists():
        print(f"History directory not found:\n  {history_dir}")
        print('\nTry: python run.py --history "C:\\path\\to\\history"')
        sys.exit(1)

    # Sort by filename (which is a Unix timestamp) so runs are in chronological order.
    run_files = sorted(history_dir.glob("*.run"), key=lambda p: int(p.stem))

    if not run_files:
        print(f"No .run files found in:\n  {history_dir}")
        sys.exit(1)

    # Parse every run file. Collect errors separately so one bad file doesn't
    # crash the whole thing.
    runs   = []
    errors = []
    for path in run_files:
        try:
            runs.append(parse_run(path))
        except Exception as e:
            errors.append((path.name, str(e)))

    skipped = f" ({len(errors)} skipped)" if errors else ""
    print(f"Parsed {len(runs)} runs{skipped}.")

    if errors:
        print("Skipped files:")
        for name, err in errors:
            print(f"  {name}: {err}")

    # Generate the HTML and write it to disk.
    html = build_html(runs)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path}")

    if not no_open:
        webbrowser.open(out_path.as_uri())


# This block only runs when you execute the script directly with `python run.py`.
# It does NOT run if someone imports this file as a module from another script.
if __name__ == "__main__":
    main()
