import gzip
import json
from datetime import datetime, timezone

from mobile_schedule_seed_builder import (
    load_bootstrap_excluded_event_ids,
    load_schedule_bootstrap,
    preserve_previous_coverage,
)


def event(event_id: int, day: str, status: str = "NS") -> dict:
    return {
        "competition_key": "league",
        "event_id": event_id,
        "kickoff": f"{day}T18:00:00+00:00",
        "status": status,
    }


def test_refresh_preserves_missing_rows_but_prefers_fresh_updates() -> None:
    previous = {
        "events": [event(1, "2026-09-06"), event(2, "2026-09-07"), event(3, "2026-09-08")],
        "docs": [
            {"competition_key": "league", "event_id": 2, "doc_name": "goals", "json_text": "old"}
        ],
    }
    fresh = {
        "events": [event(2, "2026-09-07", "FT")],
        "docs": [
            {"competition_key": "league", "event_id": 2, "doc_name": "goals", "json_text": "fresh"}
        ],
        "validation": {},
    }

    merged = preserve_previous_coverage(
        fresh, previous, {"2026-09-06", "2026-09-07", "2026-09-08"}
    )

    assert [row["event_id"] for row in merged["events"]] == [1, 2, 3]
    assert next(row for row in merged["events"] if row["event_id"] == 2)["status"] == "FT"
    assert merged["docs"][0]["json_text"] == "fresh"
    assert merged["counts_by_day"] == {
        "2026-09-06": 1,
        "2026-09-07": 1,
        "2026-09-08": 1,
    }
    assert merged["validation"]["preserved_previous_events"] == 2


def test_refresh_discards_days_outside_the_rolling_window() -> None:
    merged = preserve_previous_coverage(
        {"events": [event(5, "2026-09-09")], "docs": [], "validation": {}},
        {"events": [event(1, "2026-09-06"), event(2, "2026-09-08")], "docs": []},
        {"2026-09-07", "2026-09-08", "2026-09-09"},
    )

    assert {row["event_id"] for row in merged["events"]} == {2, 5}
    assert set(merged["counts_by_day"]) == {"2026-09-08", "2026-09-09"}


def test_season_bootstrap_is_filtered_to_active_three_day_window(tmp_path) -> None:
    path = tmp_path / "bootstrap.json.gz"
    document = {
        "excluded_event_ids": [99, "100", "bad"],
        "events": [
            {"event_id": 10, "league_id": 1, "kickoff": "2026-09-09T18:00:00Z"},
            {"event_id": 11, "league_id": 2, "kickoff": "2026-09-09T18:00:00Z"},
            {"event_id": 12, "league_id": 1, "kickoff": "2026-09-15T18:00:00Z"},
        ]
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(document, handle)

    rows = load_schedule_bootstrap(
        path,
        {1: {"key": "league"}},
        datetime(2026, 9, 8, tzinfo=timezone.utc),
        datetime(2026, 9, 11, tzinfo=timezone.utc),
    )

    assert [row["event_id"] for row in rows] == [10]
    assert load_bootstrap_excluded_event_ids(path) == {99, 100}
