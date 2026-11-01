"""What the deck actually did, per turn, against what the Runs page projected.

Reads the mod's raw event logs (one gzipped object per run, as the ingest Lambda
stores them), derives the numbers with `derive_telemetry`, and sets them against
the deck that walked into each fight.

    aws s3 sync s3://slay-my-stats-gamma-data/telemetry/ telemetry_raw/
    aws s3 sync s3://slay-my-stats-gamma-data/raw/ gamma_raw/
    python telemetry_report.py [--run <start time>]

Three sections:

1. what the turns did on their own -- damage, block, energy, cards;
2. the projection beside the measurement, for the deck that walked in;
3. the log against the run file's own record. This is the collector's check, not
   the model's: the run already says what each fight cost in HP and how many turns
   it took, so a disagreement here is the recording's fault and names itself.

Logs are read as they are; every judgement about them lives in derive_telemetry, so
a wrong reading is re-derived rather than replayed.
"""
import gzip
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import approaches as ap  # noqa: E402
import derive_telemetry as dt  # noqa: E402
import power_curve as pc  # noqa: E402
import predict_fights as pf  # noqa: E402
import run  # noqa: E402

TELEMETRY = HERE / "telemetry_raw"
RAW = HERE / "gamma_raw"
FROST = pc.ORB_PASSIVE["Frost"]


def cycle_table():
    """{monster: damage a turn its move list averages} -- the smooth expectation.

    A fight's recorded moves are exact but bounded by how long the fight lasted: kill
    the enemy on turn 3 and it never shows you turns 4 to 6. This is what the same
    monster averages if its moves come round evenly, so a short fight can still be
    read against what the encounter was capable of. Moves that deal no damage count
    as zero, which is what they are.
    """
    out = {}
    for name, record in pc.PD["monsters"].items():
        moves = record.get("moves") or []
        if not moves:
            continue
        per_move = [sum((i.get("dmg") or 0) * (i.get("hits") or 1)
                        for i in move.get("intents") or []) for move in moves]
        out[name] = sum(per_move) / len(per_move)
    return out


def move_table():
    """{move id: ([(damage per hit, hits)], what its monster averages a turn)}.

    Damage per hit is kept separate from hits because an enemy's Strength lifts each
    hit, not the total, and the owner's cycle average rides along so a fight that
    ended early can be read against the whole move list.
    """
    cycles = cycle_table()
    out = {}
    for name, record in pc.PD["monsters"].items():
        for move in record.get("moves") or []:
            out[move["id"]] = ([(i.get("dmg") or 0, i.get("hits") or 1)
                                for i in move.get("intents") or [] if i.get("dmg")],
                               cycles.get(name, 0))
    return out


def load_logs():
    """{(steam id, run start time): derived run} for every v3 log on disk.
    Older per-turn summaries are counted and set aside: they carry v1's reading."""
    out, older = {}, 0
    moves = move_table()
    for f in sorted(TELEMETRY.rglob("*.json.gz")):
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                log = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(log, dict) or "log" not in log:
            older += 1
            continue
        try:
            out[(f.parent.name, int(f.name.split(".")[0]))] = dt.derive(log, moves)
        except (ValueError, TypeError, KeyError):
            continue
    return out, older


def load_runs():
    """{(steam id, run start time): raw run} from gamma_raw/."""
    if not RAW.exists():
        return {}
    import gamma_curves as g
    g.RAW = RAW
    return dict(g.load())


def align(fights, timeline):
    """Pairs the log's fights with the run's combat nodes by encounter id, in order.

    A fight can exist in one list and not the other -- the mod sees an event
    encounter the run file records as an event, and a run written by an older
    parser may lack a fight the log has -- so this aligns on content rather than
    assuming the two lists line up. Sequence alignment keeps the order and skips
    whichever side is missing an entry.
    """
    combats = [n for n in timeline if n.get("turns") or str(n.get("enc") or "").startswith("ENCOUNTER.")]
    a = [f.get("enc") or "" for f in fights]
    b = [n.get("enc") or "" for n in combats]

    # Longest common subsequence on the encounter ids: O(len(a)*len(b)), and both
    # lists are under a few hundred.
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            table[i][j] = (table[i + 1][j + 1] + 1 if a[i] and a[i] == b[j]
                           else max(table[i + 1][j], table[i][j + 1]))
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if a[i] and a[i] == b[j]:
            pairs.append((fights[i], combats[j]))
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def costs_of(deck):
    """{card id: energy cost} for a deck, as the formula sees it."""
    out = {}
    for c in deck:
        cid = c.get("id") if isinstance(c, dict) else str(c)
        row = pf.card_row(c)
        out[cid] = 3 if (c.get("x") if isinstance(c, dict) else False) else (row.get("c") or 0)
    return out


