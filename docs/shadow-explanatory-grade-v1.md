# Shadow explanatory-grade experiment v1 (registered before counting movements)

This is a retrospective research candidate, not a production replacement or a win
probability. Inputs are the fixed six-character copied snapshot and the saved
current completed-run ratings. No new data, live saves, mod or site changes.

## Meaning and physical anchors

Grade observed encounter-adjusted efficiency through each act. Starting/ending HP
and win/loss remain separate explanatory fields. The candidate is deliberately
restricted to recorded turns and net HP expenditure, which exist broadly. It
cannot grade unmeasured damage/block capacity, card causation or shuffle robustness.
Detailed logged explanations are a separate validation/review layer.

For each training fold, normalize each fight's turns and net HP cost to that same
encounter's training winning-fight averages at the same resource/difficulty tier
(A0-1, A2-7, A8, A9, A10). Require >=5 winning fights from >=2 players for an
encounter reference. Use no fallback across encounters or difficulty. A reference
with near-zero HP cost remains usable via (cost+1)/(reference+1), explicitly not a
raw damage capacity. Retain actual turns/HP and reference values beside each ratio.

For each act and tier, derive physical/normalized anchor distributions from training
runs currently graded OP and won; OP-or-Hype and won; and all winning runs. Each
anchor cohort must contain >=10 runs and >=3 players. Report medians and 75th
percentiles, sample counts, player counts and exact values. The saved current grade
is a fixed exploratory source label, not an independent untouched truth.

An act needs >=3 eligible fights and >=70% encounter-reference coverage. Grade:

- OP: normalized net HP cost <= OP median, OR turns <= OP median AND cost <= OP Q75.
- Hype: same two routes using the OP-or-Hype anchor cohort.
- Mid: normalized cost <= all-winner Q75.
- Rough: above those costs without the control/fast-pressure routes.
- Unknown: missing/unsupported/unordered anchors or insufficient fight coverage.

Reject unordered cost anchors rather than silently repair them: OP median <=
strong median <= all-winner Q75, and OP Q75 <= strong Q75. Slow controlled fights
can qualify through the low-cost route; high block is not required of fast kills.
Lower starting HP and the mere fact of winning never change an evaluation grade.

Whole observed-run summary: OP still requires OP in Acts 2 and 3. Otherwise take
an equal-act mean of Rough=0, Mid=1, Hype=2, OP=3; Hype at >=2, Mid at >=1, Rough
below 1. Any observed act with >=3 completed fights but unknown act grade makes
run summary unknown. Missing later acts do not enter; one perfect boss is not an
entire-run promotion. Report act grades and raw metrics to expose aggregation.

The terminal fight of a lost run is excluded in both old/current reading and this
candidate to make the observed-history scope comparable. Its actual outcome/cost
must remain visible in the separate explanation. An early loss has no invented
kill pace; an unknown is not a Rough grade.

## Validation and decision

Evaluate 5 whole-run folds, whole-player holdouts and the existing forward-time
windows, fitting all physical references/anchors from training runs only. Report
all transitions including unknown, separately for winners/losers, old label, tier
and player. Compare rank stability across the two full-coverage fold schemes.

Engineering invariants: no test-run anchor contribution; changing test outcome,
starting HP or final deck cannot change the candidate; lower costs/faster pace
cannot lower its act grade; missing anchors abstain; no cross-tier borrowing.

Research adoption requires >=70% rank coverage in each claimed tier in BOTH
run/player schemes, >=80% exact rank agreement among jointly graded runs, no
unexplained invariant failure, and manual accounts for every changed checked-log
run. All other changed runs need recorded metrics/anchor reasons, not invented
mechanistic explanations. Failure means reject or restrict the candidate, not
keep tuning thresholds after seeing movements.

Surviving these checks means the candidate's mechanics/coverage are usable for
review. It does NOT prove it better represents intrinsic power or establish a
probability. Old-grade win rates are context only; new grades are not optimized
for win prediction. A new meaning must not be sold as a scientific promotion.
