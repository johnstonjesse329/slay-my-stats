# Power curve POC: decisions waiting on you

Calls the sim makes today that you may want changed. None is wired to UI copy.

## Valuation guesses
- **Exchange rate:** a draw is worth about 3 and an energy about 5. A free (0-cost) draw card is played first.
- **The Gambit** (50 Block, die if hit unblocked) is never played. Its penalty is applied when deciding whether to play it, and that may be too harsh. The lethal clause isn't simulated in the fight itself.
- **Hidden Gem** is credited half the value of the Replay it grants. It ends up played only 0.1–0.2 times a turn. That might be too low.
- **Anointed** pulls every Rare card from the draw pile and is worth about 4 per Rare. It's never played in a deck with one Rare, which is probably fair.
- **Catastrophe** (2 energy: play 2 random draw-pile cards) scores about the same as a Strike per energy, so it's rarely played on damage turns.
- **Prolong** is worth twice the current block.
- **Foregone Conclusion** is worth about 4.
- **Nostalgia** counts from the per-card play counts.
- **Scrawl** is about neutral on a starter deck: its bonus is 1 per card it would draw.
- **Paid draw cards** aren't given priority. Only 0-cost ones are.

## Mechanics simplified or skipped
- **Regent:** stars are spent as they come. There's no logic for saving them for a big card.
  - This under-plays Resonance.
  - Pale Blue Dot rarely reaches its 5 plays.
- **Mad Science** (Curious / Improvement) is not modelled.
- **Abundance** is treated as "a random card, free". Its upgrade isn't modelled.
- **Event / token cards not modelled yet:**
  - Apotheosis (upgrade all)
  - Dual Wield (copy an Attack or Power)
  - Hello World (Common cards into hand each turn)
  - Rebound (next card to the top of the draw pile)
  - Toric Toughness (stored block)
- **Knowledge Demon picks:** Disintegration, Sloth and Mind Rot are ignored as statuses. They aren't deck cards.
- **Alchemize** isn't modelled because potions aren't. **Rally** is multiplayer-only and treated as unplayable in solo runs.

## Approach for the site (see the comparison)
- **Which projection ships:**
  - The small sim (C) is the only one within 7% on damage and block.
  - The card/relic lookup (B) gets the shape but is 15–50% off on level.
  - The deck averages (A) miss badly.
- **Open:**
  - Port C to JS?
  - Show B as an instant first draw?
- **Growth:** two 200-sample sims disagree by up to 26%. Show it as a trend, rework it, or drop it.

## Archetypes (archetypes.py)
- **How runs are labelled:** each run gets the archetype with the most signature cards in its final deck. It needs 3 or more cards. A runner-up within 70% makes it a pair (for example "Exhaust + Block"); otherwise it's "Mixed".
- **Signature cards:**

  | Character | Archetypes |
  |---|---|
  | Ironclad | Strength, Exhaust, Block |
  | Silent | Shiv, Poison, Discard |
  | Defect | Lightning, Frost, Dark, 0-cost attacks |
  | Necrobinder | Doom, Osty |
  | Regent | Stars, Forge |

- **Block counts block builders only:** Body Slam, Entrench, Barricade, Juggernaut, Unmovable, Stone Armor, Rage and the like. Big Block cards alone (Blood Wall, Flame Barrier) don't count.
- **Regent Forge never comes up** in gamma's runs. Every Regent run is Stars.
- **To review:**
  - Regent's median damage is flat at about 30 from floor 17 to the end, while its block rises from 12 to 16. Necrobinder Osty's damage is flat at about 31.
  - Traced decks play a sensible mix, so this looks like deck makeup (utility and block picks) rather than a sim bug. Stars are still spent as they come.
  - A handful of runs end with less damage than floor 1. The "falls" column in archetypes.txt counts them.

## Fight replays dropped
- **Deck power is four things:** damage potential, block potential, the energy engine and the draw engine. The curve measures all four from dummy games.
- **Replays measured play, not power:** replaying each fight to project turns and damage taken depended on guessing a human's block-vs-attack calls and the enemies' move order. Across 14,787 gamma fights, the projected damage taken was more than double the actual in 38% of them. On one Ironclad Owl fight it was about 57 against 6 actual.
- **Now:** the fights table shows the encounter's HP and attack pattern beside the real turns and damage taken. About 30% less compute per run.

