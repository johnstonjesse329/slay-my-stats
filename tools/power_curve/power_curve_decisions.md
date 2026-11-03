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


## On the site (js/deck-strength.js, since removed)
The estimate came off the page on 2026-11-01; see "One reading per fight" at the end. What follows is how it worked, and the tools stay for patch-day work.

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
that turn, and `attacker_turns` is what killing first bought. Phantasmal Gardeners: 156
intent over 11 turns, 111 answered with block or HP, **about 45 cancelled by killing**.
Nearly a third of the damage aimed at the deck never existed. (This first read 208 and 97,
until the move lookup was fixed; see below.)

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
Weak. Phantasmal Gardeners: 14.2 aimed a turn, 10.1 faced, the difference cancelled by
killing four bodies before they acted. Knowledge Demon: 13.5 aimed, 9.9 faced -- one boss,
so the gap there is Weak, not killing.

With self-damage split out, the Knowledge Demon fight closes exactly: 99 points of boss hits
plus 76 from the curse is the 175 that originally looked unexplained.

### Is the deck keeping up: the fight's demand against the last five fights (2026-11-01)

*The last five fights, the half turn, the usual share stopped and what ended the turn were all
dropped the same day; see "One reading per fight" below. The band tables in this section are
last-five figures and don't apply to the page as it stands. The findings on moves, pets,
co-op scaling, ascension and patches still hold.*

The four buckets stay; the fitted projections do not. `fight_demand.py` gives each encounter
a pool, a damage coming in, a usual length and a usual share stopped, and the Runs page sets
the run's last five fights against the fight on that floor. Damage and block have an enemy to
read against. Cards and energy do not, so their chart says which ran out, and only a run with
an event log can tell. Checked on 12,814 solo fights with 802 deaths and 3,446 co-op fights with
176 party wipes (`fight_demand.py --check`). The baselines include the fight being scored, which
flatters them slightly.

**A review of the moves found the numbers above wrong.** 39 of 260 move ids are shared between
monsters and 21 of those deal different damage, and the lookup kept whichever was read last.
It is now keyed by encounter and move. Phantasmal Gardeners went from 26.9 aimed a turn to
14.2 (Silent) and 33.0 to 16.0 (Ironclad), and Terror Eel's `could` from 17.7 to 6.2. The
report was also printing `enemy_net` as HP removed, so Test Subject read 100 and not 600; the
site never used that figure.

**Damage is read as a ratio, not a predicted result.** Estimating turns or HP lost scored
worse than quoting the encounter's usual (turns off by 1.21 against 2.14 to 2.6, HP by 9.54
against about 21), so the page says how recent output compares and never predicts a number.

| recent damage / what this fight asks | fights | died here |
|---|---:|---:|
| under 0.5 | 888 | 17.2% |
| 0.5 to 0.7 | 3,126 | 9.5% |
| 0.7 to 0.85 | 2,671 | 6.5% |
| 0.85 to 1 | 2,234 | 3.8% |
| 1 to 1.2 | 1,902 | 2.8% |
| 1.2 to 1.5 | 1,299 | 1.8% |
| 1.5 to 2 | 578 | 2.4% |
| 2 and up | 116 | 1.7% |

**Add the window up before dividing.** A fight won in t turns is t - 0.5 turns of output,
because the last turn stops at the kill. Averaging each fight's rate then gives a first-turn
kill a rate of twice its pool: Terror Eel, 140 HP in one turn, read as 280 and held the
Ironclad's line at 88 from floor 15 to floor 27. Adding up HP and turns reads the same five
fights as 45. Neither predicts better (AUC for death 0.686 against 0.680, and a median of the
rates 0.681); this one simply has no spike.

**Block is read as a share, in its own units.** Block a turn is capped by need, so block over
damage in means nothing. The share stopped, 1 - taken / ((t - 1) x in), is what holds up.
Against the usual share, the overall bands are muddled because bosses have low usuals, but
within a kind it sorts (under 0.7, 0.7 to 0.85, 0.85 to 1, 1 and up): monsters 4.6, 3.7, 2.8,
1.4% died; elites 14.0, 7.9, 8.5, 6.6%; bosses 23.7, 24.5, 25.6, 15.9%. That difference is
why each bucket has its own chart and there is no shared ratio axis.

**What the demand side had to learn:**

- **Pets are in `monster_ids`.** Osty, Pael's Legion and Byrdpip sit beside the enemies, two
  of them on a placeholder 9999 HP. They are excluded. Other ids outside an encounter's
  roster are real bodies (Fabricator's bots, Tunneler's bowlbugs) and stay.
- **Content comes and goes.** Doormaker is not new, it was removed: 93 fights on v0.98.3 to
  v0.103.2, none in the 567 runs since, and not in the source we recovered, so no logged fight
  will ever fill it in. Those floors get no dot and stay out of the window. A new enemy gets
  the same treatment until the data is refreshed, and then `logged_pools` or the game data
  fills it. `fight_demand.py` prints every monster with no HP and every placeholder HP it
  sees, because `PETS` is a hand-written list and a new character's pet would otherwise read
  as a wall of HP.
- **Test Subject has no HP field**, so its phases are written out: 600, or 636 on Tough
  Enemies.
- **A negative usual is no figure.** Bygone Effigy takes more than its moves explain, so its
  usual share stopped falls below nothing and it gets none rather than a wrong one.
- **`in` adds every body**, so it reads high on multi-body fights.

**Co-op reads per player, the same way.** Hiding it was wrong: the game's own scaling is exact.
An enemy has HP x players x a step (`Creature.ScaleHpForMultiplayer`,
`MultiplayerScalingModel.GetMultiplayerScaling`): 1.1 in act 1, 1.2 in act 2, 1.2 in act 3 and
1.3 for act 3's boss. So three players face 3.3x to 3.9x the HP, and each player's share is the
solo pool x that step, with the player count cancelling. Attacks hit every player by default,
so damage coming in per player is the solo figure. Enemy block and powers scale too and are not
counted. Same encounters against solo, median per encounter (not controlled for ascension):

| kind | party | encounters | fights | turns vs solo | taken a player vs solo |
|---|---:|---:|---:|---:|---:|
| monster | 2 / 3 / 4 | 56 / 51 / 43 | 1,293 / 794 / 590 | 1.18 / 1.17 / 1.20 | 1.01 / 0.88 / 0.86 |
| elite | 2 / 3 / 4 | 12 / 12 / 11 | 282 / 240 / 113 | 1.18 / 1.20 / 1.17 | 1.11 / 1.01 / 0.89 |
| boss | 2 / 3 / 4 | 13 / 12 / 12 | 272 / 185 / 137 | 1.14 / 1.14 / 1.24 | 1.06 / 0.78 / 0.70 |

Fights do not get longer with the party, and the extra 14 to 24% is what the step predicts. An
encounter gets its own co-op usual from 5 fights and borrows solo's below that. The damage
reading stands up: 19.2, 9.3, 3.6, 2.5, 1.7, 0.7, 0, 0% of fights ended in a wipe across the
same bands as the table above. Share stopped is thinner (8.6, 8.9, 3.9, 1.4% from under 0.5 to
0.85 and up). Limits: a run file has no damage per player, so the line assumes the party splits
it evenly, and a carry and a support read the same. A wipe is one event for the whole party.
Support from other players (block, Strength) is in the numbers without being attributed. The
page ignores logged numbers on a co-op run for now: the mod marks every player as `you`, so a
log could blend the party, and there is no co-op log to check that against. Pools come from solo
logs only, as a co-op log's HP has the party in it.

**Ascension.** Tough Enemies (8) and Deadly Enemies (9) pick their own columns on both sides.
A log carries no ascension, so `load_logs` reads it off the matching run file and picks the
move table with it; a log with no run file reads base. No logged run at 9 or up exists yet, so
that path is tested on made-up moves only.

**Double Boss (10) needs nothing today.** The second boss is its own map point straight after
the first, a different boss from the act's list, with no rest site between. So it already reads
as two floors and the second one's window holds the first. On solo A10 final acts: first boss 25
fights, median 7 turns, 42 taken, 6 ended on 0 HP; second boss 19 fights, median 7 turns, 34
taken, 7 ended on 0 HP; median healed 6 on both. HP carrying over is not part of the reading,
and the second boss's deaths may lean on that as much as on the deck. The turn-level reading
is TBD: there is no A10 run with the mod enabled yet.

