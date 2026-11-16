# Bounded readiness investigation: completion audit

Objective source: the user-provided `goal-objective.md`, mirrored in
[act-boss-readiness-goal.md](act-boss-readiness-goal.md).

This audit concerns completion of the bounded snapshot investigation, including
negative and insufficient-evidence decisions. It does not claim a validated
universal deck-power threshold or a production probability model.

| Requirement | Authoritative evidence | Result |
|---|---|---|
| Fixed copied data, all catalog characters, solo/published eligibility | `six_character/snapshot-manifest.json`, `audit.json`; `bounded_goal/eligible_population_audit.csv` | Verified input hashes; six characters including Fool; population counts by player, character, difficulty, act, endpoint and checkpoint |
| Four exact feature families and quality flags | `bounded_goal/feature_dictionary.csv`; `bounded_readiness_goal.py` | Formulas, units, requirements and unknown states documented; turn-level damage requires attribution/HP-delta agreement |
| Raw/log alignment and quality exclusions by player/outcome | `bounded_goal/measurement_audit.csv`, `coverage_by_outcome_player.csv` | Missing, ambiguous, retry, HP-flow and unexplained-damage restrictions reported |
| Boss-specific distributions and failure analysis for all four families | `boss_distributions.csv`, `matched_boss_contrasts.csv`, `counterexamples.csv`, `prior_measurement_overlap.png` | One comparable clear/loss pair supports only descriptive counterexamples; sparse contrasts explicitly insufficient |
| No future-state leakage and correct outcomes | `bounded_goal/tests.json`; targeted regression modules | 42 checks cover final/future cards, target results, A10 sequencing, earlier cleared acts, pre-boss death, duplicate retries, HP/healing distinctions and actual damage/block definitions |
| Fixed baseline comparisons for each family and combined set | `bounded_goal/scores.csv`, `predictions.csv`, `uncertainty.csv`, `numerical_gate_audit.csv` | 72 stage/split/family/model comparisons; health/context includes known prior-fight progression; preprocessing is train-only; both player and time validations reported |
| Calibration/coverage/HP/player reporting | `calibration_coverage_subgroups.csv`; prior candidate `player_robustness/` | Rates, counts, coverage, intervals and HP/player strata retained; prior broad-model robustness is not passed off as measured-family validation |
| Abandoned outcomes treated as censored | `abandonment/bounds.csv`, source `boss_abandonment_sensitivity.py`; report limitations | Existing broad-candidate conservative bounds retained. The only abandoned telemetry run has one lost fight, zero completed fights and no boss; it supplies no eligible measured checkpoint, so measured-window bounds cannot change. See `log_eligibility.csv` |
| Per-family/checkpoint/difficulty verdicts | `bounded_goal/family_gate_table.csv` | 60 explicit cells; A8/A9/A10 absence is not filled using lower-level averages; measured predictive claims remain insufficient |
| One report, reviewable figures and reproduction path | `bounded_goal/report.html`, `report.md`; commands below | Consolidated results and plots, complete compared variants, diagnostic versus predictive evidence separated |
| Precise instrumentation specification | [act-boss-readiness-instrumentation.md](act-boss-readiness-instrumentation.md) | Descriptive measurements and health budget only; no measured sufficiency grade, exact probability or Dread calibration; unknown/coverage behavior explicit |
| Final machine audit | `bounded_goal/completion-audit.json` | Artifact existence, expected comparison/grid completeness, input hashes, test status, valid probabilities and no duplicate predictions checked |

All artifact paths in the table are under `local_data/act_validation/six_character/`.
Bare CSV/PNG names refer to its `bounded_goal/` subfolder; named sibling folders
refer to prior contextual studies. Repository source filenames refer to
`tools/power_curve/`.
The report package's files are generated locally and kept out of Git with player
data. Scripts, research goal, audit and specification are repository sources.

## Reproduce

From the repository root, using the dependencies in
`tools/power_curve/analysis-requirements.txt`:

```powershell
$env:OMP_NUM_THREADS = '4'
$env:MPLCONFIGDIR = Join-Path (Get-Location) 'local_data/act_validation/matplotlib'
infra/.venv/Scripts/python.exe tools/power_curve/bounded_readiness_goal.py
infra/.venv/Scripts/python.exe tools/power_curve/report_bounded_readiness.py
infra/.venv/Scripts/python.exe tools/power_curve/run_bounded_validation.py
infra/.venv/Scripts/python.exe tools/power_curve/audit_bounded_population.py
```

These commands use the existing snapshot and do not fetch data, read live game
saves, change the mod, contact players, deploy infrastructure or publish a score.
Historical reuse of the labels remains exploratory and is stated in the report.

## Final decision

The investigation meets its completion contract through explicit results, not by
finding a desired positive answer. None of the four measured capability families
has satisfied the written predictive-information gates. It is appropriate to
instrument validated damage/turn, absorbed block, HP expenditure and consistency
as observations with coverage/unknown status. It is not appropriate to instrument
those measurements as proven act-boss sufficiency targets or precise individual
clearance probabilities. Unsupported high-ascension and Dread claims remain
unknown. This is the final outcome of this bounded goal; additional model searches
or requests for new gameplay are not required for its completion.
