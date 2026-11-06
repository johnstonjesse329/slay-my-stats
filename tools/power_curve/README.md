# Power curve prototype

Offline tools for working out how strong a run's deck was, floor by floor. Not
part of the site build, apart from what `export_measured.py` and `fight_demand.py` write. Kept so the data can be regenerated when a patch drops
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
| `export_strength.py` | Writes `deck_strength.json` at the repo root: every card's and relic's numbers for the formula. The estimate is off the Runs page, so the site doesn't read this; it stays for patch-day work. Game data, so gitignored; re-run after a game-data refresh. |
| `validate_floors.py` | Walks every fight in `gamma_raw/` with the deck that walked into it and checks the formula's four lines against real damage taken and turns: each bucket against its counterpart, the fitted composite held out by run, the floor-to-floor claim, calibration by decile, and how much of the deck the model can't see. No sim, no `pcs/`. |
| `derive_telemetry.py` | Turns the mod's raw event log into per-fight and per-turn numbers, and checks them against themselves (HP given and taken two ways, energy balance, turn counts against rounds, no card played that was never drawn). Every reading of an event lives here, not in the game, so a wrong reading is a re-derive of logs already uploaded rather than another played run. |
| `test_derive_telemetry.py` | The deriver's tests: scripted logs covering the turn model, including the first version's failure (an enemy-phase hit must land in the player's turn) as a regression. Runs in a second, needs no game. |
| `test_data_coverage.py` | Fails when the game data carries a flag the cheap formula never reads -- the shape of three bugs that cost real numbers this session. Every extractor flag must be read, deliberately unread with a reason, or listed as a known gap. |
| `telemetry_report.py` | Reads the mod's event logs (`telemetry/<steamid>/<start_time>.json.gz`) in `telemetry_raw/` and sets them against the formula: damage, block and energy a turn beside the projection for the deck that walked into that fight. Section 3 is the collector's check -- damage taken against the run file's own, turn counts against the run's, and the deriver's self-checks. Section 4 measures each fight from the enemies' HP rather than our hit events (pool, HP removed a turn with its median and peak, their intent, block cover, junk). Section 5 reads each floor against every run in the data that fought the same encounter: turns and damage taken against your own median. |
| `export_measured.py` | Writes `measured_runs.json` at the repo root: what the runs with an event log actually did, floor by floor: damage aimed, arrived and taken, HP removed, cards and energy played. Player data, so gitignored. The ingest Lambda has a port (`infra/lambda/ingest/measured.py`); `infra/tests/test_measured.py` keeps the two equal. |
| `fight_demand.py` | Writes `fight_demand.json` at the repo root: each encounter's HP pool and what winning runs did on it, any character, in one line per tier of how the monsters are tuned (under 8, and 8 and up, where Tough Enemies, Deadly Enemies and Double Boss come in): average turns, damage taken, and damage taken a turn, plus the best tenth of those wins (`fast`, the median turns of the quickest tenth; `light`, the median damage taken a turn of the lightest) for the ring on the damage charts' elite and boss floors. Damage taken here has what the floor healed off it, down to 0. The Runs page's Keeping Up charts read that floor's fight against its own tier's line, solo and per player in co-op. Each act is ranked among winning acts, whose quarters (`cuts`, per act and for whole runs, every tier together) go in the JSON too: behind is more damage taken than 3 in 4 of them, ahead less than 3 in 4, or faster than 3 in 4 without taking more than the average win. A whole run reads the same way on its acts' totals, against winning runs' quarters, and OP is reading ahead in Acts 2 and 3, for the run's header bar and the run list. Each encounter also says whether it can have more than one target alive at a time (`many`), for the hover box. `--check` prints the evidence: what the readings said against who lost, and acts read on runs held out of the averages. Built from game data and runs, so gitignored. A run prints any monster with no HP and any placeholder HP, which is what new content looks like. |
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