**Patches barely move the usual.** It pools every build. Of 81 encounters with 10 solo fights
either side of v0.107, 10 have a median length off by 25% or more, and every one of those is a
turn or less, a short fight stepping from 4 to 5. None moved by 2 turns. Enemy HP and moves
come from a data refresh after a patch; the usual catches up as runs come in.

**Damage taken in the run file includes what you did to yourself.** It equals the log's
`taken` plus `self_taken` exactly (510 = 373 + 137 across 21 differing fights). So on a run
with no log, share stopped reads low for a self-damaging deck.

**What ended the turn.** Non-final turns are classed by whether energy or cards ran out, or
both at once (even), or cards were held with energy left. On 170 turns: energy 120, cards 7,
even 18, held 25 (Ironclad 62/9/13/16%, Silent 76/1/9/14%). This uses list price, so a
temporary cost cut or a Star cost is not seen. Free plays were 0 in both logged runs. Two runs
and 49 fights is all it stands on, with no outcome evidence yet: it says which ran out, not
whether that predicts anything.

**Open.** 56% of solo boss fights read under 0.7, against 38% of elites and 22% of monsters
(68, 35 and 19% in co-op). The recent window can only show what weaker enemies had HP to absorb,
and it reads about x0.81 of the next fight's rate as the deck grows. Boss deaths do sit higher
there (23.1% against about 9.5% at 1 and up), so the reading is honest, but "falling behind" is
a harsh word for a fight most runs win.

### One reading per fight: the last five and the estimate come off the page (2026-11-01)

The Runs page had two boxes, Deck Strength by Floor and Keeping Up by Floor. It now has one,
Keeping Up by Floor, with three charts and a tooltip of its own on each. Every point is the fight
on that floor; nothing is averaged across different monsters. The question the page answers is
the one the data can: how many turns the fight took, what damage came in against what stopped
it, and their HP against your damage.

| Chart | Line | Dot |
|---|---|---|
| Damage per turn | your damage a turn | their HP over that character's usual turns on that monster |
| Damage in per turn | damage taken a turn | damage aimed at you a turn |
| Energy and cards per turn | cards drawn, cards played, energy played at list price | none yet |

**What was reversed, and why:**

- **The last five fights.** Five different monsters averaged say nothing about this one, and
  the log and the run file already say what this fight did. Each floor now reads its own fight.
- **The half turn.** t - 0.5 existed to add a window up before dividing. With no window it only
  inflated short fights, and the tooltip stopped dividing as it read (45 HP in 4 turns showed
  13.1). Damage a turn is now HP over turns, on both sides. Terror Eel's one-turn kill is 140.
  The last turn stops at the kill, so every rate reads a little low the same way, and that
  only mattered to an average of rates.
- **What ended the turn.** Out of energy and out of cards make no sense as a reading, because
  running out is always the goal. What matters is how much got played. `turn_ends` is gone.
- **Usual share stopped.** The gap between damage aimed and damage taken shows what was stopped
  directly. Block stays in the tooltip, split out from what never arrived.
- **The estimate.** Its toggle set a prediction from the cards held beside what the fights did,
  and the page is meant to show real data. `js/deck-strength.js` is deleted and `deck_strength.json`
  no longer ships. `export_strength.py`, `predict_fights.py` and `validate_floors.py` stay for
  patch-day work. One side effect: the old chart labelled actual energy and cards showed energy
  available and cards seen, and its drops to 0 were 1-turn fights with no value. The new chart
  shows what was played, and those floors have no false zero.

**Damage needs a pace.** A won fight takes all their HP, so HP against damage alone always keeps
up; only the turns vary. The pace is that character's usual turns on that encounter: 439 pairs,
median 21 fights, 99.3% of fights in a pair with 5 or more. Under `CHAR_MIN` (5) it falls back to
all characters. Co-op keeps its own usual.

**Damage taken is the line, not block.** Block a turn beat damage aimed in only 2 of 23 and 4 of
26 logged fights, yet 7 and 11 of those fights took no damage, because killing first and Weak stop
damage too.

**The bands, re-tested with `--check`.** 16,104 solo fights read, 814 deaths. `doing` is capped on
a lost fight, because the run file doesn't say how much HP came off, so a death in the fight says
little: "died here" isn't monotonic (9.7, 5.1, 4.7, 9.6, 3.9, 4.9, 6.2, 7.9% across the bands).
Losing the run soon after does sort:

| this fight's pace / usual | fights won | lost the run within 3 fights |
|---|---:|---:|
| under 0.5 | 102 | 33.3% |
| 0.5 to 0.7 | 1,456 | 24.0% |
| 0.7 to 0.85 | 3,046 | 21.2% |
| 0.85 to 1 | 567 | 13.4% |
| 1 to 1.2 | 5,160 | 15.1% |
| 1.2 to 1.5 | 2,840 | 12.9% |
| 1.5 to 2 | 1,077 | 12.3% |
| 2 and up | 1,042 | 9.6% |

Grouped, under 0.7 is 24.6%, 0.7 to 1 is 20.0% and 1 and up is 13.6%, so **0.7 stayed**, until
the words on the page changed (see "The story in the middle" below). 0.85 to 1
looks as healthy as 1 and up, but it is a small band and probably long fights, one turn slower
against a long usual (not checked by kind). The 1.0 line stays because "line above the dot" is the
chart's own rule.

By kind (under 0.7, 0.7 to 1, 1 to 1.3, 1.3 and up): monsters 27.3, 22.5, 16.1, 11.0%; elites 21.1,
19.8, 14.7, 11.5%. **Bosses don't separate** (4.4, 5.3, 6.4, 2.2% on 1,349 fights won). Few runs
are lost soon after a boss, and why it doesn't sort hasn't been looked into. Co-op, 4,286 fights and 178
wipes: monsters 25.2, 21.1, 13.8, 5.9%; elites 28.3, 13.5, 9.2, 8.3%; bosses 9.1, 2.5, 1.9, 0%.

So the chart describes how each fight went. It doesn't predict the death in that fight, and the
survival figures quoted for the last-five reading no longer apply.

**What the page leaves out:**

- Runs with no event log have no energy and cards chart, because the estimate was its only
  source. Only 2 runs show it today, and logged co-op runs skip it. Dots for it wait on enough
  logged fights per character and monster.
- On a run with no log, damage a turn is the fight's HP over its turns, so the line sits above
  the dot exactly when the kill was faster than usual. Damage aimed comes from the move list,
  which assumes moves come round evenly; logged runs use what was actually aimed.
- A lost final fight on an unlogged run has no damage figure of its own; its damage taken point
  stays. The line now drops to 0 on it: see "A death is a death".
- An abandoned run reads as lost on the page (`was_abandoned` isn't parsed), so its last fight
  has no figure either and plots 0 too. Python leaves abandoned runs out.

**Page against Python.** 10,308 fights on both sides, 0 differ, none on one side only. Event fights
used to be Python-only; see the next section.

### The two logged runs, tested against what the game wrote down (2026-11-02)

`test_real_runs.py` holds every v3 log on disk to the run file and the raw events. Turns, final HP
and enemy health are the guiding truth, because the game states them apart from anything worked
out here. It reads the gitignored `gamma_raw/` and `telemetry_raw/` at test time, finds the Steam
ID rather than naming it, writes no player numbers into the repo, and skips where the files are
absent. Today that is two Ascension 1 wins, an Ironclad and a Silent, 48 floors each.

What holds on both, fight by fight: 24 of 24 and 26 of 26 fights join a floor, and every fight room
in the run file is on one. Turns equal `turns_taken`. Taken plus self-damage equals the run file's
damage. The player's HP walks to the final HP with every healed point placed. `hit.unb` equals the
HP event's loss. All HP the enemies lost has a hit behind it, apart from Living Fog's bomb (4 HP),
which dies with the Fog, and enemy HP reaches 0 in every won fight. 440 of 442 block snapshots reconcile, and Blur explains
the other two.

The tests were broken on purpose to see they bite: each of the last 10 deliberate changes (an event
fight read from the wrong room, a dropped fight, a miscounted turn, a reversed verdict, an inverted
pace or guard, a band rounded to nearest again and so on) failed a test, and the clean run passed.

**What the real data corrected:**

- **Cards seen became cards drawn.** Hand plus drawn, which is what the chart's line is.
- **`enter` is the record of a card joining a pile, not `gen`.** `gen` doesn't fire for all of them.
  Why the Ironclad's log has the gap hasn't been worked out.
- **Pantograph's log order.** The opening snapshot already shows the healed HP and its `hp` event
  fires after, with d=25, so a walk of player HP has to go by the absolute `hp`, not add `d` up.
- **Events after a fight's `fight1` keep that fight's number until the next `fight0`.** They are the
  map, so anything that sums "this fight's events" has to stop at `fight1`.
- **Damage aimed now has Vulnerable in it,** with Strength, on living enemies' moves, and enemy
  turns count only where the enemy side opened, so a fight won on the enemy's own side (Waterfall
  Giant) has its turn.
