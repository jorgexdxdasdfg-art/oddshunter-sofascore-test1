from datetime import datetime, timezone
from pathlib import Path
import gzip
import json
import sqlite3

from fixture_analysis_queue import load_schedule_seed_fixture_rows, select_pending_fixture_analyses
from stage5_complete_fixture_analysis_patch import patch_source


def row(event_id: int, league_id: int, kickoff: str) -> dict:
    return {
        "sofascore_id": event_id,
        "league_id": league_id,
        "kickoff": kickoff,
        "season": "2026",
        "home_team_id": event_id * 10,
        "home_team": f"Home {event_id}",
        "away_team_id": event_id * 10 + 1,
        "away_team": f"Away {event_id}",
    }


def test_every_pending_match_from_same_competition_is_selected(tmp_path: Path) -> None:
    rows = [row(event_id, 10, f"2026-09-09T{hour:02d}:00:00+00:00") for event_id, hour in zip(range(1, 14), range(12, 25))]
    selected = select_pending_fixture_analyses(
        rows,
        {10: {"key": "mls", "name": "MLS"}},
        tmp_path,
        now=datetime(2026, 9, 9, 11, tzinfo=timezone.utc),
        limit=64,
    )
    assert [item["event_id"] for item in selected] == list(range(1, 13))
    assert {item["competition"]["key"] for item in selected} == {"mls"}


def test_completed_bundle_is_skipped_but_ready_placeholder_is_not(tmp_path: Path) -> None:
    completed = tmp_path / "mls" / "1"
    completed.mkdir(parents=True)
    (completed / "analysis.json").write_text('{"status":"FULL"}', encoding="utf-8")
    (completed / "goals.json").write_text(
        '{"models":{"MODELO_GOLES":{"outcome_probabilities":{"home_win":0.5,"draw":0.25,"away_win":0.25}}}}',
        encoding="utf-8",
    )
    selected = select_pending_fixture_analyses(
        [row(1, 10, "2026-09-09T20:00:00Z"), row(2, 10, "2026-09-09T21:00:00Z")],
        {10: {"key": "mls"}},
        tmp_path,
        now=datetime(2026, 9, 9, 12, tzinfo=timezone.utc),
        limit=64,
    )
    assert [item["event_id"] for item in selected] == [2]


def test_named_but_empty_model_remains_pending(tmp_path: Path) -> None:
    placeholder = tmp_path / "mls" / "1"
    placeholder.mkdir(parents=True)
    (placeholder / "analysis.json").write_text('{"status":"FULL"}', encoding="utf-8")
    (placeholder / "goals.json").write_text('{"models":{"MODELO_GOLES":{}}}', encoding="utf-8")
    selected = select_pending_fixture_analyses(
        [row(1, 10, "2026-09-09T20:00:00Z")],
        {10: {"key": "mls"}},
        tmp_path,
        now=datetime(2026, 9, 9, 12, tzinfo=timezone.utc),
        limit=64,
    )
    assert [item["event_id"] for item in selected] == [1]


def test_provider_discovered_seed_fixture_joins_analysis_queue(tmp_path: Path) -> None:
    seed = tmp_path / "schedule.json.gz"
    with gzip.open(seed, "wt", encoding="utf-8") as handle:
        json.dump({"events": [{
            "event_id": 77,
            "competition_key": "saudi-pro-league",
            "kickoff": "2026-09-09T16:00:00Z",
            "status": "NS",
            "season_name": "2026/27",
            "home_team_id": 7,
            "home_team": "Al-Kholood",
            "away_team_id": 8,
            "away_team": "Al-Shabab",
        }]}, handle)
    registry = {20: {"key": "saudi-pro-league"}}
    rows = load_schedule_seed_fixture_rows(seed, registry)
    selected = select_pending_fixture_analyses(
        rows,
        registry,
        tmp_path / "analisis",
        now=datetime(2026, 9, 9, 10, tzinfo=timezone.utc),
        limit=64,
    )
    assert selected[0]["event_id"] == 77
    assert selected[0]["home_team"] == "Al-Kholood"


