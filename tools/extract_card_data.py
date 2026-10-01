"""
Extracts card, relic and potion metadata from the STS2 C# assembly and
localization files. Writes:
  card_data.json   — card type/rarity/energy/vars/varsUpgraded/keywords/title/desc
  relic_data.json  — relic rarity/title/desc/vars/imagePath
  potion_data.json — potion rarity/title/desc/vars/imagePath

Run once after a game update to refresh data.
Requires clr (pythonnet): pip install pythonnet
Requires .NET 9 runtime (ships with game or install from microsoft.com).
"""
import json, sys
from pathlib import Path

from desc_tokens import clean_desc
from pck_root import find_pck_root

HERE = Path(__file__).parent

ROOT           = HERE.parent
DLL            = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2\data_sts2_windows_x86_64\sts2.dll")
PCK_ROOT       = find_pck_root()
LOC_CARDS      = PCK_ROOT / "localization" / "eng" / "cards.json"
LOC_RELICS     = PCK_ROOT / "localization" / "eng" / "relics.json"
LOC_POTIONS    = PCK_ROOT / "localization" / "eng" / "potions.json"
# Point at the downscaled WebP copies produced by tools/downscale_art.py,
# NOT at pck_recover_full/ — that directory is gitignored (3 GB), so recording
# paths into it left relic art broken for everyone who cloned the repo.
# Run downscale_art.py before this script.
RELIC_IMG_DIR  = ROOT / "relic_images"
PORTRAIT_DIR   = PCK_ROOT / "images" / "packed" / "card_portraits"
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

def potion_img_path(stem: str) -> str:
    """Repo-relative path to a potion's art, or "" if absent."""
    p = POTION_IMG_DIR / f"{stem}.webp"
    return p.relative_to(ROOT).as_posix() if p.exists() else ""


def relic_img_path(stem: str) -> str:
    """
    Returns a path relative to ROOT (e.g. "relic_images/akabeko.webp") rather than
    an absolute file:// URI, so relic_data.json isn't tied to one machine's layout
    — run.py resolves this to a file:// URI at build time.
    """
    for base in [RELIC_IMG_DIR, RELIC_IMG_DIR / "beta"]:
        p = base / f"{stem}.webp"
        if p.exists():
            return p.relative_to(ROOT).as_posix()
        # Character-variant fallback (e.g. yummy_cookie_ironclad.webp)
        for suffix in ["ironclad", "silent", "defect", "necro", "regent"]:
            p2 = base / f"{stem}_{suffix}.webp"
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

    # CardKeywordOrder.cs: the keywords the game prints on a card, in the
    # order they are stored here -- KEYWORDS_BEFORE above the description
    # (top line first), KEYWORDS_AFTER below it. The localized description
    # never contains them; CardModel builds the card text from both.
    KEYWORDS_BEFORE = ["Unplayable", "Innate", "Retain", "Sly", "Ethereal"]
    KEYWORDS_AFTER  = ["Exhaust", "Eternal"]

    def read_keywords(inst) -> list[str]:
        have = {str(k) for k in inst.Keywords}
        return [k for k in KEYWORDS_BEFORE + KEYWORDS_AFTER if k in have]

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

                keywords = read_keywords(inst)

                # Get upgraded star cost and keywords (an upgrade can add or
                # drop one, e.g. Innate on Afterimage+)
                stars_u = -1
                keywords_u = None
                try:
                    fresh2 = System.Activator.CreateInstance(t)
                    is_mutable_field.SetValue(fresh2, True)
                    upgrade_m.Invoke(fresh2, None)
                    stars_u = int(fresh2.CanonicalStarCost) if fresh2.CanonicalStarCost >= 0 else -1
                    keywords_u = read_keywords(fresh2)
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
                if keywords:
                    entry["keywords"] = keywords
                if keywords_u is not None and keywords_u != keywords:
                    entry["keywordsUpgraded"] = keywords_u
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

    # A few relics name an enchantment in their description. Their DynamicVars
    # look the enchantment up in ModelDb, which is empty outside the running
    # game, so reading them throws; supply the names from localization instead.
    _RELIC_VAR_FALLBACK = {
        "RELIC.PAELS_CLAW":   {"EnchantmentName": "Goopy"},
        "RELIC.PAELS_GROWTH": {"EnchantmentName": "Clone"},
        "RELIC.ROYAL_STAMP":  {"Enchantment": "Royally Approved"},
    }

    def relic_vars(inst, relic_id: str) -> dict:
        try:
            return read_vars(inst)
        except Exception:
            return _RELIC_VAR_FALLBACK.get(relic_id, {})

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
                        # Without these, every numeric token ({Heal}, {Block}, ...)
                        # renders as "?" — RelicModel exposes DynamicVars like potions.
                        "vars":      relic_vars(inst, relic_id),
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
          f"Re-run the GDRE recovery to pick them up:")
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