- **Waterfall Giant's explosion is priced from the fight.** It builds a number every turn the fight
  goes on and deals it the turn after it dies. On the logged fight `STEAM_ERUPTION_POWER` read 15 on
  turn 2, rose 3 a turn to 45 on turn 12, and turn 13's `EXPLODE_MOVE` hit for 45. The move table has
  no number for it, so aimed reads the power off the last turn that showed it. Runs with no log still
  have no explosion in their aimed damage, because the run file doesn't carry the power.
- **What a fight adds to a move's number, read from the game's code and held to the logs.**
  Pressure Gun gains 5 each time it fires, not per Pressure Up. Multi Claw is 3 hits and gains one
  each time it lands; only one landed in the logs, so that growth is proved by a scripted test only.
  Every Skill played against a Prism adds the Vital Spark's amount as Tainted, added to each hit
  before Vulnerable; no logged turn had both, so that order is scripted only too. Brimstone gives
  you 2 Strength and each enemy 1 on your turn, after the turn's first snapshot, so aimed follows
  Strength and Tainted through your side. The Forgotten's Dread is priced at 13 (15 on Deadly Enemies)
  and its Dexterity on top isn't added; neither log shows it.
- **Moves that share an id in one encounter are told apart by max HP.** Six encounters hold two
  monsters with one id and different numbers. A Damp Cultist read as a Calcified one, 9 for 1, and a
  Magi Knight's Ram as a Flail Knight's, 15 for 10. Where the bands touch (small Slimes, 11 and 12)
  and in co-op, where HP is scaled, the first monster listed wins.
- **The extractor read two moves wrong.** Getters that set a local first hid Multi Claw's hits and
  Dread's damage. `power_data.json` changed in those 2 entries and no others.
- **Aimed is exact where the deck left the enemy alone.** 92 of 92 turns, 44 on the Ironclad and 48
  on the Silent. Those leave out turns where an enemy died first, was stunned, or changed move, and
  turns with Strength taken off or Weak on it. Those two go by arithmetic instead: all 12 turns of
  Strength taken off fit, and Weak is `int(hit x 0.75)`, multiplied with Vulnerable before rounding
  (16 x 0.75 x 1.5 = 18).
- **Thorns is the one thing arrived can have over aimed.** An enemy hit on your own side is it
  answering your attack, as a Toadpole does for 2. Nothing aimed it. That is why a Weak Spit of 2 x 3
  showed 8 arrived. It counts as damage in, which it is.

**Event fights live in a second room.** 167 fights across the history sit at `rooms[1]` behind an
event room (Battleworn Dummy, Dense Vegetation, Fake Merchant, Mysterious Knight behind The Lantern
Key, Punch Off). The timeline read `rooms[0]`, so the node had no turns and the page drew nothing
for them, and the Mysterious Knight dropped out of the Ironclad log's join. `run.py` now reads the
room with monsters in it for the turn count, and adds a `fight` field where that room isn't the
one `enc` names. `enc` stays the event, because it picks the map's icon and label. Runs already
stored lack `fight` until re-ingested, and the page treats them as it did before.

### The story in the middle: ahead, meeting or behind, act by act (2026-11-02)

A floor is one fight; the question is how a stretch of the run went. Each act now gets a card:
each fight against its own usual, then summed, so an act of hard monsters isn't behind for being
hard.

- **Damage is pace:** usual turns over turns. Only the turns vary in a won fight.
- **Block is guard:** (usual damage + 1) over (damage + 1). Usual damage is the usual damage a turn
  times the enemy turns of this fight, t - 1 for a won one. It stays like for like: the usuals come
  from the run file, which has self-damage in, so this reading does too, and the card says how much
  of it was your own.
- **Ahead and behind** are the top and bottom quarter of what history did on that act, solo and
  co-op apart, from 20 runs up (`BAND_MIN`). On an edge or between them is meeting. An act needs 3
  fights (`ACT_MIN`). The fight that ended a run isn't in it: every lost run would read behind for
  it.

**Does it mean anything?** Runs held out: the usual and the bands come from half the runs, and the
reading is of the other half. Run won, solo, damage down and block across (behind, meeting, ahead):

| | act 1 | act 2 | act 3 |
|---|---|---|---|
| damage behind | 0%, 8%, 22% | 0%, 23%, 50% | 18%, 45%, 92% |
| damage meeting | 9%, 23%, 35% | 6%, 33%, 72% | 52%, 70%, 76% |
| damage ahead | 6%, 37%, 58% | 38%, 54%, 64% | 91%, 88%, 88% |

Co-op sorts the same way: behind on both 0%, 0%, 23% by act; ahead on both 89%, 79%, 100%. Its cells
aren't independent, because players of one party share turns. Pace and guard barely overlap
(correlation -0.10, -0.13, 0.15 by act), so they are two readings and not one twice. By character
both-behind is near 0% everywhere; Defect, Necrobinder and Regent have thin cells. It describes the
act. It isn't a prediction. `test_runs_read_as_ahead_win_more_than_runs_read_as_behind` holds behind
on both under meeting on both under ahead on both, for every mode and act.

**Limits:**

- **Ascension.** The usual isn't split by ascension or scaled at A8 and up. A0 to 1 medians are pace
  1.00, guard 1.05; A2 to 7, 1.00 and 1.08; A8 to 10, 0.96 and 0.91. The floor ratio is unscaled
  too, so the two agree, and high ascension reads a little behind. That was this reading; the one
  on the page now has a line per tier, under "Built: winners on that fight".
- **Self-damage.** The Ironclad's act 3 reads behind on block with 55 of its 92 damage its own. All
  Ironclads' usuals have theirs in, so it's fair, but it says less about block than the word does,
  which is why the card shows it.
- **Abandoned runs** are read on the page, because their fights happened, and left out of the history.
- **The floor tooltip's words moved to match.** A fight's ratio now reads ahead, meeting or behind
  at two decimals, and the 0.7 line is gone from the page. Bosses never separated on it, as above.

**A band edge must be written outward.** Plenty of runs sit exactly on an edge, because turns are
whole numbers: Silent's act 1 is 48 turns against 54, which is 8/9, and 8/9 is the edge. Rounded to
3 decimals it became .889, the reading fell under it, and that run read behind for no reason. Across
history that moved 34 verdicts. Edges now go outward at 6 decimals, floor for the low one and ceiling
for the high one, and `test_writing_a_band_down_moves_no_verdict` holds it at 0.

**Energy and card draw get no verdict yet.** A usual needs history, and two logs can't give one, so
each act shows them against the game's base, 3 energy and 5 cards. Energy is at list price because
that catches direct and indirect energy alike; what was actually spent sits beside it. Both means
rise clearly by act, so a usual per character and act needs far fewer logs than one per monster,
and that is the likely baseline later.

**The two runs, as they read now** (damage, block, by act): Ironclad ahead/ahead, ahead/meeting,
ahead/behind. Silent meeting/meeting, ahead/meeting, meeting/ahead.

**Page against Python.** 1,562 act readings on 764 runs, 0 differ once abandoned runs are let in on
the Python side. Per-act fights, turns, cards played, energy spent and own damage match a walk of
the raw events, largest gap 0.03% from rounding.

