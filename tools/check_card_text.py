"""Report cards whose description loses text to the token grammar.

tools/desc_tokens.py can express diff/inverseDiff/percentMore/percentLess,
energyIcons, starIcons, plural, show and cond. Anything else inside braces is
dropped on purpose, because it depends on runtime state the extractor never
records. Dropping it can cost a card part of its sentence, and nothing else in
the pipeline notices:

  ONE_TWO_PUNCH  read "This turn, your next played an extra time." until cond:
                 was handled -- a dropped conditional took the subject with it
  TANK           read "Take % more damage from enemies." -- a dropped formatter
                 took the number, leaving its "%" orphaned
  MAD_SCIENCE    had no description at all; every token in it was droppable

Two things are reported:

  TOTAL    the raw string converts to nothing, so the card bakes with no text
  PARTIAL  text survives, but a dropped construct carried prose with it

Cards whose dropped construct only ever holds an empty or "0" branch are listed
as CLEAN, since nothing is lost. Run after refreshing game data:

    python tools/check_card_text.py
    python tools/check_card_text.py --fail-on-loss     # for CI

Exit status is 0 unless --fail-on-loss is given.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bake_finished_cards as bake  # noqa: E402
from desc_tokens import (  # noqa: E402
    GAME_ONLY, IMPLEMENTED as desc_IMPLEMENTED, _closing_brace, clean_desc,
    formatters_used,
)

HANDLED = desc_IMPLEMENTED
GAME_FORMATTERS = {
    "HighlightDifferencesFormatter": "diff",
    "HighlightDifferencesInverseFormatter": "inverseDiff",
    "PercentMoreFormatter": "percentMore",
    "PercentLessFormatter": "percentLess",
    "EnergyIconsFormatter": "energyIcons",
    "StarIconsFormatter": "starIcons",
    "PluralLocalizationFormatter": "plural",
    "ShowIfUpgradedFormatter": "show",
    "ConditionalFormatter": "cond",
    "ChooseFormatter": None,        # decided by a runtime value
    "IsMatchFormatter": None,       # decided by a runtime comparison
    "LoadLocFormatter": None,       # pulls another localization string
    "AbsoluteValueFormatter": "abs",
    "ListFormatter": "list",
    "SubStringFormatter": "substring",
    "LocaleNumberFormatter": "localeNumber",
    "DefaultFormatter": None,       # plain {Var}; handled by the base token
}

# Localization the site actually renders text from.
CONSUMED = ["cards.json", "relics.json", "potions.json"]


def blocks(text):
    """(payload, index) for every {...} block, including nested ones."""
    i = 0
    while i < len(text):
        if text[i] == "{":
            end = _closing_brace(text, i)
            if end < 0:
                return
            payload = text[i + 1:end]
            yield payload
            yield from blocks(payload)
            i = end + 1
        else:
            i += 1


def dropped_prose(payload):
    """The words a dropped block would have printed, if any."""
    name, sep, rest = payload.partition(":")
    if not sep:
        return ""
    if rest.startswith("choose("):
        # Every branch, since which one prints depends on the runtime value.
        body = rest.split("):", 1)[1] if "):" in rest else ""
        return " ".join(filter(None, (clean_desc(b).strip() for b in body.split("|"))))
    # energyIcons(1) and friends carry their arguments in parens; compare on the
    # bare formatter name so a handled one isn't reported as a loss.
    if re.split(r"[(:]", rest, maxsplit=1)[0] in HANDLED:
        return ""
    # extract_incombat keeps an InCombat block's content, so nothing is lost.
    if name == "InCombat":
        return ""
    return clean_desc(rest)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fail-on-loss", action="store_true",
                    help="exit 1 when any card loses text (for CI)")
    args = ap.parse_args()

    raw = bake.load_raw_card_descriptions()

    # --- formatter coverage -------------------------------------------------
    # Every formatter the descriptions we render actually use, against the set
    # the grammar implements. A formatter we don't cover means text is being
    # dropped silently, which is how ONE_TWO_PUNCH and TANK shipped broken.
    covered = HANDLED
    used, unknown = {}, {}
    loc_dir = bake.LOC_CARDS.parent
    for fn in CONSUMED:
        path = loc_dir / fn
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            if not isinstance(value, str):
                continue
            for base in formatters_used(value):
                used[base] = used.get(base, 0) + 1
                if base not in covered:
                    unknown.setdefault(base, []).append("%s: %s" % (key, value[:70]))
    print("\nFORMATTERS used by the text we render (%d distinct)" % len(used))
    for name, n in sorted(used.items(), key=lambda kv: -kv[1]):
        print("  %-16s %4d uses  %s" % (name, n, "covered" if name in covered else "NOT COVERED"))
    print("\nNOT COVERED — text is being dropped silently (%d)" % len(unknown))
    for name, ex in sorted(unknown.items()):
        print("  %s (%d uses)" % (name, len(ex)))
        for e in ex[:3]:
            print("      %s" % e)
    print("\nGame formatters with no token of ours:")
    for cls, tok in sorted(GAME_FORMATTERS.items()):
        if tok is None:
            print("  %-38s %s" % (cls, "declared runtime-only"))
        elif tok not in HANDLED:
            print("  %-38s %s" % (cls, "NOT IMPLEMENTED (unused by our files)"))
        elif tok not in used:
            print("  %-38s %s" % (cls, "implemented, not used here"))

    total, partial, clean = [], [], []
    for stem, text in sorted(raw.items()):
        if not text:
            continue
        converted = clean_desc(text)
        lost = [p for p in (dropped_prose(b) for b in blocks(text)) if p]
        if not converted.strip():
            # The grammar cannot express the whole description -- only Mad Science,
            # whose type and rider come from the Tinker Time event. The baker puts the
            # template's own "???" branch on the face, which is exactly what the game
            # shows for an unrolled one, so this is not a blank card. This check uses
            # dynamic_desc_text() only to detect that shape, not to decide what is
            # drawn.
            if bake.dynamic_desc_text(text):
                clean.append(stem)
            else:
                total.append((stem, text))
        elif lost and "".join(lost).strip():
            partial.append((stem, converted, lost))
        else:
            clean.append(stem)

    def show(title, rows):
        print("\n%s (%d)" % (title, len(rows)))
        for stem, *rest in rows:
            print("  %s" % stem)
            for r in rest:
                print("      %s" % r)

    show("TOTAL — raw text converts to nothing, card bakes with no description", total)
    show("PARTIAL — a dropped construct carried prose that is now missing",
         [(s, "kept: %r" % c[:70], "lost: %s" % " / ".join(l)[:90]) for s, c, l in partial])
    print("\nCLEAN — dropped constructs held no prose, nothing lost (%d): %s"
          % (len(clean), ", ".join(clean)))

    lost_count = len(total) + len(partial)
    print("\n%d card(s) lose text." % lost_count)
    if args.fail_on_loss and lost_count:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
