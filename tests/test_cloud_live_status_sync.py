from __future__ import annotations

import sqlite3
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class StubMatchRef:
    match_id: int | None
    kickoff: str
    home_team: str
    away_team: str
    competition: str
    season: str
    sofascore_event_id: int | None = None
    competition_id: int | None = None
    season_id: int | None = None
    home_goals: int | None = None
    away_goals: int | None = None


class StubRegistry:
    def futbol24_variants(self, value: object) -> list[str]:
        return [str(value)]

    def get(self, _value: object) -> dict[str, object]:
        return {}


match_stats = types.ModuleType("match_stats_pipeline")
match_stats.MetricPair = type("MetricPair", (), {})
sys.modules.setdefault("match_stats_pipeline", match_stats)
registry = types.ModuleType("team_identity_registry")
registry.get_default_team_identity_registry = lambda _root: StubRegistry()
sys.modules.setdefault("team_identity_registry", registry)
estimator = types.ModuleType("xg_estimator")
estimator.AggregateStats = type("AggregateStats", (), {})
sys.modules.setdefault("xg_estimator", estimator)
pipeline = types.ModuleType("xg_pipeline")
pipeline.DirectXG = type("DirectXG", (), {})
pipeline.MatchAggregateStats = type("MatchAggregateStats", (), {})
pipeline.MatchRef = StubMatchRef
sys.modules.setdefault("xg_pipeline", pipeline)

import cloud_live_status_sync as live


def test_normalized_update_live_and_final() -> None:
    assert live.normalized_update(
        {
            "state": "live",
            "provider_status": "2nd Half",
            "home_goals": 2,
            "away_goals": 1,
        }
    ) == {
        "status": "LIVE",
        "status_description": "2nd Half",
        "home_score": 2,
        "away_score": 1,
        "state": "live",
    }
    assert live.normalized_update(
        {"state": "finished", "home_goals": 3, "away_goals": 0}
    ) == {
        "status": "FT",
        "status_description": "finished",
        "home_score": 3,
        "away_score": 0,
        "state": "finished",
    }
    assert live.normalized_update(
        {"state": "finished", "home_goals": None, "away_goals": None}
    ) is None


class FakeTurso:
    def __init__(self) -> None:
        self.rows: dict[int, dict[str, object]] = {
            77: {
                "competition_key": "test-league",
                "event_id": 77,
                "status": "NS",
                "status_description": "notstarted",
                "home_score": None,
                "away_score": None,
            }
        }

    def execute(self, sql: str, params: list[object]) -> None:
        if sql.startswith("UPDATE mobile_events"):
            event_id = int(params[-1])
            row = self.rows[event_id]
            row["status"] = params[0]
            row["status_description"] = params[1]
            if params[2] is not None:
                row["home_score"] = params[2]
            if params[3] is not None:
                row["away_score"] = params[3]

    def query(self, _sql: str, params: list[object]) -> list[dict[str, object]]:
        row = self.rows.get(int(params[0]))
        return [dict(row)] if row else []


def test_publish_remote_changes_mobile_live_state() -> None:
    client = FakeTurso()
    row = {
        "event_id": 77,
        "competition_name": "Test League",
        "season_name": "2026",
        "kickoff": "2026-08-28T18:00:00+00:00",
        "home_team_id": 1,
        "home_team": "Home",
        "away_team_id": 2,
        "away_team": "Away",
    }
    update = {
        "status": "LIVE",
        "status_description": "1st Half",
        "home_score": 1,
        "away_score": 0,
        "state": "live",
    }
    assert live.publish_remote(
        client,
        row,
        {"key": "test-league"},
        update,
        "2026-08-28T18:10:00+00:00",
    ) == 1
    assert client.rows[77]["status"] == "LIVE"
    assert client.rows[77]["home_score"] == 1
    assert client.rows[77]["away_score"] == 0


def test_select_candidates_prefers_due_and_keeps_overdue_fairness() -> None:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE leagues(league_id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE teams(team_id INTEGER PRIMARY KEY,sofascore_id INTEGER,name TEXT);
        CREATE TABLE matches(
          match_id INTEGER PRIMARY KEY,sofascore_id INTEGER,league_id INTEGER,
          kickoff TEXT,status TEXT,home_goals INTEGER,away_goals INTEGER,
          season TEXT,home_team_id INTEGER,away_team_id INTEGER
        );
        INSERT INTO leagues VALUES(1,'League');
        INSERT INTO teams VALUES(1,101,'Home');
        INSERT INTO teams VALUES(2,102,'Away');
        """
    )
    now = datetime(2026, 8, 28, 18, 0, tzinfo=timezone.utc)
    rows = [
        (1, 1001, now - timedelta(minutes=10), "NS"),
        (2, 1002, now - timedelta(hours=12), "NS"),
        (3, 1003, now - timedelta(hours=40), "NS"),
        (4, 1004, now - timedelta(minutes=20), "FT"),
    ]
    con.executemany(
        "INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?)",
        [
            (mid, eid, 1, kickoff.isoformat(), status, 1 if status == "FT" else None,
             0 if status == "FT" else None, "2026", 1, 2)
            for mid, eid, kickoff, status in rows
        ],
    )

    chosen = live.select_candidates(con, now, near_limit=1, overdue_limit=2)
    assert chosen[0]["event_id"] == 1001
    assert {row["event_id"] for row in chosen[1:]} == {1002, 1003}
    con.close()

def test_select_candidates_rotates_overdue_backlog_each_minute() -> None:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE leagues(league_id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE teams(team_id INTEGER PRIMARY KEY,sofascore_id INTEGER,name TEXT);
        CREATE TABLE matches(
          match_id INTEGER PRIMARY KEY,sofascore_id INTEGER,league_id INTEGER,
          kickoff TEXT,status TEXT,home_goals INTEGER,away_goals INTEGER,
          season TEXT,home_team_id INTEGER,away_team_id INTEGER
        );
        INSERT INTO leagues VALUES(1,'League');
        INSERT INTO teams VALUES(1,101,'Home');
        INSERT INTO teams VALUES(2,102,'Away');
        """
    )
    now = datetime(2026, 8, 28, 18, 0, tzinfo=timezone.utc)
    con.executemany(
        "INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?)",
        [
            (index, 2000 + index, 1, (now - timedelta(hours=10 + index)).isoformat(),
             "NS", None, None, "2026", 1, 2)
            for index in range(1, 7)
        ],
    )

    first = live.select_candidates(con, now, near_limit=1, overdue_limit=2)
    second = live.select_candidates(
        con, now + timedelta(minutes=1), near_limit=1, overdue_limit=2
    )

    assert {row["event_id"] for row in first} != {row["event_id"] for row in second}
    assert len({row["event_id"] for row in [*first, *second]}) >= 3
    con.close()