### Is "the usual" the right ruler? Tested, and open (2026-11-02)

The objection: ahead and behind measure a run against what players did, not against what it takes to
win. A poison deck can need more turns and be doing fine, a shiv deck should need fewer, and a weaker
player on a losing streak may not get the right message. All of this is from the run files (turns,
damage taken, won or lost), solo, because only two runs have turn data and neither is a poison deck:
0% and 3% of the HP enemies lost came with no attack behind it. Nothing below measures a ramp.

**Builds: the objection holds.** Won runs only, share of acts read behind on damage: Ironclad Block
22%, Exhaust 8%; Silent Discard 31%, Shiv 0%. Median pace on won runs: Silent Poison + Discard 0.78
(93% of acts slower than usual, 15 acts, 5 runs), Shiv 1.10 (22% slower, 27 acts, 9 runs). So a deck
that won reads behind for how it wins.

**Weaker players: the objection holds.** Bands are quartiles, so a quarter of acts must read behind
and a quarter ahead however anyone plays, and the ruler has the player's own losses in it. 45% of
acts on lost runs show nothing behind, and 27% of acts on won runs show something behind. Damage
hardly separates the four players at all: behind 25%, 26%, 17%, 27%.

**Turns add nothing to the verdict.** How well each sorts run won (0.5 is a coin flip), each player
scored only against the other three, acts 1, 2, 3:

| Reading | act 1 | act 2 | act 3 |
|---|---|---|---|
| Pace | .65 | .60 | .63 |
| Guard | .71 | .73 | .73 |
| Pace × guard | .77 | .78 | .77 |
| Damage taken against what everyone paid on those fights | .79 | .81 | .80 |
| Damage taken against what winners paid on those fights | .74 | .79 | .77 |

Pace × guard is close to total damage taken against usual, because the turn count cancels. A slow
deck isn't really charged for its turns, only for what they cost it, and leaving turns out sorts as
well or better. That lets turns stop being a verdict and be a description of how a deck paid. It held
for sorting across all acts, but speed still adds at the top end: see "Speed can lift an act".

**A reading from the fight alone tested worse.** HP cost of a fight, lowest HP share and HP left sort
at .55 to .69, against .78. Absolute cost doesn't know how hard the fight was.

**What winners paid, as a line.** A sum of per-fight medians doesn't work with a line at 1.0: it sits
below typical act totals, so even won runs read over on 41% to 83% of acts. The middle half of
winners' act totals works. Each player read against the other three's winners, run won:

| Act cost against winners | act 1 | act 2 | act 3 |
|---|---|---|---|
| Over | 13% (634) | 19% (367) | 53% (179) |
| Inside | 38% (333) | 64% (218) | 82% (121) |
| Under | 49% (119) | 73% (79) | 88% (82) |

Lost runs read over 70%, inside 23%, under 7%. Won runs read over 31%, inside 46%, under 24%. So 30%
of acts on lost runs read not-over, against the 45% with nothing behind today. Silent builds on won
runs come closer together too: Poison + Discard over 13%, Shiv 26%, Discard 43%, Discard + Poison
50%, with small counts (12 to 75 acts).

**Ascension has to be in it.** Against winners the four players read over on 80%, 65%, 40% and 58%
of acts, with win rates of 0%, 8%, 22% and 30%. The 22% player reads better than the 30% one because
they mostly play A8 to 10 (177 of 269 runs) and beat the 30% player at every level the two share, so
win rate alone doesn't say who the weaker player is. A ruler with no ascension in it mixes this up.

**Limits.** This is still history, not game rules, though what winners paid answers a different
question from what people do. Four players, one with over half the runs, and about 70 wins outside
that player. A small poison sample. Co-op not tested. A real race, their HP against your damage and
your HP against what gets through, needs per-turn data on more runs, poison decks among them.

**Decided and built:** see "Built: winners on that fight".

### Kill speed and damage taken: is that enough? Tested, and open (2026-11-02)

The question: what does turn data add that the monster data can't say beforehand? Aimed damage keeps
needing another rule (Tainted, Thorns, reflect effects from cards and relics), when the real question
is how fast the fight dies and how much gets through. Card draw and energy vary by deck and may not
say much about winning.

**What the logs add.** Turns and damage taken exist on every run without a log. The run file's turns
match the log on all 50 logged fights, and its damage taken is exactly enemy hits plus the hits the
log puts down as your own: 135 of 341 on the Ironclad, 7 of 184 on the Silent. The logs alone hold block,
energy, cards played and drawn, and how much HP came off in a lost fight. No grade below uses them.
Energy and draw can't be tested against winning: only two runs have them and both won.

**The monster data alone against the logs.** Its flat rate times enemy turns gives 853 against 1,010
aimed on the Ironclad and 1,319 against 1,416 on the Silent. A fight is a median 29% and 16% off,
worst on fights that build (Waterfall Giant 108 against 181). Exact aimed doesn't tell you what
lands either: it is a median 38% off arrived on both runs, because killing first, Weak and stuns
stop it.

**How well each sorts run won** (0.5 is a coin flip), solo, each player read against the other
three, 1,086 runs and 2,132 acts. Pooled for acts 1, 2, 3, then acts of one player against that
player's own:

| Reading | pooled | one player |
|---|---|---|
| The page now, pace x guard | .77 .78 .77 | .77 .79 .79 |
| Winners' average damage taken, that fight | .68 .76 .74 | .72 .79 .79 |
| The same, that character where it has 5 or more | .73 .80 .76 | .76 .83 .79 |
| Winners' average damage a turn, that fight | .62 .61 .62 | .62 .62 .67 |
| Damage a turn and taken together, that fight | .69 .75 .73 | .73 .80 .80 |
| The same, that character where it has 5 or more | .73 .77 .74 | .75 .81 .79 |
| Taken against what comes in by a target turn, monster data only | .60 .74 .68 | .65 .77 .73 |
| That, with the act's HP over its turns | .67 .79 .73 | .71 .82 .77 |

Target turns there are the winners' median by kind of fight: monster, elite or boss. Comparing taken
with what came in over the turns actually played sorts worse (.53, .63, .62).

**Damage a turn on one exact fight is kill speed.** HP is the same, so only the turns vary, and
damage a turn sorts just as turns do (.61 to .65). Damage taken carries the sorting. Adding speed
to it gains nothing.

**An average is a comparison, not a pass mark.** Against winners' averages on that fight and
character, 77% of won acts read under on damage against 85% of lost acts, so that line says little.
54% of won acts read over on damage taken against 83% of lost ones, which does separate. Run won, by
act:

| Damage a turn, damage taken | act 1 | act 2 | act 3 |
|---|---|---|---|
| Over, under | 51% | 70% | 87% |
| Under, under | 39% | 70% | 84% |
| Over, over | 20% | 30% | 71% |
| Under, over | 18% | 28% | 59% |

So from act 2 a slow fight that cost little won as often as a fast one.

**Poison is why speed can't be graded alone.** Poison decks should be slower and take less if they
are working. Against the median and the slowest 1 in 10 of winners' turns on that fight, and winners'
average damage taken on it:

| | slower than the median | past the slowest 1 in 10 | over on damage taken |
|---|---|---|---|
| All won acts (798) | 59% | 8% | 54% |
| All lost acts (1,334) | 75% | 13% | 83% |
| Poison, won (33) | 94% | 30% | 39% |
| Poison, lost (53) | 79% | 13% | 83% |

Inside poison, speed sorts backwards (.36) and so does the slowest 1 in 10 (.35): the faster acts were
the likelier to lose. Damage taken sorts them at .81, against .74 for every other deck. Speed and
damage taken together give .73 for both, which is no better than damage taken alone. A line on speed
of either kind flags poison's wins more than its losses, so turns are read beside damage taken and
not graded. Being slow still costs nothing: see "Speed can lift an act", where speed only lifts.

It holds best on Poison + Discard: every won act slower than the median, 27% over on damage taken,
86% of lost acts over. In act 2, 9% of won poison acts read over against all 20 lost ones. It's
weaker on Discard + Poison (58% against 73%) and in act 1 (55% against 69%). Won Shiv acts are the
other shape, 37% slower than the median. Neither logged run is a poison deck, so nothing here says
how the damage was stopped.

