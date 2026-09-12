from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import datetime, timezone

from five_dollar_odds_sync import (
    _ensure_odds_tables,
    _merge_prices,
    _persist_database,
    _schedule_documents,
    _target_events,
    match_fixture,
    resolve_fixture,
)


def test_exact_kickoff_accepts_provider_team_suffixes():
    event = {
        "kickoff": "2026-09-08T18:00:00+00:00",
        "home_team": "Al-Qadsiah",
        "away_team": "Al-Ahli",
    }
    fixture = {
        "id": 3258053745,
        "kickoff_utc": "2026-09-08T18:00:00+00:00",
        "teams": {
            "home": {"name": "Al Qadisiya Al Khubar"},
            "away": {"name": "Al Ahli Jeddah"},
        },
    }
    assert match_fixture(event, [fixture]) == fixture


def test_psv_eindhoven_resolves_psv_alias_only_for_exact_fixture():
    event = {
        "competition_key": "uefa-champions-league",
        "event_id": 16938896,
        "kickoff": "2026-09-10T16:45:00+00:00",
        "home_team": "PSV Eindhoven",
        "away_team": "Shakhtar Donetsk",
    }
    fixture = {
        "id": 1,
        "kickoff_utc": "2026-09-10T16:45:00+00:00",
        "teams": {
            "home": {"name": "PSV"},
            "away": {"name": "Shakhtar Donetsk"},
        },
    }

    resolved, classification, score, _reason = resolve_fixture(event, [fixture])
    assert resolved == fixture
    assert classification == "RESOLVED_ALIAS"
    assert score == 0.7

    wrong_opponent = {
        **fixture,
        "id": 2,
        "teams": {
            "home": {"name": "PSV"},
            "away": {"name": "Ajax"},
        },
    }
    assert resolve_fixture(event, [wrong_opponent])[0] is None

    wrong_kickoff = {
        **fixture,
        "id": 3,
        "kickoff_utc": "2026-09-10T17:45:00+00:00",
    }
    assert resolve_fixture(event, [wrong_kickoff])[0] is None


def test_remaining_short_provider_names_resolve_only_exact_fixtures():
    cases = [
        {
            "competition_key": "uefa-champions-league",
            "event_id": 16938880,
            "kickoff": "2026-09-10T19:00:00+00:00",
            "wrong_kickoff": "2026-09-10T20:00:00+00:00",
            "app_home": "Manchester United",
            "app_away": "Sabah FK",
            "provider_home": "Man Utd",
            "provider_away": "Sabah",
            "score": 0.7083,
        },
        {
            "competition_key": "ligue-1",
            "event_id": 16310954,
            "kickoff": "2026-09-11T18:45:00+00:00",
            "wrong_kickoff": "2026-09-11T19:45:00+00:00",
            "app_home": "Stade Rennais",
            "app_away": "Olympique de Marseille",
            "provider_home": "Rennes",
            "provider_away": "Marseille",
            "score": 0.5881,
        },
        {
            "competition_key": "eredivisie",
            "event_id": 16316810,
            "kickoff": "2026-09-11T18:00:00+00:00",
            "wrong_kickoff": "2026-09-11T19:00:00+00:00",
            "app_home": "AZ Alkmaar",
            "app_away": "Willem II Tilburg",
            "provider_home": "AZ",
            "provider_away": "Willem II",
            "score": 0.5296,
        },
        {
            "competition_key": "laliga",
            "event_id": 16416328,
            "kickoff": "2026-09-12T12:00:00+00:00",
            "wrong_kickoff": "2026-09-12T13:00:00+00:00",
            "app_home": "Real Racing Club",
            "app_away": "Deportivo Alavés",
            "provider_home": "Racing Santander",
            "provider_away": "CD Alaves",
            "score": 0.7086,
        },
        {
            "competition_key": "saudi-pro-league",
            "event_id": 16653097,
            "kickoff": "2026-09-12T15:50:00+00:00",
            "wrong_kickoff": "2026-09-12T16:50:00+00:00",
            "app_home": "Al-Taawoun",
            "app_away": "Al-Hilal",
            "provider_home": "Al Taawon Buraidah",
            "provider_away": "Al Hilal Riyadh",
            "score": 0.6714,
        },
        {
            "competition_key": "bundesliga",
            "event_id": 16434027,
            "kickoff": "2026-09-12T16:30:00+00:00",
            "wrong_kickoff": "2026-09-12T17:30:00+00:00",
            "app_home": "1. FC Köln",
            "app_away": "SV Werder Bremen",
            "provider_home": "Cologne",
            "provider_away": "Werder Bremen",
            "score": 0.7115,
        },
        {
            "competition_key": "usa-usl-championship",
            "event_id": 15285845,
            "kickoff": "2026-09-12T23:00:00+00:00",
            "wrong_kickoff": "2026-09-13T00:00:00+00:00",
            "app_home": "SC Jacksonville",
            "app_away": "Rhode Island FC",
            "provider_home": "Sporting JAX",
            "provider_away": "Rhode Island FC",
            "score": 0.7,
        },
    ]

    for index, case in enumerate(cases, start=10):
        event = {
            "competition_key": case["competition_key"],
            "event_id": case["event_id"],
            "kickoff": case["kickoff"],
            "home_team": case["app_home"],
            "away_team": case["app_away"],
        }
        fixture = {
            "id": index,
            "kickoff_utc": case["kickoff"],
            "teams": {
                "home": {"name": case["provider_home"]},
                "away": {"name": case["provider_away"]},
            },
        }

        resolved, classification, score, _reason = resolve_fixture(event, [fixture])
        assert resolved == fixture
        assert classification == "RESOLVED_ALIAS"
        assert round(score, 4) == case["score"]

        wrong_opponent = {
            **fixture,
            "id": index + 100,
            "teams": {
                "home": {"name": case["provider_home"]},
                "away": {"name": "Wrong Opponent"},
            },
        }
        assert resolve_fixture(event, [wrong_opponent])[0] is None

        wrong_kickoff = {
            **fixture,
            "id": index + 200,
            "kickoff_utc": case["wrong_kickoff"],
        }
        assert resolve_fixture(event, [wrong_kickoff])[0] is None


