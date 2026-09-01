from __future__ import annotations

import json
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
        "kickoff": None,
    }
    assert live.normalized_update(
        {"state": "finished", "home_goals": 3, "away_goals": 0}
    ) == {
        "status": "FT",
        "status_description": "finished",
        "home_score": 3,
        "away_score": 0,
        "state": "finished",
        "kickoff": None,
    }
    assert live.normalized_update(
        {"state": "finished", "home_goals": None, "away_goals": None}
    ) is None


def test_verified_schedule_correction_requires_exact_event_and_teams() -> None:
    row = {
        "event_id": 16690997,
        "home_team": "Barranquilla FC",
        "away_team": "Millonarios",
    }
    snapshot = live.verified_schedule_snapshot(row)
    assert snapshot == {
        "state": "scheduled",
        "provider_status": "rescheduled",
        "home_goals": None,
        "away_goals": None,
        "kickoff": "2026-09-17T01:30:00+00:00",
    }
    assert live.verified_schedule_snapshot({**row, "away_team": "Otro"}) is None


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
        "kickoff": None,
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


def test_normalized_lineup_payload_keeps_real_starters_and_bench() -> None:
    payload = live.normalized_lineup_payload(
        {
            "event_id": 77,
            "match_id": 700,
            "home_team_id": 101,
            "away_team_id": 202,
        },
        {
            "lineups": {
                "home": {
                    "formation": "4-3-3",
                    "lineups": [
                        {"name": "Local Uno", "jersey": 9, "position": 11,
                         "position_name": "Attacker"}
                    ],
                    "bench": [{"name": "Local Dos", "jersey": 18}],
                },
                "away": {
                    "formation": "4-4-2",
                    "lineups": [
                        {"name": "Visita Uno", "jersey": 1, "position": 1,
                         "position_name": "Goalkeeper"}
                    ],
                    "bench": [],
                },
            }
        },
    )

    assert payload is not None
    assert payload["home"]["formation"] == "4-3-3"
    assert payload["home"]["starters"][0]["name"] == "Local Uno"
    assert payload["home"]["substitutes"][0]["name"] == "Local Dos"
    assert payload["away"]["team_id"] == 202
    assert payload["away"]["starters"][0]["shirt_number"] == 1


def test_normalized_final_actuals_payload_keeps_only_provider_actuals() -> None:
    payload = live.normalized_final_actuals_payload(
        {"event_id": 77, "match_id": 700},
        {
            "state": "finished",
            "final_actuals": {
                "real": {
                    "home_goals_1h": 1,
                    "away_goals_1h": 2,
                    "home_shots": 1,
                    "away_shots": 30,
                },
                "temporal_xg": {"expected": [], "goals": []},
                "source": "futbol24",
            }
        },
        "2026-08-30T15:00:00+00:00",
    )

    assert payload is not None
    assert payload["event_id"] == 77
    assert payload["real"]["away_shots"] == 30
    assert payload["source"] == "futbol24"


def _complete_final_actuals() -> dict[str, object]:
    return {
        "real": {
            "home_corners": 5,
            "away_corners": 4,
            "home_yellow_cards": 2,
            "away_yellow_cards": 3,
            "home_shots": 11,
            "away_shots": 9,
            "home_xg": None,
            "away_xg": None,
        }
    }


def test_final_actuals_core_complete_does_not_require_xg() -> None:
    payload = _complete_final_actuals()
    assert live.final_actuals_core_complete(payload)
    assert live.final_actuals_core_complete(json.dumps(payload))
    payload["real"]["away_shots"] = None
    assert not live.final_actuals_core_complete(payload)


def test_merge_final_actuals_updates_counts_but_preserves_valid_xg() -> None:
    existing = {
        "real": {
            "home_xg": 1.67,
            "away_xg": 2.38,
            "home_shots": 15,
            "away_shots": 15,
        },
        "source": "earlier-provider-snapshot",
    }
    incoming = {
        "real": {
            "home_xg": 0,
            "away_xg": 0,
            "home_shots": 15,
            "away_shots": 16,
        },
        "source": "sofascore-event-id",
    }
    merged = live.merge_final_actuals_payload(existing, incoming)
    assert merged["real"]["home_xg"] == 1.67
    assert merged["real"]["away_xg"] == 2.38
    assert merged["real"]["away_shots"] == 16
    assert merged["source"] == "sofascore-event-id"


