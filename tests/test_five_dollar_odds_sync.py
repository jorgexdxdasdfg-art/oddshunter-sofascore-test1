from __future__ import annotations

from five_dollar_odds_sync import _merge_prices, match_fixture


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