def test_similar_team_names_do_not_override_wrong_kickoff():
    event = {
        "kickoff": "2026-09-08T18:00:00+00:00",
        "home_team": "Al-Qadsiah",
        "away_team": "Al-Ahli",
    }
    fixture = {
        "id": 1,
        "kickoff_utc": "2026-09-07T10:00:00+00:00",
        "teams": {
            "home": {"name": "Al Qadisiya"},
            "away": {"name": "Al Ahli"},
        },
    }
    assert match_fixture(event, [fixture]) is None


def test_captured_opening_is_immutable_and_current_moves():
    opening = [{"key": "result_home", "market": "Resultado 1X2", "selection": "Local", "odds": 2.5}]
    current = [{"key": "result_home", "market": "Resultado 1X2", "selection": "Local", "odds": 2.4}]
    _, first_history, first_stats = _merge_prices({}, opening, current, "2026-09-07T12:00:00+00:00")
    existing = {"price_history": first_history}
    moved = [{"key": "result_home", "market": "Resultado 1X2", "selection": "Local", "odds": 2.3}]
    _, second_history, second_stats = _merge_prices(existing, opening, moved, "2026-09-07T13:00:00+00:00")
    row = second_history[0]
    assert row["provider_opening"]["odds"] == 2.5
    assert row["captured_opening"] == {"odds": 2.4, "captured_at": "2026-09-07T12:00:00+00:00"}
    assert row["current"] == {"odds": 2.3, "updated_at": "2026-09-07T13:00:00+00:00"}
    assert first_stats == {"opening_created": 1, "opening_preserved": 0, "current_updated": 0}
    assert second_stats == {"opening_created": 0, "opening_preserved": 1, "current_updated": 1}