**A character moved this; a split at A8 didn't.** By act and kind, 89% of won Ironclad Block acts read
over on a shared line and 69% on Ironclad's. The logged Ironclad shows one reason: 40% of its damage
taken in fights was logged as its own, against 4% on the Silent. A split by ascension moved nothing by more
than .01 on averages by act and kind. 70% of fights have 5 or more winners' fights for that
character, and the rest use that encounter's. Neither held. That split only asked whether ascension
sorts better, not whether a line should come from monsters tuned the same, and the page now has a
line per tier and none per character: see "Built: winners on that fight".

**Limits.** Same as the ruler above: history, four players, co-op not tested. Poison is 86 acts from
40 runs, 11 of them won, by one to three players a build, and a build's name comes from its final
deck.

**All inbound damage stays in, whatever its source. Decided 2026-11-02.** Each fight is compared with
the same fight and character, so the source evens out, and one number averages simply. A run file has one damage taken and no field that splits
it, so only a logged run can take it out, and winners' averages come from run files. Taking it out of
a logged run alone moves the Ironclad's acts from .95, .71, .90 to 1.35, 1.07, 2.20 against those
averages, which is the comparison changing and not the deck. The Silent's move by .04 at most. It isn't
all the player's choice either. It holds Bloodletting (51 HP on the Ironclad), and also status cards
enemies add, Beckon from the Soul Fysh and Wither from the Aeonglass, which the game logs as your own.
The chart's line on logged runs is enemy hits only, which would change to match.

**Checked before building (2026-11-02).** 1,098 solo runs, damage taken on that fight and character,
each player read against the others.

Where ahead and behind could sit, as run won and share of acts:

| Reading, winners' average over yours | Act 1 | Act 2 | Act 3 |
|---|---|---|---|
| Behind, under .75 | 12%, 51% | 19%, 53% | 51%, 43% |
| Meeting | 34%, 38% | 59%, 33% | 80%, 33% |
| Ahead, over 1.33 | 47%, 12% | 72%, 14% | 88%, 25% |

Tighter, under .8 and over 1.25, about half of acts read behind: 57%, 59%, 46%, with 14%, 21%, 53% of those
runs won. Wider, under .67 and over 1.5, behind is 40%, 43%, 35% of acts with 8%, 14%, 44% won, meeting is
33%, 58%, 82% won, and ahead is 48%, 67%, 86% won. The line is winners' average, so a tight band calls many
winning acts behind.

- **One fight is noisy.** A single fight sorts at .59, .65, .64 against .73, .80, .76 for an act. Winners'
  middle half on a typical fight runs from 4 to 18 around a mean of 11. A verdict belongs on the act.
- **Split at A8 on the exact fight it sorts .73, .79, .77.** That says nothing about whether monsters
  tuned differently belong on one line, and they don't: see "Built: winners on that fight".
- **The winners are mostly one player:** 73% of winners' fights, then 23% and 4%. The fourth player has no
  wins.
- **By player, read behind under .8:** won acts 40%, 8%, 42%, lost acts 79%, 44%, 69%, and 71% for the
  player with no wins.
- **The reading says where a player stands and doesn't soften it (the user, 2026-11-02).** A deck that is
  behind reads behind, and a player who wins shouldn't read behind just for sitting near an average. So the
  line is what winners took on that fight, never the player's own history.
- **With a player's own runs in the line, as the page would have them,** each run left out of its own line.
  Behind under .67, won acts then lost acts, by player: 11% and 47%, 6% and 36%, 21% and 50%, and 62% for the
  player with no wins. Under .8 the first player's won acts read behind 25% of the time, and with their
  runs taken out of the line, 22% under .67. Their runs make the line easier for them, because they are
  most of it.
- **.67 is about where winning acts stop.** 1 in 10 won acts read under .69, .64, .59 in acts 1, 2, 3, so
  under .67 means worse than roughly 9 in 10 winning acts.
- **Coverage is fine:** 40 of 15,335 fights have no line.
- **Co-op looks workable, not tested properly.** One player's act against solo winners, median .69 on lost
  acts and 1.04 on won.
- **Patches are not tested.** The line mixes 17 builds.

**Decided and built,** without the per-character line this tested and with a line per tier: below.

### Built: winners on that fight, by how the monsters are tuned (2026-11-02)

This replaces the ruler questions above. The wording and the band edges are drafts until the user OKs
them.

**The line.** For each encounter and tier, the average of winning runs, any character: turns, damage
taken, and damage taken a turn. It takes 3 wins on that encounter and tier to make a line. With no
line a fight gets no mark on the charts and stays out of its act's reading. Co-op has its own lines
from co-op wins, which only exist under 8. An act adds up each fight's own line and reads winners'
damage taken over yours: under .67 is behind, over 1.5 is ahead. Killing much faster can also lift an
act to ahead, and being slow never sinks one: see "Speed can lift an act". A behind act names what
was lacking from the same two numbers: damage if the fights ran long, block if too much came in each
turn. Energy and card draw are shown and not graded. All inbound damage stays in, as decided above.

**The tiers are the game's.** Under 8, 8, and 9 and up, the user's split. Tough Enemies at 8 raises
enemy HP and Deadly Enemies at 9 raises their damage. Ascensions 1 to 7 appear in no monster file in
the game source, so a monster is the same from 0 to 7. Ascension 0 going with 1 to 7 was a call made
here, not the user's. A fight never borrows another tier's line. Nothing is tuned to the difficulty
spike itself: tiers come from how monsters are tuned and the lines rebuild from runs, so a patch that
moves the spike moves them with it.

**Win rates per ascension,** solo:

| Ascension | Runs | Won |
|---|---|---|
| 0 | 114 | 16% |
| 1 | 340 | 48% |
| 2 | 29 | 38% |
| 3 | 24 | 38% |
| 4 | 28 | 32% |
| 5 | 37 | 24% |
| 6 | 33 | 27% |
| 7 | 68 | 13% |
| 8 | 36 | 22% |
| 9 | 204 | 4% |
| 10 | 185 | 6% |

By tier that is 35% of 673, 22% of 36, and 5% of 389. The same two players drop from 43% of 47 at 5 to
8 to 8% of 169 at 9 and 10, and from 24% of 51 to 3% of 220. On the same fight and character, 9 and 10
against 5 to 8 run ×1.03 turns and ×1.11 damage taken (76 pairs).

**What the verdict is worth.** `--check`, solo, run won, each half of the runs read against the other:

| Tier | Behind | Meeting | Ahead |
|---|---|---|---|
| Under 8 | 23% (532) | 57% (681) | 79% (256) |
| 8 | 33% (15) | 67% (9) | 80% (5) |
| 9 and up | 4% (190) | 17% (158) | 28% (47) |

Under 8 it holds within every act: behind, meeting, ahead sort 16%, 44%, 62% in act 1, 21%, 61%, 83%
in act 2 and 45%, 83%, 93% in act 3. Ascension 8 is too few acts to read. Meeting at 9 and up means
matching winners, not good odds. Ahead there leads meeting in act 2, 43% (14) to 25% (32), and act 3,
86% (7) to 58% (12), and still trails it in act 1, 4% (26) to 11% (114).

**Thin tiers.** On the page, fights with a line: 8,869 of 8,870 under 8, 199 of 335 at 8 (59%), 1,949
of 2,519 at 9 and up (77%). Lines at 8 and up are also narrow: 2 players each, the biggest with 62% of
8 wins and 70% of 20. Under 8 is 3 players, the biggest with 79% of 238.

**One line, whoever played.** The user's call: what matters is what winning runs did, regardless of
who. Against a line per character, held out, before healing came off: under 8 behind goes from 18% won
(371) to 25% (467), meeting stays at 55%, ahead goes from 76% to 73%. Won acts under 8 read behind 17%,
up from 9%. Tiers 8 and up barely move. 81% of acts keep their verdict. The cost landed on one
character: winning Ironclad acts read behind 29% of the time, up from 10%.

**Healing comes off damage taken.** The user's call, from the lens of did I take too much damage per
fight: healing is "blocking" that amount after the fact. Each floor counts `damage_taken` less
`hp_healed`, down to 0, so spare healing doesn't carry to the next fight (`net_taken`, and `keepTaken`
on the page). That goes for the player and for winners' lines alike, and the label stays Damage
taken. All inbound damage still counts, whatever its source.

