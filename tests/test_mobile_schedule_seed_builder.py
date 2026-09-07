from mobile_schedule_seed_builder import preserve_previous_coverage


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
