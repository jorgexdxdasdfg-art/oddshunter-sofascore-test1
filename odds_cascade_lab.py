"""OddsHunter odds provider cascade — isolated core, no network/database writes.

A source yields RAW priced selections attached to an exact fixture identity.
The collector accepts a market only when opposite outcomes are both explicit,
from the same bookmaker, source and line. Do not derive quotes from P_modelo.
Production requires explicit proof of commercial rights for every source.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
import math
import re
import unicodedata

REQUIRED = ("goals", "corners", "cards", "btts")
SIDES = {
    "goals": frozenset(("over", "under")),
    "corners": frozenset(("over", "under")),
    "cards": frozenset(("over", "under")),
    "btts": frozenset(("yes", "no")),
}


def norm_name(value: str) -> str:
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", s))


@dataclass(frozen=True)
class Fixture:
    id: str
    home: str
    away: str
    kickoff: datetime


@dataclass(frozen=True)
class Quote:
    fixture_id: str
    home: str
    away: str
    kickoff: datetime
    market: str
    selection: str
    line: float | None
    odds: float
    bookmaker: str
    source: str
    captured_at: datetime
    source_url: str


@dataclass(frozen=True)
class Provider:
    name: str
    fetch: Callable[[Fixture], list[Quote]]
    commercial_rights_verified: bool = False


def aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timezone needed")
    return value.astimezone(timezone.utc)


def good_pair(fixture: Fixture, quotes: list[Quote], now: datetime,
              max_age: timedelta = timedelta(minutes=90)) -> dict | None:
    """Validate one complete market/line/bookmaker quote without price synthesis."""
    now = aware(now)
    if not quotes:
        return None
    first = quotes[0]
    market = first.market
    if market not in SIDES:
        return None
    try:
        kickoff = aware(fixture.kickoff)
    except ValueError:
        return None
    if kickoff <= now or abs((kickoff - aware(first.kickoff)).total_seconds()) > 300:
        return None
    if norm_name(first.home) != norm_name(fixture.home) or norm_name(first.away) != norm_name(fixture.away):
        return None
    if first.fixture_id != fixture.id:
        return None
    selections: dict[str, Quote] = {}
    for q in quotes:
        if q.market != market or q.fixture_id != fixture.id or q.source != first.source:
            return None
        if q.bookmaker != first.bookmaker or q.line != first.line:
            return None
        if norm_name(q.home) != norm_name(fixture.home) or norm_name(q.away) != norm_name(fixture.away):
            return None
        try:
            if abs((aware(q.kickoff) - kickoff).total_seconds()) > 300:
                return None
            age = now - aware(q.captured_at)
        except ValueError:
            return None
        if age < timedelta(seconds=-60) or age > max_age:
            return None
        if not q.source_url.startswith("https://"):
            return None
        if type(q.odds) not in (float, int) or not math.isfinite(q.odds) or not 1.0 < q.odds < 1000:
            return None
        if q.selection not in SIDES[market] or q.selection in selections:
            return None
        selections[q.selection] = q
    if set(selections) != SIDES[market]:
        return None
    if market != "btts":
        if first.line is None or not math.isfinite(first.line) or first.line < 0 or first.line > 50:
            return None
    elif first.line is not None:
        return None
    if max(aware(q.captured_at) for q in quotes) - min(aware(q.captured_at) for q in quotes) > timedelta(minutes=2):
        return None
    return {
        "market": market, "line": first.line,
        "bookmaker": first.bookmaker, "source": first.source,
        "captured_at": max(aware(q.captured_at) for q in quotes).isoformat(),
        "source_url": first.source_url,
        "prices": {side: selections[side].odds for side in sorted(SIDES[market])},
        "price_origin": "EXACT_SOURCE_QUOTE",
    }


def collect_chain(fixture: Fixture, providers: list[Provider], *,
                  now: datetime, commercial: bool = False) -> dict:
    """Market-specific first valid provider; no interpolated or simulated quotes.

    Once a source is called for this fixture, its raw response is reused for
    all still-missing markets (one fetch, not 4). Zero network actions here.
    """
    resolved = {}
    diagnostics = {}
    for provider in providers:
        if commercial and not provider.commercial_rights_verified:
            diagnostics[provider.name] = "LICENSE_NOT_VERIFIED"
            continue
        if len(resolved) == len(REQUIRED):
            break
        try:
            rows = provider.fetch(fixture)
            if not isinstance(rows, list):
                raise TypeError("source must return list")
        except Exception as exc:
            diagnostics[provider.name] = "ERROR_" + type(exc).__name__
            continue
        added = []
        for market in REQUIRED:
            if market in resolved:
                continue
            groups = {}
            for q in rows:
                if not isinstance(q, Quote) or q.market != market or q.source != provider.name:
                    continue
                groups.setdefault((q.bookmaker, q.line), []).append(q)
            for group in groups.values():
                pair = good_pair(fixture, group, now)
                if pair:
                    resolved[market] = pair
                    added.append(market)
                    break
        diagnostics[provider.name] = {"added": added, "returned": len(rows)}
    missing = [x for x in REQUIRED if x not in resolved]
    return {
        "fixture_id": fixture.id, "status": "PASS_4_OF_4" if not missing else "FAIL_PARTIAL",
        "can_publish": not missing and commercial,
        "markets": resolved, "missing": missing, "providers_checked": diagnostics,
    }
