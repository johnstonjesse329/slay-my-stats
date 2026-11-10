"""fight_demand.json for the site: what winning took on each encounter.

A run file says how long each fight took and how much damage got through. This is the
rest of what the Runs page needs to read that fight: how much HP stood in front of the
deck, and what runs that won did on it, whoever played them: the average turns to kill
and the average damage taken. Each floor reads against its own fight, never an average of
different monsters.

The best and worst quarter of those wins (quickest and lightest, slowest and heaviest) ride
along for the min/max bars on every fight, so the average win has a range to read against.

An act reads the same way: each fight against its own winners, then summed, so an act of
hard monsters isn't behind for being hard. Where it lands is among winning acts: behind
is more damage taken than 3 in 4 of them, ahead less than 3 in 4, or faster than 3 in 4
without taking more than the average win. Damage taken decides alone otherwise, since a
poison deck wins slowly and is fine so long as damage taken holds: speed can lift an act
and never sinks one. The quarters are of winning acts in every tier at once, since each
is already held to its own tier's winners; a tier with few wins couldn't have its own.
A behind act says what was lacking from the same two numbers: damage taken is turns
times damage a turn, so it's damage if the fights ran long and block if too much came in
each turn. A run reads the same way again, its acts summed, against the quarters of
winning runs, so it follows from them, and OP is reading ahead in both of the last two
acts.

Ascension changes the fight itself from 8: Tough Enemies at 8 raises enemy HP, Deadly
Enemies at 9 raises their damage, and Double Boss at 10 adds a second boss fight. So an
encounter has one set of lines for under 8 and one for 8 and up, and a fight reads against
its own tier's wins or not at all. Ascension 0 goes with 1 to 7, none of which touch a
monster. 8, 9 and 10 go together: each alone has too few wins to read against.

Three findings shape the reading, and all are in power_curve_decisions.md:

  * A won fight takes all of the enemies' HP, so HP against damage always keeps up and
    only the turns vary. The pace is winners' average turns.
  * Damage a turn is HP over turns, whole turns on both sides, so the numbers on the page
    divide as they read. The last turn stops at the kill, which makes every fight's rate
    a little low in the same way; that matters to an average of rates, and a fight here
    is read alone.
  * Block a turn is capped by need: players block what is coming, and killing first and
    Weak stop damage too. So block over damage in means nothing, and the page draws
    damage taken against what winners took. All of it counts, whatever its source: a run
    file can't split it. What the floor healed comes off it, since that's block after the
    fact, and it lets one line hold a deck that heals after every fight beside one that
    doesn't.

An estimated number of turns or HP lost scored worse than simply quoting the encounter's
usual, so the page shows a ratio and never a predicted result. Run with --check for the
evidence: what the readings said against who lost, and the acts read on runs held out of
the averages they're read against.

Pool comes from the game data, weighed by what the rooms actually held, which is how
encounters with random line-ups and spawns get a fair figure. Game data and aggregated
from runs: gitignored, built locally, deployed with the site.

Co-op reads the same way, per player. An enemy has HP x players x hp_share, so a player
faces their share of the HP. Its averages come from co-op wins. A run file has no damage
per player, so those take the party to split it evenly.

    python fight_demand.py
    python fight_demand.py --check
"""
import json
import math
import re
import statistics
import sys
from collections import defaultdict

import power_curve as pc
import telemetry_report as tr

OUT = pc.WT / "fight_demand.json"

