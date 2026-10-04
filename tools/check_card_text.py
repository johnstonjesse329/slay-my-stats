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
from desc_tokens import _closing_brace, clean_desc  # noqa: E402

HANDLED = {"diff", "inverseDiff", "percentMore", "percentLess",
           "energyIcons", "starIcons", "plural", "show", "cond"}


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
    total, partial, clean = [], [], []
    for stem, text in sorted(raw.items()):
        if not text:
            continue
        converted = clean_desc(text)
        lost = [p for p in (dropped_prose(b) for b in blocks(text)) if p]
        if not converted.strip():
            # The baker composes a face description for cards whose branches are
            # recoverable (see dynamic_desc_text), so those are not a loss.
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
