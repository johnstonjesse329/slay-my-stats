# Shadow ranking experiment: completed findings

**Decision: reject v1 as a replacement for the current grades.** Keep the current
labels and add recorded fight/act explanations beside them. The experiment shows
where a proposed definition moves runs; it does not establish that those moves
are corrections. No production grades, game files or deployment were changed.

## What was tested

The rules in [the registered specification](shadow-explanatory-grade-v1.md) were
fixed before counting movements. The candidate measures completed-fight efficiency:
turns and net HP cost relative to the same encounter at the same difficulty. It
uses existing winning OP, OP/Hype and all-winning cohorts to anchor act thresholds.
Both low-cost control and fast pressure can qualify. It does not measure intrinsic
deck power, maximum damage/block, decision quality or shuffle-win probability.

The saved snapshot contains 1,758 eligible published standard solo runs across
seven players and six characters. Help/held uploads, multiplayer, abandoned and
other-mode runs do not calibrate it. All 217 snapshot files matched their saved
hashes before and after validation. This is the available saved production-data
snapshot, not a claim to include uploads after that snapshot.

Five run folds, seven whole-player holdouts and three forward-time windows fitted
references and anchors using training runs only. The old labels themselves come
from a saved full-history artifact, so they are exploratory source labels rather
than independent ground truth. Character/build/patch differences are unadjusted.

## Do current winning runs move?

These are **hypothetical v1 movements in the run-holdout experiment**, not approved
reclassifications. Unknowns stay in the denominator.

| Current winning class | Winners | Same | Up | Down | Unknown |
|---|---:|---:|---:|---:|---:|
| OP | 83 | 9 | 0 | 16 | 58 |
| Hype | 75 | 12 | 1 | 9 | 53 |
| Mid | 206 | 26 | 4 | 17 | 159 |
| Rough | 94 | 17 | 3 | 0 | 74 |

OP's 16 demotions split into eight Hype, seven Mid and one Rough. Hype's nine
demotions split into seven Mid and two Rough; its one promotion is OP. All four
winning Mid promotions are Hype; all three winning Rough promotions are Mid.
Rough cannot move down on this scale. Winning is not an evaluation input once
completed-fight scope is fixed, so it does not automatically promote a run.

Across winners and losers, there were 108 proposed movements: 42 up and 66 down.
All have per-act metrics, thresholds and per-fight references in the output files.
The complete transition tables retain Unrated/Unknown and split by outcome,
difficulty and player. A missing detailed log is never filled with invented damage
or block capacity.

## Why it fails the adoption checks

| Difficulty | Run-holdout ranked | Player-holdout ranked | Forward-time ranked |
|---|---:|---:|---:|
| A0–1 | 0/597 | 0/597 | 0/384 |
| A2–7 | 339/425 (79.8%) | 171/425 (40.2%) | 66/183 (36.1%) |
| A8 | 0/113 | 0/113 | 0/79 |
| A9 | 0/261 | 0/261 | 0/125 |
| A10 | 0/362 | 0/362 | 0/284 |

No tier reaches the registered 70% coverage in both run and player checks. Among
139 runs ranked by both, 117 agree exactly (84.2%), clearing the 80% agreement
check on that selected subset only. That does not rescue the missing coverage.
Forward-time windows contain different test runs from the full two-fold schemes.

At A0–1, all five run folds have unordered **Act 1** cost anchors. A whole-run OP
label requires strong Acts 2 and 3; it does not require the cheapest Act 1. Using
that whole-run label as an ordered anchor for every act is therefore unjustified.
One A2–7 fold has the same Act 1 problem. This does not prove the existing OP
label is wrong. It rejects this particular translation of it into act thresholds.

At A8, A9 and A10, OP anchor cohorts fail the minimum run/player support. Pooling
these difficulties would hide A8's HP increase, A9's damage increase and A10's
second boss. No high-ascension physical threshold or Dread grade is validated.

## Review of all five changed runs with checked boss accounts

The available checked logs cover only some bosses in some runs; the whole-run
movement is explained by the raw act measurements. Boss accounting is supporting
evidence, not a complete logged explanation of every fight. No checked winning
Rough run is available. Full raw cost/turn trails exist for all other movements.

1. **`696827807ed8`: winning OP → Hype.** Acts become OP/Mid/OP. Act 2 averages
   5.875 net HP per fight and 4.625 turns; normalized cost 0.520 exceeds the OP
   Q75 of 0.496 and normalized pace 0.930 misses the Hype fast route of 0.828.
   Both later acts therefore do not qualify as OP. Yet its recorded Act 2 boss
   removes 321 enemy HP, blocks 106 and starts/ends at 47 HP. The Act 3 boss
   removes 600 HP and starts/ends at 74. This is an act-wide definition change,
   not evidence that either boss win was weak.
2. **`940776a87c28`: winning Hype → Mid.** Acts become Hype/Mid/Mid; the equal-act
   score is 1.33. Normalized Act 2 cost 0.655 narrowly exceeds Hype's Q75 0.643,
   despite fast pace 0.647. Its three checked bosses end at 22, 17 and 52 HP.
   Recorded additional HP costs are 3, 14 and 21. Costs are real expenditures,
   but this rule cannot say whether they bought useful output/control.
