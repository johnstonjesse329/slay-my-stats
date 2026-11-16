# Measurable goal: objective act-boss readiness

## Goal

Using only the existing, immutable production-data snapshots, determine which measurable combat capabilities can identify a solo run as ready to clear its current act's boss sequence, independently of merely having high current HP. Produce a reproducible experiment package and a decision-ready instrumentation specification that separates demonstrated capability, health budget, and uncertainty.

Success is a justified decision about each proposed measurement, not a requirement to discover a positive result. Unsupported measurements must be rejected or explicitly marked unvalidated; they must not become confident scores through repeated model searches.

## Scope and fixed inputs

- Standard solo runs, accepted/published core characters from the snapshot's catalog, including The Fool. Exclude held/modded and multiplayer uploads. Abandoned unfinished acts have unknown outcomes and enter a conservative sensitivity analysis, not automatic loss labels.
- Use copied snapshots under `local_data/act_validation/`. Record the exact file manifest and hashes. Do not read live game saves, fetch replacement data, change the mod, deploy a model, or publish site ratings as part of this goal.
- Main snapshot: `local_data/act_validation/confirmation/`, with its manifest in `local_data/act_validation/six_character/snapshot-manifest.json`. Earlier frozen experiments remain unchanged and are prior exploratory evidence, not new confirmation.
- Report A0-1, A2-7, A8, A9, and A10 separately. A2+ reduced Ancient healing is cumulative; inherited missing HP is not poor current-act performance. A8 changes enemy HP, A9 incoming damage, and A10 Act 3 requires both bosses. Dread remains unsupported; any future use of A9/A10 benchmarks there must be labeled provisional.
- Do not reinterpret a broad survival classifier or partial card-acquisition counts as intrinsic deck power.

## Questions to answer

1. At comparable HP, act, difficulty, character and encounter demands, which capability measurements distinguish boss-sequence clears from failures?
2. Can completed earlier fights reveal those capabilities before the boss, including the risk of dying before arrival?
3. Which measurements generalize across represented players and time, and which depend on an encounter, character or recording artifact?
4. What can be instrumented now as observed facts, what can support a provisional readiness judgment, and where must the display say unknown?

These are observational questions. A failure pattern may be consistent with inadequate damage, setup safety or endurance; it does not prove a card choice or mechanism caused the loss.

## Outcomes and prediction checkpoints

Primary outcome: clearing the entire current act's boss sequence from the stated checkpoint. A10 Act 3 requires both bosses. Passing an earlier boss in a later-lost run still counts as clearing that earlier act.

Secondary outcomes: reaching the first boss; clearing the sequence conditional on arrival. Keep these separate and never hide pre-boss deaths by analyzing boss entrants alone.

Evaluate after completed current-act non-boss fights 3 and 6, and at first-boss entry. Each checkpoint has its own survivor population and one observation per run-act. Runs dying before a checkpoint do not validate that checkpoint; report this limitation.

## Four capability hypotheses

Test only these families in this investigation. Define the exact formula, units, required fields and failure modes before fitting a new variant.

| Family | Candidate measurement | Intended distinction |
|---|---|---|
| Damage and pace | Actual enemy HP removed per player turn; encounter HP and observed kill time; early versus sustained output where complete logs allow it | Enough damage for the encounter's duration and scaling pressure |
| Setup and burst safety | Early-turn HP cost, worst observed incoming/net-HP-loss turn, time until sustained output | Averages can conceal a lethal setup or bad turn |
| Defense and endurance | Damage actually absorbed, HP expenditure after healing, resource cost across repeated fights | Slow safe decks can qualify; A10 requires sustained survival across the sequence |
| Consistency | Zero-output turns and variability of damage/HP expenditure across turns and recent fights | Reliable capability versus occasional peaks or favorable draws |

Actual block absorbed is demand-capped and is not maximum block capacity. Generated block is not absorbed block. Attempted/overkill damage is not HP removed. Self-inflicted HP costs are not enemy damage. Energy/card draw can remain descriptive covariates; do not add an engine grade without separate evidence.

Health budget is a separate input: current/max HP and observed act-entry state where available. Do not assume an Ancient healed to full. Do not subtract an inherited deficit as if it were damage in the current act.

## Bounded experiment plan

### 1. Data and measurement audit

- Verify manifests and produce eligibility counts by character, player, difficulty, act, endpoint and checkpoint.
- Verify outcome labels, including A10 double-boss losses, pre-boss deaths, completed acts before later losses, and censored abandoned acts.
- For measured features, compare raw/log fight sequences and HP-flow balance. Admit locally complete pre-boss windows only with unambiguous target starts and exact ordered predecessors. Reject duplicate/ambiguous retry matches. Report missingness and exclusions by player/outcome; do not silently select the cleanest population.
- Add regression checks for each known leakage/measurement failure: future cards/final deck, target-fight damage/outcome, duplicate retries, attempted versus actual damage, generated versus absorbed block, and inherited HP versus current-act expenditure.

Deliverable: one audit table and a feature dictionary with quality flags. A family with unusable data receives an explicit insufficient-measurement verdict rather than a replacement proxy disguised as the same capability.

### 2. Boss-specific failure analysis

- Compare clears and failures at similar entry HP, boss identity, act and difficulty. Character is a control, not a substitute for capability.
- For each of the four families, report distributions and overlap, not only means or the most impressive wins. Record sample/player counts and representative counterexamples.
- Separate evidence observed during the target boss (diagnostic explanation only) from earlier-fight features (eligible predictors). Target-boss measurements never predict their own result.
- If the sample cannot support boss-specific contrasts, report it as insufficient. Do not pool incompatible bosses or difficulties solely to obtain a passing result.

