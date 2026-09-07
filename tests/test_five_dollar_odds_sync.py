from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone

from five_dollar_odds_sync import _merge_prices, _schedule_documents, _target_events, match_fixture


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
