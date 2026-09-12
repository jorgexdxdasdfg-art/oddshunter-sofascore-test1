"""Export the Desktop season calendar and rolling Mobile catalog snapshots.

This keeps Mobile independent from the user's PC after deployment: the full
known season calendar is shipped as a bootstrap, while the current Ecuador
yesterday/today/tomorrow window includes every existing analysis document.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mobile_schedule_seed_builder import ECUADOR_TZ, headline, parse_dt, read_documents


def _write_gzip_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as packed:
            packed.write(encoded)


def _load_excluded(path: Path) -> set[int]:
    if not path.is_file():
        return set()
    try:
        with gzip.open(path, "rt", encoding="utf-8-sig") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    source = value.get("excluded_event_ids", []) if isinstance(value, dict) else []
    return {int(item) for item in source}


def _event_rows(db: Path, active_leagues: set[int]) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = [dict(row) for row in connection.execute(
        """
        SELECT m.sofascore_id AS event_id,m.league_id,m.kickoff,m.status,
               m.home_goals,m.away_goals,m.season AS season_name,
               l.name AS competition_name,
               h.sofascore_id AS home_team_id,h.name AS home_team,
               a.sofascore_id AS away_team_id,a.name AS away_team
        FROM matches m
        JOIN leagues l ON l.league_id=m.league_id
        JOIN teams h ON h.team_id=m.home_team_id
        JOIN teams a ON a.team_id=m.away_team_id
        WHERE m.sofascore_id IS NOT NULL
        ORDER BY datetime(m.kickoff),m.sofascore_id
        """
    ) if int(row["league_id"]) in active_leagues]
    connection.close()
    return rows


def _upcoming_rows(root: Path, competitions: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Load Desktop's UI calendar, including fixtures not committed to SQLite yet."""
    rows: list[dict[str, Any]] = []
    for league_id, competition in competitions.items():
        path = root / str(competition["key"]) / "matches_upcoming.json"
        if not path.is_file():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for raw in document.get("matches", []):
            if not isinstance(raw, dict) or not raw.get("event_id") or not raw.get("kickoff"):
                continue
            rows.append({
                "event_id": int(raw["event_id"]),
                "league_id": league_id,
                "kickoff": raw["kickoff"],
                "status": raw.get("status") or "NS",
                "home_goals": raw.get("home_score"),
                "away_goals": raw.get("away_score"),
                "season_name": raw.get("season_name") or competition.get("season_name"),
                "competition_name": raw.get("competition_name") or competition.get("name"),
                "home_team_id": raw.get("home_team_id"),
                "home_team": raw.get("home_team"),
                "away_team_id": raw.get("away_team_id"),
                "away_team": raw.get("away_team"),
            })
    return rows


def _canonical_status(value: Any) -> str:
    normalized = str(value or "").strip().casefold().replace("_", "")
    return {
        "notstarted": "NS",
        "scheduled": "NS",
        "inprogress": "LIVE",
        "live": "LIVE",
        "finished": "FT",
        "afterextra": "FT",
        "afterpenalties": "FT",
        "postponed": "POSTPONED",
        "canceled": "CANCELLED",
        "cancelled": "CANCELLED",
        "abandoned": "ABANDONED",
    }.get(normalized, str(value or "NS").upper())