def throughput(fight, costs):
    """What a fight's turns put out, measured the way the deck is actually judged.

    Cards played is the honest unit: a card played for free (Cascade takes one off
    the draw pile straight into play) is energy the deck did not have to spend, so
    raw energy under-reads a deck that cheats cards into play. `equiv` is what those
    plays would have cost at list price -- the energy a deck of that shape needs to
    do what it did.
    """
    turns = fight["turns"]
    if not turns:
        return None
    played = statistics.mean(len(t["played"]) for t in turns)
    free = statistics.mean(len(t["auto_played"]) for t in turns)
    equiv = statistics.mean(sum(costs.get(c, 0) for c in t["played"]) for t in turns)
    spent = statistics.mean(t["spent"] for t in turns)
    return {"played": played, "free": free, "equiv": equiv, "spent": spent}


def measured(derived):
    """Mean per turn across every fight in the logs, in the units the projection uses.

    Two units matter and are easy to get wrong: the projection's damage is per
    target, so a turn that hit three enemies must not contribute three times its
    damage; and its energy is what the turn had to spend, which is what it spent
    plus what it left -- not what it started with.
    """
    rows = [t for f in derived.values() for fight in f["fights"] for t in fight["turns"]]
    if not rows:
        return None
    mean = lambda key: statistics.mean(t.get(key) or 0 for t in rows)  # noqa: E731

    energy = [t["available"] for t in rows if t.get("available") is not None]
    return {
        "turns": len(rows),
        "damage": mean("dmg_each"),
        "damage_total": mean("dmg"),
        "targets": statistics.mean(len(t["targets"]) or 1 for t in rows),
        "block": mean("bgn"),
        "blocked": mean("blocked"),
        "taken": mean("taken"),
        "energy": statistics.mean(energy) if energy else 0.0,
        "energy_start": mean("e0"),
        "spent": mean("spent"),
        "drawn": statistics.mean(len(t["hand"]) + len(t["drawn"]) for t in rows),
        "played": statistics.mean(len(t["played"]) for t in rows),
        "attacks": mean("attacks"),
        "potions": sum(1 for t in rows if t["potions"]) / len(rows),
        "vuln": sum(1 for t in rows if t["vuln"]) / len(rows),
        "weak": sum(1 for t in rows if t["weak"]) / len(rows),
        "vuln_dmg": (sum(t["vuln_dmg"] for t in rows) / sum(t["dmg"] for t in rows))
        if sum(t["dmg"] for t in rows) else 0.0,
    }


def projected(deck, rids):
    """The Runs page's four lines for that deck, in the same units."""
    f = pf.formula(deck, rids)
    return {
        "damage": (f["f_dmg"] + f["f_str"] + f["f_dot"])
        * (1 + f["f_vuln_bonus"] * f["f_vuln"] * (1 + f["f_vuln_double"]))
        * (1 + f["f_weak_bonus"] * f["f_weak"]),
        "block": (f["f_block"] + f["f_dex"] + f["f_turnblock"] + f["f_frost"] * FROST + f["f_summon"])
        * (1 + pf.WEAK_MULT * f["f_weak"]),
        "energy": f["f_energy"],
        "drawn": f["f_seen"],
    }


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return 0.0 if not sx or not sy else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    for r, i in enumerate(order):
        out[i] = float(r)
    return out


def spearman(xs, ys):
    return pearson(rank(xs), rank(ys))


def encounter_baseline(runs):
    """{(encounter): (runs fought, median turns, median damage taken)} from the run
    files alone.

    This is the relative anchor: a floor's fight is read against how long it usually
    takes *you* to clear it, and what it usually costs you, so nothing needs an
    invented target. Run files exist for every run, telemetry or not, so the anchor
    is not limited to the handful the mod has been in.
    """
    seen = {}
    for (sid, ts), d in runs.items():
        try:
            parsed = run.parse_run_data(d, steam_id=sid, fallback_ts=ts)
        except Exception:
            continue
        for node in parsed.get("timeline") or []:
            enc = node.get("enc")
            if not enc or not node.get("turns"):
                continue
            seen.setdefault(enc, []).append((node.get("turns") or 0, node.get("dmg") or 0))
    return {enc: (len(v), statistics.median(t for t, _ in v), statistics.median(g for _, g in v))
            for enc, v in seen.items()}