# The ascension the enemies start to change at (Tough Enemies); every level from it on does.
TOUGH = 8
# Ways the monsters are tuned, one line per tier (see tier).
TIERS = 2
# Winning fights a tier takes on an encounter before it has a line to read against.
WON_MIN = 3
# The player's own pets, listed in a room's monster_ids beside the enemies. Two of them
# carry a placeholder 9999 HP, which would otherwise read as a wall of HP to get through.
PETS = {"MONSTER.OSTY", "MONSTER.PAELS_LEGION", "MONSTER.BYRDPIP"}
# No HP in the game data: it revives through forms of 100, 200 and 300 (111, 212, 313 on
# Tough Enemies).
PHASES = {"MONSTER.TEST_SUBJECT": (600, 636)}
# A logged fight overrides the game's pool when more than this came off the enemies,
# which is what respawns (Axebots) and spawns look like from outside.
OVER_POOL = 1.25
# Winning co-op fights a tier takes before its line is theirs and not solo's.
COOP_MIN = 5
# Fights an act takes before it gets a reading. One fight against its line isn't an act.
ACT_MIN = 3
# How close to the end of a lost run a fight has to be for --check to count it as part
# of the loss.
SOON = 3
# The acts a run has to read ahead in to be OP, counted from 0: the second and third, the
# ones that sort runs best. Every held-out run under 8 ahead in both won, at the time of
# writing, as did 5 of the 6 at 9 and up.
OP_ACTS = {1, 2}
# The game version a room's monster_ids starts listing enemies that join mid-fight, not just
# the opening line-up. The last run without them is v0.103.3, the first with them v0.106.1.
SPAWNS_LISTED = (0, 106)
TIER_NAMES = ("under 8", "8 and up")
# What the game data gives a pet (see PETS). On anything else, a patch has added one.
PLACEHOLDER_HP = 9999


