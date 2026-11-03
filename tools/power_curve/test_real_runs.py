"""The logged runs against what the game itself wrote down.

Turns, final HP and enemy health are the guiding truth: the run file and the raw event
log state them independently of anything worked out here, so every number the Runs page
reports has to reconcile to them. These tests walk the raw log rather than our own
totals wherever they can, because a total can only agree with itself.

They read real runs at test time, from gamma_raw/ and telemetry_raw/. Both are gitignored
and hold player data, so nothing from them is written into this file, and the whole
module skips where they are absent. Every v3 log on disk is covered, so each new logged
run is checked by being synced. A failure on a new run is worth reading before it is
worth fixing: a monster that spawns differently, say, is news about the game.

    python -m unittest test_real_runs
"""
import statistics
import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import derive_telemetry as dt  # noqa: E402
import export_measured as em  # noqa: E402
import fight_demand as fd  # noqa: E402
import run as runmod  # noqa: E402
import telemetry_report as tr  # noqa: E402

PLAYER = dt.PLAYER

# What can change the enemies' total HP without an `hp` event between two snapshots: an
# arrival, or the sentinel. Anything else there is the log and the state disagreeing.
ARRIVALS = ("GREMLIN_MERC", "AXEBOTS", "OVICOPTER", "LIVING_FOG", "WATERFALL_GIANT")
# The only thing seen losing HP with no hit behind it: when the main enemy dies and only
# minions are left, the game kills them too, whatever HP they had.
DIES_WITH_OWNER = ("LIVING_FOG",)
# Heals when a boss fight opens: 25, up to max HP.
PANTOGRAPH = 25

LOADED = []
HISTORY = {}


class Run:
    def __init__(self, sid, ts, raw, derived):
        self.ts = ts
        self.key = (sid, ts)
        self.raw = raw
        self.derived = derived
        self.fights = derived["fights"]
        self.events = sorted(dt.load(tr.TELEMETRY / sid / f"{ts}.json.gz")["log"],
                             key=lambda e: e.get("q", 0))
        self.parsed = runmod.parse_run_data(raw, steam_id=sid, fallback_ts=ts)
        self.timeline = self.parsed["timeline"]
        self.pairs = tr.align(self.fights, self.timeline)
        self.relics = {r["id"] for r in self.fights[-1]["snaps"][-1]["you"][0].get("relics") or []}
        self.has_destinations = any(f.get("has_pile_to") for f in self.fights)

    def of(self, fight):
        """That fight's events. What follows its end keeps its number until the next one
        opens, and that is the map, not the fight: an event's damage, the next monster
        being set up."""
        events = [e for e in self.events if e.get("f") == fight["i"]]
        end = next((i for i, e in enumerate(events) if e["k"] == "fight1"), len(events))
        return events[:end + 1]


def setUpModule():
    runs = tr.load_runs()
    HISTORY.update(runs)
    logs, _ = tr.load_logs(runs)
    for (sid, ts), derived in logs.items():
        if (sid, ts) in runs:
            LOADED.append(Run(sid, ts, runs[(sid, ts)], derived))
    if not LOADED:
        raise unittest.SkipTest("no logged runs on this machine: sync telemetry_raw and gamma_raw")


def you(state):
    return next(c for c in state["creatures"] if c.get("you"))


def enemies(state):
    return [c for c in state["creatures"] if not c.get("you")]


def sentinel(delta):
    return abs(delta) >= dt.HP_SENTINEL


def fight_rooms(raw):
    """(act, room, your stats) for every fight, straight from the run file. An event's
    fight is a second room behind the event's own."""
    return [(act, room, (point.get("player_stats") or [{}])[0])
            for act, points in enumerate(raw["map_point_history"]) for point in points
            for room in point.get("rooms") or [] if room.get("monster_ids")]


class Shape(unittest.TestCase):
    def test_no_log_was_cut_short_and_each_agrees_with_itself(self):
        for r in LOADED:
            with self.subTest(run=r.ts):
                self.assertFalse(r.derived["truncated"])
                self.assertEqual(dt.check(r.derived), [])

    def test_every_fight_joins_a_floor(self):
        for r in LOADED:
            with self.subTest(run=r.ts):
                joined = {f["i"] for f, _ in r.pairs}
                self.assertEqual([f["enc"] for f in r.fights if f["i"] not in joined], [])

    def test_every_fight_on_the_map_has_a_log(self):
        for r in LOADED:
            with self.subTest(run=r.ts):
                joined = {id(n) for _, n in r.pairs}
                fought = [n for n in r.timeline if n.get("turns")]
                self.assertEqual([n["floor"] for n in fought if id(n) not in joined], [])

    def test_every_fight_in_the_run_file_is_on_a_floor(self):
        for r in LOADED:
            with self.subTest(run=r.ts):
                self.assertEqual([(room["model_id"], room["turns_taken"]) for _, room, _ in fight_rooms(r.raw)],
                                 [(n.get("fight") or n["enc"], n["turns"]) for n in r.timeline if n["turns"]])


