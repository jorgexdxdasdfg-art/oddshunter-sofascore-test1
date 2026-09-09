from __future__ import annotations

"""Select every unanalysed fixture in the Mobile today/tomorrow window."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ECUADOR_TZ = timezone(timedelta(hours=-5))
VISIBLE_ANALYSIS_STATES = {"FULL", "PARTIAL_WITH_FALLBACK"}


def _parse_dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def has_visible_characteristics(analysis_root: Path, competition_key: str, event_id: int) -> bool:
    """A READY placeholder is not complete until its real model bundle exists."""

    folder = analysis_root / competition_key / str(event_id)
    analysis_path = folder / "analysis.json"
    goals_path = folder / "goals.json"
    if not analysis_path.is_file() or not goals_path.is_file():
        return False
    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8-sig"))
        goals = json.loads(goals_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    status = str(analysis.get("status") or analysis.get("analysis_status") or "").upper()
    models = goals.get("models") if isinstance(goals, dict) else None
    return status in VISIBLE_ANALYSIS_STATES and isinstance(models, dict) and bool(models)


def select_pending_fixture_analyses(
    rows: Iterable[Mapping[str, Any]],
    by_league: Mapping[int, Mapping[str, Any]],
    analysis_root: Path,
    *,
    now: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    """Return all pending fixtures, not one representative per competition."""

    now = now.astimezone(timezone.utc)
    local_today = now.astimezone(ECUADOR_TZ).date()
    end = datetime.combine(local_today + timedelta(days=2), datetime.min.time(), ECUADOR_TZ).astimezone(timezone.utc)
    selected: list[dict[str, Any]] = []
    seen_events: set[int] = set()

    for row in rows:
        kickoff = _parse_dt(row.get("kickoff"))
        if kickoff is None or kickoff < now or kickoff >= end:
            continue
        event_id = int(row.get("sofascore_id") or 0)
        competition = by_league.get(int(row.get("league_id") or 0))
        if event_id <= 0 or competition is None or event_id in seen_events:
            continue
        key = str(competition.get("key") or "").strip()
        if not key or has_visible_characteristics(analysis_root, key, event_id):
            continue

        selected.append({
            "competition": dict(competition),
            "event_id": event_id,
            "kickoff": kickoff.isoformat(),
            "start_timestamp": int(kickoff.timestamp()),
            "home_team_id": int(row.get("home_team_id") or 0),
            "home_team": str(row.get("home_team") or ""),
            "away_team_id": int(row.get("away_team_id") or 0),
            "away_team": str(row.get("away_team") or ""),
            "season": row.get("season"),
        })
        seen_events.add(event_id)
        if len(selected) >= max(1, int(limit)):
            break

    return selected
