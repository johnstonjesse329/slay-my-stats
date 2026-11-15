# Boss-readiness instrumentation: evidence contract

This is an analysis protocol, not authorization to publish a score. Solo standard accepted runs only; held uploads, multiplayer and Dread do not calibrate these estimates.

## Intended measurements

1. Demonstrated current-act performance: encounter-adjusted kill speed and HP expenditure from completed fights, with data coverage. It is an observation of play, not a causal card/deck valuation.
2. Survival margin: current HP and uncertainty about future HP cost. Inherited missing HP is not a deck weakness; cumulative A2+ healing is explicit.
3. Outcome estimates: chance to reach the first boss, chance to clear the boss sequence given arrival, and chance to clear the sequence from the current checkpoint. A10 Act 3 requires both bosses. Displaying an estimated percentage requires validation distinct from performance labels.

## Retrospective evidence requirements

- Every predictor can be reconstructed using only events available at the prediction checkpoint. Target-fight outcome, future route, final deck and second-boss identity cannot leak into earlier predictions.
- Compare against health/context baseline. Paired run-level uncertainty must support a useful improvement; inspect player and difficulty subgroups rather than relying on pooled averages.
- Checkpoint populations are explicit: act entry, after fight 3, after fight 6, boss entry. Surviving later is not itself evidence the model improved.
- For an exploratory 'high confidence' group, use fixed >=90% model threshold; report observed success, prediction average, coverage and interval. Do not rename a threshold after looking at outcomes.
- A nominal 90% estimate is not validated when its rate is materially lower for unseen players or a supported difficulty group. Small groups must be labeled insufficient evidence rather than pooled into a confident claim.
- Whole-player holdouts test cold-start transfer. Player history may only use past available runs; it is not objective deck power. The existing history experiment did not help.
- Repeated exploration of the frozen snapshot is discovery, not independent confirmation. No retrospective p-value or bootstrap erases that fact.

## Prospective confirmation before product confidence claims

Freeze model/features, thresholds, exclusions and primary endpoint before receiving new outcomes. Save predictions using data available at that moment; store model version, stage/act, ascension, feature coverage and uncertainty. Join outcomes later. Run in shadow mode first; no publishing is implied.

Primary endpoint: whole act boss-sequence clear from the stated checkpoint. Secondary: boss arrival and conditional clearance. Keep A0Ã¢â‚¬â€œ1/A2Ã¢â‚¬â€œ7 resource rules and A8/A9/A10 distinctions visible. Track new-player versus established-player behavior separately.

For each population where a high-confidence claim is intended, gather enough independent runs and players for an informative interval around observed success and adequate coverage. As an analysis default, seek a 95% lower success bound >=85% for nominal >=90% predictions, plus evidence of calibration near 90%, no material subgroup failure and improvement over health/context. These thresholds are proposed review criteria, not user-approved product requirements. Do not use 15 acts from one person as 15 independent players. Use player/run clustering and time sensitivity.

If current data cannot meet a requirement, report the shortfall and keep the claim unvalidated. Prefer measured performance and health budget with an explicit unknown outcome probability to fabricated certainty.

## Current audit decision (November 14, 2026 snapshot)

The retrospective evidence supports recent-performance and acquired-card composition
as candidate predictive inputs. It does not validate universal calibrated probabilities
or mechanical damage/block sufficiency thresholds. Cold-start subgroup calibration
fails despite acceptable pooled rates. Full development features do not show a
supported A9/A10 error gain. Process-only counts worsen player-holdout error.

All eligible measured telemetry is from one player at A1â€“A4: 23 runs, 385 fights,
48 bosses (37 wins, 11 losses). There is no eligible high-ascension measured evidence.
A8/A9/A10 mechanical targets therefore remain unvalidated. Reusing the same
snapshot with additional feature searches is discovery, not independent confirmation.

Next work should freeze a shadow-evaluation specification and validate the data
contract, then collect complete additional-player and A8/A9/A10 solo telemetry
including losses and pre-boss deaths. Existing production collection already captures
event logs; this audit authorizes no new deployment. Unsupported populations must
remain explicit unknowns, not receive confidence borrowed from A0â€“7 averages.

## Capture audit and confirmation route

The mod's RunEndPatch runs after RunHistorySaveManager.SaveHistory and enqueues
telemetry at run end. EventHooks records fight/turn events in memory; WriteDebug
is called after combat end. That live file has no complete frozen-model prefix
contract. See the sibling mod repository's SlayMyStatsCode/{RunEndPatch,EventHooks,EventLog}.cs.

A new mod release is not necessary to independently test a frozen deterministic
algorithm on future-started runs: checkpoint inputs can be reconstructed after
the run, provided future outcomes never enter the scorer. This is prospective
cohort evaluation of a pre-fixed algorithm, not validation of live capture timing.
`confirm_future_boss_runs.py` requires both run start and S3 upload modification
time after freeze, excludes training IDs, and flags unsupported Fool predictions.
It does not convert these research models into calibrated product confidence.

The current metadata snapshot contains zero qualifying future runs. New data is
the remaining barrier to independent confirmation. Existing retrospective results
show A9 and player-specific calibration failures. They cannot become conclusive
through additional searches of the same labels. The prepared checks can be rerun
once complete new solo runs and telemetry arrive, especially from additional
players at A8/A9/A10 and including losses. No outreach or deployment was performed.
