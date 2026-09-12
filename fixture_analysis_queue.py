from __future__ import annotations

"""Select every unanalysed fixture in the Mobile today/tomorrow window."""

import json
import gzip
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ECUADOR_TZ = timezone(timedelta(hours=-5))
VISIBLE_ANALYSIS_STATES = {"FULL", "PARTIAL_WITH_FALLBACK"}


def load_schedule_seed_fixture_rows(
    seed_path: Path,
    by_league: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Load provider-discovered fixtures that are not yet in working SQLite."""

    if not seed_path.is_file():
        return []
    try:
        with gzip.open(seed_path, "rt", encoding="utf-8-sig") as handle:
            document = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    league_by_key = {
        str(item.get("key") or "").strip(): int(league_id)
        for league_id, item in by_league.items()
        if str(item.get("key") or "").strip()
    }
    rows: list[dict[str, Any]] = []
    for event in document.get("events", []) if isinstance(document, dict) else []:
        if not isinstance(event, dict):
            continue
        league_id = league_by_key.get(str(event.get("competition_key") or "").strip())
        if league_id is None:
            continue
        rows.append({
            "sofascore_id": event.get("event_id"),
            "league_id": league_id,
            "kickoff": event.get("kickoff"),
            "status": event.get("status"),
            "season": event.get("season_name"),
            "home_team_id": event.get("home_team_id"),
            "home_team": event.get("home_team"),
            "away_team_id": event.get("away_team_id"),
            "away_team": event.get("away_team"),
        })
    return rows


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
    if status not in VISIBLE_ANALYSIS_STATES or not isinstance(models, dict):
        return False
    # Placeholder bundles can contain a named but empty model.  Mobile only has
    # usable characteristics once a model exposes the complete 1X2 outcome.
    for name in ("MODELO_APRENDIDO", "MODELO_GOLES", "MODELO_XG"):
        model = models.get(name)
        outcome = model.get("outcome_probabilities") if isinstance(model, dict) else None
        if not isinstance(outcome, dict):
            continue
        try:
            values = [float(outcome[key]) for key in ("home_win", "draw", "away_win")]
        except (KeyError, TypeError, ValueError):
            continue
        if all(value >= 0 for value in values):
            return True
    return False


def select_pending_fixture_analyses(
    rows: Iterable[Mapping[str, Any]],
    by_league: Mapping[int, Mapping[str, Any]],
    analysis_root: Path,
    *,
    now: datetime,
    limit: int,
    grace_minutes: int = 0,
    priority_event_ids: Iterable[int] = (),
) -> list[dict[str, Any]]:
    """Return missing real model bundles, including recently finished fixtures."""

    now = now.astimezone(timezone.utc)
    local_today = now.astimezone(ECUADOR_TZ).date()

    # Mobile keeps yesterday / today / tomorrow. A fixture inside that
    # operational window can be recovered even if it already finished.
    window_start = datetime.combine(
        local_today - timedelta(days=1),
        datetime.min.time(),
        ECUADOR_TZ,
    ).astimezone(timezone.utc)
    end = datetime.combine(
        local_today + timedelta(days=2),
        datetime.min.time(),
        ECUADOR_TZ,
    ).astimezone(timezone.utc)

    grace_floor = now - timedelta(minutes=max(0, int(grace_minutes)))
    terminal_states = {"FT", "AET", "PEN", "FINISHED", "FINAL", "ENDED"}

    priority_ids: set[int] = set()
    for value in priority_event_ids:
        try:
            event_id = int(value)
        except (TypeError, ValueError):
            continue
        if event_id > 0:
            priority_ids.add(event_id)

    ranked: list[
        tuple[tuple[int, int, float, int], dict[str, Any]]
    ] = []
    seen_events: set[int] = set()

    for row in rows:
        record = dict(row)

        try:
            event_id = int(record.get("sofascore_id") or 0)
            league_id = int(record.get("league_id") or 0)
        except (TypeError, ValueError):
            continue

        if event_id <= 0 or event_id in seen_events:
            continue

        competition = by_league.get(league_id)
        if competition is None:
            continue

        kickoff = _parse_dt(record.get("kickoff"))
        if kickoff is None or kickoff < window_start or kickoff >= end:
            continue

        status = str(record.get("status") or "").upper()
        is_terminal = status in terminal_states
        is_priority = event_id in priority_ids

        # Normal live/upcoming debt keeps the grace window. Explicit rescue
        # targets bypass it, and genuine terminal fixtures may be completed
        # from their original pre-match target timestamp.
        if not is_priority and not is_terminal and kickoff < grace_floor:
            continue

        key = str(competition.get("key") or "").strip()
        if not key:
            continue

        if has_visible_characteristics(analysis_root, key, event_id):
            seen_events.add(event_id)
            continue

        item = {
            "competition": dict(competition),
            "event_id": event_id,
            "kickoff": kickoff.isoformat(),
            "start_timestamp": int(kickoff.timestamp()),
            "home_team_id": int(record.get("home_team_id") or 0),
            "home_team": str(record.get("home_team") or ""),
            "away_team_id": int(record.get("away_team_id") or 0),
            "away_team": str(record.get("away_team") or ""),
            "season": record.get("season"),
        }

        # 1) explicit rescued IDs
        # 2) live/upcoming missing bundles
        # 3) final missing bundles
        rank = (
            0 if is_priority else 1,
            1 if is_terminal else 0,
            kickoff.timestamp(),
            event_id,
        )
        ranked.append((rank, item))
        seen_events.add(event_id)

    ranked.sort(key=lambda pair: pair[0])
    return [
        item
        for _rank, item in ranked[:max(1, int(limit))]
    ]