class Turns(unittest.TestCase):
    def test_log_turns_are_the_run_files_turns(self):
        for r in LOADED:
            for f, n in r.pairs:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    self.assertEqual(f["turns_n"], n["turns"])

    def test_turns_are_the_rounds_the_game_counted(self):
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    self.assertEqual(f["turns_n"], f["rounds1"] + f["extra_turns"])

    def test_only_a_turn_the_enemies_acted_on_can_be_hit_by_them(self):
        for r in LOADED:
            for f in r.fights:
                for t in f["turns"]:
                    if t["blocked"] or t["taken"]:
                        self.assertTrue(t["enemy_side"], f"{f['enc']} turn {t['n']}")

    def test_the_enemies_act_on_every_turn_but_the_one_you_won_on(self):
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    self.assertTrue(all(t["enemy_side"] for t in f["turns"][:-1]))


class FinalHp(unittest.TestCase):
    def test_hp_lost_in_the_fight_is_the_run_files_damage(self):
        for r in LOADED:
            for f, n in r.pairs:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    self.assertEqual(f["hp_in"], n["dmg"])

    def test_damage_taken_and_self_damage_make_up_all_of_it(self):
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    self.assertEqual(f["taken"] + f["self_taken"], f["hp_in"])

    def test_the_fights_hp_walks_from_its_start_to_its_end(self):
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    self.assertEqual(f["hp0"] - f["hp_in"] + f["hp_out"], f["hp1"])

    def test_every_hp_the_run_file_healed_is_placed(self):
        # Before the fight (Pantograph), during it, or after it (Burning Blood).
        for r in LOADED:
            for f, n in r.pairs:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    self.assertEqual(n["healed"], (f["hp0"] - n["hpBefore"]) + f["hp_out"]
                                     + (n["hpAfter"] - f["hp1"]))

    def test_a_fight_only_opens_healed_by_pantograph(self):
        for r in LOADED:
            for f, n in r.pairs:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    if f["hp0"] == n["hpBefore"]:
                        continue
                    self.assertIn("RELIC.PANTOGRAPH", r.relics)
                    self.assertEqual(n["type"], "boss")
                    self.assertEqual(f["hp0"], min(n["hpBefore"] + PANTOGRAPH, n["maxHp"]))

    def test_each_floor_starts_on_the_hp_the_last_one_ended_on(self):
        for r in LOADED:
            with self.subTest(run=r.ts):
                for a, b in zip(r.timeline, r.timeline[1:]):
                    self.assertEqual(b["hpBefore"], a["hpAfter"], f"floor {b['floor'] + 1}")

    def test_your_hp_at_every_snapshot_is_the_hp_events_walked_forward(self):
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    hp = f["hp0"]
                    for e in r.of(f):
                        a = e.get("a") or {}
                        if e["k"] == "snap":
                            self.assertEqual(you(a)["hp"], hp, f"{a.get('why')} {a.get('round')}")
                        elif e["k"] == "hp" and a.get("c") == PLAYER:
                            # Pantograph is logged after the opening snapshot that
                            # already has it, and as 25 even when max HP capped it.
                            if hp + a["d"] != a["hp"]:
                                self.assertEqual(a["d"], PANTOGRAPH)
                            hp = a["hp"]


class EnemyHealth(unittest.TestCase):
    def test_a_hit_takes_exactly_the_hp_its_target_loses(self):
        for r in LOADED:
            pairs = 0
            for before, e in zip(r.events, r.events[1:]):
                a = e.get("a") or {}
                if e["k"] == "hit" and (a.get("t") or "") not in ("", PLAYER) and a.get("unb"):
                    self.assertEqual(before["k"], "hp", f"hit with no HP lost: {e}")
                    self.assertEqual(before["a"]["c"], a["t"])
                    self.assertEqual(-before["a"]["d"], a["unb"])
                    pairs += 1
            self.assertGreater(pairs, 0)

    def test_every_hp_an_enemy_lost_has_a_hit_behind_it(self):
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    if any(n in f["enc"] for n in DIES_WITH_OWNER):
                        continue
                    self.assertEqual(f["enemy_unexplained"], 0)
                    self.assertEqual(f["dealt_removed"], f["enemy_lost"])

    def test_enemy_lost_is_the_raw_hp_deltas(self):
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    deltas = [e["a"]["d"] for e in r.of(f) if e["k"] == "hp"
                              and e["a"].get("c") != PLAYER and not sentinel(e["a"]["d"])]
                    self.assertEqual(f["enemy_lost"], -sum(d for d in deltas if d < 0))
                    self.assertEqual(f["enemy_healed"], sum(d for d in deltas if d > 0))

    def test_enemy_hp_at_each_snapshot_is_the_hp_events_walked_forward(self):
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    total = None
                    for e in r.of(f):
                        a = e.get("a") or {}
                        if e["k"] == "snap":
                            state = sum(c["hp"] for c in enemies(a))
                            if total not in (None, state):
                                self.assertTrue(any(n in f["enc"] for n in ARRIVALS),
                                                f"tracked {total}, snapshot {state}")
                            total = state
                        elif e["k"] == "hp" and a.get("c") != PLAYER and total is not None:
                            total += 0 if sentinel(a["d"]) else a["d"]

    def test_a_won_fight_ends_with_no_enemy_hp_left(self):
        for r in LOADED:
            for f in r.fights:
                if not f["won"]:
                    continue
                with self.subTest(run=r.ts, enc=f["enc"]):
                    self.assertGreaterEqual(f["enemy_net"], f["pool"])
                    events = r.of(f)
                    last = max(i for i, e in enumerate(events) if e["k"] == "snap")
                    left = sum(c["hp"] for c in enemies(events[last]["a"]))
                    self.assertEqual(left + sum(e["a"]["d"] for e in events[last:] if e["k"] == "hp"
                                                and e["a"].get("c") != PLAYER), 0)


