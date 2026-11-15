# Power curve prototype

Offline tools for working out how strong a run's deck was, floor by floor. Not
part of the site build, apart from what `export_measured.py` and `fight_demand.py` write. Kept so the data can be regenerated when a patch drops
and new approaches can be checked against it.

| File | What it does |
|---|---|
| `power_curve.py` | Small dummy-fight sim. For each floor's deck and relics it plays sampled games and reports damage, block, energy and draw per turn, plus a fights table with real turns and damage taken. |
| `gamma_curves.py` | Runs the sim over every run pulled from gamma into `gamma_raw/`, writing `pcs/<steamid>-<start_time>.json` and `pcs/index.json`. |
| `archetypes.py` | Labels each run's archetype from its final deck and prints a baseline per character and archetype. Its card tests also drive the site's deck tags. |
| `approaches.py` | Compares cheaper estimates (deck averages, card/relic lookup) against the sim. |
| `fights_vs_setup.py` | Checks real fights: do decks with more Powers take more damage or need more turns than others facing the same encounter? Reads `pcs/`. |
| `predict_fights.py` | Scores each way of measuring a deck (sim, deck averages, a cheap formula) on how well it predicts real damage taken and turns, fitted on half the runs and tested on the other half. Reads `pcs/`. |
| `formula_curves.py` | Fits the cheap formula to every real fight, saves the weights to `formula_weights.json`, and scores each floor's deck in `pcs/`: expected damage taken and turns against an average deck, plus what the floor added or removed. No sim; seconds for all runs. |
| `export_strength.py` | Writes `deck_strength.json` at the repo root: every card's and relic's numbers for the formula. The estimate is off the Runs page, so the site doesn't read this; it stays for patch-day work. Game data, so gitignored; re-run after a game-data refresh. |
| `validate_floors.py` | Walks every fight in `gamma_raw/` with the deck that walked into it and checks the formula's four lines against real damage taken and turns: each bucket against its counterpart, the fitted composite held out by run, the floor-to-floor claim, calibration by decile, and how much of the deck the model can't see. No sim, no `pcs/`. |
| `derive_telemetry.py` | Turns the mod's raw event log into per-fight and per-turn numbers, and checks them against themselves (HP given and taken two ways, energy balance, turn counts against rounds, no card played that was never drawn). Every reading of an event lives here, not in the game, so a wrong reading is a re-derive of logs already uploaded rather than another played run. |
| `test_derive_telemetry.py` | The deriver's tests: scripted logs covering the turn model, including the first version's failure (an enemy-phase hit must land in the player's turn) as a regression. Runs in a second, needs no game. |
| `test_data_coverage.py` | Fails when the game data carries a flag the cheap formula never reads -- the shape of three bugs that cost real numbers this session. Every extractor flag must be read, deliberately unread with a reason, or listed as a known gap. |
| `telemetry_report.py` | Reads the mod's event logs (`telemetry/<steamid>/<start_time>.json.gz`) in `telemetry_raw/` and sets them against the formula: damage, block and energy a turn beside the projection for the deck that walked into that fight. Section 3 is the collector's check -- damage taken against the run file's own, turn counts against the run's, and the deriver's self-checks. Section 4 measures each fight from the enemies' HP rather than our hit events (pool, HP removed a turn with its median and peak, their intent, block cover, junk). Section 5 reads each floor against every run in the data that fought the same encounter: turns and damage taken against your own median. |
| `export_measured.py` | Writes `measured_runs.json` at the repo root: what the runs with an event log actually did, floor by floor: damage aimed, arrived and taken, HP removed, cards and energy played. Player data, so gitignored. The ingest Lambda has a port (`infra/lambda/ingest/measured.py`); `infra/tests/test_measured.py` keeps the two equal. |
| `fight_demand.py` | Writes `fight_demand.json` at the repo root: each encounter's HP pool and what winning runs did on it, any character, in one line per tier of how the monsters are tuned (under 8, and 8 and up, where Tough Enemies, Deadly Enemies and Double Boss come in): average turns, damage taken, and damage taken a turn, plus both ends of those wins for the min/max bars on every fight of the Keeping Up charts (`fast`/`light`, the median turns and damage taken a turn of the best quarter; `slow`/`heavy`, the same of the worst quarter). Damage taken here has what the floor healed off it, down to 0. The Runs page's Keeping Up charts read that floor's fight against its own tier's line, solo and per player in co-op. Each act is ranked among winning acts, whose quarters (`cuts`, per act and for whole runs, every tier together) go in the JSON too: behind is more damage taken than 3 in 4 of them, ahead less than 3 in 4, or faster than 3 in 4 without taking more than the average win. A whole run reads the same way on its acts' totals, against winning runs' quarters, and OP is reading ahead in Acts 2 and 3, for the run's header bar and the run list. Each encounter also says whether it can have more than one target alive at a time (`many`), for the hover box. `--check` prints the evidence: what the readings said against who lost, and acts read on runs held out of the averages. Built from game data and runs, so gitignored. A run prints any monster with no HP and any placeholder HP, which is what new content looks like. |
| `test_fight_demand.py` | Its tests: pets, a boss with no HP in the data, an encounter the data does not have, logged pools, the ascension steps including the move table a log reads, a co-op player's share, what goes into winners' averages, healing off damage taken, the tiers and that a fight never borrows another tier's line, a one-turn kill, act readings and what they name as lacking, speed lifting an act and never sinking one, the quarters of winning acts, a whole run and OP, more than one target at a time across game versions, moves two monsters share. Made-up monsters, so it needs neither the game data's numbers nor a run. |
| `test_real_runs.py` | Holds every logged run to what the game wrote down: turns, final HP, enemy health, block, energy and cards against the run file and the raw events, each act's and whole run's reading against the same, a log cut off mid-fight as a death, multi-enemy against what the mod saw alive, and what was aimed against what landed, with the rules monsters add to a move (Strength, Weak, Vulnerable, Tainted, Pressure Gun, Thorns). Reads the gitignored `gamma_raw/` and `telemetry_raw/` at test time and skips where they are absent, so no player data is in it. Every new logged run is covered by being synced. |
| `power_curve.html` | Viewer for `pcs/`. |
| `power_curve_decisions.md` | Valuation guesses and simplifications waiting on review, plus recent fixes. |

## Regenerating

Needs `power_data.json` at the repo root (`python tools/extract_power_data.py`).

```
cd tools/power_curve
aws s3 sync s3://slay-my-stats-gamma-data/raw/ gamma_raw/
aws s3 sync s3://slay-my-stats-gamma-data/telemetry/ telemetry_raw/
python telemetry_report.py        # per-turn telemetry beside the projection
python -m unittest test_derive_telemetry   # the deriver's own tests
python -m unittest test_data_coverage      # no data flag the formula never reads
python -m unittest test_fight_demand       # winners' lines, tiers, and the reading against them
python -m unittest test_real_runs          # the logged runs against the run file and raw events
python validate_floors.py         # checks the formula's four lines against real fights
python export_measured.py         # measured_runs.json, for the runs with an event log
python fight_demand.py            # fight_demand.json, for the Keeping Up charts
python fight_demand.py --check    # those readings against who lost, and acts on held-out runs
python gamma_curves.py            # about 16 minutes for 1,025 runs on 11 workers
python archetypes.py
python formula_curves.py          # after gamma_curves: strength score per floor
python -m http.server 8765 --bind 127.0.0.1   # then open /power_curve.html
```

`gamma_raw/`, `telemetry_raw/`, `pcs/` and `approaches/` are local only (gitignored), as is
`local.json`: player names by Steam id, and `approaches.py`'s sample runs
(`{"names": {id: name}, "picks": {character: [id, start_time]}}`). Pass the
player's Steam id to `curve(run, steamid)`: in co-op runs it picks whose deck
is scored.

## Solo act readiness experiment

`act_readiness.py` builds completed-fight checkpoints from a production snapshot in
`local_data/act_validation/{raw,users,telemetry}`. Held/unpublished runs, non-core
characters, abandoned runs, other modes and all multiplayer runs are excluded.
It compares state-only, recent-performance and trend logistic models with whole-run,
whole-player and chronological holdouts. Encounter references use training data only.
Outputs are local and ignored by Git: `review.md`, `review.ipynb`, `validation.png`,
`audit.json`, checkpoint/prediction CSVs and model metrics. No live ratings change.

Install `analysis-requirements.txt` into the repository virtual environment, then run:

```powershell
infra/.venv/Scripts/python.exe tools/power_curve/act_readiness.py
infra/.venv/Scripts/python.exe tools/power_curve/summarize_act_readiness.py
infra/.venv/Scripts/python.exe -m unittest discover -s tools/power_curve -p test_act_readiness.py
```

`validate_act_targets.py` is the earlier raw-data exploratory screen. Its published
results are superseded by this experiment's accepted-profile filtering. HP-loss bands
are hypotheses, not validated readiness thresholds.

`summarize_act_readiness.py` adds paired run-bootstrap uncertainty, per-player and
difficulty metrics, a hashed snapshot manifest, and standalone `review.html`. The
bootstrap uses fixed held-out predictions; it does not capture model-refitting or
new-player population uncertainty.

`act_targets.py` searches fixed turn-count / net-HP-loss / current-HP rules on older
runs, evaluates them unchanged on later runs, and separately checks the selection
procedure with each player held out. It writes `targets.html`, a descriptive grid,
rule results, HP/character/player/elite strata and failure audits under the same
ignored output folder. Run with the repository Python; validate with
`python -m unittest discover -s tools/power_curve -p test_act_targets.py`.
Rules are exploratory and do not modify site ratings.

## Boss-entry experiments

`boss_readiness.py` predicts the next boss and the entire boss sequence separately,
using the preceding room's HP and only completed earlier fights. Whole-run,
whole-player and forward-time tests compare context, health, recent performance
and equal-player-weight variants. `calibrate_boss_readiness.py` fits probability
corrections with nested training-only predictions. `report_boss_readiness.py`
writes the current experiment review, paired run-bootstrap comparisons and plots.
Run those three scripts in order with the repository Python; outputs live in
`local_data/act_validation/boss/`. The report's narrative describes the November 14
snapshot and must be reviewed when inputs change. Regression checks:
`python -m unittest discover -s tools/power_curve -p test_boss_readiness.py`.

The current evidence supports further boss-entry research, not a universal
90% confidence claim: player transfer and A9/A10 sample coverage remain unresolved.

`boss_player_history.py` compares forward-time performance models with and without
strictly earlier-run player history. Outputs include failure rates by boss and tier,
paired error uncertainty, and `boss/history/review.html`. Availability is approximated
by start + play duration, which omits pauses and does not reconstruct upload time;
this is retrospective evidence only. `test_boss_player_history.py` checks same-run,
future-run and unfinished-history exclusion and explicit cold starts.
`audit_boss_strata.py` checks performance gains within HP, act, difficulty and boss
strata, with paired whole-run bootstrap intervals from fixed held-out predictions.

`boss_healing_sensitivity.py` explicitly tests cumulative Weary Traveler at A2+,
observed act-entry HP and removal of current HP. It writes `boss/healing/` outputs.
Tests: `test_boss_healing_sensitivity.py`. A0–7 enemy equivalence does not mean
equal player resources; inherited missing HP must not be labeled current-act
deck weakness. Current HP remains an input to survival probability.

`path_to_boss.py` models boss arrival, clearance conditional on arrival, their
product and direct sequence clearance at fixed completed-fight checkpoints 3/6.
No future boss identity or entry HP enters checkpoint predictors. It writes
`local_data/act_validation/path_to_boss/`. See `test_path_to_boss.py` for leakage
and cumulative healing-rule checks and `docs/boss-readiness-evidence.md` for
proposed instrumentation and prospective confirmation requirements.

`boss_development.py` tests forward-only card-development events before each
first boss. It does not read final decks/relics or claim a full starter-deck
reconstruction. Outputs: `boss/development/`. Targeted checks are in
`test_boss_development.py`; results remain exploratory and do not modify ratings.

`ablate_boss_development.py` reports process, partial composition, cost, full
and without-upgrade feature variants, plus full-model player/resource-tier
calibration and paired uncertainty. Outputs: `boss/development/ablation/`.
It reports exploratory tests rather than selecting a product model from
repeatedly reused holdouts. Tests: `test_ablate_boss_development.py`.

`audit_boss_telemetry.py` inventories eligible measured fights by player, ascension
and boss status using the frozen production snapshot. It writes
`boss/telemetry_audit/`. An inventory count is not a validation of measurement
accuracy or completeness; truncated flags are retained for subsequent filtering.

## Frozen confirmation harness

`freeze_boss_experiment.py` exports fixed health, performance and acquired-card
composition candidates as integrity-checked JSON. `freeze`, `score` and `evaluate`
are local commands. `freeze` never overwrites a destination. Score accepts only
pre-boss prefix fields; evaluation joins outcomes separately and excludes training
examples. Default research artifact: `local_data/act_validation/boss/frozen-v1/`.
Read its README before using it. Caller timestamps are not independently attested;
a live prediction capture path is still needed for prospective evidence. No live
logger or production score is deployed by this harness. Checks:
`python -m unittest discover -s tools/power_curve -p test_freeze_boss_experiment.py`.

`check_new_boss_uploads.py` compares a separate confirmation download with the
frozen snapshot and applies fixed candidates to newly discovered run IDs. It
labels pre-freeze uploads as retrospective and flags Fool as unsupported by v1.
Current audit found the old five-character eligibility filter excluded Fool, a
core character in the extracted catalog. Earlier results apply only to that
restricted population; v1 must stay immutable while eligibility is corrected.

`six_character_boss_study.py` corrects eligibility using CharacterPools from
the extracted catalog and reruns the fixed ablations in a separate output
folder (`local_data/act_validation/six_character/`). It preserves frozen v1.
`audit_current_boss_telemetry.py` inventories all accepted solo non-abandoned
measured runs, including pre-boss deaths; it does not condition on boss arrival.
Tests: `test_six_character_boss_study.py`. Neither script deploys a score.

`confirm_future_boss_runs.py` evaluates frozen candidates only on runs whose
start time and S3 upload timestamp both follow the freeze. It reads a separate
confirmation snapshot and stored S3 metadata; no refitting occurs. It outputs
`confirmation/future-cohort-evaluation.json` and flags unsupported Fool entries.
Post-run prefix reconstruction tests the fixed algorithm on future outcomes,
not actual live capture. Tests: `test_confirm_future_boss_runs.py`.

Confirmation checks accept `--snapshot-root <dated-copy>` to keep experiment
inputs separate. Reports count new future-started uploads and exclusions
(multiplayer, modes, abandonment, unsupported/unpublished, missing boss entry)
so an empty confirmation set is not mistaken for a missing-data error.

`boss_interactions.py` compares fixed shallow regularized boosted-tree models
with the linear candidate on the existing six-character snapshot. Outputs are
in `six_character/interactions/`. No hyperparameter search or new uploads are
used. It tests nonlinear interactions and reports the tradeoff between time
and whole-player generalization instead of treating the best pooled rate as
a universally calibrated score.

`checkpoint_interactions.py` evaluates fixed nonlinear and linear models after
non-boss fights 3/6, including pre-boss deaths after each checkpoint. Composition
is built from observed prefixes only; no future boss identity or entry HP is
available. Outputs: `six_character/checkpoint_interactions/`. Regression checks
are in `test_checkpoint_interactions.py` (future cards/outcomes/final-deck
isolation, prefix-only acquisitions, pre-boss deaths, A10 two-boss outcome).

`boss_abandonment_sensitivity.py` scores accepted abandoned runs with fixed
other-player nonlinear models and reports lower/upper clearance bounds without
claiming abandonment is a loss. `audit_readiness_players.py` reports equal-player
and pooled selected-group success plus descriptive player-resampling uncertainty.
These produce `six_character/abandonment/` and `six_character/player_robustness/`.
The consolidated current-snapshot interpretation is `six_character/decision.html`.

`measured_boss_readiness.py` tests direct measured damage/absorbed-block/HP-cost
features from prior fights, with exact raw/log encounter sequence agreement and
HP-flow balance. It omits impossible whole-player validation when only one player
remains. Outputs: `six_character/measured_mechanics/`. Tests distinguish actual
removed HP, absorbed vs generated block and enemy damage vs HP cost in
`test_measured_boss_readiness.py`. This strict cohort is smaller than the log
inventory; mismatch audits must precede relaxing alignment for extra coverage.

`aligned_measured_readiness.py` admits a locally complete three-fight predecessor
window before a unique logged boss start, while rejecting ambiguous target
retries and HP-flow mismatches. Outputs: `six_character/aligned_measurements/`.
Tests are in `test_aligned_measured_readiness.py`. Final snapshot-level claims
and unsupported hypotheses are summarized in
`local_data/act_validation/six_character/snapshot-final-assessment.html`.

## Bounded four-family investigation

Use `bounded_readiness_goal.py`, `report_bounded_readiness.py`,
`run_bounded_validation.py`, then `audit_bounded_population.py` to reproduce
the fixed snapshot investigation and its audit. The bounded study compares
damage/pace, setup/burst safety, defense/endurance and consistency separately
and combined, with fixed linear/tree models and player/time evaluations.
Outputs: `local_data/act_validation/six_character/bounded_goal/report.html`.
The decision contract and completion audit are in
`docs/act-boss-readiness-instrumentation.md` and
`docs/act-boss-readiness-completion-audit.md`. No deployed score is produced.

## Retrospective combat explanations

`explain_boss_outcomes.py` builds checked completed-fight resource accounts from
the existing copied snapshot, with explicit raw-death endpoint fallback, overkill
and attribution flags. `plot_outcome_explanations.py` adds actual turn profiles.
Read `docs/retrospective-combat-explanations.md` for the distinction between
recorded results, comparable-encounter history and unvalidated same-deck replay
probabilities. Outputs: `six_character/outcome_explanations/review.html`.
Tests: `test_explain_boss_outcomes.py`. No prediction fitting or deployment.
