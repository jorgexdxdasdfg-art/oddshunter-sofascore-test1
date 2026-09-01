from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://api.sofascore.com/api/v1/event/{event_id}"
STATISTICS_URLS = (
    "https://www.sofascore.com/api/v1/event/{event_id}/statistics",
    "https://api.sofascore.com/api/v1/event/{event_id}/statistics",
)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def final_actuals_from_statistics_document(
    event_id: int,
    document: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Normalize the exact SofaScore event box score used by Expected/Real."""
    periods = document.get("statistics")
    if not isinstance(periods, list):
        return None
    all_period = next(
        (
            period
            for period in periods
            if isinstance(period, Mapping)
            and str(period.get("period") or "").upper() == "ALL"
        ),
        None,
    )
    if not isinstance(all_period, Mapping):
        return None

    values: dict[str, tuple[float | None, float | None]] = {}
    groups = all_period.get("groups")
    if isinstance(groups, list):
        for group in groups:
            items = group.get("statisticsItems") if isinstance(group, Mapping) else None
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                key = str(item.get("key") or "").strip()
                if not key or key in values:
                    continue
                values[key] = (
                    _number(item.get("homeValue")),
                    _number(item.get("awayValue")),
                )

    real: dict[str, float | None] = {}
    mapping = {
        "expectedGoals": ("home_xg", "away_xg"),
        "totalShotsOnGoal": ("home_shots", "away_shots"),
        "shotsOnGoal": ("home_shots_on_target", "away_shots_on_target"),
        "shotsOffGoal": ("home_shots_off_target", "away_shots_off_target"),
        "blockedScoringAttempt": ("home_blocked_shots", "away_blocked_shots"),
        "cornerKicks": ("home_corners", "away_corners"),
        "yellowCards": ("home_yellow_cards", "away_yellow_cards"),
    }
    for source_key, (home_key, away_key) in mapping.items():
        home, away = values.get(source_key, (None, None))
        real[home_key] = home
        real[away_key] = away
    if not any(value is not None for value in real.values()):
        return None
    return {
        "event_id": int(event_id),
        "real": real,
        "temporal_xg": {"expected": [], "goals": []},
        "temporal_xg_available": False,
        "xg_by_half": {"first": None, "second": None},
        "xg_zone_map_available": False,
        "source": "sofascore-event-id",
    }

def snapshot_from_document(event_id: int, document: Mapping[str, Any], expected: Mapping[str, Any] | None = None) -> dict[str, Any]:
    event = document.get("event")
    if not isinstance(event, Mapping) or _integer(event.get("id")) != int(event_id):
        raise ValueError("SofaScore devolvió una identidad de evento incorrecta")
    if expected:
        for side, actual in (("home", event.get("homeTeam") or {}), ("away", event.get("awayTeam") or {})):
            expected_id = _integer(expected.get(f"{side}_team_id"))
            actual_id = _integer(actual.get("id")) if isinstance(actual, Mapping) else None
            if expected_id is not None and actual_id is not None and expected_id != actual_id:
                raise ValueError(f"SofaScore cambió la identidad {side} del evento")
    status = event.get("status") or {}
    status_type = str(status.get("type") or "").strip().lower()
    if status_type == "finished":
        state = "finished"
    elif status_type in {"inprogress", "live", "started"}:
        state = "live"
    elif status_type in {"scheduled", "notstarted"}:
        state = "scheduled"
    elif status_type in {"canceled", "cancelled", "postponed", "abandoned", "interrupted"}:
        state = "terminal"
    else:
        state = "unknown"
    timestamp = _integer(event.get("startTimestamp"))
    home_score = event.get("homeScore") or {}
    away_score = event.get("awayScore") or {}
    return {
        "state": state,
        "provider_status": str(status.get("description") or status_type),
        "home_goals": _integer(home_score.get("current")),
        "away_goals": _integer(away_score.get("current")),
        "kickoff": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat() if timestamp is not None else None,
        "provider": "sofascore-event-id",
    }

class SofaScoreEventClient:
    def __init__(self, *, logger: Callable[[str], None] | None = None, timeout: float = 20.0, retries: int = 3) -> None:
        self.logger = logger or (lambda _message: None)
        self.timeout = timeout
        self.retries = max(1, retries)

    def _fetch_json(self, url: str, *, label: str) -> Mapping[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            curl = shutil.which("curl")
            if curl:
                try:
                    completed = subprocess.run(
                        [curl, "-fsSL", "--max-time", str(int(self.timeout)), "-H", "Accept: application/json", "-H", "User-Agent: Mozilla/5.0", url],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=self.timeout + 5,
                    )
                    document = json.loads(completed.stdout)
                    if not isinstance(document, Mapping):
                        raise ValueError("respuesta JSON sin objeto raíz")
                    return document
                except (subprocess.SubprocessError, OSError, ValueError) as exc:
                    last_error = exc
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    document = json.loads(response.read().decode("utf-8"))
                    if not isinstance(document, Mapping):
                        raise ValueError("respuesta JSON sin objeto raíz")
                    return document
            except HTTPError as exc:
                last_error = exc
                if exc.code not in RETRYABLE_STATUS or attempt >= self.retries:
                    break
            except (URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
            time.sleep(min(4.0, 0.75 * (2 ** (attempt - 1))))
        raise RuntimeError(f"SofaScore {label} no disponible: {last_error}")

    def get_match_snapshot(self, row: Mapping[str, Any]) -> dict[str, Any]:
        event_id = int(row["event_id"])
        document = self._fetch_json(
            BASE_URL.format(event_id=event_id),
            label=f"event_id={event_id}",
        )
        snapshot = snapshot_from_document(event_id, document, row)
        if snapshot.get("state") == "finished":
            for template in STATISTICS_URLS:
                try:
                    statistics = self._fetch_json(
                        template.format(event_id=event_id),
                        label=f"estadísticas event_id={event_id}",
                    )
                    actuals = final_actuals_from_statistics_document(
                        event_id, statistics
                    )
                    if actuals is not None:
                        snapshot["final_actuals"] = actuals
                        break
                    self.logger(
                        f"SofaScore estadísticas vacías event_id={event_id} "
                        f"host={template.split('/')[2]}"
                    )
                except Exception as exc:
                    # The score remains useful while the statistics-debt
                    # scheduler retries the exact event on subsequent runs.
                    self.logger(
                        f"SofaScore estadísticas pendientes event_id={event_id} "
                        f"host={template.split('/')[2]}: {exc}"
                    )
        return snapshot
