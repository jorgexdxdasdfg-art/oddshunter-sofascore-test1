"""Tests locales: cuotas reales de los cuatro mercados o N/D, nunca inventar precios."""
from datetime import datetime, timezone
from unittest import TestCase

from audit_four_markets_readonly import MARKETS, candidate_days, valid_quote


class FourMarketsQuoteTests(TestCase):
    def test_all_four_real_market_shapes(self):
        samples = {
            "goals": {"closing": {"line": 2.5, "over": 1.85, "under": 1.93}},
            "corners": {"opening": {"line": 9.5, "over": 1.88, "under": 1.89}},
            "cards": {"closing": {"line": 4.5, "over": 1.95, "under": 1.80}},
            "btts": {"closing": {"yes": 1.77, "no": 2.10}},
        }
        for name, (source, selections) in MARKETS.items():
            with self.subTest(market=name):
                row = valid_quote(samples[name], selections)
                self.assertIsNotNone(row)
                self.assertGreater(row[selections[0]], 1)
                self.assertGreater(row[selections[1]], 1)

    def test_missing_market_side_rejected(self):
        self.assertIsNone(valid_quote({"closing": {"line": 3.5, "over": 1.80}}, ("over", "under")))

    def test_missing_total_line_rejected(self):
        self.assertIsNone(valid_quote({"closing": {"over": 1.85, "under": 1.95}}, ("over", "under")))

    def test_invalid_nonreal_price_rejected(self):
        self.assertIsNone(valid_quote({"closing": {"line": 9.5, "over": 1, "under": 1.80}}, ("over", "under")))

    def test_only_future_friday_saturday_sunday(self):
        now = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)
        days = candidate_days(now)
        self.assertTrue(days)
        self.assertTrue(all(day > now and day.weekday() in (4, 5, 6) for day in days))
