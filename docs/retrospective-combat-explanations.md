# Explain completed combat using recorded numbers

This is a retrospective explanation, separate from the previous boss-win predictor.
Use existing copied snapshots only. No simulation, new data collection, mod changes,
production labels or deployment are required for this exploration.

## Finding

There is enough data for useful fight accounts today. The current snapshot has
2,853 eligible raw solo boss fights with recorded turns, damage taken, healing and
ending/max HP. Detailed logs cover a much smaller population: 60 uniquely matched
bosses across 32 runs/two players; 54 meet the current explanation checks. These
numbers describe coverage, not independent players or broad calibration.

The explanation should answer four things:

1. What the deck actually removed: attributed enemy HP, actual turns, and the shape
   of damage across those turns. Preserve enemy healing, summons/phases and
   unexplained disappearance as separate facts, not invented player damage.
2. What it actually survived: enemy hits absorbed by player block, damage reaching HP, additional HP
   costs, healing and the final cushion. Killing early and Weak may reduce demand,
   but the amount thereby avoided is a counterfactual, not a measured block number.
   Damage soaked by pets is also not included in the current player-block total.
3. What the engine actually used: energy spent, cards played, recorded draws and
   observed low/high-output turns. Usage is not maximum potential or causal proof
   that a specific card won the fight.
4. What the remaining margin was: actual ending HP and resource use. A narrow finish
   supports 'won narrowly in this attempt,' not an exact probability of losing under
   a different shuffle.

## Three checked examples

- Necrobinder A1 vs Knowledge Demon: 409 enemy HP removed in 7 turns; 33 blocked;
  no enemy HP damage; started and ended at 76 HP. Used 44 energy and played 55 cards.
  The boss recovered 30 HP during the fight, which is explicitly recorded.
- Fool A0 vs Vantom: 173 enemy HP removed in 11 turns; 89 blocked; 40 enemy HP damage
  plus 2 additional HP costs; 43 starting HP became 1. Used 30 energy and 38 cards.
- Ironclad A3 vs Kaiser Crab: 408 enemy HP removed in 9 turns; 136 blocked; 53 enemy
  HP damage plus 14 additional HP costs, offset by 18 healing; 49 starting HP became
  0. Used 39 energy and 38 cards. Endpoint comes from the saved death state because
  no logged combat-end event exists; the independently recorded HP flows reconcile.

These are different encounters/strategies and deliberately selected illustrations,
not a ranking of characters or an estimate of population success rates. The stronger
claim 'this caused the win/loss' needs causal or counterfactual evidence. What we can
already say is which recorded output and resource costs produced the observed margin.

## Probability boundary

Keep three concepts distinct:

- Actual result and resource accounting: known for a completed fight where records
  reconcile. A win is not assigned a new probability after it happened.
- Observed comparable-encounter success: available from raw runs, with character,
  act/difficulty, selection, counts, players and uncertainty attached. Examples in
  the report include 5/7, 4/4 and 15/21; none is this same deck's replay probability.
  Tiny samples must not become a confident percentage.
- Same-deck robustness to different shuffles, choices or enemy moves: not established
  by these records. Observed variability is descriptive. A quantified counterfactual
  probability requires suitable repeated evidence or a separately validated simulator.

This framing can use target-boss damage/block/turn data because it explains a completed
fight. Those fields remain forbidden inputs to a prediction made before that fight.
A2+ healing affects the starting budget; do not call inherited missing HP deck weakness.
A10's two bosses need separate accounts plus a sequence-level survival account. Current
detailed examples are A0-5; do not claim high-ascension or Dread calibration.

## Prototype and reproduction

Open `local_data/act_validation/six_character/outcome_explanations/review.html` for
plain-language examples and turn charts. Numbers link to `boss_facts.csv`,
`turn_facts.csv`, `examples.json`, `inventory.json` and `raw_field_coverage.json`.
`example-verification.json` checks each displayed health account and attribution.

Run with the repository virtual-environment Python:

```powershell
infra/.venv/Scripts/python.exe tools/power_curve/explain_boss_outcomes.py
infra/.venv/Scripts/python.exe tools/power_curve/plot_outcome_explanations.py
infra/.venv/Scripts/python.exe -m unittest discover -s tools/power_curve -p test_explain_boss_outcomes.py
```

The plot script should follow the explanation script; it reads generated examples.
Five targeted tests cover accounting, death-endpoint reconciliation, overkill, and
refusing to fill a missing winning endpoint with a potentially different room boundary.
No public display or causal card-attribution implementation is included.
