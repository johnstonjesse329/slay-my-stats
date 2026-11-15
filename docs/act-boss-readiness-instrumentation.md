# Act-boss readiness: instrumentation contract

## Research decision

The bounded existing-snapshot investigation is complete when its audit passes. It does **not** validate an objective deck-sufficiency grade or calibrated individual clearance percentage. The permitted outputs below are observed measurements with explicit coverage and uncertainty. No deployment or site change is part of this work.

Primary evidence: `local_data/act_validation/six_character/bounded_goal/report.html`, `family_gate_table.csv`, `numerical_gate_audit.csv`, and `feature_dictionary.csv`. Each of 60 family/checkpoint/difficulty cells has an explicit verdict. None currently supports a readiness grade from that measured family. This is insufficient evidence, not a causal rejection of the game mechanic.

## Common input contract

- Solo standard runs accepted into a published profile, with characters in the snapshot catalog (including Fool). Held, modded and multiplayer uploads do not calibrate these outputs.
- Predictive windows contain three completed earlier fights from the current act. Target-fight result, future route, future card gains and final deck are forbidden inputs.
- Each log window must be unambiguously aligned to saved encounter order, have complete observed turns, balanced HP flow, and matching attributed damage/HP removal without unexplained disappearance. Duplicate target-boss attempts, missing/ambiguous windows and truncated logs produce `unknown` for the affected measurement, never zero.
- Report `source` (measured or raw-run estimate), checkpoint, number of fights/turns, recording quality, and missing fields. Never silently substitute estimated HP/turn for measured damage.
- Boss-entry, after fight 3, and after fight 6 are different populations. Later survival is not itself evidence of a stronger deck. Most runs have no measured log; raw-run turns/HP observations can be displayed as separate facts but do not inherit measured-feature validation.
- Formatting: HP and turns are integers where recorded; rates may use one decimal place. A decimal does not imply calibration precision. Do not color or label a metric as sufficient/insufficient for winning without a supported scope-specific gate.

## Displayable measurements

| Display name | Formula and units | Required fields | Interpretation and abstention |
|---|---|---|---|
| Damage dealt per turn | Attributed enemy HP removed / observed player turns, HP/turn | Damage attribution, enemy HP deltas, complete turns | Includes non-attack damage and enemy healing that had to be removed again; excludes overkill and unexplained disappearance. Not the deck's maximum possible damage. |
| Early damage dealt | Mean validated enemy HP removed on each fight's first two turns, HP/turn | Turn-level HP deltas and attribution agreement | Observed setup-period output; short fights contribute their observed turns. Do not call zero output a bad turn automatically. |
| Later damage dealt | Mean validated HP removed on observed turns after turn two, HP/turn | Same, plus at least one later turn | If there are no later turns, output `unknown/not observed`, not zero sustained capability. A quick kill cannot prove long-fight endurance. |
| Fight duration | Observed turns / fights, turns/fight | Complete completed fights | Encounter-dependent kill time; no universal fast/slow cutoff is supported. |
| Early enemy damage taken | Mean enemy damage received on first two observed turns, HP/turn | Valid damage received attribution | Setup safety observation, not total net HP cost. HP paid by cards and self-attributed status damage must not be mislabeled enemy pressure. |
| Largest enemy hit-turn cost | Maximum enemy damage taken during an observed turn, HP | Same | Describes recorded burst exposure, not worst possible future draw or enemy move. |
| Damage blocked | Enemy damage actually absorbed by block / turns, HP/turn | Received-hit absorbed-block fields | Demand-capped. Killing early and Weak can lower block required. Do not substitute generated block or infer maximum defense. |
| Net HP spent | Sum max(0, HP outflow - HP inflow) per fight, HP/fight | Balanced HP events including healing/costs | Healing after/between fights must retain its recorded timing. Does not debit inherited missing HP to this act. Spare healing is not carried to another fight as hypothetical block. |
| Enemy damage taken per turn | Recorded enemy damage received / observed turns, HP/turn | Attribution and complete turns | Distinct from self-costs and net HP expenditure. Fatal fight cost is censored by death; do not infer the full cost to win. |
| Zero-output turns | Fraction of observed turns with no validated enemy HP removal | Turn-level HP deltas | Descriptive consistency; power setup and defensive turns can be valuable. |
| Output variability | Population SD of validated damage per turn, HP/turn | At least two complete observed turns | No supported good/bad variability threshold; the encounter and strategy matter. |
| Damage-taken variability | Population SD of enemy damage received per turn, HP/turn | At least two complete observed turns | No supported reliability grade; an average and SD do not describe every lethal burst. |