The evidence for it was the Ironclad. Winners on the same fight and tier, one character against
everyone else: Ironclad ×.89 turns and ×1.77 damage taken over 69 fights, Silent ×1.11 and ×.58 over
53, Necrobinder ×1.18 and ×.65 over 8, Regent ×1.00 and ×.72 over 15, Defect ×.97 and ×.81 over 22.
Ironclad heals 7.4 a fight floor in won runs against 1.0 to 1.4 for the others, which fits Burning
Blood's 6 HP after every combat. It wins by taking more and healing it back.

`hp_healed` is HP that came back. The game adds what was actually healed (`CreatureCmd.cs`), so
overhealing isn't in it, and gaining max HP is, because that heals you too. On solo runs HP walks floor
to floor on `damage_taken` and `hp_healed` alone on 30,909 of 30,911 floors that end alive. `hp_healed`
goes past `damage_taken` on 1,883 of 15,276 fight floors (12%), and those stop at 0. On a floor with
two rooms, an event then a fight (121 floors), the healing can be the event's; anything healed on the
floor counts.

| `--check`, solo | Before | Healing off, before speed lifted acts |
|---|---|---|
| Under 8: behind, meeting, ahead | 25%, 57%, 71% | 23%, 59%, 79% |
| 9 and up: behind, meeting, ahead | 3%, 16%, 31% | 4%, 19%, 22% |

It sorts better under 8. At 9 and up, ahead loses most of its lead on 37 acts. Winning acts read behind
more evenly: Ironclad 21%, Defect 20%, Regent 20%, Silent 10%, Necrobinder 6%, against 29%, 9%, 4%, 3%
and 2% before (the before figures from a probe's own halves). The middle reading of won acts is .98 to
1.01 for Ironclad, Defect and Regent, 1.17 for Silent and 1.20 for Necrobinder.

The cost is that Damage taken here isn't the run file's figure any more. The page says so three ways:
the caption, "after N healed" on the act card, and a Healed row in the hover box that keeps Arrived
less Blocked less Healed equal to Damage taken. The tie to the logs stays on the gross number: the run
file's `damage_taken` is enemy hits plus hits logged from the player to themselves, on all 50 logged
fights.

**Slow is safe.** Under 8, an act much slower than winners that held its damage taken won 59% (116),
against 32% (132) for an act that kept pace and read behind: ×1.8, up from 51% and 38% before healing
came off. Ironclad is still most of the second kind (94 of 132).

**About 1 in 6 winning acts read behind.** Under .67 catches 17% of won acts under 8 and 15% at 9 and
up, and 54% and 53% of lost ones. Under .6 would catch 11% and 13%, and 46% and 44%. The edges weren't
moved; that is the user's call with the wording.

**Speed can lift an act.** The user's call, from floor 48 of the logged Ironclad, the Test Subject
boss: 5 turns against winners' 9.7, 12 damage taken against 23.8. Plenty of block while trashing a
boss read meeting, because the verdict looked at damage taken alone; the card that said so was Act 3,
19 turns against 30.8, 44 taken against 55. "If we're not taking much damage and we're annihilating
enemies that signals ahead to me." So an act is behind on damage taken alone, and ahead on much less
damage taken (over 1.5) or on killing much faster without taking more: pace over 1.25, with damage
taken at or under winners' (`verdict`, and `place` on the page). Speed only lifts. Behind doesn't
change, so a slow deck that holds its damage taken stays safe.

The evidence: held out, solo, run won, pace down the side, winners' damage taken over yours across:

| Under 8 | under .67 | .67 to 1 | 1 to 1.5 | over 1.5 |
|---|---|---|---|---|
| Pace under .8 | 13% (159) | 44% (62) | 81% (36) | 67% (18) |
| .8 to 1.25 | 26% (352) | 50% (326) | 68% (219) | 74% (133) |
| 1.25 to 1.5 | 44% (16) | 59% (32) | 72% (32) | 95% (41) |
| Over 1.5 | 60% (5) | 83% (6) | 100% (11) | 90% (21) |

| 9 and up | under .67 | .67 to 1 | 1 to 1.5 | over 1.5 |
|---|---|---|---|---|
| Pace under .8 | 2% (47) | 13% (23) | 31% (13) | 0% (3) |
| .8 to 1.25 | 4% (136) | 11% (65) | 22% (45) | 21% (29) |
| 1.25 to 1.5 | 0% (7) | 30% (10) | 50% (8) | 0% (1) |
| Over 1.5 | - | 0% (2) | 50% (2) | 50% (4) |

Rules tried, meeting then ahead, behind fixed at 23% and 4%:

| Rule | Under 8 | 9 and up |
|---|---|---|
| Damage taken alone | 59% (724), 79% (213) | 19% (168), 22% (37) |
| Pace over 1.5, taken at or under winners' | 58%, 80% | 19%, 23% |
| Pace over 1.33, the same | 58%, 80% | 17%, 29% |
| Pace over 1.25, the same (built) | 57% (681), 79% (256) | 17% (158), 28% (47) |
| Pace over 1.5, guard over .67 | 58%, 80% | 19%, 22% |

1.25 mirrors the .8 already used for much slower, which is why it won over its neighbours, but it was
picked after seeing these rates, so it isn't a clean test. The floor of 1 keeps a fast act that took
more than winners at meeting. 53 acts lifted, 74% won: 79% of 43 under 8, 50% of 10 at 9 and up, and
55% of 20, 75% of 20, 100% of 13 by act. Ironclad is most of them, 79% of 34, then Defect 75% of 8,
Silent 67% of 6, Regent 67% of 3, Necrobinder 0% of 2. Of 75 poison acts, 1 was lifted, and it won.
Under 8, ahead now catches 7% of lost acts, up from 6%, and 28% of won ones, up from 24%.

Each graded row has its own mark, so Turns to kill and Damage taken can read differently from the act.
On a behind act Damage taken is always down by definition, so what was lacking is told by the Turns
row and the hover text on the act's mark. Those two can differ on a rare edge, because lacking compares
pace with damage a turn while the mark compares pace with .8.

**Multi-enemy.** The user's rule: more than one target is possible at a time, whenever in the fight,
and not an enemy that replaces one that died. The hover box names the kind of fight, Elite or Boss
plus Multi-enemy or Single enemy, so a bad fight can be read as a lack of damage to many targets or
unlucky draws for them.

`monster_ids` on a room holds it, with a catch. The game lists every slot of the opening line-up,
repeats and all (`CombatRoom.cs`), then adds an enemy that joins only if its id isn't listed yet
(`CreatureCmd.cs`). So a replacement on the same id never adds. Runs up to v0.103.3 list only the
opening line-up; v0.106.1 on list spawns too, and nothing in the history falls between, hence
`SPAWNS_LISTED`. `many_targets` takes the longest list across an encounter's fights on those newer
versions, and all fights if it has none. It is set per encounter and not per fight, because "possible"
is about the fight: a Fabricator killed before it built anything still reads multi. 44 of 90 encounters
read multi. Test Subject is one creature reviving through forms and Axebots replace one for one, so
both read single.

Against the logs, all 50 logged fights agree with what the mod saw alive: 21 multi fights had 2 or
more alive at a snapshot and 29 single fights never did. One known miss: the Axebots encounter opened
with two on v0.103 and earlier, and those 71 fights read single, because the encounter now opens with
one and the newer versions speak for it.

**A death is a death.** The user's call, once the last damage point of a lost run looked like missing
data: "we can at least project what was done in the fight before dying but a death is a death (just
shows closeness or not)", and if that's too hard, flatline it, which the user then spelled out: "0
damage done if we don't have turn-by-turn data or render what we know if we have it otherwise". A
logged death uses what was really done, HP removed over turns, with the turn the death cut off closed
at the end of the log. An unlogged death drops to 0 on that floor and the hover box says there's no
figure. All 483 lost solo runs with no figure plot 0, the 12 Doormaker deaths and a death in a run's
first fight among them. Doormaker has no HP in the data, so its row leaves Enemy HP off and has no
winners' icon. 4 more lost runs ended at Neow and have no fight to plot. No won run changes.

