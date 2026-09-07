"""
Extracts card, relic and potion metadata from the STS2 C# assembly and
localization files. Writes:
  card_data.json   — card type/rarity/energy/vars/varsUpgraded/title/desc
  relic_data.json  — relic rarity/title/desc/imagePath
  potion_data.json — potion rarity/title/desc/vars/imagePath

Run once after a game update to refresh data.
Requires clr (pythonnet): pip install pythonnet
Requires .NET 9 runtime (ships with game or install from microsoft.com).
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).parent

ROOT           = HERE.parent
DLL            = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2\data_sts2_windows_x86_64\sts2.dll")
LOC_CARDS      = ROOT / "pck_recover_full" / "localization" / "eng" / "cards.json"
LOC_RELICS     = ROOT / "pck_recover_full" / "localization" / "eng" / "relics.json"
LOC_POTIONS    = ROOT / "pck_recover_full" / "localization" / "eng" / "potions.json"
# Point at the committed, downscaled copies produced by tools/downscale_art.py,
# NOT at pck_recover_full/ — that directory is gitignored (3 GB), so recording
# paths into it left relic art broken for everyone who cloned the repo.
# Run downscale_art.py before this script.
RELIC_IMG_DIR  = ROOT / "relic_images"
PORTRAIT_DIR   = ROOT / "pck_recover_full" / "images" / "packed" / "card_portraits"
CARD_OUT       = ROOT / "card_data.json"
RELIC_OUT      = ROOT / "relic_data.json"
POTION_OUT     = ROOT / "potion_data.json"
POTION_IMG_DIR = ROOT / "potion_images"

# Build card_id → character mapping from portrait directory structure.
# Each subfolder name is the character (or "colorless", "curse", etc.).
# Portrait stem → CARD.<STEM_UPPERCASE>.
_CHAR_FOLDERS = {"ironclad", "silent", "defect", "necrobinder", "regent"}
_POOL_MAP: dict[str, str] = {}  # card_id → pool name
if PORTRAIT_DIR.exists():
    for folder in PORTRAIT_DIR.iterdir():
        if not folder.is_dir():
            continue
        pool = folder.name.lower()
        for sub in [folder, folder / "beta"]:
            if not sub.exists():
                continue
            for png in sub.glob("*.png"):
                card_id = "CARD." + png.stem.upper()
                char_pool = pool.upper() if pool in _CHAR_FOLDERS else pool
                _POOL_MAP[card_id] = char_pool

# ── 1. Load localization ──────────────────────────────────────────────────────
def load_loc(path: Path) -> dict[str, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for key, val in raw.items():
        stem, _, field = key.partition(".")
        out.setdefault(stem, {})[field] = val
    return out

loc_cards  = load_loc(LOC_CARDS)
loc_relics = load_loc(LOC_RELICS)
loc_potions = load_loc(LOC_POTIONS)

def _strip_braces(text: str) -> str:
    """Remove all {...} template blocks, handling nesting."""
    result = []
    depth = 0
    for ch in text:
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        elif depth == 0:
            result.append(ch)
    return "".join(result)

_PH = "\x00"  # placeholder char that survives brace-stripping

def _extract_incombat(text: str) -> str:
    """Replace {InCombat:\n(content)|} with just the content (always show it in our UI)."""
    # Match the whole outer block manually since content has nested braces
    out = []
    i = 0
    while i < len(text):
        if text[i:].startswith("{InCombat:"):
            # find matching closing }
            depth = 0
            j = i
            while j < len(text):
                if text[j] == '{': depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            block = text[i+1:j]  # contents between outer { }
            # block looks like: InCombat:\n(Hits {Var:diff()} text|)
            # strip "InCombat:" prefix and extract content before the trailing "|"
            inner = block[len("InCombat:"):]
            # drop trailing "|" (the else-branch is always empty)
            if inner.endswith("|"):
                inner = inner[:-1]
            # strip wrapping \n( ... ) if present
            inner = inner.strip()
            if inner.startswith("(") and inner.endswith(")"):
                inner = inner[1:-1]
            # Replace {Var:plural:singular|plural} → just the singular word (drop the var wrapper)
            inner = re.sub(r"\{[A-Za-z_]+:plural:([^|{]+)\|[^}]+\}", r"\1", inner)
            out.append("\n(" + inner + ")")
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)

def clean_desc(text: str) -> str:
    """Strip Godot BBCode/template tags; replace {VarName:diff()} with {{VarName}} tokens."""
    if not text:
        return ""
    # Expand {InCombat:...|} — keep the "in combat" content since we always want it shown
    text = _extract_incombat(text)
    # Protect value tokens before brace-stripping:
    #   {VarName:diff()}       → {{VarName}}    (numeric value)
    #   {VarName:energyIcons()} → {{VarName:energy}}  (render as N energy icons)
    #   {VarName:starIcons()}  → {{VarName:stars}}   (render as N star icons)
    text = re.sub(r"\{([A-Za-z_]+):diff\(\)\}", lambda m: f"{_PH}{m.group(1)}{_PH}", text)
    text = re.sub(r"\{([A-Za-z_]+):inverseDiff\(\)\}", lambda m: f"{_PH}{m.group(1)}{_PH}", text)
    text = re.sub(r"\{([A-Za-z_]+):energyIcons\(\d*\)\}", lambda m: f"{_PH}{m.group(1)}:energy{_PH}", text)
    text = re.sub(r"\{([A-Za-z_]+):starIcons\(\)\}", lambda m: f"{_PH}{m.group(1)}:stars{_PH}", text)
    # Word-form and conditional tokens. These MUST survive to render time rather
    # than being resolved here: which branch applies depends on the variable's
    # value, and a card's base and upgraded forms share one desc string with
    # different vars ({Combats:plural:combat|combats} is "combat" at 1 and
    # "combats" at 5). Dropping them is what left descriptions reading
    # "Removed from your Deck after 5 ." — 55 cards had visible artifacts.
    text = re.sub(r"\{([A-Za-z_]+):plural:([^{}|]*)\|([^{}]*)\}",
                  lambda m: f"{_PH}{m.group(1)}:plural:{m.group(2)}|{m.group(3)}{_PH}", text)
    text = re.sub(r"\{([A-Za-z_]+):show:([^{}|]*)(?:\|([^{}]*))?\}",
                  lambda m: f"{_PH}{m.group(1)}:show:{m.group(2)}|{m.group(3) or ''}{_PH}", text)
    # Bare {VarName} — a plain value, or a standalone icon like {singleStarIcon}.
    text = re.sub(r"\{singleStarIcon\}", f"{_PH}singleStarIcon:stars{_PH}", text)
    text = re.sub(r"\{([A-Za-z_]+)\}", lambda m: f"{_PH}{m.group(1)}{_PH}", text)
    # Strip all remaining {...} blocks (choose(), nested conditionals)
    text = _strip_braces(text)
    # Restore placeholders. The payload can now carry ':' and '|' and arbitrary
    # branch text, so match "anything between two placeholder chars" rather than
    # enumerating the token shapes.
    text = re.sub(re.escape(_PH) + r"([^" + re.escape(_PH) + r"]+)" + re.escape(_PH), r"{{\1}}", text)
    # Strip [gold]...[/gold] BBCode tags — keep inner text
    text = re.sub(r"\[/?[a-zA-Z_]+\]", "", text)
    # Collapse whitespace artifacts
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()

def potion_img_path(stem: str) -> str:
    """Repo-relative path to a potion's art, or "" if absent."""
    p = POTION_IMG_DIR / f"{stem}.png"
    return p.relative_to(ROOT).as_posix() if p.exists() else ""