class Block(unittest.TestCase):
    def test_your_block_at_every_snapshot_is_the_block_events_walked_forward(self):
        # Blur is the one thing that keeps block over a turn; the log says it was
        # cleared either way, so the walk has to know.
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    block, blur = 0, False
                    for e in r.of(f):
                        a = e.get("a") or {}
                        if e["k"] == "blk" and a.get("c") == PLAYER:
                            block += a.get("n") or 0
                        elif e["k"] == "blkc" and a.get("c") == PLAYER and not blur:
                            block = 0
                        elif e["k"] == "recv" and a.get("t") == PLAYER:
                            block -= a.get("blk") or 0
                        elif e["k"] == "snap":
                            self.assertEqual(you(a).get("blk"), block, f"{a.get('why')} {a.get('round')}")
                            blur = any("BLUR" in p for p in you(a).get("pow") or {})

    def test_block_gained_covers_what_it_absorbed(self):
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    self.assertLessEqual(f["blocked"] + f["self_blocked"], f["bgn"])


class Energy(unittest.TestCase):
    def test_energy_at_each_boundary_is_the_games(self):
        for r in LOADED:
            for f in r.fights:
                for t in f["turns"]:
                    with self.subTest(run=r.ts, enc=f["enc"], turn=t["n"]):
                        self.assertEqual(t["e0"], (t["snap0"]["you"][0])["en"])
                        if t["snap1"]:
                            self.assertEqual(t["e1"], t["snap1"]["you"][0]["en"])

    def test_spent_is_the_raw_energy_events(self):
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    self.assertEqual(f["spent"], sum(e["a"].get("n") or 0 for e in r.of(f)
                                                     if e["k"] == "eps"))

    def test_no_turn_spent_more_than_it_had(self):
        for r in LOADED:
            for f in r.fights:
                for t in f["turns"]:
                    if t["gained"] is not None:
                        self.assertGreaterEqual(t["gained"], 0)


class Cards(unittest.TestCase):
    def test_cards_drawn_are_the_cards_that_went_from_draw_pile_to_hand(self):
        for r in LOADED:
            if not r.has_destinations:
                continue
            with self.subTest(run=r.ts):
                moved = sum(1 for e in r.events if e["k"] == "pile" and e["a"].get("from") == "Draw"
                            and e["a"].get("to") == "Hand")
                self.assertEqual(moved, sum(len(t["hand"]) + len(t["drawn"])
                                            for f in r.fights for t in f["turns"]))

    def test_cards_played_are_the_raw_play_events(self):
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    self.assertEqual(sum(len(t["played"]) for t in f["turns"]),
                                     sum(1 for e in r.of(f) if e["k"] == "play1"))

    def test_more_played_than_drawn_is_always_explained(self):
        # Every card played left the draw pile or joined the fight. `enter` rather than
        # `gen`: only the later log has a `gen` for every card that joins.
        for r in LOADED:
            for f in r.fights:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    joined = Counter(e["a"].get("card") for e in r.of(f) if e["k"] == "enter")
                    joined.update(c for t in f["turns"] for c in t["from_draw"] + t["hand"] + t["drawn"])
                    played = Counter(c for t in f["turns"] for c in t["played"])
                    self.assertEqual(played - joined, Counter())


def strength_cut(e):
    a = e.get("a") or {}
    return e["k"] == "pow" and a.get("p") == dt.STRENGTH and (a.get("d") or 0) < 0 and a.get("c") != PLAYER


def clean_turns(run, cuts=False, weak=False):
    """(turn, its events) for the turns where what was aimed is what should land, because
    the deck left it alone: no enemy dead before it swung or still on another move by the
    end of your side (a stun, or a phase that replaced it), no Weak on them, and none of
    their Strength taken off. `cuts` and `weak` keep the turns that did those."""
    for f in run.fights:
        events = run.of(f)
        for t in f["turns"]:
            if not (t["enemy_side"] and t["snap0"] and t["snap1"]):
                continue
            start = [c for c in enemies(t["snap0"]) if c.get("hp")]
            end = {c["c"]: c for c in enemies(t["snap1"]) if c.get("hp")}
            here = [e for e in events if e.get("t") == t["n"]]
            if (all(c["c"] in end and end[c["c"]].get("move") == c.get("move") for c in start)
                    and (weak or not any("WEAK" in p for c in start + list(end.values()) for p in c.get("pow") or {}))
                    and not any(e["k"] == "die" for e in here)
                    and (cuts or not any(strength_cut(e) for e in here))):
                yield t, here


def hits_by(events, creature):
    return [e["a"].get("total") for e in events
            if e["k"] == "hit" and e["a"].get("by") == creature and e["a"].get("t") == PLAYER]


def split_sides(events):
    """A turn's events, on your side and on theirs."""
    opened = next((i for i, e in enumerate(events) if e["k"] == "side0" and e["a"].get("side") == "Enemy"),
                  len(events))
    return events[:opened], events[opened:]