def test_asian_source_identity_and_ev_are_persisted_in_odds_state():
    connection = sqlite3.connect(":memory:")
    _ensure_odds_tables(connection)
    history = [{
        "key": "goals_over_2_5", "market": "Goles", "selection": "Más de 2.5", "line": 2.5,
        "display_line": 2.5, "source_market": "goal_line", "source_side": "over",
        "source_line": 2.25, "source_odds": 1.8, "source_ev": 0.07125,
        "price_origin": "ASIAN_MAPPED",
        "provider_opening": {"odds": 1.9}, "provider_closing": {"odds": 1.8},
        "captured_opening": {"odds": 1.9, "captured_at": "2026-09-08T12:00:00Z"},
        "current": {"odds": 1.8, "updated_at": "2026-09-08T13:00:00Z"},
    }]
    event = {
        "competition_key": "test", "event_id": 7, "kickoff": "2026-09-08T18:00:00Z",
        "home_team": "Home", "away_team": "Away",
    }
    assert _persist_database(connection, event, 70, "AVAILABLE", "2026-09-08T13:00:00Z", history) == 1
    row = connection.execute(
        "SELECT display_line,source_market,source_side,source_line,source_odds,source_ev,price_origin "
        "FROM bet365_odds_state"
    ).fetchone()
    assert row == (2.5, "goal_line", "over", 2.25, 1.8, 0.07125, "ASIAN_MAPPED")


def test_target_events_reads_service_owned_schedule_catalog(tmp_path, monkeypatch):
    root = tmp_path / "release"
    (root / "data").mkdir(parents=True)
    service_seed = tmp_path / "var" / "mobile_schedule_catalog_seed.json.gz"
    service_seed.parent.mkdir(parents=True)
    with gzip.open(service_seed, "wt", encoding="utf-8") as handle:
        json.dump(
            {
                "events": [
                    {
                        "competition_key": "serie-a",
                        "event_id": 9001,
                        "kickoff": "2026-09-08T18:00:00+00:00",
                        "home_team": "Home",
                        "away_team": "Away",
                    }
                ],
                "docs": [
                    {
                        "competition_key": "serie-a",
                        "event_id": 9001,
                        "doc_name": "analysis",
                        "json_text": json.dumps({"status": "READY"}),
                    },
                    {
                        "competition_key": "serie-a",
                        "event_id": 9001,
                        "doc_name": "goals",
                        "json_text": json.dumps({"models": {"MODELO_APRENDIDO": {"lambda_home": 1.2}}}),
                    },
                ],
            },
            handle,
        )
    monkeypatch.setenv("ODDSHUNTER_SCHEDULE_CATALOG_SEED", str(service_seed))

    rows = _target_events(
        root,
        datetime(2026, 9, 8, tzinfo=timezone.utc),
        datetime(2026, 9, 9, tzinfo=timezone.utc),
    )

    assert [(row["competition_key"], row["event_id"]) for row in rows] == [("serie-a", 9001)]
    bundles = _schedule_documents(root)
    assert bundles[("serie-a", 9001)]["status"] == "READY"
    assert bundles[("serie-a", 9001)]["goals"]["models"]["MODELO_APRENDIDO"]["lambda_home"] == 1.2


def test_provider_not_found_still_persists_all_model_picks(tmp_path, monkeypatch):
    import five_dollar_odds_sync as sync_module
    event = {"competition_key": "copa-colombia", "event_id": 99,
             "home_team": "Home", "away_team": "Away", "kickoff": "2026-09-07T23:00:00Z"}
    bundle = {"goals": {"models": {"MODELO_APRENDIDO": {
        "outcome_probabilities": {"home_win": 0.6, "draw": 0.3, "away_win": 0.1},
        "lambda_home": 1.8, "lambda_away": 0.8,
        "total_goals_distribution": {"0": 0.1, "1": 0.2, "2": 0.3, "3": 0.4},
    }}}}
    monkeypatch.setenv("FIVE_DOLLAR_FOOTBALL_API_KEY", "test-only")
    monkeypatch.setattr(sync_module, "_target_events", lambda *_: [event])
    monkeypatch.setattr(sync_module, "_schedule_documents", lambda *_: {("copa-colombia", 99): bundle})
    monkeypatch.setattr(sync_module, "fetch_fixtures", lambda *_args, **_kwargs: [])
    class NoRequests:
        request_count = 0
    result = sync_module.sync(tmp_path, now=datetime(2026, 9, 7, 20, tzinfo=timezone.utc), client=NoRequests())
    document = json.loads((tmp_path / "data/analisis/copa-colombia/99/odds_value.json").read_text())
    assert document["odds_status"] == "PROVIDER_NOT_FOUND"
    assert document["all_picks"]
    assert document["probabilities"]["result_home"] == 0.6
    assert all(pick["odds"] is None for pick in document["all_picks"])
    assert result["INDIVIDUAL_FALLBACK_REQUESTS"] == 0
