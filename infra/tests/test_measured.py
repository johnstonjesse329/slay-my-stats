"""The ingest Lambda's per-floor numbers against the ones the owner's local export makes.

    infra\\.venv\\Scripts\\python.exe -m unittest discover infra/tests

infra/lambda/ingest/measured.py is a second copy of what tools/power_curve/export_measured.py
does for logs on this machine, and these hold the two together on real logs: same floors,
same numbers, field by field. They need the logs and runs under tools/power_curve (kept out
of the repo) and the game's card data, and are skipped without them.
"""
import gzip
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "infra" / "lambda" / "ingest"), str(REPO / "tools"),
                str(REPO / "tools" / "power_curve")]

import handler  # noqa: E402
import measured  # noqa: E402
import run  # noqa: E402

LOGS = REPO / "tools" / "power_curve" / "telemetry_raw"
RAW = REPO / "tools" / "power_curve" / "gamma_raw"
CARDS = REPO / "card_data.json"


def _local():
    """[(steam id, ts, raw log, raw run)] for every v3 log that has its run file beside it."""
    if not (LOGS.exists() and RAW.exists() and CARDS.exists()):
        return []
    import telemetry_report as tr
    runs = tr.load_runs()
    out = []
    for f in sorted(LOGS.rglob("*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            log = json.load(fh)
        key = (f.parent.name, int(f.name.split(".")[0]))
        if isinstance(log, dict) and log.get("v") == 3 and key in runs:
            out.append((*key, log, runs[key]))
    return out


LOCAL = _local()


class PartyDamage(unittest.TestCase):
    def test_resume_uses_completed_retry_and_keeps_repeated_floors(self):
        enc = "ENCOUNTER.TEST_SUBJECT"
        events = []
        for attempt, (damage, closed) in enumerate(((141, False), (1560, True), (200, True), (30, False))):
            args = [
                ("fight0", {"enc": enc, "damageSlots": 2}),
                ("turn0", {}),
                ("hp", {"c": "enemy", "enemy": True, "d": -damage}),
                ("hit", {"by": "P", "t": "enemy", "sourceSlot": 0, "enemy": True, "unb": damage - 1}),
                ("hit", {"by": "P", "t": "enemy", "sourceSlot": 1, "enemy": True, "unb": 1}),
            ]
            if closed:
                args.append(("fight1", {}))
            events.extend({"k": kind, "a": data, "t": 1, "f": attempt} for kind, data in args)

        nodes = [{"floor": floor, "turns": 1, "fight": enc} for floor in (44, 47, 50)]
        log = handler.clean_event_log({"v": 3, "log": events})
        rows = measured.measured(log, nodes)
        self.assertEqual([(r["floor"], r["removed"], r.get("damageBySlot")) for r in rows], [
            (45, 1560, [1559, 1]), (48, 200, [199, 1]), (51, 30, None),
        ])

    def test_incoming_damage_requires_reconciled_player_slots(self):
        # Both players are named P, including when one player hits the other.
        # The lethal hit has no recv, while the blocked hit appears in both hooks.
        blocked = {"t": "P", "targetSlot": 0, "blk": 15, "unb": 0}
        lethal = {"by": "P", "sourceSlot": 0, "t": "P", "targetSlot": 1,
                  "blk": 3, "unb": 8, "ovk": 5}
        combat = [("hit", blocked), ("recv", blocked), ("hit", lethal),
                  ("hp", {"c": "P", "targetSlot": 1, "d": -8})]
        cases = [
            ("attributed", 2, combat, True, [{"blocked": 15, "taken": 0}, {"blocked": 3, "taken": 8}]),
            ("legacy", None, combat, True, None),
            ("unassigned", 2, combat + [("hit", {"t": "P", "blk": 1, "unb": 0})], True, None),
            ("missing_hit", 2, combat[1:], True, None),
            ("mismatched", 2, combat + [("hp", {"c": "P", "targetSlot": 0, "d": -2})], True, None),
            ("incomplete", 2, combat, False, None),
        ]
        for name, slots, events, closed, expected in cases:
            with self.subTest(name=name):
                events = [("fight0", {"enc": "ENCOUNTER.TOAD", "damageSlots": slots}),
                          ("turn0", {}), *events]
                if closed:
                    events.append(("fight1", {}))
                log = {"v": 3, "log": [{"k": kind, "a": args, "t": 1} for kind, args in events]}
                nodes = [{"floor": 25, "turns": 1, "enc": "ENCOUNTER.TOAD"}]
                rows = measured.measured(handler.clean_event_log(log), nodes)
                self.assertEqual(rows[0].get("incomingBySlot"), expected)

    def test_only_completed_fights_with_player_attribution_have_party_damage(self):
        def events(encounter, slots, closed=True):
            args = {"enc": encounter}
            if slots:
                args["damageSlots"] = slots
            events = [
                ("fight0", args),
                ("hit", {"by": "P", "t": "enemy", "sourceSlot": 0, "enemy": True, "unb": 11, "ovk": 50}),
                ("hit", {"by": "P", "t": "enemy", "sourceSlot": 1, "enemy": True, "unb": 7}),
                ("hit", {"t": "enemy", "enemy": True, "unb": 99}),
                ("hit", {"by": "P", "t": "pet", "sourceSlot": 0, "enemy": False, "unb": 99}),
            ]
            if closed:
                events.append(("fight1", {}))
            return events

        fights = [events("ENCOUNTER.NEW", 3), events("ENCOUNTER.OLD", None),
                  events("ENCOUNTER.PARTIAL", 3, closed=False)]
        log = {"v": 3, "log": [{"k": kind, "a": args, "t": 1}
                               for fight in fights for kind, args in fight]}
        nodes = [{"floor": i, "turns": 1, "enc": enc} for i, enc in enumerate(
            ("ENCOUNTER.NEW", "ENCOUNTER.OLD", "ENCOUNTER.PARTIAL"))]
        rows = measured.measured(log, nodes)
        self.assertEqual([r.get("damageBySlot") for r in rows], [[11, 7, 0], None, None])


class Overkill(unittest.TestCase):
    """Overkill is a fun number: carried on the floor row, never added to any damage figure."""

    def _rows(self, hits, closed=True):
        events = [("fight0", {"enc": "ENCOUNTER.TOAD"}), ("turn0", {}),
                  ("hp", {"c": "toad", "enemy": True, "d": -20}), *hits]
        if closed:
            events.append(("fight1", {}))
        log = {"v": 3, "log": [{"k": k, "a": a, "t": 1} for k, a in events]}
        nodes = [{"floor": 3, "turns": 1, "enc": "ENCOUNTER.TOAD"}]
        return measured.measured(handler.clean_event_log(log), nodes)

    def test_the_floor_carries_overkill_dealt_and_the_most_on_one_hit(self):
        rows = self._rows([
            ("hit", {"by": "P", "t": "toad", "enemy": True, "total": 12, "unb": 12, "ovk": 9}),
            ("hit", {"by": "P", "t": "toad", "enemy": True, "total": 3, "unb": 3, "ovk": 3}),
            ("hit", {"by": "P", "t": "toad", "enemy": True, "total": 5, "unb": 5, "ovk": 0}),
        ])
        self.assertEqual((rows[0]["overkillDealt"], rows[0]["overkillBest"]), (12, 9))

    def test_overkill_never_changes_a_damage_figure(self):
        hits = [("hit", {"by": "P", "t": "toad", "enemy": True, "total": 12, "unb": 12, "ovk": 9})]
        plain = [("hit", {"by": "P", "t": "toad", "enemy": True, "total": 12, "unb": 12})]
        with_ovk, without = self._rows(hits)[0], self._rows(plain)[0]
        self.assertNotIn("overkillDealt", without)
        self.assertEqual({k: v for k, v in with_ovk.items() if not k.startswith("overkill")}, without)

    def test_overkill_on_a_pet_or_on_the_player_is_not_ours(self):
        rows = self._rows([
            ("hit", {"by": "P", "t": "Osty", "enemy": False, "total": 3, "unb": 3, "ovk": 7}),
            ("hit", {"by": "toad", "t": "P", "total": 5, "unb": 5, "ovk": 6}),
        ])
        self.assertNotIn("overkillDealt", rows[0])


class PartySupport(unittest.TestCase):
    def _support(self, events):
        log = handler.clean_event_log({"v": 3, "log": [{"q": i, "k": kind, "a": args}
            for i, (kind, args) in enumerate([
                ("fight0", {"damageSlots": 3, "support": 1}), *events, ("fight1", {})
            ])]})
        return measured.party_numbers(log["log"], {})["supportBySlot"]

    def test_tag_team_credits_the_replay_only_when_it_resolves(self):
        attack = {"action": 1, "sourceSlot": 1, "card": "CARD.STRIKE_IRONCLAD"}
        replay = {"action": 1, "targetSlot": 1, "card": attack["card"], "before": 1, "after": 2,
                  "modifiers": [{"model": "POWER.TAG_TEAM_POWER", "sourceSlot": 0}]}
        events = [("playCount", replay), ("play1", {**attack, "playIndex": 0})]
        self.assertEqual(self._support(events), [])  # the first play ended the fight
        self.assertEqual(self._support(events + [("play1", {**attack, "playIndex": 1})]),
                         [{"from": 0, "to": 1, "extraPlays": 1}])

    def test_plot_credits_actual_extra_draws_in_an_unambiguous_later_hand(self):
        power = {"p": "POWER.DRAW_CARDS_NEXT_TURN_POWER", "card": "CARD.PLOT", "sourceSlot": 0, "d": 2, "n": 2}
        hand = {"before": 5, "after": 7, "nextTurnDraw": True, "nextTurnOnly": True}
        events = [
            ("pow", {**power, "targetSlot": 1}),
            ("pow", {**power, "targetSlot": 2}),
            ("pow", {**power, "targetSlot": 2, "sourceSlot": 1, "n": 4}),
            ("turn0", {"targetSlot": 1, "turn": 1}),
            ("handDraw", {**hand, "targetSlot": 1}),
            ("handDraw", {**hand, "targetSlot": 2, "after": 9}),
            *(("draw1", {"targetSlot": 1, "hand": True}),) * 6,
            *(("draw1", {"targetSlot": 2, "hand": True}),) * 9,
            ("turn0", {"targetSlot": 1, "turn": 2}),
            ("draw1", {"targetSlot": 1, "hand": True}),
        ]
        self.assertEqual(self._support(events), [{"from": 0, "to": 1, "draw": 1}])

    def test_only_cross_player_transfers_and_confirmed_enemy_redirects_are_credited(self):
        redirect = {"targetSlot": 0, "targetId": 10, "originalTargetSlot": 1, "originalTargetId": 11,
                    "blocked": 3, "intendedHpLoss": 9}
        self.assertEqual(self._support([
            ("cardTransfer", {"sourceSlot": 0, "targetSlot": 1, "card": "CARD.THE_BALL"}),
            ("cardTransfer", {"sourceSlot": 0, "targetSlot": 0, "card": "CARD.THE_BALL"}),
            ("damageResolved", {**redirect, "damageId": 1}),  # outside an enemy attack
            ("atk", {"side": "Player", "by": "E0", "done": False}),
            ("damageResolved", {**redirect, "damageId": 2}),
            ("damageResolved", {**redirect, "damageId": 2}),
            ("damageResolved", {**redirect, "damageId": 3, "sourceSlot": 2}),
            ("damageResolved", {**redirect, "damageId": 4, "targetSlot": None}),  # a pet took the hit
            ("damageCalc", {"targetSlot": 1, "targetId": 11, "before": 10, "after": 0,
                            "modifiers": [{"model": "POWER.COVERED_POWER", "sourceSlot": 0}]}),
            ("damageResolved", {"targetSlot": 1, "targetId": 11, "originalTargetId": 11,
                                "damageId": 5, "intendedHpLoss": 0, "blocked": 0}),
            ("atk", {"side": "Player", "by": "E0", "done": True}),
        ]), [{"from": 0, "to": 1, "transferred": 1, "damageRedirected": 12, "damageReduced": 10}])

    def test_damage_reduction_and_debuffs_from_confirmed_enemy_hits(self):
        target = {"targetSlot": 2, "targetId": 2}
        hit = {**target, "originalTargetId": 2, "blocked": 2, "intendedHpLoss": 3}
        weak = {"model": "POWER.WEAK_POWER", "sourceSlot": 0}
        enemy = {"c": "E0", "targetId": 3}
        events = [
            ("fight0", {"damageSlots": 3, "support": 1}),
            ("snap", {"creatures": [{"combatId": 3, "move": "ATTACK"}]}),
            ("pow", {**enemy, "p": "POWER.WEAK_POWER", "sourceSlot": 0, "d": 3, "n": 3}),
            ("pow", {**enemy, "p": "POWER.DEBILITATE_POWER", "sourceSlot": 1, "d": 2, "n": 2}),
            ("pow", {**enemy, "p": "POWER.VULNERABLE_POWER", "sourceSlot": 1, "d": 2, "n": 2}),
            ("pow", {**enemy, "p": "POWER.STRENGTH_POWER", "sourceSlot": 1, "d": -2, "n": -2}),
            ("pow", {**enemy, "p": "POWER.WEAK_POWER", "sourceSlot": 0, "d": -1, "n": 2}),
            ("pow", {**enemy, "p": "POWER.STRENGTH_POWER", "sourceSlot": 0, "d": 1, "n": -1}),
            ("pow", {"targetSlot": 2, "targetId": 2, "p": "POWER.WEAK_POWER", "sourceSlot": 0, "d": 2}),
            ("atk", {"side": "Player", "by": "E0", "done": False}),
            ("damageCalc", {**target, "before": 10, "after": 5, "modifiers": [weak]}),
            ("damageResolved", {**hit, "damageId": 1}),
            ("damageCalc", {**target, "before": 10, "after": 5, "modifiers": [weak]}),
            ("damageResolved", {**hit, "damageId": 1}),  # same result reported again
            ("damageCalc", {**target, "before": 10, "after": 5,
                            "modifiers": [weak, {"model": "POWER.STRENGTH_POWER"}]}),
            ("damageResolved", {**hit, "damageId": 2}),  # mixed calculation
            ("damageCalc", {**target, "before": 10, "after": 5, "modifiers": [weak]}),
            ("damageResolved", {**hit, "damageId": 3, "originalTargetId": 0}),
            ("damageCalc", {**target, "before": 10, "after": 5, "modifiers": [weak]}),
            ("atk", {"side": "Player", "by": "E0", "done": True}),  # unresolved preview
            ("pow", {**enemy, "p": "POWER.DEBILITATE_POWER", "d": -2, "n": 0}),
            ("damageCalc", {**target, "before": 10, "after": 7.5, "modifiers": [weak]}),
            ("damageResolved", {**hit, "damageId": 4, "intendedHpLoss": 5}),
            ("fight1", {}),
        ]
        rows = measured.party_numbers([{"k": kind, "a": args} for kind, args in events], {})
        self.assertEqual(rows["debuffsBySlot"], [1, 3, 0])
        self.assertEqual(rows["supportBySlot"], [
            {"from": 0, "to": 2, "damageReduced": 6},
            {"from": 1, "to": 2, "damageReduced": 2},
        ])

    def test_one_observer_measures_both_seats_and_credits_only_attributable_effects(self):
        card = "CARD.STRIKE_IRONCLAD"
        hit = {"action": 2, "sourceSlot": 1, "targetId": 4, "card": card}
        calculation = {**hit, "before": 8, "after": 12, "modifiers": [{"sourceSlot": 0}]}
        resolution = {**hit, "originalTargetId": 4, "blocked": 3, "intendedHpLoss": 9, "hpLost": 7}
        events = [
            ("fight0", {"enc": "ENCOUNTER.TOAD", "damageSlots": 2, "support": 1}),
            ("turn0", {"turn": 1, "targetSlot": 0}),
            ("turn0", {"turn": 1, "targetSlot": 1}),
            ("action0", {"id": 1, "sourceSlot": 0}),
            ("blk", {"action": 1, "sourceSlot": 0, "targetSlot": 1, "n": 5}),
            ("blk", {"action": 1, "sourceSlot": 1, "targetSlot": 1, "n": 99}),
            ("draw1", {"action": 1, "targetSlot": 1, "hand": True, "card": card}),
            ("draw1", {"action": 1, "targetSlot": 1, "hand": False, "card": card}),
            ("energy+", {"action": 1, "targetSlot": 1, "n": 2}),
            ("energy+", {"targetSlot": 1, "n": 99}),
            ("gen", {"sourceSlot": 0, "targetSlot": 1, "card": card}),
            ("costReduction", {"sourceSlot": 0, "targetSlot": 1, "instance": 1, "before": 1, "after": 0}),
            ("action0", {"id": 2, "sourceSlot": 1}),
            ("play1", {**hit, "instance": 1, "energySpent": 0, "playIndex": 0, "auto": False}),
            ("damageCalc", calculation),
            ("damageResolved", {**resolution, "damageId": 1}),
            ("hit", {**hit, "damageId": 1, "enemy": True, "unb": 7}),
            ("hit", {**hit, "damageId": 1, "enemy": True, "unb": 7}),
            ("damageCalc", {**calculation, "modifiers": [{"sourceSlot": 0}, {"sourceSlot": 1}]}),
            ("damageResolved", {**resolution, "damageId": 2}),
            ("hit", {**hit, "damageId": 2, "enemy": True, "unb": 7}),
            ("fight1", {}),
        ]
        log = {"v": 3, "log": [{"q": i, "k": k, "a": a} for i, (k, a) in enumerate(events)]}
        timeline = [{"floor": 4, "turns": 1, "enc": "ENCOUNTER.TOAD"}]
        rows = measured.measured(handler.clean_event_log(log), timeline)
        self.assertEqual(rows[0]["supportBySlot"], [
            {"from": 0, "to": 1, "block": 5, "draw": 1, "energy": 2, "generated": 1,
             "energySaved": 1, "freePlays": 1, "damage": 2},
        ])
        self.assertEqual([(p["draw"], p["played"], p["spent"]) for p in rows[0]["playBySlot"]],
                         [(0, 0, 0), (2, 1, 0)])
        self.assertEqual(measured.party_numbers(log["log"][:-1], {}), {})

    def test_anonymous_seats_do_not_copy_missing_stats_or_account_ids(self):
        data = {"map_point_history": [[
            {"player_stats": [{"current_hp": 70}, {"current_hp": 12, "player_id": "private"}]},
            {"player_stats": [{"current_hp": 60}]},
        ]]}
        players = [{"character": "CHARACTER.IRONCLAD"}, {"id": "private"}]
        seats = run.party_seats(data, players, 0)
        self.assertIsNone(seats[0])
        self.assertEqual(seats[1]["timeline"][0]["hpAfter"], 12)
        self.assertNotIn("hpAfter", seats[1]["timeline"][1])
        self.assertNotIn("private", json.dumps(seats))


@unittest.skipUnless(LOCAL, "no local event logs with their runs")
class ParityWithTheLocalExport(unittest.TestCase):
    def test_card_table_matches_the_report(self):
        import build_measured_cards
        import telemetry_report as tr
        table = build_measured_cards.build(json.loads(CARDS.read_text(encoding="utf-8")))
        self.assertEqual(table["costs"], tr.card_costs())
        self.assertEqual(set(table["junk"]), set(tr.dt.JUNK))

    def test_floors_match_export_measured(self):
        import export_measured as em
        import telemetry_report as tr
        costs = tr.card_costs()
        for sid, ts, log, raw in LOCAL:
            with self.subTest(ts=ts):
                parsed = run.parse_run_data(raw, steam_id=sid, fallback_ts=ts)
                expected = []
                for fight, node in tr.align(tr.dt.derive(log, {})["fights"], parsed.get("timeline") or []):
                    if fight["turns"]:
                        row = {"floor": node["floor"] + 1}
                        row.update({k: round(v, 2) if isinstance(v, float) else v
                                    for k, v in em.floor_numbers(fight, costs).items()})
                        expected.append(row)
                got = measured.measured(handler.clean_event_log(log), parsed["timeline"])
                self.assertTrue(got)
                self.assertEqual([{k: v for k, v in row.items()
                                   if k not in ("playBySlot", "supportBySlot", "debuffsBySlot")}
                                  for row in got], expected)

    def test_an_upload_carries_them_on_the_run(self):
        sid, ts, log, raw = LOCAL[0]
        line = json.dumps({**raw, "telemetry": log}).encode()
        with handler.Spool() as spool:
            good, rejected, _, _ = handler.spool_upload(gzip.compress(line), sid, spool)
            (month,) = spool.months()
            (parsed,) = spool.runs(month)
        self.assertEqual((good, rejected), (1, 0))
        self.assertEqual(parsed["measured"], measured.measured(handler.clean_event_log(log), parsed["timeline"]))


@unittest.skipUnless(LOCAL, "no local event logs with their runs")
class Backfill(unittest.TestCase):
    def test_a_stored_run_gets_numbers_from_its_stored_log(self):
        import tempfile
        import backfill_measured
        sid, ts, log, raw = LOCAL[0]
        parsed = run.parse_run_data(raw, steam_id=sid, fallback_ts=ts)
        with tempfile.TemporaryDirectory() as tmp:
            store = handler.DirStore(tmp)
            handler.save_profile(store, sid, None, None, "Tester", [parsed], {}, 1_800_000_000.0)
            store.put(handler.telemetry_key(sid, ts), handler._pack(handler.clean_event_log(log)), {}, None)
            slug = handler._unpack(store.get(handler.id_key(sid))[0])["slug"]

            dry = backfill_measured.backfill_profile(store, sid, slug, dry_run=True)
            self.assertEqual((dry["runs"], dry["added"]), (1, 1))
            month = handler.month_key(slug, handler.month_of(ts))
            self.assertNotIn("measured", handler._unpack(store.get(month)[0])["runs"][0])

            done = backfill_measured.backfill_profile(store, sid, slug)
            self.assertEqual(done["added"], 1)
            (stored,) = handler._unpack(store.get(month)[0])["runs"]
            self.assertEqual(stored["measured"], measured.measured(handler.clean_event_log(log), parsed["timeline"]))
            self.assertEqual({k: v for k, v in stored.items() if k != "measured"}, json.loads(json.dumps(parsed)))

            again = backfill_measured.backfill_profile(store, sid, slug)
            self.assertEqual((again["runs"], again["added"]), (0, 0))


class WithoutALog(unittest.TestCase):
    def test_nothing_to_read_is_no_rows(self):
        self.assertEqual(measured.measured(None, []), [])
        self.assertEqual(measured.measured({"v": 2, "fights": []}, []), [])
        self.assertEqual(measured.measured({"v": 3, "log": []}, []), [])


if __name__ == "__main__":
    unittest.main()