No real logged death exists yet: both logged runs won. `RunEndPatch` runs once at the end of a run, win,
death or abandon, so a death's log will carry its final fight. Whether `EventCombatEnd` fires on a death
isn't verified, so the parser doesn't need `fight1`. The `Death` test cuts both real logs off partway
through a fight, which stands in for that.

**A run as a whole.** The user's call: ahead, meeting or behind in the run's header bar and the run
list, so awesome runs and crappy runs are easy to find, with OP for ahead "in acts 2/3 across
everything". A run's act totals go through the same verdict, so it follows from the cards under it
(`run_reading`, and `runReading` on the page). The fight that ended a lost run stays out, as it does
from an act. No act to read means no reading: 20 runs on the page, none won, none past floor 20.

Held out, solo, run won. OP runs also count under the verdict their totals gave:

| Tier | Behind | Meeting | Ahead | OP |
|---|---|---|---|---|
| Under 8 | 8% (276) | 51% (323) | 75% (68) | 100% (33) |
| 8 | 23% (13) | 50% (4) | 67% (3) | 100% (1) |
| 9 and up | 2% (140) | 10% (114) | 20% (25) | 83% (6) |

Co-op under 8 reads 8% (308), 55% (366), 77% (82), and OP 100% (46). Other ways to read a run, behind,
meeting, ahead, won:

| Rule | Under 8 | 9 and up |
|---|---|---|
| Totals through the verdict (built) | 8%, 51%, 75% | 2%, 10%, 20% |
| Most of its acts | 10%, 44%, 77% | 0%, 11%, 21% |
| Its latest act | 13%, 50%, 79% | 4%, 8%, 21% |
| Its worst act | 23%, 57%, 45% | - |

The worst act puts ahead below meeting. OP on runs that reached acts 2 and 3, won:

| Rule | Under 8 | 8 | 9 and up |
|---|---|---|---|
| All of them | 74% (321) | 100% (6) | 47% (30) |
| Both acts read ahead (built) | 100% (33) | 100% (1) | 83% (6) |
| Both acts' Turns and Damage marks ahead | 100% (7) | none | none |
| All three acts read ahead | 100% (10) | none | 100% (4) |

"Across everything" could mean ahead on both measures, the third row. That gives 7 runs, none at 9 and
up, and bars a slow deck the verdict says is fine, so OP is the verdict on both acts, however it got
there (`OP_ACTS`, counted from 0). It takes no win: 1 of the 6 at 9 and up lost.

On the page OP is a pill by Victory or Defeat and a chip in a sortable "+/–" list column, green rather
than gold so it doesn't read as meeting. The list counts 31 OP, 33 ahead, 318 meeting, 362 behind and
20 with no reading. Reading all 764 runs takes about 2 ms and fetches nothing new. None of the user's
9 and up runs read OP: all 5 against the full line belong to another player. Their 6 wins there read
meeting on 4 and behind on 2. Taking a run out of its own line doesn't explain that gap; 9 and up stays
5 OP and 17 ahead either way. Held out shows 6 and 19 because half the history gives a different line.

The list is 40px wider for the column. The user wants it clean on phones, as much as possible in
portrait. It fits from 381 px up with tighter padding. At 380 px and under, upright, it drops the "M"
tag and the date's year and tightens further, which fits down to 320. The run's own header still says
MODDED, and a phone on its side has the full list.

**`held_out` reads both halves now.** It read one half against the other, which read half the runs and
let act 3's meeting and ahead cross by a point. Each half now reads against the other, so every run
counts.

**Wording.** Damage done and damage taken, always. HP only for a health pool. The reference marks are
map icons by kind of fight: monster, elite, and the boss's own portrait. The legend leaves all of them
out, as the user asked ("self explanatory"), and the caption says what they are, so the legend only
keys lines. An act card counts its fights the same way, on a line of its own under the act and its
mark: normal, elites, boss, with the fights the card's numbers cover. Readings are signals and not text: ▲ ahead, – meeting and ▼ behind on filled green, yellow
and red rounds, for the act and on Turns to kill and Damage taken, with what was lacking in the hover
text on the act's mark. The caption has a key too, since phones have no hover. The hover box's row for
winners on damage taken is "Winners took", because a bare "Winners" didn't say what.

**Checked.** Page against Python on 764 runs: 737 the same, 26 abandoned runs read on the page only,
and 1 differs. That one is a float tie: run 1779331015's act 1 has a pace of exactly .8 in Python 3.13,
whose `sum` is compensated, and .7999999999999999 on the page, so its Turns mark reads behind there and
meeting here. The verdict and what was lacking agree, and it is left alone. Whole runs: 738 the same,
0 differ, 26 abandoned on the page only.

Breaking the tiers on purpose (all one tier, 8 lumped with 9 and up, 0 alone, borrowing another
tier) fails tests every time. So does breaking `net_taken`, `verdict` (speed lifts nothing, no floor on
damage taken, speed lifts behind too, a fast act pinned at 1, slow sinks an act) and `many_targets` (no
version gate, needs three at once, fewest not most, older fights never speak, any id at all). Every
winners' point on the six test runs has a loaded icon and none clip, at 1280 and 390 px; each chart's
tooltip holds only its own numbers, with no page errors. Every fight floor on two test runs shows its
kind on each chart, the same on all of them, and no tooltip leaves the screen at either width.

Breaking `run_reading` fails tests too: OP on acts 1 and 2, on every act, on any two, on either late
act, or on the damage mark alone; a run read as most of its acts, its last or its worst, or at one act's
pace. So does `held_out` skipping OP. Dropping the close at the end of a log fails `Death` on both real
logs.

### Keeping Up by Floor, tidied: words, rule, totals, pickups (2026-11-02)

Page only; no number or edge moved. The wording here is a draft until the user OKs it, except the
verdict words, which are the user's own.

**Verdict words.** The page says OP > Hype > Mid > Low. Hype is ahead, Mid is meeting, Low is behind
(`KEEP_WORDS`). Everything above this section, the Python, the tests and the CSS classes keep ahead,
meeting and behind; the marks ▲ – ▼ and their colours are the same. Only acts and whole runs get a
word. A floor has no verdict: it sits above or below the average-win icon on the charts and that is all.

**"Winners" is "average win" on the page.** The user's call, for the labels: "Winners" didn't say it
was an average. The table head is "Avg win", the chart's icon is "Average win", hovers say "average
win", and the fight table's footnote reads "Average of N wins". The old "Winners took" row is gone with
the rest of the old five-row box. The maths are still `winners_of` and friends.

**The rule is on the page.** Damage taken decides: Low at 150% or more of the average win's, Hype at
67% or less, and finishing in under 80% of the turns with no more damage lifts a Mid to Hype. Each act's Taken row has a three-zone
bar with the act marked on it and the two cut points as HP, computed from the average win by
`keepCuts`, which settles each cut with `keepMark`'s own comparison so it never disagrees with the
verdict at a float edge. A brute-force probe over 1.46 million (average win, taken) pairs and every
turns pair found 3 mismatches before that fix and 0 after. A Mid within a fifth of the bar of an edge
says how many HP from it, so a borderline run is visible. The Turns row has no bar, since turns never
lower an act; it says "Hype at N or fewer, with damage ≤ M" while the lift can still apply.

**Labels for energy.** "Card cost" is the face value of what was played, X counted as 3
(`listPrice`, from `equiv`). "Energy paid" is what the turn actually spent (`spent`, the raw energy
events). Free and discounted plays pull paid under cost; X plays push it over. Floor 8 of the logged
Ironclad shows 9 paid against a cost of 4 on one turn: Bloodletting, Taunt and a Whirlwind played for 8.
The energy and draw chart's third line is "Card cost" now, not "Energy played"; field names are the same.

