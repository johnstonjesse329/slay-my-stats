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
                self.assertEqual(got, expected)

    def test_an_upload_carries_them_on_the_run(self):
        sid, ts, log, raw = LOCAL[0]
        line = json.dumps({**raw, "telemetry": log}).encode()
        with handler.Spool() as spool:
            good, rejected, _ = handler.spool_upload(gzip.compress(line), sid, spool)
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