class Aimed(unittest.TestCase):
    def test_with_nothing_in_the_way_what_was_aimed_is_what_arrived(self):
        # To the point, every turn. This is what makes the gap on the chart mean what it
        # says: all of it is something the deck did, none of it is the sum being off.
        for r in LOADED:
            with self.subTest(run=r.ts):
                turns = [t for t, _ in clean_turns(r)]
                self.assertGreater(len(turns), 30)
                self.assertEqual([(t["n"], t["intent"], t["blocked"] + t["taken"]) for t in turns
                                  if t["intent"] != t["blocked"] + t["taken"]], [])

    def test_strength_you_took_off_comes_off_each_hit(self):
        # Aimed stays as it was shown: the cut is damage the deck stopped. So the turns
        # left out above have to come back to what landed, by exactly the cut.
        checked = 0
        for r in LOADED:
            for t, here in clean_turns(r, cuts=True):
                cut = [e["a"] for e in here if strength_cut(e)]
                if not cut or {a["c"] for a in cut} != {e["a"].get("by") for e in here if e["k"] == "hit"
                                                        and e["a"].get("t") == PLAYER}:
                    continue
                with self.subTest(run=r.ts, turn=t["n"]):
                    hits = hits_by(here, cut[0]["c"])
                    each, spare = divmod(t["intent"], len(hits))
                    self.assertEqual(spare, 0)
                    self.assertEqual(hits, [max(0, each + sum(a["d"] for a in cut))] * len(hits))
                    checked += 1
        self.assertGreater(checked, 5)

    def test_weak_takes_a_quarter_off_each_hit_rounding_down(self):
        # The same for Weak. One attacker, so aimed splits evenly across its hits, and not
        # while you're Vulnerable, because the two multiply before the rounding.
        checked = 0
        for r in LOADED:
            for t, here in clean_turns(r, weak=True):
                weak = {c["c"] for c in enemies(t["snap1"]) if c.get("hp") and "POWER.WEAK_POWER" in (c.get("pow") or {})}
                swings = split_sides(here)[1]
                attackers = {e["a"].get("by") for e in swings if e["k"] == "hit" and e["a"].get("t") == PLAYER}
                if len(attackers) != 1 or attackers != weak or "POWER.VULNERABLE_POWER" in (you(t["snap0"]).get("pow") or {}):
                    continue
                with self.subTest(run=r.ts, turn=t["n"]):
                    hits = hits_by(swings, weak.copy().pop())
                    each, spare = divmod(t["intent"], len(hits))
                    self.assertEqual(spare, 0)
                    self.assertEqual(hits, [int(each * 0.75)] * len(hits))
                    checked += 1
        self.assertGreater(checked, 10)

    def test_an_enemy_hit_on_your_side_is_thorns(self):
        # Attack something spiked and it hits you back. That counts as damage in, which
        # it is, but nothing aimed it, so it is the one thing arrived can have over aimed.
        checked = 0
        for r in LOADED:
            for f in r.fights:
                events = r.of(f)
                for t in f["turns"]:
                    if not t["snap0"]:
                        continue
                    mine = split_sides([e for e in events if e.get("t") == t["n"]])[0]
                    spikes = {(c["c"], (c.get("pow") or {}).get("POWER.THORNS_POWER"))
                              for c in enemies(t["snap0"]) if c.get("hp")}
                    for e in mine:
                        a = e["a"]
                        if e["k"] == "hit" and a.get("t") == PLAYER and a.get("by") not in (PLAYER, ""):
                            with self.subTest(run=r.ts, enc=f["enc"], turn=t["n"], by=a.get("by")):
                                self.assertIn((a["by"], a["total"]), spikes)
                                checked += 1
        self.assertGreater(checked, 0)

    def test_the_giants_explosion_is_exactly_what_it_built(self):
        # Not in the clean turns: the Giant is dead by then, which is the whole mechanic.
        turns = [t for r in LOADED for f in r.fights if "WATERFALL_GIANT" in f["enc"] for t in f["turns"]
                 if t["enemy_side"] and t["snap0"]
                 and any(c.get("move") == dt.EXPLODE for c in enemies(t["snap0"]))]
        self.assertTrue(turns, "no explosion to check")
        for t in turns:
            self.assertGreater(t["intent"], 0)
            self.assertEqual(t["intent"], t["blocked"] + t["taken"])

    def test_what_was_aimed_at_you_while_vulnerable_is_what_arrived(self):
        turns = [t for r in LOADED for t, _ in clean_turns(r)
                 if t["intent"] and any(p.endswith("VULNERABLE_POWER") for p in you(t["snap0"]).get("pow") or {})]
        self.assertTrue(turns, "no Vulnerable turn to check")
        self.assertEqual([t["n"] for t in turns if t["intent"] != t["blocked"] + t["taken"]], [])


