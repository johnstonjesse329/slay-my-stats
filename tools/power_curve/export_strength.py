"""deck_strength.json: every card's and relic's numbers for the formula, as
plain rows. The estimate is off the Runs page, so the site no longer reads
this; it stays for patch-day work.

The numbers come from the game data (card_data.json, relic_data.json,
power_data.json at the repo root). Like those, the output is game data:
gitignored, built locally. Re-run after a game-data refresh.

    python export_strength.py
"""
import json
import approaches as ap
import power_curve as pc
import predict_fights as pf

OUT = pc.WT / "deck_strength.json"


def rounded(row):
    return {k: round(v, 3) for k, v in row.items()}


def main():
    cards = {cid: [rounded(pf.card_row(pc.card(cid, up))) for up in (False, True)] for cid in pc.CD}
    relics = {rid: round(b, 3) for rid in pc.RD if (b := pf.relic_block(rid))}
    relic_energy = {rid: round(e, 3) for rid in pc.RD if (e := pf.relic_energy(rid))}
    # Strength and Dexterity a relic grants, which the damage and block lines need
    # (Vajra, Brimstone and its compounding +2 a turn). Emitted per relic so the
    # site applies the ones a deck actually holds.
    relic_stats = {}
    for rid in pc.RD:
        stats = ap.relic_bits(pc.relic_effects([rid]), pc.TURNS)[3]
        if stats:
            relic_stats[rid] = {k: round(v, 3) for k, v in stats.items()}
    # Block a relic pays per event (Ornamental Fan's block every third attack),
    # which the block line needs the same way a card's does.
    relic_trig = {}
    for rid in pc.RD:
        trig = pf.relic_triggers(rid)
        if trig.get("bpc") or trig.get("bpa"):
            relic_trig[rid] = {k: round(v, 3) for k, v in trig.items() if k in ("bpc", "bpa")}
    out = {
        "turns": pc.TURNS, "frostBlock": pc.ORB_PASSIVE["Frost"],
        "cards": cards, "relics": relics, "relicEnergy": relic_energy, "relicStats": relic_stats,
        "relicTrig": relic_trig,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT.name}: {len(cards)} cards, {len(relics)} relics with block, "
          f"{len(relic_energy)} with energy, {len(relic_stats)} with strength or dexterity, "
          f"{len(relic_trig)} with block per event, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
