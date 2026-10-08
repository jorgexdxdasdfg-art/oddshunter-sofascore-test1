#!/usr/bin/env python3
"""Auditoria READ ONLY de cuotas reales 4/4 para OddsHunter.

No escribe en la base de datos ni modifica cuotas, picks, EV o servicios.
Fuente: 5DollarFootballAPI (credencial desde entorno, nunca en CLI).
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError

from five_dollar_odds_sync import Client, _strict_bet365, _snapshot_has_prices, fetch_fixtures

MARKETS = {
    "goals": ("goal_line", ("over", "under")),
    "btts": ("btts", ("yes", "no")),
    "corners": ("corner_line", ("over", "under")),
    "cards": ("card_line", ("over", "under")),
}
TOP_FIVE = ("premier league", "bundesliga", "serie a", "serie a tim", "la liga", "laliga", "ligue 1")
MAX_ODDS_CALLS = 22
MAX_FIXTURE_DAYS = 12


def candidate_days(now: datetime) -> list[datetime]:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    future = [today + timedelta(days=delta) for delta in range(1, 25)]
    # Friday/Saturday/Sunday: football fixture density and fewer API calls.
    weekends = [day for day in future if day.weekday() in (4, 5, 6)]
    return weekends[:MAX_FIXTURE_DAYS]


def valid_quote(market: object, names: tuple[str, str]) -> dict | None:
    if not _snapshot_has_prices(market, names) or not isinstance(market, dict):
        return None
    for snapshot in ("closing", "opening"):
        item = market.get(snapshot)
        if not isinstance(item, dict):
            continue
        try:
            values = [float(item[name]) for name in names]
        except (ValueError, KeyError, TypeError):
            continue
        if not all(1.0 < v < 2000.0 for v in values):
            continue
        result = {"snapshot": snapshot, names[0]: values[0], names[1]: values[1]}
        if "line" in item:
            try:
                line = float(item["line"])
            except (ValueError, TypeError):
                continue
            if line < 0 or line > 50:
                continue
            result["line"] = line
        elif names == ("over", "under"):
            # Nunca registrar un total sin saber la linea que cotiza.
            continue
        return result
    return None


def audit(client: Client, now: datetime) -> dict:
    fixtures, seen = [], set()
    report = {
        "read_only": True,
        "source": "5DollarFootballAPI",
        "bookmaker": "bet365",
        "generated_at": now.isoformat(),
        "markets_found": {market: 0 for market in MARKETS},
        "examples": {},
        "complete_4_of_4_matches": [],
        "fixture_requests": 0,
        "odds_requests": 0,
        "errors": [],
        "coverage_gate": "FAIL",
    }
    for day in candidate_days(now):
        try:
            results = fetch_fixtures(client, day, day + timedelta(days=1), include_odds=False)
        except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            report["errors"].append(f"fixtures {day.date()}: {type(exc).__name__} {getattr(exc, 'code', '')}")
            continue
        for row in results:
            if not isinstance(row, dict):
                continue
            league = str((row.get("league") or {}).get("name") or "").casefold()
            try:
                kickoff = datetime.fromisoformat(str(row.get("kickoff_utc")).replace("Z", "+00:00"))
                fid = int(row["id"])
            except (ValueError, TypeError, KeyError):
                continue
            if not any(name in league for name in TOP_FIVE) or kickoff <= now or fid in seen:
                continue
            seen.add(fid)
            fixtures.append(row)
    report["fixture_requests"] = client.request_count
    fixtures.sort(key=lambda row: str(row.get("kickoff_utc") or ""))

    for fixture in fixtures[:MAX_ODDS_CALLS]:
        fid = int(fixture["id"])
        try:
            payload = client.get(f"/fixtures/{fid}/odds", bookmakers="bet365")
        except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            report["errors"].append(f"odds fixture {fid}: {type(exc).__name__} {getattr(exc, 'code', '')}")
            continue
        report["odds_requests"] += 1
        bookmaker = _strict_bet365((payload.get("data") or {}).get("bookmakers"))
        markets = bookmaker.get("odds") or {}
        found = {}
        for name, (source, fields) in MARKETS.items():
            sample = valid_quote(markets.get(source), fields)
            if sample is not None:
                report["markets_found"][name] += 1
                found[name] = sample
                report["examples"].setdefault(name, {
                    "fixture_id": fid,
                    "match": f"{(fixture.get('teams') or {}).get('home', {}).get('name')} vs {(fixture.get('teams') or {}).get('away', {}).get('name')}",
                    "kickoff_utc": fixture.get("kickoff_utc"),
                    **sample,
                })
        if len(found) == len(MARKETS):
            report["complete_4_of_4_matches"].append({
                "fixture_id": fid, "kickoff_utc": fixture.get("kickoff_utc"),
                "markets": found,
            })
        if len(report["complete_4_of_4_matches"]) >= 2:
            break

    report["fixtures_candidate_count"] = len(fixtures)
    report["market_names"] = list(MARKETS)
    report["coverage_gate"] = (
        "PASS" if all(report["markets_found"].values())
        and len(report["complete_4_of_4_matches"]) >= 2
        else "FAIL"
    )
    return report


def main() -> int:
    key = os.environ.get("FIVE_DOLLAR_FOOTBALL_API_KEY", "").strip()
    if not key:
        print(json.dumps({"coverage_gate": "FAIL", "reason": "NO_API_KEY",
                          "markets": list(MARKETS), "read_only": True}))
        return 2
    try:
        result = audit(Client(key, min_interval=6.1), datetime.now(timezone.utc))
    except Exception as exc:
        print(json.dumps({"coverage_gate": "FAIL", "reason": type(exc).__name__, "read_only": True}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["coverage_gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