def main():
    only = None
    if "--run" in sys.argv:
        only = int(sys.argv[sys.argv.index("--run") + 1])
    logs, older = load_logs()
    runs = load_runs()
    if not logs:
        print(f"No v3 event logs in {TELEMETRY}"
              + (f" ({older} older summaries, which carry v1's reading)" if older else "")
              + ". Sync them from the data bucket first.")
        return
    print(f"{len(logs)} run(s) with an event log"
          + (f", {older} older summary/summaries set aside" if older else "")
          + (f", {len(runs)} run files to join" if runs else ", no run files (measured only)"))

    # 1. What the turns did, on their own.
    m = measured(logs)
    if m:
        print(f"\n1. Measured per turn, {m['turns']} turns")
        print(f"   damage dealt {m['damage']:5.1f} a target ({m['targets']:.2f} targets hit a turn,"
              f" {m['damage_total']:5.1f} in all)")
        print(f"   block gained {m['block']:5.1f}   damage taken {m['taken']:5.1f}"
              f"   of which blocked {m['blocked']:5.1f}")
        print(f"   energy {m['energy']:5.1f} to spend a turn ({m['energy_start']:4.1f} at turn start,"
              f" {m['spent']:4.1f} spent)")
        print(f"   cards {m['drawn']:4.1f} seen, {m['played']:4.1f} played"
              f"   attacks {m['attacks']:4.1f}   potions on {m['potions']:.0%} of turns")
        print(f"   {m['vuln_dmg']:.0%} of the damage you dealt landed on a Vulnerable target")

    # 2. Projected against measured, where the run files are here.
    if not runs:
        return
    rows = []
    for (sid, ts), derived in logs.items():
        d = runs.get((sid, ts))
        if d is None or (only and ts != only):
            continue
        try:
            parsed = run.parse_run_data(d, steam_id=sid, fallback_ts=ts)
            st = ap.states(d, sid)
        except Exception:
            continue
        for fight, node in align(derived["fights"], parsed.get("timeline") or []):
            floor = node["floor"] + 1
            if floor < 2 or floor - 2 >= len(st):
                continue
            _, deck, rids, _ = st[floor - 2]
            turns = fight["turns"]
            if not turns:
                continue
            rows.append({
                "run": ts, "floor": floor, "enc": node["enc"],
                "p": projected(deck, rids),
                "m": {"damage": statistics.mean(t["dmg_each"] for t in turns),
                      "block": fight["bgn"] / len(turns),
                      "energy": statistics.mean([t["available"] for t in turns
                                                 if t["available"] is not None] or [0])},
                "run_taken": node.get("dmg") or 0,
                "run_turns": node.get("turns") or 0,
                "log_taken": fight["taken"],
                "log_turns": len(turns),
                "vuln": pf.formula(deck, rids)["f_vuln"],
                "weak": pf.formula(deck, rids)["f_weak"],
                "m_vuln": fight["vuln_share"],
                "m_weak": sum(1 for t in turns if t["weak"]) / len(turns),
                "thru": throughput(fight, costs_of(deck)),
            })
    if not rows:
        print("\nNo fight could be matched to a run file.")
        return
    print(f"\n2. Projected against measured, {len(rows)} fights")
    print("   damage and block are what the deck could play all-in for that job, so they read")
    print("   as ceilings; energy is what the turn actually had to spend.")
    for key, label in (("damage", "damage a turn"), ("block", "block a turn"), ("energy", "energy a turn")):
        rho = spearman([r["p"][key] for r in rows], [r["m"][key] for r in rows])
        print(f"   {label:<15} projected {statistics.mean(r['p'][key] for r in rows):5.1f}"
              f"   measured {statistics.mean(r['m'][key] for r in rows):5.1f}   rho {rho:+.3f}")

    # What the two conditional multipliers guess, against what the fights did.
    guessed_v = statistics.mean(r["vuln"] for r in rows)
    guessed_w = statistics.mean(r["weak"] for r in rows)
    seen_v = statistics.mean(r["m_vuln"] for r in rows)
    print(f"\n   conditional multipliers (the share of damage that landed at the boost)")
    print(f"     Vulnerable   formula assumes {guessed_v:5.0%}   measured {seen_v:5.0%}"
          f"   -> damage x{1 + pf.VULN_MULT * guessed_v:.2f} assumed, x{1 + pf.VULN_MULT * seen_v:.2f} real")
    print(f"     Weak         formula assumes {guessed_w:5.0%}")

    # Cards played is the unit a deck is actually judged by: a card played for free
    # is energy the deck did not have to spend, so raw energy under-reads a deck
    # that cheats cards into play.
    thru = [r["thru"] for r in rows if r["thru"]]
    if thru:
        p_cards = statistics.mean(r["p"]["drawn"] for r in rows)
        print(f"\n   throughput per turn (what the deck actually put out)")
        print(f"     cards played   measured {statistics.mean(t['played'] for t in thru):5.2f}"
              f"   of which free {statistics.mean(t['free'] for t in thru):4.2f}")
        print(f"     energy spent   measured {statistics.mean(t['spent'] for t in thru):5.2f}")
        print(f"     their list price       {statistics.mean(t['equiv'] for t in thru):5.2f}"
              f"   (energy-equivalent, so free plays count)")
        print(f"     projected energy       {statistics.mean(r['p']['energy'] for r in rows):5.2f}"
              f"   against {statistics.mean(r['m']['energy'] for r in rows):5.2f} raw")
        print(f"     projected cards seen   {p_cards:5.2f}   against"
              f" {statistics.mean(t['played'] for t in thru):5.2f} played")

    # How much of the ceiling a player actually uses. A fight is not spent all-in on
    # one job, so these lines read high by design -- but by how much, and how steadily,
    # is the question anyone looking at the chart is really asking.
    for key, label in (("damage", "damage"), ("block", "block")):
        share = [r["m"][key] / r["p"][key] for r in rows if r["p"][key]]
        if not share:
            continue
        over = sum(1 for s in share if s > 1.0)
        print(f"\n   {label}: you used {statistics.median(share):.0%} of the ceiling a turn (median),"
              f" {statistics.mean(share):.0%} on average")
        print(f"     range {min(share):.0%} to {max(share):.0%}; over the ceiling in {over} of {len(share)} fights")

    # 3. The log against the run's own record.
    run_taken = sum(r["run_taken"] for r in rows)
    log_taken = sum(r["log_taken"] for r in rows)
    share = f" ({log_taken / run_taken:.0%} of it)" if run_taken else ""
    off = sum(1 for r in rows if r["run_turns"] and r["log_turns"] != r["run_turns"])
    print(f"\n3. The log against the run's own record, {len(rows)} fights")
    print(f"   damage taken   run says {run_taken:>5}   log says {log_taken:>5}{share}")
    print(f"   turn count     differs on {off} of {len(rows)} fights")
    problems = []
    for derived in logs.values():
        problems += dt.check(derived)
    print(f"   self-checks    {len(problems)} problem(s)" + (":" if problems else " -- none"))
    for p in problems[:20]:
        print(f"      {p}")
    if only:
        print("\n   floor  enc                                  dmg proj/meas   block proj/meas"
              "   turns  taken run/log")
        for r in rows:
            print(f"   {r['floor']:>5}  {r['enc'][:34]:<34} {r['p']['damage']:6.1f}/{r['m']['damage']:<6.1f}"
                  f" {r['p']['block']:6.1f}/{r['m']['block']:<6.1f} {r['log_turns']:>5}"
                  f" {r['run_taken']:>5}/{r['log_taken']:<5}")

    # 4. Per fight, from the enemies' HP and their own intent. This is the ground
    # truth the projection is only ever guessing at: what there was to kill, what
    # was killed, and what was aimed back at us while it happened.
    print("\n4. Per fight, from the enemies' HP")
    print("   damage is HP removed, not hit events -- poison and the killing blow both")
    print("   count, and overkill does not. intent is what the living enemies' moves")
    print("   would have dealt, with their Strength; killing one before it acts")
    print("   cancels its share. expected is the same enemies' average damage a turn")
    print("   across their whole move list, which is what they would have done given")
    print("   more turns, so a fight that ends early still reads against the encounter.")
    print("   self is damage a curse or status did to us, which is not the enemy's.")
    header = (f"   {'k':>3} {'encounter':<32} {'turns':>5} {'pool':>5} {'removed':>7} "
              f"{'a turn':>6} {'median':>6} {'peak':>5} {'idle':>4} {'aimed':>6} "
              f"{'faced':>6} {'could':>6} {'blocked':>7} {'taken':>5} {'self':>5} {'junk':>4}")
    for (steam, start), derived in sorted(logs.items(), key=lambda kv: kv[0][1]):
        if only and start != only:
            continue
        print(f"\n   run {start}" + (f"  ({steam})" if len(logs) > 1 else ""))
        print(header)
        for f in derived["fights"]:
            if not f["turns_n"]:
                continue
            faced = (f["blocked"] + f["taken"]) / f["turns_n"]
            selfhurt = (f["self_blocked"] + f["self_taken"]) / f["turns_n"]
            print(f"   {f['i']:>3} {f['enc'].replace('ENCOUNTER.', '')[:32]:<32} {f['turns_n']:>5} "
                  f"{f['pool'] or 0:>5} {f['enemy_net']:>7} {f['enemy_net'] / f['turns_n']:>6.1f} "
                  f"{f.get('lost_median', 0):>6} {f.get('lost_peak', 0):>5} {f.get('idle_turns', 0):>4} "
                  f"{f['intent_total'] / f['turns_n']:>6.1f} {faced:>6.1f} "
                  f"{f['expected_total'] / f['turns_n']:>6.1f} {f['blocked']:>7} {f['taken']:>5} "
                  f"{selfhurt:>5.1f} {f['junk']:>4}")
        spawned = [f for f in derived["fights"] if f.get("spawned")]
        if spawned:
            print("   enemies that appeared or healed mid-fight (more removed than stood there): "
                  + ", ".join(f"{f['enc'].replace('ENCOUNTER.', '')} +{f['spawned']}" for f in spawned))
        odd = [f for f in derived["fights"] if f.get("enemy_sentinel") or f.get("self_dmg")]
        if odd:
            print("   fights with a sentinel HP delta or HP the deck paid itself: "
                  + ", ".join(f"{f['enc'].replace('ENCOUNTER.', '')}"
                              f" ({f['enemy_sentinel']} sentinel, {f['self_dmg']} self)"
                              for f in odd))
        if any(f.get("dmg_other") for f in derived["fights"]):
            other = sum(f["dmg_other"] for f in derived["fights"])
            total = sum(f["enemy_net"] for f in derived["fights"]) or 1
            print(f"   damage with no attacker behind it (poison and friends): "
                  f"{other} of {total} removed, {other / total:.0%}")
        unattributed = sum(f.get("enemy_unexplained", 0) for f in derived["fights"])
        if unattributed:
            total = sum(f["enemy_net"] for f in derived["fights"]) or 1
            print(f"   HP taken off enemies with no hit behind it (Doom's countdown, HP-loss "
                  f"effects): {unattributed} of {total} removed, {unattributed / total:.0%}")

    # 5. Floor by floor, against your own history of that encounter. The run files
    # make this possible for every run, so the anchor is "how long this fight usually
    # takes me", not a number invented here.
    base = encounter_baseline(runs)
    if base:
        print("\n5. Each floor against your own record on that encounter")
        print("   turns and damage taken are this fight; the medians are every run in")
        print("   the data that fought the same encounter. a turn is HP removed a turn,")
        print("   the ground-truth supply side, so its trend down the floors is the deck.")
        for (sid, start), derived in sorted(logs.items(), key=lambda kv: kv[0][1]):
            if only and start != only:
                continue
            print(f"\n   run {start}")
            print(f"   {'floor':>5} {'encounter':<32} {'turns':>5} {'usual':>5} "
                  f"{'taken':>5} {'usual':>5} {'a turn':>6}")
            mine, usual = [], []
            pairs = align(derived["fights"], run.parse_run_data(
                runs[(sid, start)], steam_id=sid, fallback_ts=start).get("timeline") or []) \
                if runs.get((sid, start)) else []
            for fight, node in pairs:
                if not fight["turns_n"]:
                    continue
                stats = base.get(node.get("enc") or "")
                if not stats:
                    continue
                mine.append(fight["turns_n"])
                usual.append(stats[1])
                print(f"   {node['floor'] + 1:>5} {(node.get('enc') or '').replace('ENCOUNTER.', '')[:32]:<32} "
                      f"{fight['turns_n']:>5} {stats[1]:>5.0f} {fight['taken']:>5} {stats[2]:>5.0f} "
                      f"{fight['enemy_net'] / fight['turns_n']:>6.1f}")
            if mine:
                print(f"   {'':>5} {'all matched floors':<32} {sum(mine):>5} {sum(usual):>5.0f}")


if __name__ == "__main__":
    main()