class MonsterRules(unittest.TestCase):
    """What the monsters do that a move list can't say, each read off the log rather than
    off the rule it is supposed to prove."""

    def fights(self, name):
        return [(r, f) for r in LOADED for f in r.fights if name in f["enc"]]

    def test_two_monsters_sharing_a_move_each_hit_for_their_own(self):
        # Dark Strike is 9 on a Calcified Cultist and 1 on a Damp one.
        checked = 0
        for r, f in self.fights("CULTISTS_NORMAL"):
            events = r.of(f)
            for t in f["turns"]:
                if not (t["enemy_side"] and t["snap0"]):
                    continue
                here = [e for e in events if e.get("t") == t["n"]]
                for c in enemies(t["snap0"]):
                    hits = hits_by(here, c["c"])
                    if hits and c.get("move") == "DARK_STRIKE_MOVE":
                        priced = tr.move_table()[(f["enc"], "DARK_STRIKE_MOVE", c["max"])][0][0][0]
                        self.assertEqual(hits, [priced + (c.get("pow") or {}).get(dt.STRENGTH, 0)], c["c"])
                        checked += 1
        self.assertGreater(checked, 0)

    def test_every_skill_against_a_prism_adds_the_sparks_amount(self):
        fights = self.fights("INFESTED_PRISMS")
        self.assertTrue(fights, "no Prism fight to check")
        skills = 0
        for r, f in fights:
            with self.subTest(run=r.ts):
                events = r.of(f)
                played = [e for e in events if e["k"] == "play1"
                          and (tr.pc.CD.get(e["a"].get("card")) or {}).get("type") == "Skill"]
                rises = [e["a"] for e in events if e["k"] == "pow" and e["a"].get("p") == dt.TAINTED
                         and e["a"].get("c") == PLAYER and (e["a"].get("d") or 0) > 0]
                self.assertEqual(len(rises), len(played))
                sparks = {(c.get("pow") or {}).get("POWER.VITAL_SPARK_POWER") for t in f["turns"] if t["snap0"]
                          for c in enemies(t["snap0"]) if c.get("hp")}
                self.assertLessEqual({a["d"] for a in rises}, sparks)
                skills += len(played)
        self.assertGreater(skills, 0)

    def turn_of(self, move, r, f):
        """Hits each turn this move was showing and landed, in order."""
        events = r.of(f)
        for t in f["turns"]:
            if t["enemy_side"] and t["snap0"]:
                for c in enemies(t["snap0"]):
                    hits = hits_by([e for e in events if e.get("t") == t["n"]], c["c"])
                    if c.get("move") == move and hits:
                        yield hits

    def test_the_pressure_gun_hits_five_harder_each_time_it_fires(self):
        fights = self.fights("WATERFALL_GIANT")
        self.assertTrue(fights, "no Giant to check")
        base = tr.move_table()["PRESSURE_GUN_MOVE"][0][0][0]
        for r, f in fights:
            guns = [sum(hits) for hits in self.turn_of("PRESSURE_GUN_MOVE", r, f)]
            self.assertGreater(len(guns), 1)
            self.assertEqual(guns, [base + dt.GROWS["PRESSURE_GUN_MOVE"][0] * i for i in range(len(guns))])

    def test_a_multi_claw_starts_at_three_hits_and_adds_one_each_time(self):
        fights = self.fights("TEST_SUBJECT")
        self.assertTrue(fights, "no Test Subject to check")
        for r, f in fights:
            claws = [len(hits) for hits in self.turn_of("MULTI_CLAW_MOVE", r, f)]
            self.assertTrue(claws)
            self.assertEqual(claws, [3 + i for i in range(len(claws))])

    def test_strength_rising_from_nowhere_is_brimstone(self):
        # 2 for you and 1 for each enemy at the start of your turn. Nothing else gives an
        # enemy Strength with no creature behind it, so it should only be in a fight where
        # you held the relic, and it should be in every turn of those.
        held, without = 0, 0
        for r in LOADED:
            for f in r.fights:
                relics = {x["id"] for x in f["snaps"][-1]["you"][0].get("relics") or []}
                rises = [e["a"] for e in r.of(f) if e["k"] == "pow" and e["a"].get("p") == dt.STRENGTH
                         and e["a"].get("c") != PLAYER and (e["a"].get("d") or 0) > 0 and not e["a"].get("by")]
                with self.subTest(run=r.ts, enc=f["enc"]):
                    if "RELIC.BRIMSTONE" in relics:
                        self.assertTrue(rises)
                        self.assertEqual({a["d"] for a in rises}, {1})
                        held += 1
                    else:
                        self.assertEqual(rises, [])
                        without += 1
        self.assertGreater(held, 0)
        self.assertGreater(without, 0)

    def test_a_minion_loses_hp_unhit_only_once_its_owner_is_dead(self):
        unhit = 0
        for r, f in self.fights("LIVING_FOG"):
            events = r.of(f)
            for i, e in enumerate(events[:-1]):
                if e["k"] == "hp" and e["a"].get("c") != PLAYER and e["a"].get("d") < 0 and events[i + 1]["k"] != "hit":
                    with self.subTest(run=r.ts, event=e["q"]):
                        self.assertEqual(e["a"]["hp"], 0)
                        self.assertTrue(any(x["k"] == "die" and x["a"].get("c") == "livingFog" for x in events[:i]))
                    unhit -= e["a"]["d"]
            self.assertEqual(sum(1 for x in events if x["k"] == "potion-"), 0)
        self.assertEqual(unhit, sum(f["enemy_unexplained"] for _, f in self.fights("LIVING_FOG")))
        self.assertGreater(unhit, 0)


