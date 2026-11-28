"""
tools/derive_shop_prices.py -- what the shop asks for a card (shop_prices.json).

The saves record no shop price. player_stats carries one gold_spent figure for a
whole visit, covering cards, card removals, relics and potions together, and
card_choices has no price field. But a visit that bought exactly one card and
nothing else -- no removal, relic or potion, and no gold gained there -- still
gives that card's price: the gold the previous floor ended with, minus the gold
the run had after the shop.

A shop draws the price from a small range around the card's base price (new
shops, new roll), so the median over those single-card visits is what the card
costs. Membership Card (50% off) and The Courier (20% off) land as further
clusters below it; those samples are dropped before the median, and the site
reads their percentages from the same table so a shelf is priced at what the
shop charged that run. A card seen too rarely takes its rarity's median instead.

The result is checked in, since the site can only price a shelf card that some
player's recorded visit already priced:

    python tools/derive_shop_prices.py [--users local_data/users] [--write]

    { "cards": { "CARD.POMMEL_STRIKE": {"price": 50, "n": 37} },
      "rarity": {"Common": 50, "Uncommon": 76, "Rare": 155},
      "discountRelics": {"RELIC.MEMBERSHIP_CARD": 50, "RELIC.THE_COURIER": 20} }
"""
import argparse
import gzip
import json
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "shop_prices.json"
CARD_DATA = ROOT / "card_data.json"
RELIC_DATA = ROOT / "relic_data.json"


def default_users() -> Path:
    """The profile root to read. A worktree has no local_data/ of its own (it is
    gitignored), so a run there reads the main checkout's."""
    own = ROOT / "local_data" / "users"
    if own.exists():
        return own
    common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute",
                             "--git-common-dir"], capture_output=True, text=True)
    if common.returncode == 0:
        main = Path(common.stdout.strip()).parent / "local_data" / "users"
        if main.exists():
            return main
    return own


# Relics that cut what the shop charges. The percentage is the relic's own
# `Discount` var in relic_data.json, so a patch that changes it changes the table.
DISCOUNT_RELICS = ["RELIC.MEMBERSHIP_CARD", "RELIC.THE_COURIER"]
# The shop rolls each price within about 10% of the card's base, so a card's
# cheapest full-price visit is ~0.82 of its dearest one, while a 20%-off visit
# lands at ~0.73. Anything under this is a discounted visit, not the price.
DISCOUNT_FLOOR = 0.82
# Fewest clean samples a card needs before its own median is used.
MIN_SAMPLES = 3
# A card whose every sample sits this far under its rarity's median was only ever
# seen discounted; it takes the rarity median rather than a price nobody paid.
DISCOUNTED_ONLY = 0.75


def discount_relics(path: Path = RELIC_DATA) -> dict:
    """{ "RELIC.X": 50 } for the relics that discount the shop, as a percentage."""
    if not path.exists():
        return {}
    relics = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for rid in DISCOUNT_RELICS:
        pct = ((relics.get(rid) or {}).get("vars") or {}).get("Discount")
        if pct:
            out[rid] = int(round(float(pct)))
    return out


def samples_by_card(users: Path) -> dict:
    """{ "CARD.X": [price, ...] } from visits that bought exactly that one card."""
    prices = defaultdict(list)
    for path in users.glob("*/*.json.gz"):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(gzip.decompress(path.read_bytes()))
        except (OSError, ValueError):
            continue
        for run in data.get("runs", []):
            timeline = run.get("timeline") or []
            for i, node in enumerate(timeline):
                if node.get("type") != "shop":
                    continue
                bought = node.get("cardsBought") or []
                if len(bought) != 1:
                    continue
                if (node.get("relicsBought") or node.get("potionsBought")
                        or node.get("goldGained") or node.get("cardsRemoved")):
                    continue
                previous = timeline[i - 1] if i else None
                if not previous or previous.get("floor") != node.get("floor", 0) - 1:
                    continue
                if previous.get("gold") is None or node.get("gold") is None:
                    continue
                spent = previous["gold"] - node["gold"]
                if spent > 0:
                    prices[bought[0]].append(spent)
    return prices


def price_table(samples: dict, rarities: dict, discounts: dict) -> dict:
    """The shipped table, from {card: [prices]} and {card: rarity}."""
    full = {}
    for cid, values in samples.items():
        dearest = max(values)
        kept = [v for v in values if v >= DISCOUNT_FLOOR * dearest]
        if len(kept) >= MIN_SAMPLES:
            full[cid] = statistics.median(kept)

    by_rarity = defaultdict(list)
    for cid, price in full.items():
        by_rarity[rarities.get(cid)].append(price)
    # A card whose every sample sits well under its rarity's first estimate was
    # only ever seen with a discount relic; it is left out, and the rarity's
    # price is taken again without it, so one discounted card cannot drag the
    # fallback down for every card of that rarity.
    first = {r: statistics.median(v) for r, v in by_rarity.items() if v}
    discounted_only = {
        cid for cid, price in full.items()
        if rarities.get(cid) in first and price < DISCOUNTED_ONLY * first[rarities[cid]]
    }
    by_rarity = defaultdict(list)
    for cid, price in full.items():
        if cid not in discounted_only:
            by_rarity[rarities.get(cid)].append(price)
    rarity_prices = {r: int(round(statistics.median(v))) for r, v in by_rarity.items() if v}

    cards = {cid: {"price": int(round(price)), "n": len(samples[cid])}
             for cid, price in full.items() if cid not in discounted_only}

    return {
        "cards": dict(sorted(cards.items())),
        "rarity": dict(sorted(rarity_prices.items())),
        "discountRelics": dict(sorted(discounts.items())),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--users", type=Path, default=None,
                    help="profile root to read runs from (default: local_data/users)")
    ap.add_argument("--write", action="store_true", help="write shop_prices.json (else print a summary)")
    args = ap.parse_args()

    rarities = {k: v.get("rarity") for k, v in json.loads(CARD_DATA.read_text(encoding="utf-8")).items()}
    samples = samples_by_card(args.users or default_users())
    table = price_table(samples, rarities, discount_relics())
    text = json.dumps(table, separators=(",", ":"), sort_keys=False)
    print(f"{len(table['cards'])} cards priced from {sum(len(v) for v in samples.values())} single-card shops; "
          f"{len(samples) - len(table['cards'])} cards fell back to rarity")
    for rarity, price in table["rarity"].items():
        print(f"  {rarity}: {price}")
    if args.write:
        OUT.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
