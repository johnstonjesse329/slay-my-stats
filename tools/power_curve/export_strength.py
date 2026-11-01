"""deck_strength.json for the site: every card's and relic's numbers for the
formula, so js/deck-strength.js can give a run's damage, block, energy and
cards per turn floor by floor.

The numbers come from the game data (card_data.json, relic_data.json,
power_data.json at the repo root). Like those, the output is game data:
gitignored, built locally, deployed with the site. Re-run after a game-data
refresh.

    python export_strength.py
"""
import json

import power_curve as pc
import predict_fights as pf

OUT = pc.WT / "deck_strength.json"


def rounded(row):
    return {k: round(v, 3) for k, v in row.items()}


def main():
    cards = {cid: [rounded(pf.card_row(pc.card(cid, up))) for up in (False, True)] for cid in pc.CD}
    relics = {rid: round(b, 3) for rid in pc.RD if (b := pf.relic_block(rid))}
    relic_energy = {rid: round(e, 3) for rid in pc.RD if (e := pf.relic_energy(rid))}
    out = {
        "turns": pc.TURNS, "frostBlock": pc.ORB_PASSIVE["Frost"],
        "cards": cards, "relics": relics, "relicEnergy": relic_energy,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT.name}: {len(cards)} cards, {len(relics)} relics with block, "
          f"{len(relic_energy)} with energy, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
