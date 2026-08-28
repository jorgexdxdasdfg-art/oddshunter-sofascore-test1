from __future__ import annotations

import dataclasses
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclasses.dataclass
class MatchRef:
    competition: str
    season: str
    kickoff: str
    home_team: str
    away_team: str
    sofascore_event_id: int | None = None
    match_id: int | None = None
    home_goals: int | None = None
    away_goals: int | None = None


class Registry:
    def futbol24_variants(self, value: Any) -> list[str]:
        return [str(value)]

    def get(self, _value: Any) -> dict[str, Any]:
        return {}


def load_module():
    match_stats = types.ModuleType("match_stats_pipeline")
    match_stats.MetricPair = type("MetricPair", (), {})
    sys.modules[match_stats.__name__] = match_stats

    registry = types.ModuleType("team_identity_registry")
    registry.get_default_team_identity_registry = lambda _root: Registry()
    sys.modules[registry.__name__] = registry

    estimator = types.ModuleType("xg_estimator")
    estimator.AggregateStats = type("AggregateStats", (), {})
    sys.modules[estimator.__name__] = estimator

    pipeline = types.ModuleType("xg_pipeline")
    pipeline.DirectXG = type("DirectXG", (), {})
    pipeline.MatchAggregateStats = type("MatchAggregateStats", (), {})
    pipeline.MatchRef = MatchRef
    sys.modules[pipeline.__name__] = pipeline

    path = Path(__file__).resolve().parents[1] / "futbol24_client.py"
    spec = importlib.util.spec_from_file_location("futbol24_client_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


class ResolverTests(unittest.TestCase):
    def client(self):
        client = object.__new__(MODULE.Futbol24Client)
        client.identity_registry = Registry()
        client.logger = lambda _message: None
        return client

    def test_reversed_neutral_venue_result_is_normalized(self):
        client = self.client()
        match = MatchRef(
            competition="leagues-cup",
            season="2026",
            kickoff="2026-08-27T02:55:00+00:00",
            home_team="Club America",
            away_team="Columbus Crew",
        )
        candidate = {
            "date": "2026-08-27T02:55:00+00:00",
            "league": {
                "name": "CNCF LC",
                "label": "CONCACAF Leagues Cup Quarterfinal",
                "slug": "international/CONCACAF/Leagues-Cup/2026/Quarterfinal",
            },
            "team1": {"name": "Columbus Crew"},
            "team2": {"name": "Club América"},
            "score1": "0-2",
        }

        validation = client._candidate_validation(match, candidate, require_score=False)

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["orientation"], "reversed")
        home, away = client._score_pair(candidate)
        if validation["orientation"] == "reversed":
            home, away = away, home
        self.assertEqual((home, away), (2.0, 0.0))

    def test_wrong_competition_is_rejected_even_with_same_date(self):
        client = self.client()
        match = MatchRef(
            competition="leagues-cup",
            season="2026",
            kickoff="2026-08-27T02:55:00+00:00",
            home_team="Club America",
            away_team="Columbus Crew",
        )
        candidate = {
            "date": "2026-08-27T02:55:00+00:00",
            "league": {"name": "Champions League", "slug": "UEFA/Champions-League"},
            "team1": {"name": "Club América"},
            "team2": {"name": "Columbus Crew"},
            "score1": "2-0",
        }

        validation = client._candidate_validation(match, candidate, require_score=False)

        self.assertFalse(validation["valid"])
        self.assertFalse(validation["competition_pass"])

    def test_signed_team_results_parameters_are_alphabetical(self):
        client = self.client()
        calls: list[tuple[str, Any]] = []

        def request(endpoint: str, params: Any = None):
            calls.append((endpoint, params))
            if endpoint == "/stats/team/meta":
                return {"id": 1387, "expire": 9999999999, "sign": "signed"}
            if endpoint == "/stats/team/results/latest":
                return [
                    {
                        "date": "2026-08-27T02:55:00+00:00",
                        "team1": {"name": "Columbus Crew"},
                        "team2": {"name": "Club América"},
                        "score1": "0-2",
                        "slug": "target",
                    }
                ]
            self.fail(endpoint)

        client._request = request
        rows = client._team_results({"slug": "Mexico/Club-America"})

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["status"]["is_ended"])
        signed_params = calls[-1][1]
        self.assertEqual(
            [key for key, _value in signed_params],
            ["expire", "hostGuest", "id", "lang", "limit", "sign"],
        )

    def test_result_sync_preserves_validated_database_identity(self):
        source = (ROOT / "cloud_incremental_result_sync.py").read_text(encoding="utf-8")
        self.assertIn(
            "row = _db_row(event_id) or _schedule_row(key, event_id)",
            source,
        )
        self.assertNotIn(
            "row = _schedule_row(key, event_id) or _db_row(event_id)",
            source,
        )
        for field in (
            "l.name AS competition_name",
            "l.country AS competition_country",
            "m.season AS season_name",
            "l.source_tournament_id AS competition_id",
            "l.source_season_id AS season_id",
        ):
            self.assertIn(field, source)


if __name__ == "__main__":
    unittest.main()