def export(args: argparse.Namespace) -> dict[str, Any]:
    now = parse_dt(args.now) if args.now else datetime.now(timezone.utc)
    assert now is not None
    today = now.astimezone(ECUADOR_TZ).date()
    window_start = datetime.combine(today - timedelta(days=1), datetime.min.time(), ECUADOR_TZ).astimezone(timezone.utc)
    window_end = datetime.combine(today + timedelta(days=2), datetime.min.time(), ECUADOR_TZ).astimezone(timezone.utc)
    season_start = parse_dt(args.season_start) if args.season_start else window_start
    assert season_start is not None

    registry = json.loads(args.registry.read_text(encoding="utf-8-sig"))
    competitions = {
        int(row["league_id"]): row
        for row in registry.get("competitions", [])
        if isinstance(row, dict) and row.get("active") and row.get("league_id") is not None
    }
    excluded = _load_excluded(args.bootstrap_output)
    # SQLite is the durable base; the same per-league calendar used by the PC
    # wins for reschedules and adds freshly discovered fixtures not inserted in
    # SQLite yet. Identity remains the canonical provider event_id.
    by_event = {int(row["event_id"]): row for row in _event_rows(args.db, set(competitions))}
    for row in _upcoming_rows(args.schedule_root, competitions):
        by_event[int(row["event_id"])] = row
    rows = sorted(
        (
            row for row in by_event.values()
            if int(row["event_id"]) not in excluded
            and (parse_dt(row["kickoff"]) or season_start) >= season_start
        ),
        key=lambda row: ((parse_dt(row["kickoff"]) or season_start), int(row["event_id"])),
    )

    generated_at = now.isoformat()
    bootstrap = {
        "generated_at": generated_at,
        "source": "desktop_season_calendar_bootstrap",
        "events": rows,
        "validation": {
            "event_count": len(rows),
            "active_competition_count": len(competitions),
            "excluded_stale_duplicate_event_ids": sorted(excluded),
            "first_kickoff": rows[0]["kickoff"] if rows else None,
            "last_kickoff": rows[-1]["kickoff"] if rows else None,
        },
        "excluded_event_ids": sorted(excluded),
    }

    catalog_events: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []
    missing_analysis: list[int] = []
    counts_by_day: dict[str, int] = defaultdict(int)
    leagues_by_day: dict[str, set[str]] = defaultdict(set)
    event_ids_by_day: dict[str, list[int]] = defaultdict(list)

    for row in rows:
        kickoff = parse_dt(row["kickoff"])
        if kickoff is None or not (window_start <= kickoff < window_end):
            continue
        league_id = int(row["league_id"])
        competition_key = str(competitions[league_id]["key"])
        event_id = int(row["event_id"])
        parsed, document_rows = read_documents(args.analysis_root / competition_key / str(event_id))
        upcoming = parsed.get("input_match", {}).get("upcoming_match", {})
        if not isinstance(upcoming, dict):
            upcoming = {}
        status_doc = parsed.get("status", {})
        analysis_doc = parsed.get("analysis", {})
        analysis_status = status_doc.get("status") or analysis_doc.get("status") or ("READY" if document_rows else "pending")
        if "analysis" not in parsed:
            missing_analysis.append(event_id)
        status = _canonical_status(row.get("status") or upcoming.get("status") or "NS")
        catalog_events.append({
            "competition_key": competition_key,
            "event_id": event_id,
            "competition_name": row.get("competition_name") or competitions[league_id].get("name"),
            "season_name": row.get("season_name") or competitions[league_id].get("season_name"),
            "round_name": upcoming.get("round_name") or upcoming.get("round"),
            "stage": upcoming.get("stage") or row.get("competition_name"),
            "kickoff": kickoff.isoformat(),
            "status": status,
            "status_description": upcoming.get("status_description") or status,
            "home_team_id": row.get("home_team_id"),
            "home_team": row.get("home_team"),
            "away_team_id": row.get("away_team_id"),
            "away_team": row.get("away_team"),
            "home_score": row.get("home_goals"),
            "away_score": row.get("away_goals"),
            "analysis_status": analysis_status,
            "headline_json": json.dumps(headline(parsed.get("goals") or {}), ensure_ascii=False, separators=(",", ":")),
        })
        for document in document_rows:
            docs.append({"competition_key": competition_key, "event_id": event_id, **document})
        day = kickoff.astimezone(ECUADOR_TZ).date().isoformat()
        counts_by_day[day] += 1
        leagues_by_day[day].add(competition_key)
        event_ids_by_day[day].append(event_id)

    expected_days = [(today + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)]
    seed = {
        "generated_at": generated_at,
        "window": {"timezone": "America/Guayaquil", "start": window_start.isoformat(), "end_exclusive": window_end.isoformat()},
        "events": catalog_events,
        "docs": docs,
        "missing_analysis": sorted(missing_analysis),
        "counts_by_day": {day: counts_by_day.get(day, 0) for day in expected_days},
        "leagues_by_day": {day: sorted(leagues_by_day.get(day, set())) for day in expected_days},
        "event_ids_by_day": {day: sorted(event_ids_by_day.get(day, [])) for day in expected_days},
        "validation": {
            "input_events": len(catalog_events),
            "active_competition_count": len(competitions),
            "excluded_stale_duplicate_event_ids": sorted(excluded),
            "source": "desktop_complete_analysis_snapshot",
        },
    }
    _write_gzip_json(args.bootstrap_output, bootstrap)
    _write_gzip_json(args.seed_output, seed)
    return {"bootstrap_events": len(rows), "catalog_events": len(catalog_events), "documents": len(docs), "counts_by_day": seed["counts_by_day"], "missing_analysis": len(missing_analysis)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--analysis-root", type=Path, required=True)
    parser.add_argument("--schedule-root", type=Path, required=True)
    parser.add_argument("--bootstrap-output", type=Path, default=Path("deploy/mobile_schedule_bootstrap.json.gz"))
    parser.add_argument("--seed-output", type=Path, default=Path("deploy/mobile_schedule_catalog_seed.json.gz"))
    parser.add_argument("--now")
    parser.add_argument("--season-start")
    args = parser.parse_args()
    print(json.dumps(export(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
