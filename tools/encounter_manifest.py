"""Build the encounter render manifest: which monsters make up each fight, and
how the game places and scales them. Reads the PCK extraction only; writes JSON.

Everything here mirrors the game's own data:
  * src/Core/Models/Encounters/<Class>.cs -> GenerateMonsters() roster + slot names
  * scenes/creature_visuals/<id>.tscn     -> skeleton data, scale, offset, bounds
  * animations/.../<x>_skel_data.tres     -> the .atlas/.skel pair
  * scenes/encounters/<class>.tscn        -> Marker2D slots (encounters with a scene)
Encounters without a scene are laid out by NCombatRoom.PositionEnemies, which the
renderer reproduces from the bounds widths recorded here.

tools/render_encounter_art.py runs this; it is not usually run by hand.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pck_root import find_pck_root

PCK = Path(sys.argv[1]) if len(sys.argv) > 1 else find_pck_root()
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("manifest.json")


ENC_DIR = PCK / "src/Core/Models/Encounters"
VIS_DIR = PCK / "scenes/creature_visuals"
ENC_SCENES = PCK / "scenes/encounters"


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def parse_tres(tres: Path) -> dict:
    """The .atlas and .skel a SpineSkeletonDataResource points at."""
    text = tres.read_text(encoding="utf-8", errors="replace")
    out = {}
    for kind, path in re.findall(r'type="Spine(\w+)Resource"[^\]]*path="res://([^"]+)"', text):
        if kind == "Atlas":
            out["atlas"] = path
        elif kind == "SkeletonFile":
            out["skel"] = path
    return out


def parse_visuals(mid: str) -> dict | None:
    """Skeleton, scale, offset and footprint width from creature_visuals/<id>.tscn."""
    tscn = VIS_DIR / f"{mid}.tscn"
    if not tscn.exists():
        return None
    text = tscn.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'type="SpineSkeletonDataResource"[^\]]*path="res://([^"]+)"', text)
    if not m:
        return None
    tres = PCK / m.group(1)
    if not tres.exists():
        return None
    info = parse_tres(tres)
    if "atlas" not in info or "skel" not in info:
        return None

    def node(name: str) -> str:
        m = re.search(r'\[node name="%s"[^\]]*\](.*?)(?=\n\[node|\Z)' % name, text, re.S)
        return m.group(1) if m else ""

    vis = node("Visuals")
    bounds = node("Bounds")

    def vec(block: str, key: str, default):
        m = re.search(r"^%s = Vector2\(([-\d.e]+), ([-\d.e]+)\)" % key, block, re.M)
        return [float(m.group(1)), float(m.group(2))] if m else default

    def num(block: str, key: str, default=0.0):
        m = re.search(r"^%s = ([-\d.e]+)" % key, block, re.M)
        return float(m.group(1)) if m else default

    skin = re.search(r'preview_skin = "([^"]*)"', vis)
    width = num(bounds, "offset_right", 0.0) - num(bounds, "offset_left", 0.0)
    return {
        "id": mid,
        "atlas": info["atlas"],
        "skel": info["skel"],
        "scale": vec(vis, "scale", [1.0, 1.0]),
        "offset": vec(vis, "position", [0.0, 0.0]),
        "skin": skin.group(1) if skin else "",
        # Falls back to a sane width so an entry with no Bounds node still lays out.
        "width": width if width > 0 else 300.0,
    }


# Rosters the parser cannot read from the returned sequence, because the game
# builds them in a switch. One representative line-up each, matching a real fight.
CLASS_ALIASES = {
    # An old run-data key: the encounter was one class before it split into V2/V3.
    "BattlewornDummyEventEncounter": "BattlewornDummyEventV2Encounter",
}
ROSTER_OVERRIDES = {
    "SlitheringStranglerNormal": [("SnappingJaxfruit", None), ("SlitheringStrangler", None)],
}
# KaiserCrabBoss' monsters (the claws) have no art of their own: they are slots in
# the boss's own skeleton, which the game draws with bestiary_layout_kaiser_crab.
ART_OVERRIDES = {"KaiserCrabBoss": ["kaiser_crab_boss"]}


def _fields(text: str) -> tuple[dict, dict]:
    """Static monster arrays, valid-count dictionaries and slot-name arrays."""
    monsters, strings = {}, {}
    for name, items in re.findall(
        r"(\w+) =>?[^;\n]*?new MonsterModel\[\d+\]\s*\{([^}]*)\}", text, re.S
    ):
        monsters[name] = re.findall(r"Monster<(\w+)>", items)
    for name, items in re.findall(r"(\w+) =>?[^;\n]*?new string\[\d+\] \{([^}]*)\}", text):
        strings[name] = re.findall(r'"([^"]*)"', items)
    for name, items in re.findall(
        r"(\w+ValidCounts) = new Dictionary<MonsterModel, int>\s*\{(.*?)\n\t\};", text, re.S
    ):
        monsters[name] = re.findall(r"Monster<(\w+)>", items)
    return monsters, strings


def _drop_dread(body: str) -> str:
    """Keep the standard line-up where the game branches on the Dread ascension."""
    i = body.find("if (AscensionHelper.IsDread())")
    if i < 0:
        return body
    j = body.index("{", i)
    depth, k = 0, j
    for k in range(j, len(body)):
        if body[k] == "{":
            depth += 1
        elif body[k] == "}":
            depth -= 1
            if depth == 0:
                break
    rest = body[k + 1:].lstrip()
    if rest.startswith("else"):
        rest = rest[4:].lstrip()
        if rest.startswith("{"):
            rest = rest[1:]
    return body[:i] + rest


def parse_roster(text: str) -> list:
    """The monsters GenerateMonsters() returns, in order, with their slot names.

    Reads the returned sequence rather than every ModelDb.Monster<> mention, so
    locals, random picks and valid-count loops each contribute exactly one entry.
    A random pick resolves to the first candidate, keeping output deterministic.
    """
    found = re.search(r"GenerateMonsters\(\)(.*?)\n\t\}", text, re.S)
    if not found:
        return []
    body = _drop_dread(found.group(1))
    arrays, strings = _fields(text)

    # list2 = _smallSlimes.ToList() and friends: an alias for a static array.
    aliases = {}
    for var, field in __import__("re").findall(r"(\w+) = (\w+)\.ToList\(\)", body):
        if field in arrays:
            aliases[var] = arrays[field]
    arrays.update(aliases)

    locals_ = {}
    for var, mcls in re.findall(r"(\w+) = (?:\(\w+\))?ModelDb\.Monster<(\w+)>\(\)", body):
        locals_.setdefault(var, mcls)
    # Two picks from the same array are different monsters in game (the first is
    # removed from the pool), so take successive entries rather than repeating one.
    taken: dict = {}
    for var, field in re.findall(r"MonsterModel (\w+) = base\.Rng\.NextItem\((\w+)\);", body):
        pool = arrays.get(field) or []
        if pool:
            i = taken.get(field, 0)
            locals_.setdefault(var, pool[i % len(pool)])
            taken[field] = i + 1
    for var, rest in re.findall(r"MonsterModel (\w+) = \((.*?)\);", body, re.S):
        m = re.search(r"Monster<(\w+)>", rest)
        if m:
            locals_.setdefault(var, m.group(1))

    def monster(expr: str):
        expr = re.sub(r"\.ToMutable\(\)|^\(\w+\)", "", expr.strip()).strip()
        m = re.search(r"Monster<(\w+)>", expr)
        if m:
            return m.group(1)
        m = re.search(r"NextItem\((\w+)\)", expr)
        if m and arrays.get(m.group(1)):
            return arrays[m.group(1)][0]
        return locals_.get(expr)

    def slot(expr):
        if not expr:
            return None
        expr = expr.strip()
        m = re.fullmatch(r'"([^"]*)"', expr)
        if m:
            return m.group(1) or None
        m = re.fullmatch(r"(\w+)\[(\d+)\]", expr)
        if m and strings.get(m.group(1)):
            names, i = strings[m.group(1)], int(m.group(2))
            return names[i] if i < len(names) else None
        return None

    # Entries appear as tuple literals, span assignments or Add() calls; a loop
    # over a valid-counts dictionary stands for N picks from that dictionary.
    pattern = re.compile(
        r"span\[\w+\] = (?P<s>[^;]+);"
        r"|\w+\.Add\((?P<a>[^;]+)\);"
        r"|for \(int \w+ = 0; \w+ < (?P<n>\d+); \w+\+\+\)"
        r"|\((?P<t>[^,;(]*(?:\([^()]*\)[^,;(]*)*)\s*,\s*"
        r"(?P<ts>\"[^\"]*\"|null|\w+\[\d+\])\)"
    )
    # "foreach (string slot in Slots)" fills every slot the encounter declares.
    loop = re.search(r"foreach \(string (\w+) in (\w+)\)(.*?)\n\t\t\}", body, re.S)
    if loop and strings.get(loop.group(2)):
        mcls = monster(loop.group(3))
        if mcls:
            return [(mcls, name) for name in strings[loop.group(2)]]

    roster = []
    for m in pattern.finditer(body):
        if m.group("n"):
            name = next((k for k in arrays if k.endswith("ValidCounts")), "")
            keys = arrays.get(name, [])
            for i in range(int(m.group("n"))):
                if keys:
                    roster.append((keys[i % len(keys)], None))
            continue
        raw = m.group("s") or m.group("a")
        if raw:
            raw = raw.strip().strip("()")
            parts = raw.rsplit(",", 1)
            mcls = monster(parts[0])
            if mcls:
                roster.append((mcls, slot(parts[1]) if len(parts) == 2 else None))
            continue
        mcls = monster(m.group("t"))
        if mcls:
            roster.append((mcls, slot(m.group("ts"))))
    return roster


def parse_encounter(cls: str) -> dict | None:
    cls = CLASS_ALIASES.get(cls, cls)
    src = ENC_DIR / f"{cls}.cs"
    if not src.exists():
        return None
    text = src.read_text(encoding="utf-8", errors="replace")

    roster = ROSTER_OVERRIDES.get(cls) or parse_roster(text)

    has_scene = "public override bool HasScene => true" in text
    slots = {}
    if has_scene:
        scene = ENC_SCENES / f"{snake(cls)}.tscn"
        if scene.exists():
            stext = scene.read_text(encoding="utf-8", errors="replace")
            for name, block in re.findall(
                r'\[node name="([^"]+)" type="Marker2D"[^\]]*\](.*?)(?=\n\[node|\Z)', stext, re.S
            ):
                m = re.search(r"^position = Vector2\(([-\d.e]+), ([-\d.e]+)\)", block, re.M)
                if m:
                    slots[name] = [float(m.group(1)), float(m.group(2))]

    cam = re.search(r"GetCameraScaling\(\)\s*\{\s*return ([-\d.e]+)f", text, re.S)

    monsters = []
    for mid in ART_OVERRIDES.get(cls, []):
        vis = parse_visuals(mid)
        if vis:
            vis["slot"] = vis["pos"] = None
            monsters.append(vis)
    if monsters:
        roster = []
    for mcls, slot in roster:
        vis = parse_visuals(snake(mcls))
        if vis is None:
            monsters.append({"class": mcls, "missing": True})
            continue
        vis["slot"] = slot if slot in slots else None
        vis["pos"] = slots.get(slot) if slot in slots else None
        monsters.append(vis)

    return {
        "class": cls,
        "camera_scaling": float(cam.group(1)) if cam else 1.0,
        "slots": slots,
        "monsters": monsters,
    }


def encounter_classes() -> list[str]:
    """Every encounter the game still ships: one <Class>.cs per fight, minus the
    abstract bases (a split like BattlewornDummyEvent -> V2/V3 leaves the old
    name behind as one) and the Deprecated placeholder. Driving the list off the
    extraction rather than off our own run data means a fight that arrives in a
    patch gets an image without anyone editing a list -- and one the patch
    removes stops being rendered, which is why DOORMAKER_BOSS and
    TOADPOLES_NORMAL (both in old runs, both gone from the game) have no image.
    """
    out = []
    for path in sorted(ENC_DIR.glob("*.cs")):
        cls = path.stem
        if cls == "DeprecatedEncounter":
            continue
        if re.search(r"abstract class", path.read_text(encoding="utf-8", errors="replace")):
            continue
        out.append(cls)
    return out


def key_for(cls: str) -> str:
    """ENCOUNTER.<SCREAMING_SNAKE>, the key run data uses for a fight."""
    return "ENCOUNTER." + snake(cls).upper()


def main() -> None:
    out, missing = {}, []
    for cls in encounter_classes():
        enc = parse_encounter(cls)
        if enc is None:
            missing.append(cls)
            continue
        out[key_for(cls)] = enc
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"encounters": out}, indent=1), encoding="utf-8")
    gone = [k for k, v in out.items() if any(m.get("missing") for m in v["monsters"])]
    print(f"{len(out)} encounters -> {OUT}")
    if missing:
        print(f"  {len(missing)} with no roster the parser could read: {missing}")
    if gone:
        print(f"  {len(gone)} with a monster missing art: {gone}")


if __name__ == "__main__":
    main()
