"""
Merge the game's own card export into card_data.json.

card_data.json is what run.py / build_site.py / js/*.js consume: title, type,
rarity, pool, cost, keywords, vars and description. It used to be produced by
tools/extract_card_data.py reading the compiled game, which meant every value was
a re-derivation -- and some were wrong. Two examples it got wrong:

  * DynamicVar values were read as int, so Tank's DamageIncrease 1.5 and
    DamageDecrease 0.5 became 1 and 0, and its card read "Take 0% more damage"
    where the game says 50%.
  * Descriptions went through a hand-written port of the game's text grammar,
    which dropped constructs the game supports (energyIcons' "4 orbs becomes a
    numeral" rule, its literal argument form).

tools/ExportCards.cs now asks the game instead: it emits card_game_data.json with
the final rendered text and the real decimal values. This script folds that into
card_data.json so every existing consumer keeps its contract but gets game-truth
values. Run it in the recovery project first:

    $env:EXPORT_CARDS="1"
    Godot_v4.5.2-stable_mono_win64_console.exe --path . --quit-after 5400

then here:

    python tools/import_game_data.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME_DATA = ROOT / "card_game_data.json"
CARD_DATA = ROOT / "card_data.json"
VARIANT_DATA = ROOT / "card_variants.json"
RELIC_DATA = ROOT / "relic_data.json"
POTION_DATA = ROOT / "potion_data.json"
ENCHANT_DATA = ROOT / "enchantments_data.json"
ENCHANT_ART = ROOT / "enchantment_images"

# The game marks up text with its own BBCode. The site's description rendering
# understands {{token}} placeholders, not BBCode, and these are final strings with
# nothing left to substitute, so the markup is reduced to plain text here.
_ENERGY_ICON = re.compile(r"\[img\]res://[^\]]*?/(\w+)_energy_icon\.png\[/img\]")
_STAR_ICON = re.compile(r"\[img\]res://[^\]]*?/star_icon\.png\[/img\]")
_TAG = re.compile(r"\[/?[a-zA-Z_]+(=[^\]]*)?\]")

# A {Placeholder} in the game's template grammar.
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")

# A {{Placeholder}} in the site's grammar, which the page's own resolver renders.
_SITE_TOKEN = re.compile(r"\{\{(.*?)\}\}")

# The game's formatter names, mapped onto the kinds js/run-detail.js's
# substituteDescVars understands. `diff` -- and anything else that turns up --
# deliberately has no mapping: the resolver would render an unknown kind as "?",
# so a template using one is rejected in favour of the rendered text.
_FORMATTERS = {
    "energyIcons": "energy",
    "starIcons": "stars",
    "plural": "plural",
    "percentMore": "percentMore",
    "percentLess": "percentLess",
}


def to_plain_text(text: str) -> str:
    """BBCode -> plain text, for text the site will not substitute.

    Icons become the glyphs the existing tooltips use. Card fallback text goes
    through here; relic and potion text uses to_display_text() instead, which keeps
    an energy icon as something the page can draw as the real orb sprite.
    """
    if not text:
        return ""
    text = _ENERGY_ICON.sub("⚡", text)
    text = _STAR_ICON.sub("✦", text)
    text = _TAG.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# The site's resolver draws an energy/star icon from a variable's value, so an
# already-rendered description needs a variable for each icon it contains. These
# are value 1 -- the count is already baked into the text by the game, which is
# what makes this exact: for 4 energy the game writes the numeral "4" and one
# icon, and the page then draws one orb after the 4.
GLYPH_VARS = {"EnergyGlyph": 1, "StarGlyph": 1}
ENERGY_TOKEN = "{{EnergyGlyph:energy}}"
STAR_TOKEN = "{{StarGlyph:stars}}"

# The game marks the numbers it emphasises with [blue], and the site's resolver
# renders a bare {{Var}} as <b> (in HTML) or as plain text (in the plain-text mode
# an aria-label uses). Routing the value through a token keeps emphasis without
# putting markup in a string that may be read as text.
_EMPHASIS = re.compile(r"\[blue\](.*?)\[/blue\]", re.S)


def display_tokens(text: str) -> tuple[str, dict]:
    """An already-rendered description -> site token form.

    Returns (text, extra vars). Icons and emphasised numbers both become tokens
    the page's own resolver renders, so a description the game rendered keeps its
    real energy orb and its bold values.
    """
    extra: dict = {}
    counter = 0

    # Icons first: they can sit inside an emphasised run ("a [blue]4[img]..[/img]
    # [/blue]"), and a token inside a variable's value would never be expanded --
    # variables are substituted literally.
    text = text or ""
    if _ENERGY_ICON.search(text):
        text = _ENERGY_ICON.sub(ENERGY_TOKEN, text)
        extra.update({k: GLYPH_VARS[k] for k in ("EnergyGlyph",)})
    if _STAR_ICON.search(text):
        text = _STAR_ICON.sub(STAR_TOKEN, text)
        extra.update({k: GLYPH_VARS[k] for k in ("StarGlyph",)})

    def emphasis(match: re.Match) -> str:
        nonlocal counter
        inner = match.group(1)
        if "{{" in inner:
            # Already a token; wrapping it would bury the token in a value.
            return inner
        key = f"Emphasis{counter}"
        counter += 1
        extra[key] = inner
        return "{{%s}}" % key

    text = _EMPHASIS.sub(emphasis, text)
    return _TAG.sub("", text).strip(), extra


class _Unresolvable(Exception):
    """The site's resolver cannot render this template, so don't use it."""


def _resolve_site_template(template: str, variables: dict) -> str:
    """Render the site's {{...}} grammar the way js/run-detail.js does.

    Only used as an oracle: a template is used only when this reproduces the
    game's own rendered text, so a kind modelled slightly wrong here cannot make
    the site show something the game doesn't. Names are checked against the vars
    the model actually exposes -- several templates read a value the canonical
    model has no answer for, where the game's rendered text is the only correct
    source.
    """
    def swap(match: re.Match) -> str:
        name, _, rest = match.group(1).partition(":")
        if name not in variables:
            raise _Unresolvable(name)
        value = variables[name]
        if not rest:
            return str(value)
        kind, _, arg = rest.partition(":")
        if kind == "energy":
            return " {energy} " * int(value)
        if kind == "stars":
            return " {star} " * int(value)
        if kind == "plural":
            one, _, many = arg.partition("|")
            return one if float(value) == 1 else (many or one)
        if kind == "percentMore":
            return str(round((float(value) - 1) * 100))
        if kind == "percentLess":
            return str(round((1 - float(value)) * 100))
        raise _Unresolvable(kind)

    return re.sub(r"\s+", " ", _TAG.sub("", _SITE_TOKEN.sub(swap, template))).strip()


def to_display_text(record: dict) -> tuple[str, dict]:
    """The text the site should show for a relic or potion.

    Prefers the site's own template form, because it draws the real per-pool
    energy orb and substitutes the game's vars at render time -- but only where it
    provably reproduces what the game itself renders. Otherwise the game's
    rendered text is used, which is correct by definition. Either way the extra
    vars it needs ride on the record.
    """
    rendered = record.get("Description") or ""
    variables = {k: float(v) for k, v in (record.get("Vars") or {}).items()}
    template = to_site_template(record.get("RawText") or "")
    if template:
        try:
            if _resolve_site_template(template, variables) == _normalize(rendered):
                return template, {}
        except (_Unresolvable, TypeError, ValueError, ZeroDivisionError):
            pass
    return display_tokens(rendered)


def _normalize(text: str) -> str:
    """Collapse the two representations to something comparable: icon images and
    the placeholder glyphs both become markers, markup goes away."""
    text = _ENERGY_ICON.sub(" {energy} ", text or "")
    text = _STAR_ICON.sub(" {star} ", text)
    text = _TAG.sub("", text)
    text = text.replace("\u26a1", " {energy} ").replace("\u2726", " {star} ")
    return re.sub(r"\s+", " ", text).strip()


def to_site_template(raw: str) -> str | None:
    """The game's template grammar -> the site's {{...}} one, or None if the text
    uses a formatter the site's resolver cannot render.

    Worth doing rather than shipping the rendered text: the game flattens an
    "gain 2 energy" icon to a lightning glyph, while the site's {{Energy:energy}}
    draws the real per-pool energy orb. Returning the template also keeps the
    values substituted at render time from the game's own vars.
    """
    if not raw:
        return None
    rejected = False

    def swap(match: re.Match) -> str:
        nonlocal rejected
        name, _, rest = match.group(1).partition(":")
        if not rest:
            return "{{%s}}" % name
        kind, _, arg = rest.partition(":")
        mapped = _FORMATTERS.get(kind.split("(")[0])
        if mapped is None:
            rejected = True
            return match.group(0)
        return "{{%s:%s%s}}" % (name, mapped, f":{arg}" if arg else "")

    text = _PLACEHOLDER.sub(swap, raw)
    if rejected:
        return None
    return _TAG.sub("", text).strip()


def merge(card: dict, game: dict, character_pools: set[str]) -> list[str]:
    """Copy one game record onto one card_data entry. Returns the fields changed."""
    changed = []
    mapping = (
        ("title", "Title"),
        ("type", "Type"),
        ("rarity", "Rarity"),
    )
    for ours, theirs in mapping:
        if card.get(ours) != game[theirs]:
            changed.append(ours)
            card[ours] = game[theirs]

    # The site's convention is mixed: a character pool is upper-case because it is
    # compared against a run's "char" field (run.py emits "REGENT"), while every
    # other pool is matched against lower-case literals such as "colorless".
    pool = game["Pool"]
    if pool in character_pools:
        pool = pool.upper()
    if card.get("pool") != pool:
        changed.append("pool")
        card["pool"] = pool

    for ours, theirs in (("energy", "Cost"), ("stars", "Stars")):
        if card.get(ours) != game[theirs]:
            changed.append(ours)
            card[ours] = game[theirs]

    # How far a card can be upgraded at all. 0 means it has no upgraded form, so no
    # *_UP face should exist for it -- the old extractor assumed every card had one
    # and left 39 phantom files behind (curses and statuses cannot be upgraded).
    if card.get("maxUpgradeLevel") != game["MaxUpgradeLevel"]:
        card["maxUpgradeLevel"] = game["MaxUpgradeLevel"]
        changed.append("maxUpgradeLevel")

    if bool(card.get("costsX")) != bool(game["CostsX"]):
        card["costsX"] = game["CostsX"]
        changed.append("costsX")
    if bool(card.get("starsX")) != bool(game["StarsX"]):
        card["starsX"] = game["StarsX"]
        changed.append("starsX")

    # Real decimals, unlike the old int() read.
    vars_now = {k: float(v) for k, v in (game.get("Vars") or {}).items()}
    if {k: float(v) for k, v in (card.get("vars") or {}).items()} != vars_now:
        card["vars"] = vars_now
        changed.append("vars")

    vars_up = {k: float(v) for k, v in (game.get("VarsUpgraded") or {}).items()}
    if vars_up:
        if {k: float(v) for k, v in (card.get("varsUpgraded") or {}).items()} != vars_up:
            card["varsUpgraded"] = vars_up
            changed.append("varsUpgraded")
    elif card.pop("varsUpgraded", None) is not None:
        changed.append("varsUpgraded(removed)")

    if list(card.get("keywords") or []) != list(game.get("Keywords") or []):
        card["keywords"] = list(game.get("Keywords") or [])
        changed.append("keywords")

    kw_up = list(game.get("KeywordsUpgraded") or [])
    if kw_up and list(card.get("keywordsUpgraded") or []) != kw_up:
        card["keywordsUpgraded"] = kw_up
        changed.append("keywordsUpgraded")

    desc = to_plain_text(game["Text"])
    if card.get("desc") != desc:
        card["desc"] = desc
        changed.append("desc")

    desc_up = to_plain_text(game["TextUpgraded"] or "")
    if desc_up and card.get("descUpgraded") != desc_up:
        card["descUpgraded"] = desc_up
        changed.append("descUpgraded")

    # The game hides a couple of cards from its own library because they have no
    # canonical form (Mad Science before Tinker Time rolls it, DeprecatedCard).
    if card.get("showInCardLibrary") != game["ShowInCardLibrary"]:
        card["showInCardLibrary"] = game["ShowInCardLibrary"]
        changed.append("showInCardLibrary")

    return changed


def _vars_match(existing: dict, game_vars: dict) -> bool:
    """Compare vars numerically, but treat a non-numeric value (the old extractor
    left strings like 'Goopy' in relic vars) as a mismatch so the game wins."""
    if set(existing) != set(game_vars):
        return False
    for key, value in game_vars.items():
        try:
            if float(existing[key]) != float(value):
                return False
        except (TypeError, ValueError):
            return False
    return True


def merge_relics_or_potions(data: dict, records: list[dict], prefix: str) -> tuple[list[str], dict[str, int]]:
    """Relics and potions, described by the game.

    These keep their `{{token}}` placeholders *resolved*, unlike card text: the
    game's own desc for a relic is its final text, and the site's stored run data
    carries no relic/potion props (finalRelics is [{id}]), so nothing per-run
    needs to substitute into it. Their dynamic vars ride along so a consumer that
    does substitute still gets the game's values rather than a re-derived guess.
    """
    missing, tally = [], {}
    for game in records:
        key = f"{prefix}.{game['Entry']}"
        meta = data.get(key)
        if meta is None:
            missing.append(key)
            continue
        # The site's own template where it provably reproduces the game's text
        # (so the real energy orb still draws), the game's rendered text otherwise
        # -- which is the only correct source for the templates that read a value
        # the canonical model does not expose, use a nested accessor, or name an
        # enchantment. See to_display_text().
        desc, glyph_vars = to_display_text(game)
        for ours, value in (("title", game["Title"]), ("rarity", game["Rarity"]), ("desc", desc)):
            if meta.get(ours) != value:
                meta[ours] = value
                tally[ours] = tally.get(ours, 0) + 1
        # imagePath is the site's own extracted art -- the game's IconPath points
        # inside its .pck, which never ships.
        vars_now = {k: float(v) for k, v in (game.get("Vars") or {}).items()}
        # A rendered description spells an icon as an image and an emphasised
        # number as [blue]; the page draws both from a variable instead.
        vars_now.update(glyph_vars)
        if not _vars_match(meta.get("vars") or {}, vars_now):
            meta["vars"] = vars_now
            tally["vars"] = tally.get("vars", 0) + 1
    return missing, tally


def build_enchantments(game_file: dict) -> dict:
    """Enchantments as the save stores them: {amount: n, id: "ENCHANTMENT.X"} on a
    card, so the keys here are ENCHANTMENT.<Entry> to match what a run records.

    Text is per amount because a canonical enchantment has Amount 0 and its
    template reads {Amount}, so formatting it unattached says "Gain 0 Block".
    Where the game itself reads a value off the enchanted card ("Gain {Block}
    Block") there is no honest answer without one, so no text is carried and the
    UI should show the title and amount only.
    """
    out = {}
    for game in game_file.get("Enchantments") or []:
        icon = ENCHANT_ART / f"{game['Entry'].lower()}.png"
        record = {
            "title": game["Title"],
            "showAmount": game["ShowAmount"],
            "hasExtraCardText": game["HasExtraCardText"],
            "cardDependent": game["CardDependent"],
            "imagePath": f"enchantment_images/{icon.name}" if icon.exists() else "",
        }
        by_amount = {k: to_plain_text(v) for k, v in (game.get("Descriptions") or {}).items()}
        if by_amount:
            record["desc"] = by_amount.get("1", "")
            record["descByAmount"] = by_amount
        out["ENCHANTMENT." + game["Entry"]] = record
    return out


def main() -> int:
    for path, what in ((GAME_DATA, "card_game_data.json (export it from the game first)"),
                       (CARD_DATA, "card_data.json")):
        if not path.exists():
            print(f"ERROR: {path.name} not found - {what}", file=sys.stderr)
            return 1

    game_file = json.loads(GAME_DATA.read_text(encoding="utf-8"))
    game = {c["Entry"]: c for c in game_file["Cards"]}
    character_pools = set(game_file.get("CharacterPools") or [])
    cards = json.loads(CARD_DATA.read_text(encoding="utf-8"))

    tally: dict[str, int] = {}
    missing = []
    for entry, game_card in game.items():
        card = cards.get("CARD." + entry)
        if card is None:
            missing.append(entry)
            continue
        for field in merge(card, game_card, character_pools):
            tally[field] = tally.get(field, 0) + 1

    CARD_DATA.write_text(json.dumps(cards, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Cards whose rendered form depends on state saved with the card. The site needs
    # these to label a deck entry by what the card actually is: the canonical model
    # for Mad Science says type None, so without this a deck files it under "None"
    # even though the face it is showing says Power.
    variants = {
        v["Key"]: {
            "type":  v["Type"],
            "rider": v["Rider"],
            "desc":  to_plain_text(v["Text"]),
            # The portrait the game draws for this roll. Mad Science's three
            # Tinker Time groups each have their own art, so the tooltip's
            # fallback path can show the roll rather than always the attack one.
            **({"portrait": v["Portrait"]} if v.get("Portrait") else {}),
            **({"descUpgraded": to_plain_text(v["TextUpgraded"])} if v.get("TextUpgraded") else {}),
        }
        for v in (game_file.get("Variants") or [])
    }
    VARIANT_DATA.write_text(json.dumps(variants, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"merged {len(game) - len(missing)} of {len(game)} game cards into {CARD_DATA.name}")
    for field, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {field:28} {n}")
    if missing:
        print(f"\nin the game but not in card_data.json: {len(missing)}  {missing[:10]}")

    for path, section, prefix in ((RELIC_DATA, "Relics", "RELIC"),
                                  (POTION_DATA, "Potions", "POTION")):
        if not path.exists():
            print(f"\nskipping {path.name}: not present")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        gone, relic_tally = merge_relics_or_potions(data, game_file.get(section) or [], prefix)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nmerged {len(game_file.get(section) or []) - len(gone)} "
              f"{section.lower()} into {path.name}")
        for field, n in sorted(relic_tally.items(), key=lambda kv: -kv[1]):
            print(f"  {field:28} {n}")
        if gone:
            print(f"  in the game but not in {path.name}: {len(gone)}  {gone[:5]}")

    enchantments = build_enchantments(game_file)
    ENCHANT_DATA.write_text(json.dumps(enchantments, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    desc = sum(1 for e in enchantments.values() if e.get("descByAmount"))
    print(f"\nwrote {ENCHANT_DATA.name}: {len(enchantments)} enchantments, "
          f"{desc} with per-amount text, "
          f"{sum(1 for e in enchantments.values() if not e['imagePath'])} without art")
    print(f"\nwrote {VARIANT_DATA.name}: {len(variants)} per-instance variants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
