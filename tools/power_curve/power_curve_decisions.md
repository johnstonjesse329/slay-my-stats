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

## Walk-forward check (validate_floors.py, 2026-11-01)
20,609 fights in 1,456 gamma runs, the deck that walked into each fight, each encounter's own average taken out. Held out by run: fit on half, score the other half.

| | Result |
|---|---|
| block/turn vs damage taken | rho **−0.173** |
| damage/turn vs turns | rho **−0.194** |
| energy/turn vs turns | rho −0.109 |
| cards/turn vs damage taken | rho −0.125 |
| block/turn vs turns | rho +0.160 (right way: tanky decks take longer) |
| damage/turn vs damage taken | rho −0.054 |
| composite, held out | **6.6%** of the damage-taken gap, **10.1%** of the turns gap |

- **All four lines point the right way and all four are weak.** Each is a real signal at roughly rho 0.1–0.2, so the chart is directionally honest and noisy, not wrong.
- **Floor to floor, damage taken behaves.** A floor the fitted score called stronger was followed by −0.22 damage taken against the encounter's average; a weaker floor by +0.05.
- **Floor to floor, turns goes backwards** (+0.13 when stronger, −0.19 when weaker). That matches the setup finding above: decks the model calls stronger tend to add Powers, which cost turns before they pay.
- **Calibration is monotone to the middle and flattens at the top.** Decile 1 takes −3.17, decile 5 +1.56, then 6–9 barely move and decile 10 falls back to −0.48. The extreme high scores aren't the worst decks, so the very bottom of the scale is being over-read.
- **The blind spot is measurable.** A deck held 3.3 unmodelled cards on average (52% of fights had 3+), plus 6.6 unmodelled relics. Block vs damage taken: rho **−0.346** with no unmodelled cards, **−0.221** with 1–2, **−0.107** with 3+. The model's strongest signal is on the decks it can fully see.
- **Next:** the 188 unmodelled cards are 36% of the pool but 23.6% of card slots, and they win more than average (38.9% vs 33.7%), so modelling them is where the accuracy is.

- **Uptime, not amounts.** Vulnerable and Weak are 8.6% and 4.2% of card slots (22 and 19 cards), the biggest conditional class by far — bigger than on-play triggers (1.3%) and energy-per-turn (1.0%). Each application lasts as many turns as the number applied, so a card that adds N a turn keeps it up all fight once N × how often it's played reaches 1: `min(1, Σ stacks × share)`. Vulnerable lifts the damage line by 50% of that uptime, Weak lifts the block line by 25%. Neither is throughput of its own; they are multipliers, so they belong on the line they multiply.
- **Measured:** 6.6% → **8.8%** of the damage-taken gap on held-out runs (turns 10.1% → 10.9%), block/turn against damage taken −0.173 → −0.197, damage/turn against turns −0.194 → −0.234. With the (unshipped) card priors on top: 9.0% / 11.3%.
- On gamma since 130662a: a Bash deck's damage line now reads 1.5x its raw throughput at full Vulnerable uptime (the Ironclad win at floor 48: raw 19.7, shown 23.8).
- **Open:** `formula_weights.json` predates `f_vuln` and `f_weak`, so `formula_curves.py` is fitting an 11-feature model against a 13-feature one. Refit it the next time `pcs/` is regenerated; nothing on the site reads the weights.

## The small conditional classes (2026-11-01)
- **Energy a turn (10 cards: Charge Battery, Outmaneuver, Hegemony...)**: modelled as `energy += Σ amount × the Power's share of turns in play`. A wash on the fit (8.8% → 8.9% of the damage-taken gap, turns 10.9% → 10.8%) but correct, and it stops those cards reading as nothing.
- **On-play triggers (12 cards: Afterimage, Rage, Panache, Subroutine...)**: modelled as `amount × share of turns in play × cards played a turn`, tried both as their own features and folded into the damage and block lines. **Dropped**: it cost the block line 0.013 of its correlation against damage taken (−0.197 → −0.184) for no gain anywhere, because the estimate is too generous — Rage's block only lasts the turn it's played, and Afterimage's single block per card doesn't add up to what the estimate credits.
- **Relic triggers are unmodelled in the data**, not just in the formula: `relic_effects` comes back empty for Mummified Hand and Lost Wisp, and only 11 of 299 relics carry any `trig`. Covering those needs the extractor (`tools/extract_power_data.py`), not another term.

### Per-event triggers, given a proper vocabulary and still not enough (2026-11-01)
11 relics and 12 cards pay per event — Kunai's Dexterity and Shuriken's Strength per attack, Ornamental Fan's block per attack, Art of War's and Nunchaku's energy per attack, Afterimage's block per card played, Rage's per attack, Panache's damage every fifth card. The formula sees none of them, so they are now encoded as one vocabulary both cards and relics use: an effect, the event it counts (card / attack / power), and an amount per event. A deck's own rate of those events then prices them, which is what should make a Shiv deck's Kunai + Afterimage matter.