def relic_img_path(stem: str) -> str:
    """
    Returns a path relative to ROOT (e.g. "pck_recover_full/images/relics/akabeko.png")
    rather than an absolute file:// URI, so relic_data.json isn't tied to one machine's
    layout — run.py resolves this to a file:// URI at build time.
    """
    for base in [RELIC_IMG_DIR, RELIC_IMG_DIR / "beta"]:
        p = base / f"{stem}.png"
        if p.exists():
            return p.relative_to(ROOT).as_posix()
        # Character-variant fallback (e.g. yummy_cookie_ironclad.png)
        for suffix in ["ironclad", "silent", "defect", "necro", "regent"]:
            p2 = base / f"{stem}_{suffix}.png"
            if p2.exists():
                return p2.relative_to(ROOT).as_posix()
    return ""

# ── 2. Load from C# assembly via pythonnet ───────────────────────────────────
try:
    import pythonnet as _pn  # type: ignore
    _pn.load("coreclr")
    import clr  # type: ignore
    clr.AddReference(str(DLL))
    import System  # type: ignore

    asm = System.Reflection.Assembly.LoadFrom(str(DLL))

    _BF = (System.Reflection.BindingFlags.Instance
           | System.Reflection.BindingFlags.NonPublic
           | System.Reflection.BindingFlags.Public)

    card_model_type    = asm.GetType("MegaCrit.Sts2.Core.Models.CardModel")
    abstract_model_type = asm.GetType("MegaCrit.Sts2.Core.Models.AbstractModel")

    type_prop        = card_model_type.GetProperty("Type")
    rarity_prop      = card_model_type.GetProperty("Rarity")
    energy_cost_prop = card_model_type.GetProperty("EnergyCost")
    dyn_vars_prop    = card_model_type.GetProperty("DynamicVars")
    upgrade_m        = card_model_type.GetMethod("UpgradeInternal", _BF)
    is_mutable_field = abstract_model_type.GetField("<IsMutable>k__BackingField", _BF)

    energy_cost_type = (asm.GetType("MegaCrit.Sts2.Core.Entities.Cards.CardEnergyCost")
                        or asm.GetType("MegaCrit.Sts2.Core.Models.CardEnergyCost"))
    canonical_prop   = energy_cost_type.GetProperty("Canonical") if energy_cost_type else None
    costs_x_prop     = energy_cost_type.GetProperty("CostsX")    if energy_cost_type else None
    # _base field is the true post-upgrade cost; Canonical caches the pre-upgrade value
    ec_base_field    = energy_cost_type.GetField("_base", _BF)    if energy_cost_type else None

    def read_energy(inst) -> int:
        ec = energy_cost_prop.GetValue(inst)
        if ec is None: return -1
        # Prefer _base (reflects upgrades) over Canonical (stale cached value)
        if ec_base_field:
            return int(ec_base_field.GetValue(ec))
        return int(canonical_prop.GetValue(ec)) if canonical_prop else -1

    def read_vars(inst) -> dict[str, int]:
        # Resolve DynamicVars from the instance's own type rather than closing
        # over CardModel's PropertyInfo — potions expose the same property, and
        # a card-bound PropertyInfo throws when handed a PotionModel.
        prop = inst.GetType().GetProperty("DynamicVars") or dyn_vars_prop
        if prop is None:
            return {}
        dvset = prop.GetValue(inst)
        if dvset is None:
            return {}
        dvset_type = dvset.GetType()
        item_prop  = dvset_type.GetProperty("Item")
        keys_prop  = dvset_type.GetProperty("Keys")
        if not item_prop or not keys_prop:
            return {}
        result = {}
        for k in keys_prop.GetValue(dvset):
            try:
                dv = item_prop.GetValue(dvset, System.Array[System.Object]([str(k)]))
                result[str(k)] = int(dv.IntValue)
            except Exception:
                pass
        return result

    def get_upgraded(inst):
        """Force-upgrade a fresh canonical instance; return (vars, energy) or (None, None)."""
        if not upgrade_m or not is_mutable_field:
            return None, None
        try:
            fresh = System.Activator.CreateInstance(inst.GetType())
            is_mutable_field.SetValue(fresh, True)
            upgrade_m.Invoke(fresh, None)
            return read_vars(fresh), read_energy(fresh)
        except Exception:
            return None, None

    # ── Cards ────────────────────────────────────────────────────────────────
    card_results: dict = {}
    for t in asm.GetTypes():
        if (t.Namespace == "MegaCrit.Sts2.Core.Models.Cards"
                and not t.IsAbstract
                and card_model_type.IsAssignableFrom(t)
                and t.GetConstructor(System.Type.EmptyTypes) is not None):
            try:
                inst    = System.Activator.CreateInstance(t)
                card_id = str(inst.Id)
                stem    = card_id.replace("CARD.", "")

                ec      = energy_cost_prop.GetValue(inst)
                energy  = read_energy(inst)
                costs_x = bool(costs_x_prop.GetValue(ec))  if (ec and costs_x_prop)  else False
                stars   = int(inst.CanonicalStarCost) if inst.CanonicalStarCost >= 0 else -1
                stars_x = bool(inst.HasStarCostX)

                base_vars = read_vars(inst)
                upgraded_vars, energy_u = get_upgraded(inst)

                # Get upgraded star cost
                stars_u = -1
                try:
                    fresh2 = System.Activator.CreateInstance(t)
                    is_mutable_field.SetValue(fresh2, True)
                    upgrade_m.Invoke(fresh2, None)
                    stars_u = int(fresh2.CanonicalStarCost) if fresh2.CanonicalStarCost >= 0 else -1
                except Exception:
                    pass

                vars_changed   = upgraded_vars is not None and upgraded_vars != base_vars
                energy_changed = energy_u is not None and energy_u != energy
                stars_changed  = stars_u >= 0 and stars_u != stars

                entry: dict = {
                    "type":   str(type_prop.GetValue(inst)),
                    "rarity": str(rarity_prop.GetValue(inst)),
                    "energy": energy,
                    "costsX": costs_x,
                    "stars":  stars,
                    "starsX": stars_x,
                    "pool":   _POOL_MAP.get(card_id, "other"),
                    "title":  loc_cards.get(stem, {}).get("title", ""),
                    "desc":   clean_desc(loc_cards.get(stem, {}).get("description", "")),
                    "vars":   base_vars,
                }
                if vars_changed:
                    entry["varsUpgraded"] = upgraded_vars
                if energy_changed:
                    entry["energyUpgraded"] = energy_u
                if stars_changed:
                    entry["starsUpgraded"] = stars_u
                card_results[card_id] = entry
            except Exception:
                pass

    # ── Relics ───────────────────────────────────────────────────────────────
    relic_model_type  = asm.GetType("MegaCrit.Sts2.Core.Models.RelicModel")
    relic_rarity_prop = relic_model_type.GetProperty("Rarity") if relic_model_type else None

    relic_results: dict = {}
    if relic_model_type:
        for t in asm.GetTypes():
            if (t.Namespace and "Relics" in t.Namespace
                    and not t.IsAbstract
                    and relic_model_type.IsAssignableFrom(t)
                    and t.GetConstructor(System.Type.EmptyTypes) is not None):
                try:
                    inst      = System.Activator.CreateInstance(t)
                    relic_id  = str(inst.Id)
                    stem      = relic_id.replace("RELIC.", "").lower()
                    loc_stem  = relic_id.replace("RELIC.", "")

                    rarity = str(relic_rarity_prop.GetValue(inst)) if relic_rarity_prop else ""

                    relic_results[relic_id] = {
                        "rarity":    rarity,
                        "title":     loc_relics.get(loc_stem, {}).get("title", ""),
                        "desc":      clean_desc(loc_relics.get(loc_stem, {}).get("description", "")),
                        "imagePath": relic_img_path(stem),
                    }
                except Exception:
                    pass

    # ── Potions ──────────────────────────────────────────────────────────────
    # Same shape as relics, but PotionModel also exposes DynamicVars, so the
    # numeric tokens in a potion's description ({HealPercent}, {DamageDecrease})
    # resolve exactly like a card's rather than rendering as "?".
    potion_model_type  = asm.GetType("MegaCrit.Sts2.Core.Models.PotionModel")
    potion_rarity_prop = potion_model_type.GetProperty("Rarity") if potion_model_type else None

    potion_results: dict = {}
    if potion_model_type:
        for t in asm.GetTypes():
            if (t.Namespace and "Potion" in t.Namespace
                    and not t.IsAbstract
                    and potion_model_type.IsAssignableFrom(t)
                    and t.GetConstructor(System.Type.EmptyTypes) is not None):
                try:
                    inst      = System.Activator.CreateInstance(t)
                    potion_id = str(inst.Id)
                    stem      = potion_id.replace("POTION.", "").lower()
                    loc_stem  = potion_id.replace("POTION.", "")

                    potion_results[potion_id] = {
                        "rarity":    str(potion_rarity_prop.GetValue(inst)) if potion_rarity_prop else "",
                        "title":     loc_potions.get(loc_stem, {}).get("title", ""),
                        "desc":      clean_desc(loc_potions.get(loc_stem, {}).get("description", "")),
                        "vars":      read_vars(inst),
                        "imagePath": potion_img_path(stem),
                    }
                except Exception:
                    pass

