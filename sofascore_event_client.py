from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://www.sofascore.com/api/v1/event/{event_id}"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None

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

    def get_match_snapshot(self, row: Mapping[str, Any]) -> dict[str, Any]:
        event_id = int(row["event_id"])
        url = BASE_URL.format(event_id=event_id)
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
                    return snapshot_from_document(event_id, json.loads(completed.stdout), row)
                except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
                    last_error = exc
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return snapshot_from_document(event_id, json.loads(response.read().decode("utf-8")), row)
            except HTTPError as exc:
                last_error = exc
                if exc.code not in RETRYABLE_STATUS or attempt >= self.retries:
                    break
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
            time.sleep(min(4.0, 0.75 * (2 ** (attempt - 1))))
        raise RuntimeError(f"SofaScore event_id={event_id} no disponible: {last_error}")
