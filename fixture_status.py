from __future__ import annotations

"""One status contract shared by fixture ingestion and live publication."""

import re
from typing import Any


def status_token(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("type") or value.get("name_short") or value.get("name") or value.get("description")
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").strip().upper()).strip("_")


LIVE_STATUS_TOKENS = {
    "1H", "1ST_HALF", "FIRST_HALF", "HT", "HALF_TIME", "HALFTIME",
    "2H", "2ND_HALF", "SECOND_HALF", "ET", "EXTRA_TIME", "BT", "BREAK_TIME",
    "P", "PENALTIES", "LIVE", "IN_PLAY", "INPLAY", "IN_PROGRESS", "INPROGRESS",
    "STARTED", "PAUSED",
}
FINAL_STATUS_TOKENS = {
    "FT", "AET", "PEN", "FINISHED", "FINAL", "ENDED", "COMPLETED",
}
SPECIAL_STATUS_TOKENS = {
    "CANCELED", "CANCELLED", "POSTPONED", "ABANDONED", "SUSPENDED",
    "INTERRUPTED", "WALKOVER", "WO",
}
SCHEDULED_STATUS_TOKENS = {"NS", "SCHEDULED", "NOT_STARTED", "NOTSTARTED"}


def is_fixture_live(status: Any) -> bool:
    return status_token(status) in LIVE_STATUS_TOKENS


def fixture_state(status: Any) -> str:
    token = status_token(status)
    if token in LIVE_STATUS_TOKENS:
        return "live"
    if token in FINAL_STATUS_TOKENS:
        return "finished"
    if token in SPECIAL_STATUS_TOKENS:
        return "terminal"
    if token in SCHEDULED_STATUS_TOKENS:
        return "scheduled"
    return "unknown"
