import unittest
from sofascore_event_client import snapshot_from_document

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