**The damage tooltip** is one table: You and Avg win each get Fight and A turn columns. Damage done's
fight total is the enemy's HP. The damage taken tip splits what arrived into blocked, healed and got
through, as a bar and as rows with their percent of what arrived, with the average win's got-through
as a tick on the bar (clamped to the bar's end when winners got more through). "Got through" takes the
colour of the Damage taken line. The palette was checked for dark on the tip's surface: tritan ΔE is 6.1, under
the 8 target, so every colour ships with an icon and a label. A lost fight with no log reads "Lost here,
no log to say."; a run with no log at all has no energy or draw chart and no act rows for them.

**Pickups** (superseded: the box is now enterable by hover, see "Keeping Up on gamma: readable, reachable" below). The tip's chips carry the card or relic picture; hovering one shows the full card or relic.
The plan had the box stay open for a short grace delay so the pointer could reach the chip. It is
click-to-pin instead: a click on a chart holds that floor's box (a hint line says so), and Esc, a click
away, a scroll or a resize lets it go. A grace delay would have either left the box jumping to the next
floor while the pointer crossed the chart, or frozen it on the wrong one.

**Checked.** At 1920 the act cards are three across and at 390 stacked, no sideways scroll or clipped
text at either. The act figures still come from the same aggregation code: the only change there is
`enemyTurns` on a fight's row, which the tip uses for the fight totals. Pin, hint, Esc,
click-away, scroll and resize all behave on the logged Ironclad; run 1774189616 (lost, no log) gives
the lost-fight line and no log rows.


### Keeping Up on gamma: readable, reachable, and the energy chart for every uploaded run (2026-11-02)

The user opened a real Silent win on gamma and listed what was wrong. What changed, and why:

**The tip is reachable.** The click-to-pin above was the wrong fix: it left hovering a race, the box
vanished as the pointer left the floor's point, and "Click to hold" meant nothing to a visitor. Now the
box opens straight below the pointer (above when it would not fit), centred on it, so reaching it is a
vertical move that stays on the same floor. A transparent strip bridges the gap, and leaving the chart
or the box closes it after 450 ms, which entering the box cancels. That alone still lost the box on a
diagonal approach, so while the pointer is on a line from where the box opened to any point of it, the
box holds its floor and the timer restarts; moving sideways along the chart still changes floors. Chips open the full card or relic on
hover. Touch has no hover, so a tap holds the box until a tap elsewhere, Esc, a scroll or a resize.
Text is 15 px. Checked by moving the pointer 250 px into the box in 15 px steps: open all the way.

**Charts match.** HP and Gold by Floor got a heading, a caption and the HTML key under the chart like
Deck, Relics and Keeping Up (Gold is one line, so no key), and every floor chart has the same x gridlines.
Secondary text everywhere is one brighter colour (`--text-dim`, `#d2cdea`, chart ticks the same) so it no
longer reads as unimportant next to the white; the old hard-coded greys `#8a8aa0` and `#bcbcd0` are gone as text
colours. The act card's Draw row says only its base; "Cards played" is its own row, since a card drawn is not
a card played (a full hand with no energy is a different problem from a deck that draws little). Act cards are two columns when the card is 560px wide or more.
The three chart names inside the Keeping Up box (Damage done per turn, Damage taken per turn, Energy and cards per turn) are 16 px, a step under the box's 24 px heading; they had inherited the 24 px by accident.

**Wording.** "This run" / "Avg win" on the tip. "Fight turns" replaces "Turns to kill", which did not
say what was killed. The rule is stated once, in the section caption, with numbers a reader can use at a
glance and no ratios or percent signs: *For every 100 damage the average win took on the same fights, how
much did you take? Hype: 67 or less. Mid: 68 to 149. Low: 150 or more. A Mid counts as Hype if you took 100 or
less and finished in 4 turns or fewer for every 5 of theirs.* A first plain-words-only draft ("a lot less,
about the same, a lot more") said nothing and was dropped: the reader wants the numbers, just not the maths.
The maths underneath is unchanged: Hype under 67% of the winners' damage taken, Low at 150% or more, and a
Mid lifts to Hype when your turns are under 80% of theirs (4 for every 5; the first draft's "25% fewer" was
wrong) with damage taken at 100% or less. A mark's hover gives this reading's own numbers ("The average win
took 95 damage on these fights. Hype: you took 63 or less. Mid: 64 to 142. Low: 143 or more."). These strings are drafts until the user OKs them.

**Act cards.** 16 px text, one grid for every row (label, figure, mark, "vs N") so the columns line up
across cards and nothing floats mid-card, kind icons in the heading. The meter is a 12 px gauge: each
zone carries its sign and word (Hype, Mid, Low), the cut points are numbers under the zone boundaries,
the act's value is a pointer with its number, and the average win is a tick.

**Damage done and taken are different colours.** They were `#e0604f` and `#d9652b`, ΔE 4.1, a FAIL in
`validate_palette.js`. The first fix made taken blue (`#3f8fd8`), which sat next to the grey-blue blocked
(`#8b93b5`) in the tip's split bar and read as the same thing. The user's call: red is for the damage
chart's line (`#e05252`) and for the incoming-damage segment of the tip's bar (what got through); the
damage taken line is gold `#e8a83a` and dashed (done/taken ΔE 20 normal, 15 colour-blind). Blocked is a
clear shield blue `#5aa0e6`, healed green `#5cba7d`. Drawn `#9b7fe0`, played `#2fa384`, card cost `#b5861a`
are unchanged; card cost is the closest to the gold (ΔE 12.6), and the two never share a chart.

**Energy and draw on gamma.** The chart read `measured_runs.json`, which is built on the owner's machine
from their logs and is not on the site, so an uploaded run never had it: not a regression, it never
existed there. The event log is in the data bucket (`telemetry/<steamid>/<ts>.json.gz`), but CloudFront
serves only `users/*` and the page does not fetch it. Chosen: read the log once at ingest
(`infra/lambda/ingest/measured.py`: `derive_telemetry.derive`, the log's fights aligned to the run's
timeline, the same per-floor numbers as `export_measured.py`) and store them as `measured` on the run in
its month file, about 3 KB a run. The page reads `run.measured` first, then `DATA.measuredRuns`. The
Lambda bundle gets `derive_telemetry.py` and a `measured_cards.json` (card costs and junk ids) cut from
the local `card_data.json` at synth time; the game data stays out of the repo. `derive` takes an enemy
move table that only feeds what an enemy was about to do, none of it these numbers, so the Lambda passes
none (checked: identical output on both local logs). `infra/tests/test_measured.py` holds the two
copies together on the Ironclad and Silent logs, field by field; change one and the other has to follow.
Runs uploaded before this have the log but no `measured`: `tools/backfill_measured.py` writes it onto
them. A run with no log shows "No per-turn log for this run." in that slot instead of nothing.


### Output, mitigation and speed: tested, verdict unchanged (2026-11-02)

The question: a Mid that wins fast (took as much damage as the winners did, in fewer turns) reads odd, and
anchoring speed inside Mid felt wrong. The idea was that output, mitigation and speed together tell the
story. Tested on held-out acts (runs split in halves, each half read against the other's averages; 3,723
acts, AUC of a won run scoring above a lost one):

- **Output and speed are one number here.** Damage done per turn is the enemies' HP over the turns taken,
  and the enemies' HP is fixed by the fight, so it cannot be tested apart from speed.
- **Mitigation is the winners' damage per turn over yours** (`each = guard / pace`). Alone it reads about
  as well as damage taken (solo 0.735 against 0.772).
- **Speed matters in every damage band**, and most in co-op. Solo Hype: 74% won at an even pace, 94% fast.
  Co-op Mid: 59% even, 93% fast. Solo Low: 26% even, 48% fast (21 acts). Asc 9+ is too small to trust.
- **No three-level rule beats the current one by more than noise.** Letting a fast Low lift, letting a
  slow Hype sink: within 0.01 AUC of the shipped rule, solo and co-op (the best, co-op 0.732 against 0.723,
is inside the noise). Stepping fast up and slow down is worse (solo 0.705 against 0.721). The
  larger loss is cutting damage taken into three bins (0.772 raw, 0.721 as Hype/Mid/Low).

So the verdict is unchanged (speed lifts a Mid to Hype, never sinks anything). A "Taken per turn" row (the
winners' damage per turn over yours, marked on the same edges) was tried beside Fight turns and Damage taken
and dropped: it is those two rows divided, and the user read three rows as one number shown twice. The act
card keeps Fight turns (speed) and Damage taken (the rating); damage done per turn stays in the log-only rows,
not rated.