## Recent fixes (for context when reviewing runs)
- **Overnight hang:** 2 of 1,025 runs looped forever, and the batch never finished. There were three causes:
  - **Drum of Battle:** it gave its 2 energy on play instead of when exhausted. As a 1-cost card that draws 2, it made energy forever, and Cascade then played hundreds of cards a turn.
  - **No limit on cards played by other cards:** a turn now stops at 200 plays in total, autoplays included.
  - **Havoc vs Uproar/Beat Down valuation:** each valued the other's pile, which recursed without end. It now goes one level deep.
  - **Safety net:** a run now gives up after 60 seconds and shows as an error, so one deck can't hold up the batch.
- **Tyranny / Toasty Mittens:** exhausting 2+ cards at the start of a turn could pick the same card twice and crash the run. It now picks them one at a time. This fixed the 2 failed gamma runs.
- **Panache:** it now counts plays from scratch each turn, as the game does. It used to carry the count across turns.
- **draw_worth:** energy the hand will already spend is no longer counted as free for drawn cards.
  - Scrawl went from a loss to neutral.
  - Glimmer now does more damage and blocks more.
  - Silent's Speedster + Acrobatics lost about 8 damage over five turns against the pack.

## Predicting real fights (predict_fights.py)
- **Answer key:** each fight's real damage taken and turns, as the gap from that encounter's average, over 14,784 gamma fights. Fitted on half the runs, scored on the other half, both ways round.
- **Share of the gap explained** (who played, ascension and act alone: 2.7% on damage taken):

  | Measures | Damage taken | Turns | Cost |
  |---|---|---|---|
  | Sim | 7.6% | 11.1% | about 10 CPU-s a run |
  | Deck averages (A) | 3.9% | 6.8% | |
  | Formula | 6.7% | 10.2% | 0.06 ms a deck |
  | Sim + formula | 9.9% | 13.9% | |

- **What carries it:** damage output predicts turns; block, Dexterity, block relics and Plating, Osty, Strength and poison predict damage taken.
- **Tried and dropped:** setup (Power) count, deck size, Unmovable, Barricade, Afterimage / Feel No Pain. None helped on the held-out half.
- **Setup cards in real fights (fights_vs_setup.py):** decks heavy on Powers didn't take more damage than others in the same encounter, but needed 0.2–0.3 more turns in Acts 2–3. Two experienced players, so the trap may just be rare here.
- **Open:** sim + formula beats either, so the sim still sees something the formula doesn't.
- **Fewer features:** without the energy term, damage taken holds (6.9%) and turns drop to 9.4%; without energy and cards seen too, 6.7% and 8.9%. All 11 stay.
- **Turns and damage go together:** each extra turn in a fight goes with about 2.5 HP taken (2.2–2.9 by act).

## Strength per floor (formula_curves.py)
- The formula's weights, fitted on every fight, score the deck after each floor: expected damage taken and turns against an average deck in the same fight. 0 is an average deck; lower is stronger.
- A skip leaves the score flat. Junk cards raise it, since they thin out the cards a turn sees. Setup-heavy shops can raise it too (one run's floor-37 shop of Forgotten Ritual, Mayhem and Inferno).
- The viewer shows both as charts, with the floor's changes in the tooltip, and a table of every change with how far it moved each score.
- **Your call:** the viewer wording is placeholder copy.


## On the site (js/deck-strength.js)
- The Runs page shows the formula's raw numbers per floor, not the fitted HP and turns: damage and block per turn on one chart, energy and cards per turn on another. The fit stays here as evidence that these numbers predict real fights.
- Damage counts Strength and poison; block counts Dexterity, Plating, block relics, Frost (2 a turn, as the sim's passive) and Osty's HP. Energy counts what relics give a turn (Blood-Soaked Rose, Sozu, a bigger pool) and what cards gain, so a run's energy line moves when an energy relic is picked up. Cards drawn leave out dead cards, so junk shows as a dip.
- `predict_fights.formula_rows` and `strengthFeatures` in the JS are line-for-line copies; checked on 30,948 floors to within the export's rounding.
- **Open:** the user isn't sold on the numbers' accuracy yet; to be judged across more runs on gamma.