Deliverable: a failure-analysis table linking each proposed capability to supported observations, counterexamples and unresolved confounding.

### 3. Earlier-fight predictive test

- Baseline: health plus context available at the checkpoint. Include act/difficulty, cumulative healing rule, character/build and known progression. Boss identity may enter only if known at that checkpoint, never supplied from future outcomes.
- Compare the baseline with each capability family and then the predeclared combined set. Test both a regularized linear model and one fixed shallow nonlinear model; reuse documented settings. No unbounded hyperparameter search or new feature-family hunt after looking at results.
- Fit preprocessing, encounter references and any threshold choices on training data only. Whole runs stay together. Use whole-player holdouts and the existing forward-time windows. Report all variants, including worse ones.
- Within available samples, examine HP strata and player balance so capability does not merely proxy current HP or one prolific player. Repeat the abandoned-run bounds.

Deliverable: a comparison table with error, discrimination, calibration, coverage, paired uncertainty, and subgroup results. Historical reuse of these labels remains exploratory evidence; nested fitting does not turn the snapshot into untouched confirmation.

### 4. Instrumentation decision

Classify each family and readiness claim as:

- **Descriptive:** accurately measurable, but no demonstrated additional readiness information.
- **Retrospectively supported:** adds readiness information and passes the gates below in a named population.
- **Rejected candidate:** fails a meaningful test or introduces unacceptable measurement/leakage bias.
- **Insufficient evidence:** the snapshot cannot distinguish the hypothesis; specify exactly which contrast is missing.

Write the display contract: metric name, formula, units, checkpoint, required fields, data quality/coverage, supported populations, health treatment, uncertainty/abstention behavior, and examples/counterexamples. Unknown must be a legitimate output.

No production UI implementation or deployment is required to complete this investigation.

## Fixed decision gates

These are explicit research acceptance criteria for this investigation, not claims that nature has an exact universal cutoff.

### Additional predictive information

A capability family is retrospectively supported as adding readiness information only if:

1. Relative Brier error reduction versus the matched health/context baseline is at least 5% in both whole-player and forward-time evaluations.
2. The paired whole-run bootstrap 95% interval for the error difference excludes zero in the favorable direction in both evaluations.
3. Direction is not explained entirely by one player or current-HP stratum; report equal-player results and individual-player effects.
4. The formula and coverage remain valid in the population being claimed. No target-fight leakage or silent difficulty borrowing is permitted.

Otherwise use descriptive, rejected or insufficient-evidence status as appropriate. Do not call an underpowered null result proof that a mechanic is irrelevant. Multiple comparisons are exploratory; disclose them rather than claiming confirmatory significance.

### Favorable-readiness category

For a predeclared nominal >=90% candidate threshold, the named population must have:

- At least 50 selected distinct run-act observations, at least three represented players and at least 10% checkpoint coverage, in each reported evaluation scheme.
- Observed clearance >=90%, with a descriptive 95% lower bound >=85%, in both whole-player and forward-time tests.
- Pooled and equal-player reporting, a player-cluster sensitivity, and no adequately represented subgroup with a material calibration failure (an observed shortfall of more than five percentage points whose interval excludes the nominal rate).
- Explicit exclusions for unsupported populations; success at A0-8 never validates A9/A10 or Dread.

These gates can support only a restricted retrospective category. They do not establish an individual guarantee or independent prospective calibration. If an exact percentage is not validated, the specification must not present one.

For every rate, report the observed numerator/denominator, distinct runs and players, threshold, average prediction, interval method and coverage. Do not present many acts from one player as independent players. Suppress degenerate player-bootstrap certainty from tiny player counts.

## Completion checklist

The investigation is complete when all of these exist and have been checked against files and command output:

- [x] Immutable input manifest and catalog-derived eligibility audit.
- [x] Feature dictionary and measured-data quality/alignment audit.
- [x] Boss-specific failure analysis for all four families, with missing contrasts explicit.
- [x] Outcome/feature regression checks passing.
- [x] Fixed-checkpoint and boss-entry baseline comparisons for the predeclared families, or a documented data-unavailability verdict that prevents the experiment.
- [x] Decision-gate table with one verdict per family, checkpoint and claimed difficulty population; no unsupported cell silently pooled into a success.
- [x] One consolidated report and reviewable plots, linked to reproducible scripts and exact results.
- [x] Instrumentation specification identifying what to show, what not to grade, and when to abstain.
- [x] Final audit states which conclusions are positive, negative or limited by the snapshot. It does not claim that every proposed target has been validated.

An explicit, evidenced **do not instrument this claim** is a completed research result. It is not permission to mark a universal mechanical-target objective achieved. A result requiring absent measurements must end with a bounded insufficient-evidence verdict, not endless refits, repeated production polling or a demand that the user play the game.

## Guardrails against drift

- The deliverable is capability evidence and an instrumentation decision, not the best pooled win predictor.
- Finish the four planned families and the gate table; do not add successive model families just to improve a number.
- Do not request new runs as a prerequisite for finishing this snapshot investigation.
- Keep capability and health separate in interpretation even when both improve survival prediction.
- Report progress in terms of completed experiments and changed conclusions. Do not repeatedly restate that the goal remains active without a new result.

Completion evidence: [requirement audit](act-boss-readiness-completion-audit.md) and [instrumentation contract](act-boss-readiness-instrumentation.md). This checklist records completion of the bounded investigation, including insufficient-evidence results; it does not certify universal boss-clearance targets.