def test_accepts_sqlite_rows_used_by_stage5(tmp_path: Path) -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        "CREATE TABLE q(sofascore_id,league_id,kickoff,season,home_team_id,home_team,away_team_id,away_team);"
        "INSERT INTO q VALUES(99,10,'2026-09-09T20:00:00Z','2026',1,'Home',2,'Away');"
    )
    rows = connection.execute("SELECT * FROM q").fetchall()
    selected = select_pending_fixture_analyses(
        rows,
        {10: {"key": "mls"}},
        tmp_path,
        now=datetime(2026, 9, 9, 12, tzinfo=timezone.utc),
        limit=64,
    )
    assert [item["event_id"] for item in selected] == [99]


def test_patch_removes_two_match_and_one_per_competition_contract() -> None:
    source = '''def future_analysis_targets(\n    old\n):\n    seen = set()\n    return []\n\ndef write_schedule(target):\n    pass\n\ndef main():\n    analysis_targets = future_analysis_targets(con, by_league, 2)\n'''
    patched = patch_source(source)
    assert "ODDSHUNTER_ANALYSIS_TARGET_LIMIT" in patched
    assert "select_pending_fixture_analyses" in patched
    assert "seen = set()" not in patched
    assert "analysis_registry, _analysis_active = active_registry()" in patched
    assert "con, analysis_registry" in patched


def test_patch_accepts_named_legacy_limit() -> None:
    source = '''def future_analysis_targets(\n    old\n):\n    return []\n\ndef write_schedule(target):\n    pass\n\ndef main():\n    analysis_targets = future_analysis_targets(con, by_league, FUTURE_LIMIT)\n'''
    patched = patch_source(source)
    assert "FUTURE_LIMIT" not in patched
    assert "ODDSHUNTER_ANALYSIS_TARGET_LIMIT" in patched


def test_patch_repairs_already_patched_call_that_depended_on_by_league() -> None:
    source = '''def future_analysis_targets(\n    old\n):\n    return []\n\ndef write_schedule(target):\n    pass\n\ndef main():\n    analysis_targets = future_analysis_targets(\n            con, by_league,\n            int(os.environ.get("ODDSHUNTER_ANALYSIS_TARGET_LIMIT", "64")),\n        )\n'''
    patched = patch_source(source)
    assert "con, by_league" not in patched
    assert patched.count("analysis_registry, _analysis_active = active_registry()") == 1
    compile(patched, "cloud_stage5_cycle.py", "exec")


def test_finished_missing_fixture_can_be_recovered(tmp_path: Path) -> None:
    finished = row(700, 10, "2026-09-11T12:00:00Z")
    finished["status"] = "FT"

    selected = select_pending_fixture_analyses(
        [finished],
        {10: {"key": "turkey-super-lig"}},
        tmp_path,
        now=datetime(2026, 9, 11, 23, 0, tzinfo=timezone.utc),
        limit=64,
        grace_minutes=90,
    )

    assert [item["event_id"] for item in selected] == [700]


def test_priority_fixture_bypasses_grace_and_wins_limit(tmp_path: Path) -> None:
    recent = row(1, 10, "2026-09-11T22:30:00Z")
    rescued = row(2, 10, "2026-09-11T14:00:00Z")

    selected = select_pending_fixture_analyses(
        [recent, rescued],
        {10: {"key": "usa-usl-championship"}},
        tmp_path,
        now=datetime(2026, 9, 11, 23, 0, tzinfo=timezone.utc),
        limit=1,
        grace_minutes=90,
        priority_event_ids=[2],
    )

    assert [item["event_id"] for item in selected] == [2]


def test_stage5_patch_wires_priority_event_ids() -> None:
    source = """def future_analysis_targets(
    old
):
    return []

def write_schedule(target):
    pass

def main():
    analysis_targets = future_analysis_targets(con, by_league, 2)
"""
    patched = patch_source(source)
    assert "ODDSHUNTER_ANALYSIS_PRIORITY_EVENT_IDS" in patched
    assert "priority_event_ids=priority_event_ids" in patched
