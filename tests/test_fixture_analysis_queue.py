from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from fixture_analysis_queue import select_pending_fixture_analyses
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
    (completed / "goals.json").write_text('{"models":{"MODELO_GOLES":{}}}', encoding="utf-8")
    selected = select_pending_fixture_analyses(
        [row(1, 10, "2026-09-09T20:00:00Z"), row(2, 10, "2026-09-09T21:00:00Z")],
        {10: {"key": "mls"}},
        tmp_path,
        now=datetime(2026, 9, 9, 12, tzinfo=timezone.utc),
        limit=64,
    )
    assert [item["event_id"] for item in selected] == [2]


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