| Variant (held out by run; "with" = the 3,772 fights in decks carrying a trigger) | with decks, taken R² | with decks, turns R² |
|---|---|---|
| Triggers off | **7.2%** | **9.7%** |
| Per card played only | 6.7% | 8.7% |
| The vocabulary, weighted by the Power's share of turns in play | 6.7% | 8.7% |
| The vocabulary, with skills and Shivs counted in cards played | 6.5% | 8.1% |

- **Every linear version makes those decks worse**, so triggers stay encoded but off (`PF_ATK=1` turns them on). The synergies are real; the arithmetic isn't.
- **Why:** the term multiplies two per-turn averages — "how often this fires" and "how many events a turn" — and the average of a product isn't the product of averages. Afterimage only pays on the turns it's already down and you're already flooding cards, and the formula has no turn where both are true. A linear fit can only see the average of each.
- **What would work:** measure the firings instead of inferring them — per fight, how often each relic and power actually triggered (the telemetry design in TODO). Those rates are also the calibration this term needs, if it is to survive at all.




## Guessing the cards nobody can read (2026-11-01)
189 live cards carry nothing the formula can use. Three ways of covering them, each measured on the same 20,609 fights:

| | Held out R², damage taken | … turns | block vs taken, decks with 3+ unreadable cards |
|---|---|---|---|
| Nothing (baseline) | **6.6%** | 10.1% | −0.107 |
| Every stat of the average readable card of that type and cost | 4.3% | 8.8% | −0.117 |
| One stat, chosen by type and job (kept) | 6.4% | **10.9%** | −0.118 |

- **Blanket priors are worse than nothing.** Handing Barricade the average 3-cost Power's row gave it 16 damage and 3 energy a play, and the fit lost a third of its explanatory power.
- **Shape-aware priors are a wash on damage taken and a small gain on turns.** One stat — an Attack that helps damage borrows the median hit of Attacks at its cost, a Power that helps block borrows the median Plating/Dexterity of Powers — plus the card's own cost and Power flag.
- **The hypothesis is falsified:** knowing how many cards a deck holds that can't be read still costs the model two thirds of its block signal (−0.35 on decks it can read against −0.12 on decks it can't). A typical-card guess does not recover it, because what's missing is conditional — on-play triggers, Weak/Vulnerable uptime, free plays — not an average value.
- If the priors ship it is for the chart's honesty (a card stops reading as nothing), not for accuracy. The accuracy is only going to come from modelling the conditional classes or from telemetry.



## Per-turn telemetry (2026-11-01)

> Superseded in part by "The event log replaces the summary", below: what is
> recorded is now raw events, and every reading of them lives in
> `derive_telemetry.py`. The sections before that one describe the first two
> schemas, which the deriver sets aside.

Everything above is fitted on what a run ended with — deck, relics, the fight's
damage taken. None of it can see a turn, which is why every conditional class
came out either a wash or worse: Vulnerable and Weak survived only because
uptime could be approximated from stacks, and the on-play triggers failed
because the formula multiplies two per-turn averages and the average of a
product isn't the product of averages.

The mod now records the turns themselves. Each fight carries its encounter id and
the HP it started and ended on, and per turn: energy and stars at the start,
energy spent, damage dealt, damage taken and how much of it block absorbed, block
gained, orbs channelled, the card ids drawn and played, and the powers in play
with their stacks. Everything is counted from Harmony hooks
(`AfterCardPlayed`, `AfterDamageGiven`, `AfterDamageReceived`, `AfterBlockGained`,
`AfterEnergySpent`, `AfterOrbChanneled`, `AfterPowerAmountChanged`,
`AfterPlayerTurnStart`, `BeforeCombatStart`, `AfterCombatEnd`), so nothing is
inferred from card text and nothing needs a new card to be described before it
counts.

- **Answers the two questions the model can't:** whether a deck's power rises
  floor to floor (`formula_curves.py` projects it; only turns can confirm it), and
  whether the conditions actually fire — shared stacks against turn count, card
  and attack rate against the triggers that pay per event.
- **No archetype sweep needed.** The comparison is within-run and
  floor-to-floor, so a player's own decks supply the contrast; partial pooling
  across players then borrows strength for the thin archetypes. A run only has to
  be played, not played well.
- **Patches and new characters** stay out of it: card and relic effects are
  read from the game's own models at the moment they happen, so a rebalanced or
  brand-new card is measured the first time anyone plays it.
- **Size:** ~10-15 KB gzipped a run, one object per upload. Storage and transfer
  at this scale are pennies; the report is the cost, not the capture.

`telemetry_report.py` sets the two beside each other: damage, block and energy a
turn against the projection for the deck that walked into that fight, and the
first turn against the rest — the first turn being where a deck's setup either
lands or doesn't, and the one thing the formula has no term for at all.

### The first real run, and what it caught (2026-11-01)

Run 1793552310 on gamma: 25 fights, 98 turns, 3.2 KB gzipped. Checked against
the run file, whose own `damage_taken` per fight and turn count are ground
truth:

