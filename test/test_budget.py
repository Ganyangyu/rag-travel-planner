"""Verify one arithmetic ledger for group and per-person cost bases."""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.budget import calculate_budget, render_budget, summary_budget


class BudgetTests(unittest.TestCase):
    def profile(self, days=5):
        return {"days": days, "budget": 1000, "audience": "老年人"}

    def costs(self, **changes):
        costs = {"people": None, "rooms": None, "room_rate": 150,
                 "meals_per_person_day": 50, "tickets_per_person": 60,
                 "transport": {"basis": "person", "unit_price": 10, "quantity": 4},
                 "reserve_per_person": 50}
        costs.update(changes)
        return costs

    def test_full_trip_budget_not_daily_cap(self):
        ledger = calculate_budget(self.profile(), self.costs())
        self.assertEqual(ledger["team_spend"], Decimal(950))
        self.assertEqual(ledger["plan_total"], Decimal(1000))
        self.assertEqual(ledger["limit"], Decimal(1000))
        self.assertEqual(ledger["difference"], Decimal(0))

    def test_shared_rooms_and_vehicle_before_per_person(self):
        costs = self.costs(people=3, rooms=2,
                           transport={"basis": "vehicle", "unit_price": 60, "quantity": 2, "vehicles": 1})
        ledger = calculate_budget(self.profile(), costs)
        self.assertEqual(ledger["rows"][0]["team"], Decimal(1200))
        self.assertEqual(ledger["rows"][3]["person"], Decimal(40))
        self.assertEqual(ledger["team_spend"], Decimal(2250))
        self.assertEqual(ledger["plan_total"], Decimal(2400))
        self.assertEqual(ledger["limit"], Decimal(3000))
        self.assertEqual(ledger["plan_per_person"], Decimal(800))

    def test_senior_label_does_not_imply_two_people(self):
        ledger = calculate_budget(self.profile(), self.costs())
        self.assertEqual(ledger["people"], 1)
        self.assertFalse(ledger["people_known"])
        self.assertIn("条件情景", summary_budget(ledger))
        self.assertIn("人数尚未提供", render_budget(ledger))

    def test_day_trip_has_no_lodging_night(self):
        ledger = calculate_budget(self.profile(days=1), self.costs())
        self.assertEqual(ledger["nights"], 0)
        self.assertEqual(ledger["rows"][0]["team"], 0)

    def test_overspend_targets_largest_expense(self):
        ledger = calculate_budget(self.profile(), self.costs(room_rate=250))
        self.assertEqual(ledger["difference"], Decimal(-400))
        self.assertIn("超预算 400.00 元/人", summary_budget(ledger))
        self.assertIn("优先调整占比最大的住宿", render_budget(ledger))

    def test_invalid_or_nonfinite_prices_are_rejected(self):
        for invalid in [-1, float("nan"), float("inf"), True, None]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                calculate_budget(self.profile(), self.costs(room_rate=invalid))


if __name__ == "__main__":
    unittest.main()