3. **`c1076fc5fce9`: winning Mid → Rough.** Acts become Rough/Mid/Mid, whose mean
   is 0.67. Act 1 cost ratio 1.418 exceeds the winner Q75 1.055. Its checked Act 1
   boss uses 35 of 40 starting HP, blocks 57 and removes 222 enemy HP. Act 2 ends
   at 48 from 62 HP. The label is driven by early cost and the chosen aggregation;
   later recovery and victory remain visible. There is no checked Act 3 boss here.
4. **`728ccdc16d27`: winning Mid → Rough.** Acts become Mid/Rough/Mid, also 0.67.
   Act 2 cost 1.111 exceeds winner Q75 1.020 despite fast pace 0.756. Checked
   bosses remove 307/408/600 HP and end at 31/37/30 HP. Additional HP costs are
   6/17/39; the last boss also heals 17. Treating those expenditures as a deck
   weakness would be an unsupported interpretation of the candidate's cost score.
5. **`7b3ea104b5b0`: losing Mid → Hype.** Eight completed Act 1 fights average
   5.125 HP and 4.375 turns, giving cost ratio 0.609 below OP's Act 1 median 0.711.
   An Act 1-only OP act aggregates to Hype, since whole-run OP needs Acts 2 and 3.
   The excluded terminal boss starts at 29 HP, ends at zero, removes 120 enemy HP
   and includes 13 additional HP costs. The existing comparison scope excludes
   terminal lost fights too, but this promotion shows why the result must say
   "prior completed-fight efficiency," never overall survival capability.

All twelve available checked boss accounts for these five runs reconcile HP and
damage attribution under the existing checks. Pet absorption and damage prevented
by early kills/Weak are not silently credited to player block.

## Instrumentation to retain

Store the existing label alongside a separate versioned observation record. The
offline prototype already emits this paired view; no new mod deployment is needed
to review it. Keep these fields at fight, act and run scope:

- Identity/context: snapshot, run, player, encounter, act, ascension, character,
  game build, fight order, completed/lost status and measurement source.
- Output: attributed enemy HP removed, turns and turn-by-turn output. Track enemy
  healing, phases/summons, overkill and unexplained HP disappearance separately.
- Survival: player-hit block absorbed, enemy damage reaching HP, other HP costs,
  actual healing, entry HP and ending HP. Flag pet/prevention attribution gaps.
- Engine usage: energy spent, cards played and recorded draws. These are observed
  usage, not maximum capacity or proof a particular card caused victory.
- Quality: complete/truncated, matching certainty, endpoint source, HP/damage
  balance, covered fights and unavailable measurements. Unknown is not zero.
- Comparison trail: old label, candidate version, raw metric, encounter reference,
  cohort counts/players, threshold, route/reason and resulting hypothetical label.

A2 and above retain missing HP after transition healing. Record that budget;
never charge the inherited deficit to the next act's combat efficiency. A10 needs
individual boss accounts plus the carried health budget across the two bosses.
Terminal losses must remain explicit even when excluded from completed kill pace.

## What the evidence supports next

Ship no relabeling from this experiment. The useful result is the separate
explanation: what was removed, what was absorbed/spent, what the engine used and
what margin remained. A Mid or Rough run can have a convincingly strong boss
performance; a strong act can recover from earlier cost. Preserve that timeline.

Any later replacement needs act-level anchors rather than borrowing whole-run OP
labels for Act 1, and a stated treatment of productive self-cost and failed fights.
That is a new registered candidate, not an adjustment to make this one pass.
Reliable shuffle probabilities need repeated comparable deck attempts or a
separately validated simulator; they are not identifiable from these single-run
accounts. The current snapshot cannot supply missing high-ascension telemetry.

## Reproduction and checks

Use Python 3.13 with the existing analysis dependencies (the default Python 3.14
here lacks numpy). Run from the repository root:

```powershell
python313 tools/power_curve/shadow_explanatory_grades.py
python313 tools/power_curve/validate_shadow_explanatory_grades.py
python313 -m unittest discover -s tools/power_curve -p test_shadow_explanatory_grades.py
```

`python313` above denotes the installed Python 3.13 interpreter, not a supplied
wrapper. Seven invariant tests pass. Independent pandas reconstruction verified
6,108 encounter references, 648 anchor records, 9,290 act records and all 4,571
run evaluations across the three schemes. The snapshot hashes still match.
The outcome-accounting test suite separately verifies its five accounting cases.

Artifacts: `local_data/act_validation/six_character/shadow_explanatory_v1/` contains
`review.html`, `ratings.csv`, `transitions*.csv`, `winning_movements.csv`,
`coverage.csv`, `stability.csv`, `changed_run_reasons.csv`,
`changed_checked_bosses.csv`, `fights.csv`, `acts.csv`, `references.csv`,
`anchors.csv`, `folds.csv`, `summary.json` and `validation.json`.