| | run file | mod, v1 |
|---|---|---|
| damage taken, whole run | 343 | **107** |
| turn count, per fight | 25 fights | 25 fights, none off |
| HP lost (summed per fight) | 343 | 343 |

- **The skeleton is exact.** Turn counts match fight for fight, and the HP the
  mod reads at combat start and end sums to the run's `damage_taken` to the
  point. So the fight boundaries, the turn boundaries and the HP reads are all
  right.
- **Enemy-phase damage was being thrown away.** The turn was closed at the
  player's side turn end, so every enemy attack landed with no turn open. A
  turn now stays open until the next player turn begins, and its number comes
  from the player's own `TurnNumber` rather than the round number (which moves
  mid-round and would split one turn in two).
- **The hand was never counted as drawn.** Every hand is dealt before the
  turn-start hook, so `AfterCardDrawn` only ever saw mid-turn draws: 1.8 cards a
  turn against 3.7 played. The turn now snapshots the hand it was dealt (`hand`)
  and keeps `drawn` for what came after. v1's first turn reads `drawn 0, played 4`.
- **Powers are now a snapshot, not a change log.** A Power that was already up
  never fired `AfterPowerAmountChanged`, so uptime was invisible; turn 1 of the
  Waterfall Giant fight recorded 2 powers and turn 2 recorded 3, for a deck that
  had far more standing.
- **Schema is v2** for the three fixes above. v1 objects stay readable but must
  not be pooled with v2: their `taken` is a third of the truth. The report's
  section 3 is the check — it compares each run's mod-counted damage taken with
  the run file's own.

## The event log replaces the summary (2026-11-01, second attempt)

The first version built a *summary* inside the game: per fight and per turn it
counted what it thought mattered. That put every judgement at capture time, and
the run proved it wrong twice over -- a turn closed at the player's side turn end
(dumping the whole enemy phase), and the dealt hand never counted as drawn. Both
were unfixable after the fact, because the evidence had never been written down.

The log inverts it. The mod now records events and nothing else, and every reading
of those events lives in `derive_telemetry.py`, where it can change and be re-run
over logs already in the data bucket. A wrong reading is a re-derive, not a replay.

- **The spine is the game's own HP hook.** `AfterCurrentHpChanged` runs "after a
  creature's HP changes for any reason (damage, heal, HP loss)", with damage
  negative and healing positive. Damage taken is that sum, so it cannot depend on
  block arithmetic or on which damage hook fired. It also makes every fight
  checkable: the HP the fight started and ended on must equal the deltas.