class FloorRows(unittest.TestCase):
    def test_the_export_says_what_the_log_says(self):
        costs = tr.card_costs()
        for r in LOADED:
            for f, n in r.pairs:
                with self.subTest(run=r.ts, enc=f["enc"]):
                    row = em.floor_numbers(f, costs)
                    raw = r.of(f)
                    hits = [e["a"] for e in raw if e["k"] == "recv" and e["a"].get("t") == PLAYER
                            and e["a"].get("by") != PLAYER]
                    self.assertEqual(row["taken"], sum(h.get("unb") or 0 for h in hits))
                    self.assertEqual(row["removed"], f["enemy_lost"])
                    self.assertAlmostEqual(row["arrived"] * row["enemyTurns"],
                                           sum((h.get("unb") or 0) + (h.get("blk") or 0) for h in hits))
                    self.assertEqual(row["enemyTurns"], sum(t["enemy_side"] for t in f["turns"]))
                    self.assertAlmostEqual(row["spent"], f["spent"] / f["turns_n"])
                    self.assertAlmostEqual(row["played"], sum(1 for e in raw if e["k"] == "play1") / f["turns_n"])
                    self.assertAlmostEqual(row["draw"], statistics.mean(
                        len(t["hand"]) + len(t["drawn"]) for t in f["turns"]))


