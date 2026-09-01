import unittest
from sofascore_event_client import (
    final_actuals_from_statistics_document,
    snapshot_from_document,
)

class SofaScoreEventClientTests(unittest.TestCase):
    def test_finished_event_by_exact_id(self):
        document = {"event": {"id": 16391180, "status": {"type": "finished", "description": "Ended"}, "homeTeam": {"id": 46}, "awayTeam": {"id": 1}, "homeScore": {"current": 1}, "awayScore": {"current": 2}, "startTimestamp": 1788012000}}
        snapshot = snapshot_from_document(16391180, document, {"home_team_id": 46, "away_team_id": 1})
        self.assertEqual(snapshot["state"], "finished")
        self.assertEqual((snapshot["home_goals"], snapshot["away_goals"]), (1, 2))

    def test_wrong_identity_rejected(self):
        document = {"event": {"id": 20, "status": {"type": "scheduled"}, "homeTeam": {"id": 10}, "awayTeam": {"id": 11}}}
        with self.assertRaises(ValueError):
            snapshot_from_document(21, document, {})

    def test_exact_event_statistics_are_normalized_for_expected_real(self):
        document = {
            "statistics": [
                {
                    "period": "ALL",
                    "groups": [
                        {
                            "statisticsItems": [
                                {"key": "expectedGoals", "homeValue": 0.83, "awayValue": 0.23},
                                {"key": "totalShotsOnGoal", "homeValue": 9, "awayValue": 8},
                                {"key": "shotsOnGoal", "homeValue": 4, "awayValue": 2},
                                {"key": "shotsOffGoal", "homeValue": 1, "awayValue": 5},
                                {"key": "blockedScoringAttempt", "homeValue": 4, "awayValue": 1},
                                {"key": "cornerKicks", "homeValue": 2, "awayValue": 2},
                                {"key": "yellowCards", "homeValue": 2, "awayValue": 3},
                            ]
                        }
                    ],
                }
            ]
        }
        payload = final_actuals_from_statistics_document(16450844, document)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["event_id"], 16450844)
        self.assertEqual(payload["real"]["home_xg"], 0.83)
        self.assertEqual(payload["real"]["away_shots"], 8.0)
        self.assertEqual(payload["real"]["home_corners"], 2.0)
        self.assertEqual(payload["real"]["away_yellow_cards"], 3.0)