except ImportError:
    print("pythonnet not found; using card_types.json for type data", file=sys.stderr)
    types_raw = json.loads((HERE / "card_types.json").read_text())
    card_results = {}
    for card_id, card_type in types_raw.items():
        stem = card_id.replace("CARD.", "")
        card_results[card_id] = {
            "type":   card_type,
            "rarity": "",
            "energy": -1,
            "costsX": False,
            "title":  loc_cards.get(stem, {}).get("title", ""),
            "desc":   clean_desc(loc_cards.get(stem, {}).get("description", "")),
            "vars":   {},
        }
    relic_results = {}
    potion_results = {}

# The DLL and pck_recover_full/ are refreshed separately, so the DLL can know
# about cards the extracted localization doesn't yet (the game updates on the
# beta branch far more often than anyone re-runs the ~10 min GDRE recovery).
# Emitting those anyway would ship entries with an empty title and desc, which
# renders *worse* than omitting them: dashboard.js falls back to
# fmtCardLabel(id), turning CARD.BLADE_SYMPHONY into "Blade Symphony", whereas
# a present-but-blank title renders as nothing at all. So drop them, and say
# so — a non-empty list here means the extraction is stale.
_untitled = [cid for cid, meta in card_results.items() if not (meta.get("title") or "").strip()]
for cid in _untitled:
    del card_results[cid]