def body_pool(monster):
    """(base, Tough Enemies) HP of one enemy, mid-range. Zero when the game data has
    none: Doormaker, gone from the game after v0.103.2, and anything a patch adds until
    the data is refreshed. Those fights get no reading rather than a guess."""
    if monster in PHASES:
        return PHASES[monster]
    record = pc.PD["monsters"].get(monster) or {}
    lo, hi = record.get("hpMin") or (0, 0), record.get("hpMax") or (0, 0)
    return (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2


def hp_share(act, kind):
    """One player's share of a co-op enemy's HP, over its solo HP. The game gives it
    HP x players x this (MultiplayerScalingModel.GetMultiplayerScaling), so the player
    count cancels. The page's keepShare is this function."""
    if act == 0:
        return 1.1
    return 1.3 if act == 2 and kind == "boss" else 1.2


def net_taken(stats):
    """A floor's damage taken with what it healed off it, down to 0: spare healing doesn't
    carry to the next fight. The game counts HP that came back, so overhealing isn't in it,
    and gaining max HP is, because that heals you too. The page's keepTaken is this
    function."""
    return max(0, (stats.get("damage_taken") or 0) - (stats.get("hp_healed") or 0))


def run_fights(runs):
    """One list of fights per run. A co-op fight's damage taken is the party's mean,
    which is what its averages are built from; the page reads the local player's, and each
    keeps them all so --check can too. An abandoned run stays out of the history; the
    page still reads one, because its fights happened."""
    out = []
    for raw in runs.values():
        party = len(raw.get("players") or [])
        if not party or raw.get("was_abandoned"):
            continue
        build = tuple(int(n) for n in re.findall(r"\d+", raw.get("build_id") or ""))
        fights = []
        for act, points in enumerate(raw.get("map_point_history") or []):
            for point in points:
                stats = point.get("player_stats") or [{}]
                kind = point.get("map_point_type")
                for room in point.get("rooms") or []:
                    if room.get("monster_ids") and room.get("turns_taken"):
                        fights.append({
                            "enc": room["model_id"],
                            "ids": [m for m in room["monster_ids"] if m not in PETS],
                            "t": room["turns_taken"],
                            "taken": statistics.mean(net_taken(s) for s in stats),
                            "each": [net_taken(s) for s in stats],
                            "asc": raw.get("ascension") or 0,
                            "build": build,
                            "kind": kind,
                            "act": act,
                            "coop": party > 1,
                            "share": hp_share(act, kind) if party > 1 else 1,
                            "died": False,
                        })
        if fights:
            fights[-1]["died"] = not raw.get("win")
            out.append(fights)
    return out


def logged_pools(logs):
    """{encounter: median HP that came off the enemies} across the fights the mod saw.
    Gross, so what healed back or respawned still counts."""
    chewed = defaultdict(list)
    for derived in logs.values():
        for fight in derived["fights"]:
            if fight["enemy_lost"]:
                chewed[fight["enc"]].append(fight["enemy_lost"])
    return {enc: statistics.median(v) for enc, v in chewed.items()}


def swung(f):
    """Turns the enemies got. They act after you, so a fight you won gave them one less."""
    return f["t"] - (not f["died"])


def winners(fights):
    """What runs that won did on a fight: average turns, average damage taken, and that
    damage for each turn the enemies got, a sum over a sum since a one-turn kill has no
    turn to divide by. A run file's damage taken has everything in it, whatever its
    source, so a logged fight has to be held to this with the run file's number, not the
    log's."""
    turns = sum(swung(f) for f in fights)
    out = {"turns": round(statistics.mean(f["t"] for f in fights), 2),
           "taken": round(statistics.mean(f["taken"] for f in fights), 2),
           "rate": round(sum(f["taken"] for f in fights) / turns, 2) if turns else 0,
           "n": len(fights)}
    # The best quarter, for the green cap of the page's min/max bars: turns of the quickest
    # wins, and damage taken a turn of the lightest. The worst quarter (red cap) follows.
    out["fast"] = round(best_quarter(f["t"] for f in fights), 2)
    light = [f["taken"] / swung(f) for f in fights if swung(f)]
    if light:
        out["light"] = round(best_quarter(light), 2)
    # And the worst quarter, the far end of the page's bars: the slowest wins' turns, and the
    # heaviest wins' damage taken a turn. How bad a win can get and still be one.
    out["slow"] = round(worst_quarter(f["t"] for f in fights), 2)
    if light:
        out["heavy"] = round(worst_quarter(light), 2)
    return out


def best_quarter(values):
    """The median of the lowest quarter of values, at least one of them: how the best wins
    did."""
    low = sorted(values)
    return statistics.median(low[:max(1, math.ceil(len(low) / 4))])


def worst_quarter(values):
    """The median of the highest quarter of values, at least one of them: best_quarter's other end."""
    high = sorted(values)
    return statistics.median(high[-max(1, math.ceil(len(high) / 4)):])


def tier(asc):
    """How an ascension's monsters are tuned: 0 as the game made them, 1 from Tough
    Enemies on. The page's keepTier is this function."""
    return int(asc >= TOUGH)


def winners_of(f, d):
    """Which of an encounter's lines a fight reads against, or None if too few have won it
    with the monsters tuned the same. It never borrows from another tier."""
    line = d["tiers"][tier(f["asc"])]
    how = line.get("coop", line) if f["coop"] else line
    return how if "turns" in how else None


def lines(fights):
    """What winning fights did, and for a party. Fights too few have won leave a tier
    with an empty line."""
    solo = [f for f in fights if not f["coop"]]
    coop = [f for f in fights if f["coop"]]
    out = {}
    if len(solo or coop) >= WON_MIN:
        out.update(winners(solo or coop))
    if len(coop) >= COOP_MIN:
        out["coop"] = winners(coop)
    return out


def many_targets(fights):
    """Whether an encounter can have more than one target alive at a time. The game lists
    the opening line-up, repeats and all, then each kind of enemy that joins, once. So an
    Axebot that comes back when one dies stays one, and a Fabricator killed before it built
    anything still counts, because another run saw the bots. Older game versions only speak
    for an encounter nothing newer has fought: their Axebots came in twos."""
    listed = [f for f in fights if f["build"] >= SPAWNS_LISTED]
    return max(len(f["ids"]) for f in listed or fights) > 1


def table(runs, logged=None):
    """{encounter: {pool, many, tiers}}. pool is [base, Tough Enemies]: the solo HP to
    chew through, from every fight there, won or lost. many is many_targets. tiers holds
    what wins did on it, one entry per tier: turns, taken, rate and n from solo wins, and
    coop for a party, once enough parties have won it."""
    logged = logged or {}
    rooms, wins = defaultdict(list), defaultdict(list)
    for fights in runs:
        won = not fights[-1]["died"]
        for f in fights:
            rooms[f["enc"]].append(f)
            if won:
                wins[f["enc"]].append(f)

    out = {}
    for enc, fights in rooms.items():
        pool = [statistics.mean(sum(body_pool(m)[i] for m in f["ids"]) for f in fights)
                for i in (0, 1)]
        got = logged.get(enc)
        if got and not pool[0]:
            pool = [got, got]
        elif got and got > pool[0] * OVER_POOL:
            pool = [p * got / pool[0] for p in pool]
        out[enc] = {"pool": [round(p) for p in pool], "many": many_targets(fights),
                    "tiers": [lines([f for f in wins[enc] if tier(f["asc"]) == t]) for t in range(TIERS)]}
    return out


def readings(fights, demand):
    """One row per fight, read on its own: the HP it took a turn, over what clearing the
    same HP in winners' turns asks. The page's fightReadings is this function; keep them
    together. In co-op each of those is one player's.

    A lost fight's damage is a ceiling: the run file does not say how much HP came off,
    so this reads as if it all did. The page leaves it out unless a log says. A logged
    fight's HP on the page is what came off, not this table's middle, which only moves
    the two sides of the ratio together.
    """
    out = []
    for f in fights:
        d = demand.get(f["enc"])
        pool = d and d["pool"][f["asc"] >= TOUGH] * f["share"]
        how = pool and winners_of(f, d)
        if not how:
            continue
        ask = pool / how["turns"]
        doing = pool / f["t"]
        out.append({**f, "ask": ask, "doing": doing, "damage": doing / ask})
    return out


def act_totals(fights, demand, taken=lambda f: f["taken"]):
    """One row per act of a run, each fight held to its own winners and the act summed.
    Over 1 is better than winners on all three: pace is their turns over yours, guard is
    their damage taken over yours, with 1 added to both so an act with none still divides,
    and each is what's left of guard once pace is out of it, their damage a turn over
    yours. The fight that ended the run is left out: it says how the run ended, and every
    lost run would read behind for it."""
    out = []
    for act in sorted({f["act"] for f in fights}):
        part = [(f, how) for f in fights if f["act"] == act and not f["died"] and f["enc"] in demand
                and (how := winners_of(f, demand[f["enc"]]))]
        if len(part) < ACT_MIN:
            continue
        turns = sum(f["t"] for f, _ in part)
        win_turns = sum(how["turns"] for _, how in part)
        got = sum(taken(f) for f, _ in part)
        win_got = sum(how["taken"] for _, how in part)
        pace, guard = win_turns / turns, (win_got + 1) / (got + 1)
        out.append({"act": act, "fights": len(part), "turns": turns, "winTurns": win_turns,
                    "taken": got, "winTaken": win_got, "pace": pace, "guard": guard, "each": guard / pace})
    return out


def act_readings(fights, demand, cuts, taken=lambda f: f["taken"]):
    """act_totals, each act read against its own act's quarters of winning acts. pace and
    guard make the verdict and each has its own mark, speed and held; each says why. The
    page's actReadings is this function; keep them together."""
    out = []
    for row in act_totals(fights, demand, taken):
        cut = act_cut(cuts, row["act"])
        place = verdict(row["pace"], row["guard"], cut)
        out.append({**row, "speed": mark(row["pace"], cut["pace"]), "held": mark(row["guard"], cut["guard"]),
                    "verdict": place, "lacking": lacking(row["pace"], row["each"]) if place == "behind" else None})
    return out


def run_totals(acts):
    """A run's acts added up, with pace and guard on the totals. None with no act."""
    if not acts:
        return None
    turns, win_turns = (sum(a[key] for a in acts) for key in ("turns", "winTurns"))
    got, win_got = (sum(a[key] for a in acts) for key in ("taken", "winTaken"))
    return {"turns": turns, "winTurns": win_turns, "taken": got, "winTaken": win_got,
            "pace": win_turns / turns, "guard": (win_got + 1) / (got + 1)}


def run_reading(acts, cuts):
    """A run as a whole, from its act_readings: their totals through the same verdict,
    against the quarters of winning runs, so it follows from the acts it sits above. None
    with no act to read. op is both OP_ACTS reading ahead, whichever way they got there,
    and takes no win: the fight that ended a lost run is left out here as it is from an
    act. The page's runReading is this function; keep them together."""
    whole = run_totals(acts)
    if not whole:
        return None
    ahead = {a["act"] for a in acts if a["verdict"] == "ahead"}
    return {**whole, "verdict": verdict(whole["pace"], whole["guard"], cuts["run"]), "op": OP_ACTS <= ahead}


def players(runs, demand, read):
    """(solo or coop, tier, won the run, read(fights, demand, taken)) for every player of
    every run. The page reads the local player of a party, and any of them could be."""
    for fights in runs:
        mode = "coop" if fights[0]["coop"] else "solo"
        for who in range(len(fights[0]["each"])):
            yield mode, tier(fights[0]["asc"]), not fights[-1]["died"], read(fights, demand, lambda f: f["each"][who])


def player_acts(runs, demand, cuts):
    """(solo or coop, tier, won the run, act readings) for every player of every run."""
    return players(runs, demand, lambda fights, d, taken: act_readings(fights, d, cuts, taken))


def act_rows(runs, demand, cuts):
    """player_acts, one act to a row."""
    for mode, level, won, acts in player_acts(runs, demand, cuts):
        for row in acts:
            yield mode, level, won, row


def quarters(rows):
    """{guard, pace}: where the worst and best quarter of these rows start on each,
    rounded so the page reads the same numbers."""
    return {key: [round(q, 3) for q in statistics.quantiles([r[key] for r in rows], n=4)[::2]]
            for key in ("guard", "pace")}


def cuts_of(runs, demand):
    """{acts: [one per act], run}: the quarters of winning players' acts, act by act, and
    of winning runs as a whole. Every tier and both modes go in together: each act is
    already held to its own tier's winners, and a tier with few wins couldn't have its
    own quarters. Goes in fight_demand.json for the page."""
    won = [acts for _, _, w, acts in players(runs, demand, act_totals) if w and acts]
    acts = sorted({a["act"] for each in won for a in each})
    return {"acts": [quarters([a for each in won for a in each if a["act"] == act]) for act in acts],
            "run": quarters([run_totals(each) for each in won])}


def act_cut(cuts, act):
    """An act's quarters. An act past the last one winners reached has the run's."""
    return cuts["acts"][act] if act < len(cuts["acts"]) else cuts["run"]


def mark(value, edges):
    """Where a number over 1 is better sits between two edges. `keepMark` on the page."""
    return "behind" if value < edges[0] else "ahead" if value > edges[1] else "meeting"


def verdict(pace, guard, cut):
    """Where an act reads among winners: by damage taken, unless it killed faster than 3
    in 4 of them without taking more than the average win. Speed only ever lifts a
    reading. `keepVerdict` on the page."""
    held = mark(guard, cut["guard"])
    return "ahead" if held == "meeting" and pace > cut["pace"][1] and guard >= 1 else held


def lacking(pace, each):
    """What held a behind act back, the worse of the two parts of its damage taken: damage
    if the fights ran long, block if too much came in each turn. `short` in the page's
    actReadings is this function."""
    return "damage" if pace < each else "block"


def band(rows, value, edges, label, outcome=lambda r: r["died"], tag="died here"):
    """How often something went wrong, by band of a reading."""
    print(f"  {label}")
    low = -1e9
    for high in [*edges, 1e9]:
        hit = [r for r in rows if low <= value(r) < high]
        if hit:
            bad = sum(bool(outcome(r)) for r in hit) / len(hit)
            print(f"    {low:>7.2f} to {high:<7.2f} {len(hit):>6} fights  {bad:6.1%} {tag}")
        low = high


def check(runs, demand):
    rows = []
    for fights in runs:
        for i, f in enumerate(fights):
            f["soon"] = fights[-1]["died"] and len(fights) - 1 - i <= SOON
        rows += readings(fights, demand)
    check_rows("Solo", [r for r in rows if not r["coop"]])
    check_rows("\nCo-op, where a death is the party wiping", [r for r in rows if r["coop"]])
    check_acts(runs)


def check_rows(label, rows):
    print(f"{label}: {len(rows)} fights read, {sum(r['died'] for r in rows)} deaths\n")
    damage = lambda r: r["damage"]
    soon = dict(outcome=lambda r: r["soon"], tag=f"lost the run within {SOON} fights")
    won = [r for r in rows if not r["died"]]
    band(rows, damage, (0.5, 0.7, 0.85, 1, 1.2, 1.5, 2), "Damage: this fight / what winners' turns ask")
    band(won, damage, (0.5, 0.7, 0.85, 1, 1.2, 1.5, 2), "Fights won, and what came after", **soon)
    for kind in ("monster", "elite", "boss"):
        part = [r for r in won if r["kind"] == kind]
        print(f"\n{kind}: {len(part)} fights won")
        band(part, damage, (0.7, 1, 1.3), "Damage", **soon)


def held_out(runs, cuts=None):
    """{(mode, tier, act, verdict): [(run won, pace, much slower), ...]}, and the same under
    (mode, tier, "run", verdict) for whole runs and (mode, tier, "run", "op") for OP ones.
    The averages and the quarters come from half the runs and the reading is of the other
    half, both ways round, so every run is read and none against a line it helped make.
    cuts, if given, stands in for the quarters. Tiers stay apart because how often a run
    wins depends on the tier as much as on the reading: at the time of writing, 35% under 8
    and 5% at 9 and up."""
    halves = runs[::2], runs[1::2]
    cells = defaultdict(list)
    for train, test in (halves, halves[::-1]):
        demand = table(train)
        cut = cuts or cuts_of(train, demand)
        for mode, level, won, acts in player_acts(test, demand, cut):
            for row in acts:
                cells[mode, level, row["act"], row["verdict"]].append((won, row["pace"], row["speed"] == "behind"))
            whole = run_reading(acts, cut)
            if whole:
                slow = mark(whole["pace"], cut["run"]["pace"]) == "behind"
                cells[mode, level, "run", whole["verdict"]].append((won, whole["pace"], slow))
                if whole["op"]:
                    cells[mode, level, "run", "op"].append((won, whole["pace"], slow))
    return cells


def check_acts(runs):
    """Run won, by how each act read, and on the acts slower than 3 in 4 winners alone,
    which is whether slow is safe. Then the same by how the whole run read, with OP runs
    among them."""
    cells = held_out(runs)
    rate = lambda c: f"{sum(won for won, *_ in c) / len(c):4.0%} ({len(c):3})" if c else "   -  "
    for mode, level, act in sorted({k[:3] for k in cells if k[2] != "run"}):
        print(f"\n{mode}, {TIER_NAMES[level]}, act {act + 1}, held out: run won, by reading")
        for place in ("behind", "meeting", "ahead"):
            c = cells[mode, level, act, place]
            print(f"  {place:8}{rate(c)}   much slower {rate([x for x in c if x[2]])}")
    for mode, level in sorted({k[:2] for k in cells}):
        print(f"\n{mode}, {TIER_NAMES[level]}, whole run, held out: run won, by reading")
        for place in ("behind", "meeting", "ahead", "op"):
            print(f"  {place:8}{rate(cells[mode, level, 'run', place])}")


def main():
    raw = tr.load_runs()
    runs = run_fights(raw)
    logs, _ = tr.load_logs(raw)
    # A co-op log's HP has the party in it, and the pools here are solo.
    solo_logs = {k: v for k, v in logs.items() if len(raw.get(k, {}).get("players") or ()) <= 1}
    demand = table(runs, logged_pools(solo_logs))
    if "--check" in sys.argv:
        check(runs, demand)
        return
    cuts = cuts_of(runs, demand)
    OUT.write_text(json.dumps({"encounters": demand, "cuts": cuts}, separators=(",", ":")), encoding="utf-8")
    print(f"quarters of winning acts, guard then pace: "
          f"{[(c['guard'], c['pace']) for c in cuts['acts']]}; runs {cuts['run']['guard']}, {cuts['run']['pace']}")
    seen = {m for fights in runs for f in fights for m in f["ids"]}
    missing = sorted(m for m in seen if not body_pool(m)[0])
    print(f"{OUT.name}: {len(demand)} encounters from {len(runs)} runs, "
          f"{OUT.stat().st_size // 1024} KB; no HP known for {missing or 'none'}")
    walls = sorted(m for m in seen if body_pool(m)[0] >= PLACEHOLDER_HP)
    if walls:
        print(f"placeholder HP, probably a new pet for PETS: {walls}")


if __name__ == "__main__":
    main()
