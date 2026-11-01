# Power curve prototype

Offline tools for working out how strong a run's deck was, floor by floor. Not
part of the site build, apart from `export_strength.py`'s output. Kept so the data can be regenerated when a patch drops
and new approaches can be checked against it.

| File | What it does |
|---|---|
| `power_curve.py` | Small dummy-fight sim. For each floor's deck and relics it plays sampled games and reports damage, block, energy and draw per turn, plus a fights table with real turns and damage taken. |
| `gamma_curves.py` | Runs the sim over every run pulled from gamma into `gamma_raw/`, writing `pcs/<steamid>-<start_time>.json` and `pcs/index.json`. |
| `archetypes.py` | Labels each run's archetype from its final deck and prints a baseline per character and archetype. |
| `approaches.py` | Compares cheaper estimates (deck averages, card/relic lookup) against the sim. |
| `fights_vs_setup.py` | Checks real fights: do decks with more Powers take more damage or need more turns than others facing the same encounter? Reads `pcs/`. |
| `predict_fights.py` | Scores each way of measuring a deck (sim, deck averages, a cheap formula) on how well it predicts real damage taken and turns, fitted on half the runs and tested on the other half. Reads `pcs/`. |
| `formula_curves.py` | Fits the cheap formula to every real fight, saves the weights to `formula_weights.json`, and scores each floor's deck in `pcs/`: expected damage taken and turns against an average deck, plus what the floor added or removed. No sim; seconds for all runs. |
| `export_strength.py` | Writes `deck_strength.json` at the repo root: every card's and relic's numbers for the formula, which `js/deck-strength.js` turns into the Runs page's damage, block, energy and cards per turn. Game data, so gitignored; re-run after a game-data refresh. |
| `validate_floors.py` | Walks every fight in `gamma_raw/` with the deck that walked into it and checks the Runs page's four lines against real damage taken and turns: each bucket against its counterpart, the fitted composite held out by run, the floor-to-floor claim, calibration by decile, and how much of the deck the model can't see. No sim, no `pcs/`. |
| `derive_telemetry.py` | Turns the mod's raw event log into per-fight and per-turn numbers, and checks them against themselves (HP given and taken two ways, energy balance, turn counts against rounds, no card played that was never drawn). Every reading of an event lives here, not in the game, so a wrong reading is a re-derive of logs already uploaded rather than another played run. |
| `test_derive_telemetry.py` | The deriver's tests: scripted logs covering the turn model, including the first version's failure (an enemy-phase hit must land in the player's turn) as a regression. Runs in a second, needs no game. |
| `test_data_coverage.py` | Fails when the game data carries a flag the cheap formula never reads -- the shape of three bugs that cost real numbers this session. Every extractor flag must be read, deliberately unread with a reason, or listed as a known gap. |
| `telemetry_report.py` | Reads the mod's event logs (`telemetry/<steamid>/<start_time>.json.gz`) in `telemetry_raw/` and sets them against the Runs page: damage, block and energy a turn beside the projection for the deck that walked into that fight. Section 3 is the collector's check -- damage taken against the run file's own, turn counts against the run's, and the deriver's self-checks. Section 4 measures each fight from the enemies' HP rather than our hit events (pool, HP removed a turn with its median and peak, their intent, block cover, junk). Section 5 reads each floor against every run in the data that fought the same encounter: turns and damage taken against your own median. |
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
python validate_floors.py         # checks the Runs page's four lines against real fights
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