CARD_OUT.write_text(json.dumps(card_results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {len(card_results)} cards to {CARD_OUT}")
if _untitled:
    print(f"  ! skipped {len(_untitled)} card(s) with no localized title — "
          f"{LOC_CARDS.parent.parent.parent.name}/ is older than the DLL. "
          f"Re-run the GDRE recovery (CLAUDE.md step 1) to pick them up:")
    print("    " + ", ".join(sorted(_untitled)))

if relic_results:
    # Same staleness guard as cards above.
    _untitled_relics = [rid for rid, meta in relic_results.items()
                        if not (meta.get("title") or "").strip()]
    for rid in _untitled_relics:
        del relic_results[rid]

    RELIC_OUT.write_text(json.dumps(relic_results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(relic_results)} relics to {RELIC_OUT}")
    if _untitled_relics:
        print(f"  ! skipped {len(_untitled_relics)} relic(s) with no localized title: "
              + ", ".join(sorted(_untitled_relics)))

if potion_results:
    # Same staleness guard as cards and relics.
    _untitled_potions = [pid for pid, meta in potion_results.items()
                         if not (meta.get("title") or "").strip()]
    for pid in _untitled_potions:
        del potion_results[pid]

    POTION_OUT.write_text(json.dumps(potion_results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(potion_results)} potions to {POTION_OUT}")
    if _untitled_potions:
        print(f"  ! skipped {len(_untitled_potions)} potion(s) with no localized title: "
              + ", ".join(sorted(_untitled_potions)))