The exact model-feature formulas and quality flags are in `feature_dictionary.csv`. The models also used an early-zero-output fraction as a setup covariate; it carries the same descriptive limitation as zero-output turns.

## Health budget is separate

Show current HP/max HP and, when recorded, observed act-entry HP. A2 **and every higher ascension** carry reduced Ancient healing: never assume a full heal or label an inherited deficit as current-act deck failure. Missing entry HP stays unknown; do not reconstruct it from a later boss outcome. Current HP legitimately affects survival likelihood, but it must not determine a deck-power grade.

A descriptive example is: “Recent fights: 28 HP dealt/turn; 3 net HP spent/fight. Current health: 24/80. Boss readiness: unknown.” These numbers illustrate formatting only; they are not empirical success thresholds. A slower deck that blocks/heals effectively can be capable; a fast deck with insufficient health can still die. Neither example alone establishes readiness.

## Readiness labels and percentages

- **Four-family capability grade:** do not instrument. The added-predictive-information gates were not met with the measured cohort.
- **Early-act readiness after fights 3 or 6:** unknown by default. Broad-model high-success subsets are small or context-driven; added nonlinear performance/composition did not clearly outperform nonlinear HP/context.
- **Boss-entry favorable candidate at A0-1/A2-7 or pooled A0-8:** prior broad-model research supports investigating this category, but it is not a validated output of these four mechanical families. Do not introduce it under a damage/block sufficiency label. Any separate adoption requires its own scope-specific readiness gate audit; this contract authorizes descriptive outputs only.
- **A8/A9/A10 mechanical targets:** unknown. No eligible measured high-ascension logs calibrate them. A8 enemy HP, A9 incoming damage and A10 two-boss sequence must remain distinct. Do not apply A0-7 physical thresholds at higher levels.
- **Dread:** unsupported. Any A9/A10 reference shown there must explicitly say provisional/unvalidated; no confident readiness label.
- **Exact clearance percentage:** do not publish from this investigation. Historical reused labels and sparse player variation do not establish individual calibrated probabilities.

## Boundary cases and counterexamples

A matched Kaiser Crab context (Ironclad, Act 2, A2-7, entry HP 50-75%) contains one clear and one loss: the failed run had higher prior damage output and absorbed block than the clear. This pair is illustrative, not statistical proof or a causal explanation. Exact HP within the band, deck mechanics, choices and route differ. See `matched_boss_contrasts.csv` and `counterexamples.csv` for values and pseudonymous run references.

After A10's first final boss, survival of that fight does not mean the act is cleared. Predictor inputs from that fight become available only for the second-boss checkpoint; the first-entry prediction may not use them or the second boss's identity from future history.

An abandoned unfinished act is censored. Do not automatically treat it as a deck failure, discard its already-cleared earlier acts, or turn an unknown outcome into a calibration success.

## Delivery and validation

No UI, mod, infrastructure or deployment changes are required for this contract. Implementers must preserve the source/quality/unknown distinctions and run the outcome/leakage tests before wiring a display. Research scripts, all compared models, population/measurement audits, per-scope verdicts, plots and targeted test output are included in the bounded report package. Positive descriptive findings, rejected interpretations and insufficient predictive evidence are distinct final results.
