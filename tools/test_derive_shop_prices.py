"""What a shop charged, from the visits that bought exactly one card.

Run with infra/.venv/Scripts/python tools/test_derive_shop_prices.py
Reads no profile: the runs are built here, since the point is which visits count
and what the median makes of them.
"""
import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "derive_shop_prices", Path(__file__).resolve().parent / "derive_shop_prices.py")
shop = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(shop)


def shop_node(floor, gold, bought=(), skipped=(), **extra):
    return {"type": "shop", "floor": floor, "gold": gold, "cardsBought": list(bought),
            "cardsSkipped": list(skipped), "goldGained": 0, **extra}


def room_node(floor, gold):
    return {"type": "monster", "floor": floor, "gold": gold}


def write_profile(root: Path, name: str, runs: list):
    month = root / name
    month.mkdir(parents=True, exist_ok=True)
    (month / "2026-11.json.gz").write_bytes(gzip.compress(json.dumps({"runs": runs}).encode()))


class SamplesByCard(unittest.TestCase):
    def collect(self, timeline):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_profile(root, "player", [{"ts": 1, "timeline": timeline}])
            return shop.samples_by_card(root)

    def test_a_lone_purchase_is_the_gold_the_visit_cost(self):
        got = self.collect([room_node(0, 200), shop_node(1, 113, bought=["CARD.A"])])
        self.assertEqual(got["CARD.A"], [87])

    def test_a_visit_that_also_removed_or_bought_elsewhere_is_not_a_price(self):
        for extra in ({"cardsRemoved": ["CARD.X"]}, {"relicsBought": ["RELIC.X"]},
                      {"potionsBought": ["POTION.X"]}, {"goldGained": 20}):
            with self.subTest(extra=extra):
                got = self.collect([room_node(0, 200), shop_node(1, 113, bought=["CARD.A"], **extra)])
                self.assertEqual(dict(got), {})

    def test_two_cards_in_one_visit_leave_the_split_unknown(self):
        got = self.collect([room_node(0, 200), shop_node(1, 113, bought=["CARD.A", "CARD.B"])])
        self.assertEqual(dict(got), {})

    def test_a_floor_whose_predecessor_is_missing_is_skipped(self):
        got = self.collect([room_node(0, 200), room_node(1, 180), shop_node(5, 100, bought=["CARD.A"])])
        self.assertEqual(dict(got), {})

    def test_underscore_files_are_not_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_profile(root, "player", [{"ts": 1, "timeline": [room_node(0, 200), shop_node(1, 113, bought=["CARD.A"])]}])
            (root / "_showcase.json.gz").write_bytes(gzip.compress(json.dumps({"runs": []}).encode()))
            self.assertEqual(shop.samples_by_card(root)["CARD.A"], [87])


class PriceTable(unittest.TestCase):
    rarities = {"CARD.COMMON": "Common", "CARD.RARE": "Rare", "CARD.SALE": "Uncommon",
                "CARD.OFFTEN": "Uncommon", "CARD.THIN": "Common"}
    discounts = {"RELIC.MEMBERSHIP_CARD": 50, "RELIC.THE_COURIER": 20}

    def test_the_median_of_the_clean_shelf_prices_is_the_price(self):
        table = shop.price_table({"CARD.COMMON": [48, 49, 51, 52]}, self.rarities, self.discounts)
        self.assertEqual(table["cards"]["CARD.COMMON"], {"price": 50, "n": 4})
        self.assertEqual(table["rarity"], {"Common": 50})

    def test_discount_visits_do_not_drag_the_price_down(self):
        # 43 is a Membership Card visit (50% off) on a card the shop asks 87 for,
        # and 70 is The Courier's 20% off on the same card.
        table = shop.price_table({"CARD.OFFTEN": [85, 87, 88, 43, 70]}, self.rarities, self.discounts)
        self.assertEqual(table["cards"]["CARD.OFFTEN"]["price"], 87)
        self.assertEqual(table["cards"]["CARD.OFFTEN"]["n"], 5)

    def test_a_card_only_ever_seen_discounted_takes_its_rarity(self):
        samples = {"CARD.COMMON": [48, 49, 51], "CARD.RARE": [150, 154, 158],
                   "CARD.SALE": [40, 41, 42], "CARD.OFFTEN": [75, 76, 77]}
        table = shop.price_table(samples, self.rarities, self.discounts)
        self.assertNotIn("CARD.SALE", table["cards"])
        self.assertEqual(table["rarity"]["Uncommon"], 76)

    def test_a_card_with_too_few_visits_is_left_to_its_rarity(self):
        table = shop.price_table({"CARD.THIN": [50, 51]}, self.rarities, self.discounts)
        self.assertNotIn("CARD.THIN", table["cards"])
        self.assertEqual(table["discountRelics"], self.discounts)


class DiscountRelics(unittest.TestCase):
    def test_the_percentages_come_from_the_relics_themselves(self):
        got = shop.discount_relics()
        self.assertEqual(got["RELIC.MEMBERSHIP_CARD"], 50)
        self.assertEqual(got["RELIC.THE_COURIER"], 20)


class ShippedTable(unittest.TestCase):
    def test_the_checked_in_table_keeps_its_shape(self):
        table = json.loads((Path(__file__).resolve().parents[1] / "shop_prices.json").read_text(encoding="utf-8"))
        self.assertTrue(table["cards"])
        for entry in table["cards"].values():
            self.assertGreater(entry["price"], 0)
        self.assertEqual(table["rarity"], dict(sorted(table["rarity"].items())))
        self.assertIn("Common", table["rarity"])
        self.assertEqual(table["discountRelics"], {"RELIC.MEMBERSHIP_CARD": 50, "RELIC.THE_COURIER": 20})


if __name__ == "__main__":
    unittest.main()