- **A turn opens at the first sign of one** -- `BeforeHandDraw` ("runs before the
  player draws their hand at the beginning of their turn"), the energy reset, the
  turn-start hook, or the player's side starting -- and closes only when the next
  turn opens. The enemy phase therefore belongs to the player's turn, which is
  where the damage is.
- **The hand is recorded as drawn.** `AfterCardDrawn` reports `fromHandDraw`, so the
  cards a turn was dealt are told apart from the cards drawn during it.
- **Nothing is summarised at capture, and the log is never rewritten.** Additions
  are additive; the deriver carries the version.

Checks that run on every log, and fail loudly with the fight and the event: HP
deltas against start/end HP, damage taken against the HP drops, energy end against
start plus spend, turn count against the game's round count, and no card played
that was never drawn.

The mod ships `tools/check_patches.py` alongside it: Harmony binds a patch's
parameters **by name**, so a game update that renames one would silently stop an
event being recorded. The tool reflects `sts2.dll` and fails on any mismatch --
28 patches checked, no launch required.

### Everything live-only is now in the file (2026-11-01)

The rule for what goes in the log is not "is it useful" but "can it be recovered
later". Three things cannot, and none of them are in the run file:

| live-only fact | source | why it cannot be recovered afterwards |
|---|---|---|
| each enemy's next move and whether it intends to attack | `MonsterModel.NextMove.Id`, `IntendsToAttack` | it is only true for that turn; the run file records what happened, not what was coming |
| every relic's counter and whether it is spent | `RelicModel.DisplayAmount`, `IsUsedUp`, `Status` | Pen Nib's tally and Nunchaku's count decide whether a per-event relic fires; a fight that ends does not leave them anywhere |
| potions held, and each use with its target | `Player.Potions`, `AfterPotionUsed` | a resource decision, and who the potion hit |

So a per-turn snapshot sits at each boundary beside the event stream: creature HP,
max HP, block and powers with stacks; enemy intents; the player's energy, stars,
hand, pile counts, orbs, gold, potions and relic counters. Deltas could be walked to
reach the state, but a snapshot cannot disagree with itself.

What stays out is now a rule rather than a judgement: anything that is a function of
facts already logged. `Modify*` and `Should*` hooks adjust or veto values that other
events already report, so logging them too would put two sources of truth in the
file, and a contradiction cannot be adjudicated later -- refining a deriver has no
way to know which copy was right.

`hook_coverage.md` in the mod repo keeps that honest: all 147 documented hooks,
marked recorded / derivable / skipped-with-reason, generated from `sts2.xml` and the
patch source. 41 / 8 / 98, none undecided.

### The first real run: verified against the run file (2026-11-01)

Run 1793564096: 24 fights, 93 turns, 7,480 events, 831 KB raw / **76 KB gzipped** --
3.8% of the 2 MB upload cap, 1.1 MB for a 1,500-run dataset.

The log was joined to the run's own combat nodes and compared on the two things the
run file states independently: damage taken per fight and turns per fight.

| | result |
|---|---|
| fights joined | **23 of 24**, zero disagreeing |
| damage taken, per fight | **0 mismatches** (e.g. 4/4, 25/25, 42/42, 18/18) |
| turns, per fight | **0 mismatches** (4/4, 7/7, 13/13, 5/5) |
| the deriver's own checks | **0 problems** |

What that run taught, all of it from the transcript rather than from reasoning:

- **The hand is dealt before `AfterPlayerTurnStart`.** The real order is side start,
  block cleared, energy reset, `BeforeHandDraw`, the draws, then `AfterPlayerTurnStart`,
  then `AfterSideTurnStart`. A turn must open at the first of those, not at the
  turn-start hook.
- **Cascade plays the top card of your draw pile straight from Draw into play.** It is
  never "drawn", so `AfterCardDrawn` never fires, and a card looks like it was played
  out of nowhere. The pile event now records where the card went; without that, hand
  tracking cannot be exact.
- **Post-combat healing fires `AfterCurrentHpChanged` after the fight has ended.** A
  fight that cost 4 HP read as costing 0 because a +6 heal landed afterwards. The end
  HP has to come from `AfterCombatEnd`.
- **`AfterCombatVictory` is not the end state either**: it fires before the fight is
  closed and before that healing, so its HP is not what the fight ended on.
- **The run file does not record `ENCOUNTER.MYSTERIOUS_KNIGHT_EVENT_ENCOUNTER` as a
  combat** (event encounters are stored as events), so a positional join lost every
  fight after it -- 12 of 24 instead of 23 of 24. The join now aligns on encounter id
  as a sequence, skipping whichever side is missing an entry.
- **`BeforeDamageReceived` was a duplicate** of `DamageResult.total` on the receiving
  event: 7% of the log for a second copy of the same number. Dropped.

### Comparing like with like, and the energy line's over-read (2026-11-01)

The report compared the projection against measurements in the wrong units, in two
ways, both of which flattered nothing and misled plenty:

- **Damage was summed over every enemy hit** while the projection is per target. On
  a run averaging 1.77 targets a turn, the measurement read 56 damage a turn against
  a 25 projection -- a 78% over-read that was pure double counting. Per target it is
  **25.4 projected against 23.5 measured**.
- **Energy was the turn's opening energy** while the projection is what the deck has
  to spend. Most turns gain energy, so the measurement under-read; against what the
  turn actually had to spend (spent + left over) it is 4.1.

Like for like on run 1793564096 (23 fights, 93 turns):

| per turn | projected | measured | reading |
|---|---|---|---|
| damage, per target | 25.4 | 23.5 | accurate to 8% |
| block (all-in ceiling) | 15.3 | 8.7 | a ceiling, not a promise |
| **energy to spend** | **5.5** | **4.1** | **over-reads 34%** |

- **The damage line holds up on a deck the fit never saw.** That is the first
  per-target check ever run, and it lands within 8%.
- **The energy line is 1.4 energy a turn too generous.** `validate_floors` cannot see
  this: it measures damage taken and turns taken, never per-turn energy. Only
  telemetry can, which is the whole argument for capturing it -- one run already
  produced a calibration fact the 20,609-fight harness could not.
- **The conditional classes were absent from this deck**: Vulnerable on 0 of 90 turns,
  Weak on 0 of 90. Whatever they are worth, they were worth nothing here.
- Block over-reading by 40% is expected rather than wrong: `f_block` is what the hand
  can block if it plays everything for block, and no deck does that every turn. The
  report now says so where the numbers are printed, so the next reader does not
  mistake a ceiling for a forecast.

### What the telemetry found in the model (2026-11-01, same run)

Two entries the fit had been carrying that the run itself contradicts.

**Venerable Tea Set was credited 2 energy on every turn.** Its text is "whenever
you enter a Rest Site, start the next combat with an additional 2 energy", and its
code holds a `GainEnergyInNextCombat` saved flag -- one shot, and only after a rest
site. The extractor read `PlayerCmd.GainEnergy` in a turn-start path and had no way
to see the bound, so the relic contributed 2 energy to every turn of every fight it
was held in. In the run, fights holding it measured **base energy, 3.00**, against a
projection of 5.00. The other one-shot relics were already amortised the same way
(Lantern 1 energy -> 0.2, Very Hot Cocoa 4 -> 0.8); Tea Set simply was not.

Fixed in `tools/extract_power_data.py` with a `RELIC_TURN_OVERRIDES` table stating
the bound the reader cannot infer, so regenerating the data keeps the fix. Only the
two Tea Set records changed.

| | projected energy per turn | measured |
|---|---|---|
| before | 5.5 | 3.7 |
| after | **4.3** | 3.7 |

The over-read went from 34% to 16%. Held out by run over the 20,657-fight harness,
the composite moved from 8.9% to 8.7% of the damage-taken gap and 10.8% to 10.6% of
the turns gap -- inside noise, and the energy bucket's own correlation with turns
improved slightly (-0.092 to -0.087). A small cost for reporting a true number.

**Vulnerable is over-read, but by a fifth, not by four times.** The formula's
`min(1, stacks x share)` says an enemy is Vulnerable for 75% of a fight's turns for
this deck. My first attempt to check that counted turns where it was up *at the turn
start*, which read 15% -- and was wrong: Vulnerable applied during a turn boosts that
turn's hits, so the turns it pays on are exactly the ones a boundary sample misses.

Measured properly -- the share of the damage actually dealt that landed on a
Vulnerable target -- it is **37%**:

| | assumed | measured |
|---|---|---|
| share of damage at the boost | 75% | **34-37%** |
| damage multiplier | x1.37 | **x1.17** |

So the over-read is about a fifth of the multiplier, not a half. The gap is real but
modest: the formula assumes every hit during those turns lands on the debuffed
target, and in practice some go elsewhere, to a fresh enemy, or land after it dies.
That needs a targeting and decay idea to do better than a constant, which is why it
is left as a calibration question rather than patched.

An earlier note in this file claimed the deck "applied Vulnerable on 0 of 90 turns".
That was wrong twice: the power id is `POWER.VULNERABLE_POWER`, and the deriver was
only tracking powers on the player. The deck applied it **66 times**.

### Per-turn effects, checked one by one (2026-11-01)

A player's own reading of the run -- "two Stone Armors, a Pyre, Bloodletting; 4 energy
a turn is way too low on later floors" -- was worth checking against the data rather
than against my assumptions. All three, on the final deck:

| card | what the data carries | what the formula did |
|---|---|---|
| Stone Armor x2 (one upgraded) | applies Plating 6 and Plating 4; Plating's turn effect is `block` | **counted**: 10 block a turn, via `tb` |
| Pyre (upgraded) | applies Pyre 2; PyrePower overrides `ModifyMaxEnergy` (+1 a stack) | **not counted at all** |
| Bloodletting | `does: [damage, energy]`, 3 energy | counted, but x deck-share (0.57 a turn) |

- **Pyre was invisible** because it raises the energy ceiling instead of firing a
  turn effect: the row builder reads `turnEffects`, and Pyre's power carries
  `maxEnergy`. Fixed, and the shipped data now shows `CARD.PYRE: [{et:1},{et:2}]`
  for its two upgrade levels.
- **Stone Armor was already right.** Worth saying plainly: the two most visible
  per-turn effects in that deck were being counted, and the one that was not turned
  out to be energy rather than block.
- **Bloodletting's 0.57 is the model's real weakness**, not a bug: it assumes you see
  3 energy's worth of Bloodletting once per deck cycle, and in a long fight the deck
  cycles more than that.

### Energy is the wrong unit; cards played is the right one

Raw energy cannot see a card played for free. Cascade takes a card off the draw pile
straight into play: no energy spent, a card's worth of value delivered. So the report
now measures throughput as the **list price of the cards actually played**:

| per turn | this run |
|---|---|
| cards played | 4.00 |
| energy spent | 4.02 |
| their list price (energy-equivalent) | **4.79** |
| projected energy | 4.46 |

Against raw energy the projection over-reads (4.46 vs 3.73); against what the cards
actually cost it under-reads by 7% (4.46 vs 4.79). The second comparison is the
honest one, and it says the deck was doing more than the energy line credits -- which
is what it felt like from inside the run.

### Relic Strength never reached the damage line (2026-11-01)

A deck measuring **120.8 damage a turn** at the final boss projected **30.5**. Three
bugs sat on the same path, and each one alone would have hidden the others:

1. **The amount was the enemies'. ** A relic's power turn effect takes its amount from
   the relic's vars. Brimstone carries `SelfStrength: 2` and `EnemyStrength: 1`, and
   the reader took the first numeric var -- so it used the bonus the *enemies* get.
2. **Per-turn buffs were skipped.** `relic_bits` counted Strength only when the effect
   had `on == 1`, a combat-start buff like Vajra's. Brimstone has no `on` because it
   fires every turn, so it fell through and contributed nothing.
3. **`formula()` built the stat Counter and dropped it.** Only block and energy were
   forwarded into the model. So even Vajra's +1 Strength reached nothing at all.

Strength that arrives every turn **accumulates**, so it is a ramp and not a flat
bonus: it is now counted at the fight's average, `amt x (turns + 1) / 2` -- 6 Strength
for Brimstone across five turns.

| | before | after | measured |
|---|---|---|---|
| damage at the final boss, per target | 30.5 | **56.2** | 61.8 |

Held out over 20,657 fights, every metric improves rather than trading off:

| | before | after |
|---|---|---|
| taken R^2 | 8.7% | **9.0%** |
| turns R^2 | 10.5% | **10.9%** |
| block/turn vs damage taken | -0.196 | **-0.202** |
| damage/turn vs turns | -0.234 | **-0.244** |
| trigger-deck taken R^2 | 7.2% | **7.5%** |

Verified on the deployed site rather than the data alone: the run's damage tooltip
reads 56.2, and the page's own JavaScript agrees with Python to ten decimal places
(`f_str 21.0692520444`). Worth remembering when checking a deploy: changing only the
URL hash does not reload the page, and a stale bundle looks exactly like a broken
fix.

Still open, and deliberately not bundled in: `f_vuln` guesses 0.571 uptime against
0.15 measured, inflating the damage line by 1.29x. That is a calibration change
needing a decay and targeting model, not a bug with a single right answer.

### How Vulnerable actually works (confirmed, 2026-11-01)

Base is +50% damage taken. It covers the turn it is applied in; with 2 or more stacks
it rolls into the next turn and steps down by one each turn. So K stacks bought on a
turn covers K turns, and the expected coverage of a card you see with frequency
`share` is `min(1, stacks x share)` -- which is what the formula already computes.
The term is not the wrong shape. It over-states the payoff because it assumes every
attack in those turns lands on the debuffed target. Some cards also modify the
effectiveness, which the model does not carry at all.

The measurement now weights by damage rather than by turns: a hit counts as boosted
only if its own target was Vulnerable at that instant, tracked from the power events
and rebuilt from each turn's opening snapshot.

### The debuff-effectiveness cards, which the data had all along (2026-11-01)

Three cards change what Vulnerable and Weak are worth, and the cheap formula used a
hard-coded 50% and 25% for every deck:

| card | what it does | in the data | consumed by |
|---|---|---|---|
| Cruelty | Vulnerable enemies take an extra 25% | `vulnBonus` | the simulator only |
| Tracking | Weak enemies take 50% more from Attacks | `weakBonus` | the simulator only |
| Debilitate | Vulnerable and Weak twice as effective for 2 turns | **nothing** | nothing |

- `predict_fights.formula_rows` (the cheap formula behind the Runs page) ignored all
  three, so a deck with Cruelty read as if its Vulnerable were the plain 50%.
- **Debilitate had no flag at all.** Its power returns `amount + (amount - 1)` from
  `ModifyVulnerableMultiplier`, which doubles the bonus rather than adding to it --
  a shape the extractor's value-adding pattern did not cover. It now sets
  `debuffDouble`, and it applies to the enemy, so the check runs before the
  self-only filter. Missing that filter was why the first attempt showed nothing.
- The formula now reports `f_vuln_bonus` (0.5 plus any Cruelty), `f_vuln_double`
  (Debilitate's uptime) and `f_weak_bonus` (Tracking), and the damage line uses all
  three. Python and the page's JavaScript agree to ten decimal places on a deck
  built to hold both: **43.2** either side, bonus 0.70, doubling 1.00.
- Nothing moves on the 20,657-fight harness (taken R^2 stays 9.0%, turns 10.9%)
  because these cards are rare in that dataset and the base case is unchanged. The
  point is that a deck holding them is now read correctly rather than as a plain
  Vulnerable deck.

### A guard for the bug that kept happening (2026-11-01)

Three bugs in one session had the same shape: **the game data carried a fact and the
cheap formula never looked at it.** Relic Strength (returned, then dropped), Cruelty
and Tracking (`vulnBonus` / `weakBonus`, read only by the simulator), Pyre
(`maxEnergy` rather than a `turnEffect`, so invisible). The extractor was ahead of
the formula and nothing checked.

`test_data_coverage.py` closes that. Every flag in the extractor's vocabulary
(`power_curve.RULES` and `DMG_RULES`) must be either:

- **read** -- the name appears in `predict_fights.py`, or
- **in `NOT_READ`** -- it changes how a fight is *simulated* (replays, free plays,
  where a card lands) and a per-turn average cannot price it, or
- **in `KNOWN_GAP`** -- the data has it, the formula does not read it, and nothing
  design-wise stops it being fixed.

An unlisted flag fails the test with the flag named and the three ways to resolve it.
A second test pins `MUST_BE_READ` -- the flags whose absence has already produced a
wrong number -- so they cannot quietly stop being read, and a third keeps `KNOWN_GAP`
visible so a gap cannot be quietly reclassified as unmodellable.

Its first run found two real gaps, recorded rather than hidden:

| gap | what it would move | cards |
|---|---|---|
| `handDraw` | `f_seen` -- extra cards drawn next turn | Glow, Guiding Star, Plot, Predator, Relax |
| `orbHooks` | `f_block` and `f_dmg` for orb decks | Coolant, Hailstorm, Loop, Lightning Rod and 5 more |

Verified it bites: deleting the `vulnBonus` reference from the formula fails two
tests and names the flag.

### How close the ceiling is to real play (2026-11-01, one run, 23 fights)

The lines are ceilings -- what the deck could put into one job in a turn -- so they
read high by design. Measured against the first run's telemetry, by how much:

| per turn | projected | real | median share of the ceiling used |
|---|---|---|---|
| damage, per target | 31.8 | 27.1 | **67%** (mean 86%) |
| block | 15.3 | 8.7 | **52%** (mean 54%) |

- **The spread is the honest weakness, not the level.** Damage runs 34% to 319% of
  the ceiling across the fights; over the ceiling in 7 of 23. Block runs 0% to 154%.
  The projection moves smoothly with deck contents; real output is lumpy -- burst
  when a fight demands it, near nothing when it doesn't, and a block line nobody
  draws from on a turn they don't need block.
- **Direction is what holds.** Over the run the damage ceiling goes 24 -> 56 while
  the real figure goes 13 -> 62; both climb. For "is this deck getting stronger",
  which is the question the four buckets exist to answer, that is the signal.
- **Ranking is moderate**: rho +0.64 on damage, +0.53 on block, so fights are ordered
  roughly right even where the level is high.
- The 0.67 and 0.52 are plausible calibration constants, and fitting them on one run
  would be exactly the overfitting this file keeps warning about. They need several
  runs before they mean anything.

`telemetry_report.py` now prints these, so the question is answered by the tool
rather than by hand, and the Runs page caption says what the lines are.

### Second run, a Silent deck: the block line was missing most of its block (2026-11-01)

Run 1793569704, Silent, 26 fights. Its block line read 9.7 a turn against 12.9 measured
-- not a ceiling at all but an under-estimate, over the line in 17 of 26 fights, with the
ranking backwards (rho -0.35). Cause: **42% of the block that run gained came in one-point
payments**, 821 of them at 1 block apiece across 727 plays. That is Afterimage, a Power
that pays block for every card played, and the formula had never read it: the game data
has carried `triggers: [{block: "Amount", on: "play"}]` all along, and `numeric_row` put
it in `bpc` -- which `formula_rows` consumed only behind `PF_ATK=1`, an experiment into
whether trigger terms help the *fit*. They don't; that says nothing about whether the
block is real, and it was 42% of the run.

Block paid per event is now counted unconditionally in `f_turnblock` (`per_block`), for
cards and for relics. The other event payments stay behind the flag, because those were
judged as fit terms.

Two bugs fell out of turning it on:

- **Every trigger was paid twice.** `numeric_row` computed which event a trigger counts
  (`event`) and never compared it, so `("block", "card")` and `("block", "attack")` both
  matched every block trigger: Afterimage read as 1 block per card *and* per attack, Rage
  as 3 of each. Now `stat[1] != event` skips the key that isn't the trigger's event.
- **Conditional triggers were being paid unconditionally.** DanseMacabre's cost floor and
  Spirit of Ash's Ethereal keyword pay some plays and not others, and a deck's play count
  cannot say how many. A block trigger is only read when it has no condition on it beyond
  `type` and `every`; the rest are left out and the loss is noted here rather than guessed.

After the fix, over both runs (49 fights):

| per turn | projected | measured | median share of the line used |
|---|---|---|---|
| damage, per target | 30.6 | 28.1 | **77%** (mean 91%) |
| block | 13.7 | 11.0 | **69%** (mean 87%) |

Per run, and this is the part that keeps the caption honest: Ironclad uses 67% of the
damage line and 48% of the block line; Silent uses 83% and 106%. A defensive deck spends
what the block line says it has, an aggressive one doesn't. One number for both would be
a lie, so the caption gives the rough range and says it varies by deck. `validate_floors`
moved 9.0% -> 9.1% on damage taken and 10.9% -> 11.0% on turns: the correction costs the
fit nothing.

Known gap from the same run: **an upgraded Afterimage still reads as 1 block a proc.** The
card data gives the power's amount as a name (`amounts: {Afterimage: AfterimagePower}`),
not a number, so `num(amt, 1)` falls back to 1 and the upgrade never reaches the row.

### The hand check was wrong about Silent, not the data (2026-11-01)

The first look at the Silent log reported 92 self-check failures in 220 turns. All 92 were
the checker's fault. It compared the hand the snapshot states at the turn's opening against
every card that moved into the hand during the turn, so it called a Shiv from Up My Sleeve
a contradiction (it arrives after the snapshot), and it demanded a Retain card be drawn
again on the next turn (it never is).

The check now follows the hand card by card across the whole fight -- arrivals on a pile
move into the hand, departures on a move out -- and compares it to the snapshot at both
boundaries. It is stricter than before and it passes: 0 problems on 49 fights, 326 + 184
damage taken accounted for exactly, 0 turn-count mismatches.

### Ground truth first: the fight measured from the enemies (2026-11-01)

The projection stopped being the headline. What a fight cost and what it returned can be
read off the game's own numbers, and the demand side is not a guess at all -- it is the
encounter's HP and the moves its enemies were recorded on.

**Damage is HP removed, not hit events.** In the Silent run our hits accounted for 4,267 of
the 4,407 HP the enemies lost; the other 3% arrived with no attacker attached (poison and
friends) and the killing blow was being dropped entirely by an earlier "hp is now 0" branch.
That one branch made every won fight look like it removed about 10% less HP than stood
there, and it is the kind of error that makes a strong deck look weak.

Three facts the HP deltas forced, none of which may be averaged away:

- **A sentinel.** Waterfall Giant logs 1,000,000,259 HP removed. Anything within a million
  of that is the game saying "infinite", not damage.
- **Spawns and heals.** Axebots took 249 damage on a 71 HP body, Ovicopter 176 on 127:
  more removed than stood there. That is an encounter fact (`spawned`), not a missing log
  entry, and a fight whose removed total falls *short* of its pool in a fight that was won
  is the one worth flagging.
- **Self-damage.** HP the deck pays itself is not the log contradicting itself. Without the
  split, every Ironclad run with Offering or Bloodletting reads as broken.

**The demand side is exact.** Every move a fight records resolves to a monster in
`power_data.json` -- 217 of 217 on the Silent run -- so `intent` is the damage aimed at us
that turn, and `attacker_turns` is what killing first bought. Phantasmal Gardeners: 208
intent over 11 turns, 111 answered with block or HP, **97 cancelled by killing**. Nearly
half the damage aimed at the deck never existed.

**Per turn is a distribution, not an average.** Soul Fysh goes 2, 6, 10, 63, 2, 21, 15, 31,
5. Its halves average to 12.8 and 27.0, which reads as "the deck doubled" and is an artifact
of one 11-card turn landing in the first half. Damage a turn is now reported as median, peak
and idle turns, and the run shows it: the Silent deck went from 10.6 HP removed a turn at
floor 2 to 73.1 at floor 48, with a median of 50 and a peak of 182 on Aeonglass.

**Read against your own record, not a target.** Section 5 sets each floor beside every run
in the data that fought the same encounter: median turns and median damage taken. That run
totalled 127 turns against a usual 128 -- but the shape is the story: 11 turns on Phantasmal
Gardeners against a usual 5, and 1 turn on Decimillipede against a usual 4. Slow while the
deck was small, ahead of the pack once it was built, which is the power curve the page has
been trying to draw all along.

**Junk counts.** Enemies insert statuses that occupy draws: 14 in one Entomancer fight, 6
across Soul Fysh, 33 in the run. It is measured per fight so a weak fight caused by junk is
not mistaken for a weak deck.

### Damage we did to ourselves was counted as damage we dealt (2026-11-01)

The Ironclad run had 88 hits logged with the player as both attacker and target: Bloodletting
paying 3 HP. Two things went wrong with them, and together they are the answer to "30 damage
a turn seems way too low".

- They were counted as **damage dealt**, because the hit branch only looked at who attacked.
- They were appended to the turn's **target list**, and damage per target divides by the
  number of targets. A turn that hit one enemy and played Bloodletting was therefore divided
  by two. The Ironclad run read 27.1 damage a turn; with the fix it reads 43.4, and the
  Silent run barely moved (29.0 -> 30.7) because it played three self-damage cards all run.

Damage taken is split the same way: the Knowledge Demon's curse deals 6 a turn with the
player as the source, which is a status doing its work, not the boss. Counting it as enemy
demand made 99 points of boss hits look like 175.

### Expected against faced: the encounter's average, and what actually arrived (2026-11-01)

Section 4 now carries four damage numbers per fight, and they answer different questions:

| column | what it is |
|---|---|
| a turn | HP removed from the enemies a turn, with its median and peak |
| aimed | what the living enemies' recorded moves would deal, with their Strength |
| faced | what actually arrived: blocked plus taken, enemy hits only |
| could | the enemies' whole move list averaged, times the turns the fight took |

`aimed` beats `could` for accuracy -- the recorded move is what the enemy was on, while
`could` assumes its moves come round evenly -- but `could` is what makes two floors
comparable and what gives a three-turn fight a fair reading, since a fight that ends early
never shows you the enemy's later turns.

`faced` below `aimed` is the deck working: killing an enemy before it acts, or keeping it
Weak. Phantasmal Gardeners: 26.9 aimed a turn, 10.1 faced, the difference cancelled by
killing four bodies before they acted. Knowledge Demon: 13.5 aimed, 9.9 faced -- one boss,
so the gap there is Weak, not killing.

With self-damage split out, the Knowledge Demon fight closes exactly: 99 points of boss hits
plus 76 from the curse is the 175 that originally looked unexplained.
