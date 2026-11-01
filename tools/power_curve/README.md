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
| `power_curve.html` | Viewer for `pcs/`. |
| `power_curve_decisions.md` | Valuation guesses and simplifications waiting on review, plus recent fixes. |

## Regenerating

Needs `power_data.json` at the repo root (`python tools/extract_power_data.py`).

```
cd tools/power_curve
aws s3 sync s3://slay-my-stats-gamma-data/raw/ gamma_raw/
python gamma_curves.py            # about 16 minutes for 1,025 runs on 11 workers
python archetypes.py
python formula_curves.py          # after gamma_curves: strength score per floor
python -m http.server 8765 --bind 127.0.0.1   # then open /power_curve.html
```

`gamma_raw/`, `pcs/` and `approaches/` are local only (gitignored), as is
`local.json`: player names by Steam id, and `approaches.py`'s sample runs
(`{"names": {id: name}, "picks": {character: [id, start_time]}}`). Pass the
player's Steam id to `curve(run, steamid)`: in co-op runs it picks whose deck
is scored.
