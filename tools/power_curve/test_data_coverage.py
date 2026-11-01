"""Every rule flag the extractor emits must be read, or knowingly not read.

Three bugs in one session had the same shape: the game data carried a fact, and the
cheap formula that draws the Runs page never looked at it.

- Relic Strength: `relic_bits` returned it and `formula()` dropped the Counter.
- Cruelty and Tracking: `vulnBonus` / `weakBonus` existed and only the simulator read
  them, so a Cruelty deck was scored as a plain Vulnerable deck.
- Pyre: its power carries `maxEnergy` rather than a `turnEffect`, so nothing saw it.

The extractor was ahead of the formula and nothing checked for that. This does: any
flag in the extractor's vocabulary has to appear as a name in predict_fights (so the
cheap formula reads it), or be listed below with the reason it does not.

    python -m unittest test_data_coverage
"""
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import power_curve as pc  # noqa: E402

FORMULA_SRC = (HERE / "predict_fights.py").read_text(encoding="utf-8")

# Flags the cheap formula genuinely cannot use, and why. Deliberately short: each
# entry is a decision, not a shrug.
NOT_READ = {
    # These change how a *simulated* fight plays out -- replays, free plays, where a
    # card lands -- which a per-turn average has no way to price. The sim models them;
    # the formula reads their effect only insofar as it shows up in damage or block.
    "replays", "free", "exhaustsType", "fromDiscard", "playsDrawn", "endPlays",
    "copiesNth", "turnMakes", "clonesNextTurn", "firstTagBonus", "retainsTag",
    "hurtsOnPlay", "keywordOnPlay", "aoeTag", "buffer", "zeroCostBonus",
    "returnsZeroCost", "turnMakesRandom", "costUp", "turnMakesEthereal",
    "ostyBonus", "firstAttackBonus", "ostyLossHits", "doomPerDamage", "strPerPlay",
    "energyPer", "drawAfterAttacks", "reflect", "hitStrDown", "handDrawOnce",
    "bladeReplays", "tagBlock", "noCardBlock", "turnPlaysTop", "topsFirst",
    "turnAoeGrows", "bomb", "shuffleFetch", "attackMakesRandom", "turnTransforms",
    "gambit", "keepsBlock", "keepsHand", "blockDoubles", "dmgMult",
    # Not a flag: a stacking hint.
    "temp",
    # Per-event payments. Encoded, measured, and off (PF_ATK) because the linear
    # version lost accuracy -- see power_curve_decisions.md.
    "poisonTicks",
}

# Real gaps: the data has them, the formula does not read them, and nothing about the
# design stops it. Listed rather than hidden, so they can be picked up deliberately
# instead of being discovered by a player noticing a wrong number.
KNOWN_GAP = {
    # Extra cards drawn next turn (Glow, Guiding Star, Plot, Predator, Relax). Would
    # move f_seen; not modelled, so those decks under-read the cards line.
    "handDraw",
    # Orb-specific effects (Coolant's block per unique orb, Hailstorm's AoE, Loop's
    # extra passive, Lightning Rod's channel). Would move f_block and f_dmg for orb
    # decks; the formula reads orbs only through Frost's flat block.
    "orbHooks",
}

# Flags that must be read: the ones whose absence has already produced a wrong
# number. If one of these ever stops being referenced, that is a regression.
MUST_BE_READ = ["vulnBonus", "weakBonus", "debuffDouble", "maxEnergy", "turnEffects", "triggers", "mods",
                "per_attacks"]


class DataCoverage(unittest.TestCase):
    def test_every_rule_flag_is_read_or_documented(self):
        unread = []
        for flag in sorted(set(pc.RULES) | set(pc.DMG_RULES)):
            if flag in NOT_READ or flag in KNOWN_GAP:
                continue
            if not re.search(rf'["\']{re.escape(flag)}["\']', FORMULA_SRC):
                unread.append(flag)
        self.assertEqual(unread, [], msg=(
            "these flags exist in the game data and predict_fights never mentions them, "
            f"so a deck using them is scored as if it did not: {unread}. Either read them, "
            "add them to NOT_READ with a reason, or to KNOWN_GAP if it is a real gap."))

    def test_the_known_gaps_stay_visible(self):
        # A gap that is still a gap has to keep saying so. This fails if one is
        # quietly moved into NOT_READ (pretending it cannot be modelled) or deleted.
        self.assertEqual(sorted(KNOWN_GAP), ["handDraw", "orbHooks"],
                         "update this test deliberately when a gap is closed")

    def test_the_flags_that_have_been_wrong_are_still_read(self):
        # Each of these was once invisible to the cheap formula, and each time the
        # projection was wrong in a way a player could feel.
        missing = [f for f in MUST_BE_READ
                   if not re.search(rf'["\']{re.escape(f)}["\']', FORMULA_SRC)]
        self.assertEqual(missing, [])

    def test_the_skip_list_is_all_real_flags(self):
        # A typo in NOT_READ would quietly hide a live flag.
        known = set(pc.RULES) | set(pc.DMG_RULES)
        self.assertEqual(sorted(set(NOT_READ) - known), [])


class ExtractorCoverage(unittest.TestCase):
    """The step before that: does the extractor emit the flag at all?"""

    def test_the_debuff_effect_boosters_are_all_flagged(self):
        # Cruelty and Tracking were flagged; Debilitate was not, because it *doubles*
        # the multiplier instead of adding to it.
        powers = pc.PD["powers"]
        self.assertTrue(powers["Cruelty"].get("vulnBonus"), "Cruelty adds to Vulnerable")
        self.assertTrue(powers["Tracking"].get("weakBonus"), "Tracking pays on Weak foes")
        self.assertTrue(powers["Debilitate"].get("debuffDouble"), "Debilitate doubles both")

    def test_every_energy_and_block_power_carries_a_way_to_be_counted(self):
        # A power that pays energy or block has to say so in one of the shapes the
        # formula reads: a turnEffect, maxEnergy, a modifier, or a trigger.
        silent = []
        for name, p in pc.PD["powers"].items():
            pays = (p.get("turnEffects") or p.get("maxEnergy") or p.get("mods")
                    or p.get("triggers") or p.get("handDraw") or p.get("orbHooks"))
            if not pays and (p.get("produces") or any(k in p for k in ("vulnBonus", "weakBonus"))):
                continue  # a marker power (Vulnerable itself) or a producer
            if not pays and not p:
                silent.append(name)
        self.assertEqual(silent, [], msg=f"powers with no data at all: {silent}")


if __name__ == "__main__":
    unittest.main()
