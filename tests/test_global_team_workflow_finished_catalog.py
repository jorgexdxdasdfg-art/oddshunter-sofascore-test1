from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ODDSHUNTER_CLOUD_LINUX_STAGE4_STAGE5_V4.zip"


def load_workflow(tmp_path: Path):
    with zipfile.ZipFile(PACKAGE) as archive:
        archive.extract("global_team_workflow.py", tmp_path)
    module_path = tmp_path / "global_team_workflow.py"
    spec = importlib.util.spec_from_file_location(
        "global_team_workflow_under_test",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_catalog(path: Path, matches: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"matches": matches}),
        encoding="utf-8",
    )


def match(event_id: int, kickoff: int) -> dict[str, int]:
    return {"event_id": event_id, "start_timestamp": kickoff}


def test_recent_finished_catalog_events_remain_due_after_schedule_refresh(
    tmp_path: Path,
) -> None:
    workflow = load_workflow(tmp_path)
    now = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)
    workflow.utc_now = lambda: now
    workflow.COMPETITIONS_DIR = tmp_path / "data" / "competitions"

    competition = workflow.COMPETITIONS_DIR / "serie-a"
    recent_finished = int(datetime(2026, 9, 20, 20, 0, tzinfo=timezone.utc).timestamp())
    expired_upcoming = int(datetime(2026, 9, 20, 19, 0, tzinfo=timezone.utc).timestamp())
    old_finished = int(datetime(2026, 8, 1, 20, 0, tzinfo=timezone.utc).timestamp())
    settled_finished = int(datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc).timestamp())

    write_catalog(
        competition / "matches_upcoming.json",
        [match(100, expired_upcoming)],
    )
    write_catalog(
        competition / "matches_finished.json",
        [
            match(200, recent_finished),
            match(300, old_finished),
            match(400, settled_finished),
        ],
    )

    due, report = workflow.select_due_events(
        "serie-a",
        {
            200: {"status": "NS", "settled_rows": 0},
            400: {"status": "FT", "settled_rows": 2},
        },
        {},
        ignore_retry=True,
    )

    assert due == [100, 200]
    assert report["selected_total"] == 2


def test_finished_catalog_is_deduplicated_against_upcoming_catalog(
    tmp_path: Path,
) -> None:
    workflow = load_workflow(tmp_path)
    now = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)
    workflow.utc_now = lambda: now
    workflow.COMPETITIONS_DIR = tmp_path / "data" / "competitions"
    kickoff = int(datetime(2026, 9, 20, 20, 0, tzinfo=timezone.utc).timestamp())
    competition = workflow.COMPETITIONS_DIR / "j1-league"
    write_catalog(competition / "matches_upcoming.json", [match(500, kickoff)])
    write_catalog(competition / "matches_finished.json", [match(500, kickoff)])

    due, report = workflow.select_due_events(
        "j1-league",
        {500: {"status": "NS", "settled_rows": 0}},
        {},
        ignore_retry=True,
    )

    assert due == [500]
    assert report["selected_total"] == 1


def test_cloud_cycle_selects_expired_ns_and_skips_settled_matches(
    tmp_path: Path,
) -> None:
    with zipfile.ZipFile(PACKAGE) as archive:
        archive.extractall(tmp_path)
    module_path = tmp_path / "cloud_stage5_cycle.py"
    sys.path.insert(0, str(tmp_path))
    try:
        spec = importlib.util.spec_from_file_location("cloud_stage5_under_test", module_path)
        assert spec is not None and spec.loader is not None
        workflow = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(workflow)
    finally:
        sys.path.remove(str(tmp_path))

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE teams(team_id INTEGER PRIMARY KEY, name TEXT, sofascore_id INTEGER);
        CREATE TABLE matches(
            match_id INTEGER PRIMARY KEY, sofascore_id INTEGER, league_id INTEGER,
            kickoff TEXT, status TEXT, season TEXT, home_goals INTEGER,
            away_goals INTEGER, home_team_id INTEGER, away_team_id INTEGER
        );
        CREATE TABLE team_match_stats(
            stat_id INTEGER PRIMARY KEY, match_id INTEGER, data_quality TEXT,
            xg_for REAL, shots INTEGER, corners_for INTEGER, yellow_cards INTEGER
        );
        """
    )
    connection.executemany(
        "INSERT INTO teams VALUES (?, ?, ?)",
        [(1, "Home", 1), (2, "Away", 2)],
    )
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    connection.executemany(
        "INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (10, 100, 1, expired, "NS", "2026", None, None, 1, 2),
            (20, 200, 1, expired, "FT", "2026", 1, 0, 1, 2),
        ],
    )
    connection.executemany(
        "INSERT INTO team_match_stats VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 20, "FULL", 1.0, 10, 5, 2),
            (2, 20, "FULL", 0.5, 8, 3, 3),
        ],
    )

    candidates = workflow.recent_sync_candidates(
        connection,
        {1: {"key": "serie-a"}},
    )

    assert [(row["event_id"], row["database_status"]) for row in candidates] == [
        (100, "NS")
    ]