class RemoteCandidateTurso:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def query(self, sql: str, _params: list[object]) -> list[dict[str, object]]:
        assert "expected_real_actuals" in sql
        return [dict(row) for row in self.rows]


def _remote_row(
    event_id: int,
    now: datetime,
    *,
    status: str = "FT",
    actuals: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "competition_key": "test-league",
        "event_id": event_id,
        "competition_name": "Test League",
        "season_name": "2026",
        "kickoff": (now - timedelta(hours=2)).isoformat(),
        "status": status,
        "home_team_id": 101,
        "home_team": "Home",
        "away_team_id": 202,
        "away_team": "Away",
        "home_score": 1 if status == "FT" else None,
        "away_score": 0 if status == "FT" else None,
        "final_actuals_json": json.dumps(actuals) if actuals is not None else None,
        "final_actuals_mtime": (now - timedelta(hours=1)).timestamp(),
    }


def test_select_remote_candidates_retries_finished_event_without_actuals() -> None:
    now = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    client = RemoteCandidateTurso([_remote_row(7001, now)])
    chosen = live.select_remote_candidates(
        client,
        now,
        {1: {"key": "test-league", "league_id": 1, "name": "Test League"}},
        event_ids=(),
        near_limit=5,
        overdue_limit=5,
    )
    assert [row["event_id"] for row in chosen] == [7001]
    assert chosen[0]["actuals_debt"] is True


def test_select_remote_candidates_refreshes_recent_complete_actuals() -> None:
    now = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    client = RemoteCandidateTurso(
        [_remote_row(7002, now, actuals=_complete_final_actuals())]
    )
    chosen = live.select_remote_candidates(
        client,
        now,
        {1: {"key": "test-league", "league_id": 1, "name": "Test League"}},
        event_ids=(),
        near_limit=5,
        overdue_limit=5,
    )
    assert [row["event_id"] for row in chosen] == [7002]
    assert chosen[0]["actuals_debt"] is False
    assert chosen[0]["actuals_refresh"] is True


def test_select_remote_candidates_skips_old_finished_event_with_complete_actuals() -> None:
    now = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    row = _remote_row(7004, now, actuals=_complete_final_actuals())
    row["kickoff"] = (now - timedelta(hours=25)).isoformat()
    client = RemoteCandidateTurso([row])
    chosen = live.select_remote_candidates(
        client,
        now,
        {1: {"key": "test-league", "league_id": 1, "name": "Test League"}},
        event_ids=(),
        near_limit=5,
        overdue_limit=5,
    )
    assert chosen == []


def test_select_remote_candidates_retries_incomplete_actuals() -> None:
    now = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    actuals = _complete_final_actuals()
    actuals["real"]["home_corners"] = None
    client = RemoteCandidateTurso([_remote_row(7003, now, actuals=actuals)])
    chosen = live.select_remote_candidates(
        client,
        now,
        {1: {"key": "test-league", "league_id": 1, "name": "Test League"}},
        event_ids=(),
        near_limit=5,
        overdue_limit=5,
    )
    assert [row["event_id"] for row in chosen] == [7003]


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


def test_select_candidates_rotates_recent_simultaneous_fixtures() -> None:
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
    now = datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)
    con.executemany(
        "INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?)",
        [
            (
                index,
                3000 + index,
                1,
                (now - timedelta(minutes=45 + index)).isoformat(),
                "NS",
                None,
                None,
                "2026",
                1,
                2,
            )
            for index in range(1, 9)
        ],
    )

    first = live.select_candidates(con, now, near_limit=2, overdue_limit=1)
    second = live.select_candidates(
        con, now + timedelta(minutes=1), near_limit=2, overdue_limit=1
    )

    first_ids = {row["event_id"] for row in first}
    second_ids = {row["event_id"] for row in second}
    assert first_ids != second_ids
    assert len(first_ids | second_ids) == 4
    con.close()