class Death(unittest.TestCase):
    """Both logged runs won, so a death here is made from a real log: stopped at an enemy
    hit partway through its longest fight, as a log stops when that hit kills you."""

    def test_a_log_stopped_by_a_death_still_tallies_what_came_off(self):
        costs = tr.card_costs()
        for r in LOADED:
            f = max(r.fights, key=lambda x: x["turns_n"])
            raw = r.of(f)
            hits = [i for i, e in enumerate(raw) if e["k"] == "recv"
                    and e["a"].get("t") == PLAYER and e["a"].get("by") != PLAYER]
            stop = hits[len(hits) // 2]
            log = [e for e in r.events if e["q"] <= raw[stop]["q"]]
            with self.subTest(run=r.ts, enc=f["enc"]):
                died = dt.derive({"v": 3, "log": log})["fights"][-1]
                self.assertEqual(died["enc"], f["enc"])
                self.assertFalse(died["won"])
                came_off = sum(-e["a"]["d"] for e in raw[:stop + 1] if e["k"] == "hp"
                               and e["a"].get("c") != PLAYER and e["a"]["d"] < 0
                               and not sentinel(e["a"]["d"]))
                self.assertEqual(died["enemy_lost"], came_off)
                self.assertTrue(0 < came_off < f["enemy_lost"])
                # The turn it stopped on is counted, and the enemies were on theirs.
                self.assertEqual(died["turns_n"], raw[stop]["t"])
                row = em.floor_numbers(died, costs)
                self.assertEqual(row["removed"], came_off)
                self.assertEqual(row["enemyTurns"], died["turns_n"])


class Targets(unittest.TestCase):
    """Multi-enemy means more than one target alive at a time, whenever in the fight. What
    the mod saw alive is the truth; the run files' lists have to agree with it."""

    @classmethod
    def setUpClass(cls):
        cls.demand = fd.table(fd.run_fights(HISTORY))

    def test_a_fight_with_two_alive_at_once_reads_multi_enemy(self):
        for r in LOADED:
            for f in r.fights:
                alive = max(sum(1 for c in enemies(s) if c.get("hp")) for s in f["snaps"])
                with self.subTest(run=r.ts, fight=f["enc"]):
                    self.assertEqual(self.demand[f["enc"]]["many"] or alive == 1, True)

    def test_one_enemy_at_a_time_is_single_however_many_come(self):
        for enc in ("ENCOUNTER.AXEBOTS_NORMAL", "ENCOUNTER.TEST_SUBJECT_BOSS"):
            with self.subTest(enc=enc):
                self.assertFalse(self.demand[enc]["many"])

    def test_an_enemy_that_only_joins_mid_fight_is_multi_enemy(self):
        for enc in ("ENCOUNTER.FABRICATOR_NORMAL", "ENCOUNTER.OVICOPTER_NORMAL", "ENCOUNTER.GREMLIN_MERC_NORMAL",
                    "ENCOUNTER.PHROG_PARASITE_ELITE", "ENCOUNTER.LIVING_FOG_NORMAL"):
            with self.subTest(enc=enc):
                self.assertTrue(self.demand[enc]["many"])


class ActReading(unittest.TestCase):
    """The story in the middle. Ahead, meeting and behind are worked out, so they have to
    sum back to turns and damage the game wrote down, the line has to be what winners
    wrote down, and the verdict has to mean something."""

    @classmethod
    def setUpClass(cls):
        cls.runs = fd.run_fights(HISTORY)
        cls.demand = fd.table(cls.runs)
        cls.cuts = fd.cuts_of(cls.runs, cls.demand)

    def rows(self, r):
        return fd.act_readings(fd.run_fights({r.key: r.raw})[0], self.demand, self.cuts)

    def test_an_act_sums_to_the_run_file_and_to_the_log_apart(self):
        for r in LOADED:
            # The fight that ended a lost run is left out of the reading.
            lost = not r.raw.get("win")
            rooms = fight_rooms(r.raw)[:-1 if lost else None]
            pairs = r.pairs[:-1 if lost else None]
            for row in self.rows(r):
                with self.subTest(run=r.ts, act=row["act"]):
                    filed = [(room, stats) for act, room, stats in rooms if act == row["act"]]
                    logged = [f for f, n in pairs if n["act"] == row["act"] + 1]
                    self.assertEqual(row["fights"], len(filed))
                    self.assertEqual(row["fights"], len(logged))
                    self.assertEqual(row["turns"], sum(room["turns_taken"] for room, _ in filed))
                    self.assertEqual(row["turns"], sum(f["turns_n"] for f in logged))
                    self.assertEqual(row["taken"], sum(fd.net_taken(stats) for _, stats in filed))
                    # The run file's damage has your own in it, and so does winners' average.
                    self.assertEqual(sum(stats.get("damage_taken") or 0 for _, stats in filed),
                                     sum(f["taken"] + f["self_taken"] for f in logged))

    def test_every_act_of_a_logged_run_gets_a_reading(self):
        for r in LOADED:
            with self.subTest(run=r.ts):
                self.assertEqual([row["act"] for row in self.rows(r)],
                                 sorted({act for act, _, _ in fight_rooms(r.raw)}))

    def test_a_run_sums_to_the_run_file_and_to_the_log_apart(self):
        for r in LOADED:
            with self.subTest(run=r.ts):
                whole = fd.run_reading(self.rows(r), self.cuts)
                lost = not r.raw.get("win")
                pairs = r.pairs[:-1 if lost else None]
                rooms = fight_rooms(r.raw)[:-1 if lost else None]
                self.assertEqual(whole["turns"], sum(room["turns_taken"] for _, room, _ in rooms))
                self.assertEqual(whole["turns"], sum(f["turns_n"] for f, _ in pairs))
                self.assertEqual(whole["taken"], sum(fd.net_taken(stats) for *_, stats in rooms))

    def test_no_run_reads_against_every_one_of_its_acts(self):
        # A run is its acts added up, so it can't be behind on the header with every card
        # below it ahead, or the other way round.
        # Next door can happen: acts just under the speed edge can total just over it.
        opposite = {"ahead": "behind", "behind": "ahead"}
        read = 0
        for _, _, _, acts in fd.player_acts(self.runs, self.demand, self.cuts):
            marks = {a["verdict"] for a in acts}
            if len(marks) == 1 and marks & set(opposite):
                read += 1
                self.assertNotEqual(fd.run_reading(acts, self.cuts)["verdict"], opposite[marks.pop()])
        self.assertGreater(read, 0)

    def test_a_won_fight_gave_the_enemies_one_turn_less(self):
        # What winners' damage a turn is worked out over, since a run file can't count them.
        # A fight won on the enemies' own side is the exception: Waterfall Giant's explosion.
        fights = [f for r in LOADED for f, _ in r.pairs if f["won"]]
        off = [f["enc"] for f in fights
               if sum(t["enemy_side"] for t in f["turns"]) != fd.swung({"t": f["turns_n"], "died": False})]
        self.assertLess(len(off) / len(fights), 0.1, off)

    def test_the_line_is_what_won_runs_wrote_down_on_that_fight(self):
        # Worked out again from the run files alone, whoever played them, with only the wins
        # of the same tier. The table rounds, so a mean ending in 5 can sit half a cent off.
        won = defaultdict(list)
        for raw in HISTORY.values():
            if raw.get("win") and not raw.get("was_abandoned") and len(raw.get("players") or []) == 1:
                level = fd.tier(raw.get("ascension") or 0)
                for _, room, stats in fight_rooms(raw):
                    won[room["model_id"], level].append((room["turns_taken"], fd.net_taken(stats)))
        held = 0
        for enc, d in self.demand.items():
            for level, line in enumerate(d["tiers"]):
                if "turns" in line and won[enc, level]:
                    with self.subTest(enc=enc, tier=level):
                        turns, taken = zip(*won[enc, level])
                        self.assertEqual(line["n"], len(turns))
                        self.assertAlmostEqual(line["turns"], statistics.mean(turns), delta=0.0051)
                        self.assertAlmostEqual(line["taken"], statistics.mean(taken), delta=0.0051)
                        held += line["n"]
        # The tiers apart hold every winning fight once: none lost and none counted twice.
        self.assertEqual(held, sum(len(v) for v in won.values() if len(v) >= fd.WON_MIN))

    def test_what_a_floor_healed_is_hp_that_came_back(self):
        # Why healing can come off damage taken: HP walks floor to floor on these two numbers
        # alone, so hp_healed is HP the player got back, overhealing and all left out. A
        # floor the run ended on has no HP after it to walk to.
        walked = off = 0
        for raw in HISTORY.values():
            if len(raw.get("players") or []) != 1:
                continue
            hp = None
            for points in raw["map_point_history"]:
                for point in points:
                    stats = (point.get("player_stats") or [{}])[0]
                    now = stats.get("current_hp")
                    if hp and now:
                        walked += 1
                        off += hp - (stats.get("damage_taken") or 0) + (stats.get("hp_healed") or 0) != now
                    hp = now
        self.assertLess(off / walked, 0.001, (off, walked))

    def test_a_behind_act_names_the_worse_of_its_two_parts(self):
        rows = [row for *_, row in fd.act_rows(self.runs, self.demand, self.cuts)]
        for row in rows:
            self.assertAlmostEqual(row["pace"] * row["each"], row["guard"])
            self.assertEqual(row["lacking"] is not None, row["verdict"] == "behind")
            if row["lacking"]:
                self.assertEqual(min(row["pace"], row["each"]), row["pace" if row["lacking"] == "damage" else "each"])
        self.assertEqual({r["lacking"] for r in rows}, {None, "damage", "block"})

    def test_runs_that_read_ahead_win_more_than_runs_that_read_behind(self):
        # On runs that had no hand in the line: the verdict has to mean something beyond the
        # run it was read from. Each act of the one tier with the wins for it, which is why
        # the tiers stay apart: how often a run wins depends on the tier too.
        cells = fd.held_out(self.runs)
        rate = lambda *key: sum(won for won, *_ in cells[key]) / len(cells[key])
        for act in {k[2] for k in cells if k[:2] == ("solo", 0)}:
            with self.subTest(act=act):
                self.assertLess(rate("solo", 0, act, "behind"), rate("solo", 0, act, "meeting"))
                self.assertLess(rate("solo", 0, act, "meeting"), rate("solo", 0, act, "ahead"))

    def test_runs_that_read_ahead_as_a_whole_win_more_than_runs_that_read_behind(self):
        # The same held-out test for the reading on the run's header, in both tiers with
        # the runs for it: a run's acts add up to something that means what they do.
        cells = fd.held_out(self.runs)
        for level in (0, 1):
            rate = lambda place: statistics.mean(won for won, *_ in cells["solo", level, "run", place])
            with self.subTest(tier=level):
                self.assertLess(rate("behind"), rate("meeting"))
                self.assertLess(rate("meeting"), rate("ahead"))

    def test_op_runs_win_more_than_any_other_reading(self):
        # OP names the runs that got away from the fights. Under 8, where there are enough
        # of them to say so, they beat the reading they mostly are.
        cells = fd.held_out(self.runs)
        rate = lambda place: statistics.mean(won for won, *_ in cells["solo", 0, "run", place])
        self.assertGreater(rate("op"), rate("ahead"))
        self.assertLess(len(cells["solo", 0, "run", "op"]), len(cells["solo", 0, "run", "ahead"]))

    def test_the_verdict_holds_up_where_winning_is_rare(self):
        # 8 and up is a far harder game: fewer wins to draw a line from and fewer runs that
        # win. Reading behind there still has to cost something.
        cells = fd.held_out(self.runs)
        share = lambda place: [won for (mode, level, _, p), rows in cells.items() if (mode, level, p) == ("solo", 1, place)
                               for won, *_ in rows]
        self.assertLess(sum(share("behind")) / len(share("behind")),
                        sum(share("meeting")) / len(share("meeting")))

    def test_a_tier_with_the_wins_reads_its_winners_as_meeting(self):
        # The point of the tiers: a run that won at 8 and up reads about as a run that won
        # under 8 does, though it faced harder monsters.
        for level in (0, 1):
            with self.subTest(tier=level):
                guards = [row["guard"] for mode, t, won, row in fd.act_rows(self.runs, self.demand, self.cuts)
                          if mode == "solo" and t == level and won]
                self.assertAlmostEqual(statistics.median(guards), 1, delta=0.15)

    def test_a_fight_never_reads_against_a_line_from_another_tier(self):
        for fights in self.runs:
            for f in fights:
                d = self.demand[f["enc"]]
                how = fd.winners_of(f, d)
                if how:
                    line = d["tiers"][fd.tier(f["asc"])]
                    self.assertTrue(how is line or how is line.get("coop"))

    def test_killing_much_faster_is_worth_more_than_meeting(self):
        # The reason speed can lift an act: on runs that had no hand in the line, an act
        # lifted to ahead by its turns has to win more than the acts left at meeting.
        halves = self.runs[::2], self.runs[1::2]
        lifted, meeting = [], []
        for train, test in (halves, halves[::-1]):
            demand = fd.table(train)
            for mode, level, won, row in fd.act_rows(test, demand, fd.cuts_of(train, demand)):
                if (mode, level) == ("solo", 0):
                    if row["verdict"] == "meeting":
                        meeting.append(won)
                    elif row["verdict"] == "ahead" and row["held"] == "meeting":
                        lifted.append(won)
        self.assertGreater(sum(lifted) / len(lifted), sum(meeting) / len(meeting))

    def test_slow_is_safe_so_long_as_damage_taken_holds(self):
        # The reason being slow never sinks an act: an act well behind winners' turns that
        # held its damage taken has to beat an act that kept their pace and didn't.
        cells = fd.held_out(self.runs)
        slow, level = [], []
        for (mode, tier, _, place), rows in cells.items():
            if mode == "solo" and tier == 0:
                slow += [won for won, _, slower in rows if slower and place != "behind"]
                level += [won for won, pace, _ in rows if pace >= 1 and place == "behind"]
        self.assertGreater(sum(slow) / len(slow), 1.5 * sum(level) / len(level))


if __name__ == "__main__":
    unittest.main()
