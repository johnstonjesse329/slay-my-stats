"""
tools/build_event_catalog.py -- the option catalog for the Events page (event_catalog.json).

event_choices in a run save holds only the option taken, never the ones passed over, so
the options a visit could have taken come from the game's own text: the localization file
events.json lists every option of every page ("X.pages.<PAGE>.options.<OPTION>.title").
The result is checked in. Regenerate it after a game patch:

    python tools/build_event_catalog.py

    { "EVENT.X": { "title": "Byrdonis Nest",
                   "initial": ["TAKE", "EAT"],          # first page, in the game's order, no LOCKED variants
                   "labels": {"TAKE": "Take the Egg"},   # first-page options bare, later pages "PAGE.OPTION"
                   "conditional": false, "random_offer": false, "random_outcome": false } }

conditional    an option has a LOCKED variant (or NO_OPTIONS): what was offered depends on the
               deck, gold or potions at that moment, which the save does not record.
random_offer   the set of options differs per visit (dishes, characters, relics, dolls).
acts           the acts whose event pool holds it (empty: shared, any act).
random_outcome the same option can give a different result (random card, relic, potion, gold).
The last two come from reading each event's code (src/Core/Models/Events/<Name>.cs: Rng use);
they are the lists below, taken from output/event-audit.md sections 2 and 3 (FB-75).
Only an event that is neither conditional nor random_offer is a fixed set, and only a fixed
set may list the options not taken.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pck_root  # noqa: E402

OUT = pck_root.ROOT / "event_catalog.json"

RANDOM_OFFER = {"COLORFUL_PHILOSOPHERS", "ENDLESS_CONVEYOR", "RELIC_TRADER", "DOLL_ROOM"}
RANDOM_OUTCOME = {
    "TRASH_HEAP", "DOLL_ROOM", "RANWID_THE_ELDER", "RELIC_TRADER", "THIS_OR_THAT", "ROUND_TEA_PARTY",
    "UNREST_SITE", "LUMINOUS_CHOIR", "WELCOME_TO_WONGOS", "TRIAL", "TINKER_TIME", "TABLET_OF_TRUTH",
    "REFLECTIONS", "AROMA_OF_CHAOS", "MORPHIC_GROVE", "SYMBIOTE", "WHISPERING_HOLLOW", "WELLSPRING",
    "POTION_COURIER", "THE_LEGENDS_WERE_TRUE", "STONE_OF_ALL_TIME", "BATTLEWORN_DUMMY",
    "SLIPPERY_BRIDGE", "CRYSTAL_SPHERE", "ENDLESS_CONVEYOR", "COLOSSAL_FLOWER",
    "COLORFUL_PHILOSOPHERS", "LOST_WISP", "SUNKEN_STATUE", "SUNKEN_TREASURY", "JUNGLE_MAZE_ADVENTURE",
    "PUNCH_OFF", "DENSE_VEGETATION",
}
ACTS = ["Overgrowth", "Underdocks", "Hive", "Glory"]   # src/Core/Models/Acts/<Act>.cs, AllEvents
_KEY = re.compile(r"^([A-Z0-9_]+)\.pages\.([A-Z0-9_]+)\.options\.([A-Z0-9_]+)\.title$")


def act_events(pck: Path) -> dict:
    """{ "SUNKEN_STATUE": ["Overgrowth", "Underdocks"] } from each act's AllEvents list.
    An event in none of them is shared (it can turn up in any act) and gets no acts."""
    out: dict = {}
    for act in ACTS:
        src = (pck / "src" / "Core" / "Models" / "Acts" / f"{act}.cs").read_text(encoding="utf-8")
        block = re.search(r"AllEvents =>.*?\}\)", src, re.S)
        for cls in re.findall(r"ModelDb\.Event<(\w+)>", block.group(0) if block else ""):
            out.setdefault(re.sub(r"(?<!^)(?=[A-Z])", "_", cls).upper(), []).append(act)
    return out


def build(loc: dict, acts: dict | None = None, art: set[str] | None = None) -> dict:
    events: dict = {}
    for key, text in loc.items():
        if key.endswith(".title") and key.count(".") == 1:
            events.setdefault(key.split(".")[0], {})["title"] = text
    for key, text in loc.items():
        m = _KEY.match(key)
        if not m:
            continue
        name, page, opt = m.groups()
        e = events.setdefault(name, {})
        e.setdefault("initial", [])
        e.setdefault("labels", {})
        e.setdefault("_locked", False)
        if opt.endswith("_LOCKED") or opt == "NO_OPTIONS" or text == "Locked":
            e["_locked"] = True
            continue
        if "{" not in text and "[" not in text:
            e["labels"][opt if page == "INITIAL" else f"{page}.{opt}"] = text
        if page == "INITIAL":
            e["initial"].append(opt)
    out = {}
    for name in sorted(events):
        e = events[name]
        if not e.get("initial"):
            continue
        out[f"EVENT.{name}"] = {
            "title": e.get("title") or name.replace("_", " ").title(),
            "initial": e["initial"],
            "labels": dict(sorted(e["labels"].items())),
            "conditional": e["_locked"],
            "random_offer": name in RANDOM_OFFER,
            "random_outcome": name in RANDOM_OUTCOME,
            "acts": (acts or {}).get(name, []),
            # The event's own illustration, for the Events page. A path relative to
            # the repo (tools/downscale_art.py builds event_images/); run.py and
            # build_site.py resolve it to a URL, or blank it where the art is missing.
            **({"imagePath": f"event_images/{name.lower()}.webp"} if art and name.lower() in art else {}),
        }
    return out


def main() -> None:
    pck = pck_root.find_pck_root()
    loc = json.loads((pck / "localization" / "eng" / "events.json").read_text(encoding="utf-8"))
    art = {p.stem for p in (pck / "images" / "events").glob("*.png")}
    cat = build(loc, act_events(pck), art)
    OUT.write_text(json.dumps(cat, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(cat)} events -> {OUT}")


if __name__ == "__main__":
    main()
