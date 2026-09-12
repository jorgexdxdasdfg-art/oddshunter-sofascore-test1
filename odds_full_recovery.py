from __future__ import annotations

"""Emergency/full recovery for every OddsHunter odds field for Today+Tomorrow.

Uses the existing OddsHunter model and pricing engine unchanged. It performs one
controlled Bet365 detailed-odds read per deterministically resolved fixture,
then rebuilds every visual row (1X2, double chance, goals, BTTS, first half,
cards and corners) from real Bet365 quotes/anchors. No synthetic Bet365 quote is
ever created without a real Bet365 anchor.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import five_dollar_odds_sync as syncmod
from odds_value_engine import (
    attach_asian_source_values,
    build_all_picks,
    immutable_all_picks,
    immutable_top_picks,
    market_anchored_prices,
    model_probabilities,
    provider_prices,
    rank_value_picks,
)

ROOT = Path(__file__).resolve().parent


def _same_pair_fallback(event: dict[str, Any], fixtures: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str, float, str]:
    """Resolve only a unique same-team fixture when catalog kickoff drift exists.

    Mobile schedule seeds occasionally carry a placeholder kickoff while the
    provider has the correct prematch kickoff. We permit a wider time window
    only when both home/away identities are strong and the pair is unique.
    """

    event_kickoff = syncmod._datetime(event.get("kickoff"))
    candidates: list[tuple[float, float, dict[str, Any]]] = []
    for fixture in fixtures:
        score, home_score, away_score, delta = syncmod._fixture_identity(event, fixture)
        if delta is None or delta > 18 * 3600:
            continue
        teams = fixture.get("teams") or {}
        provider_home = (teams.get("home") or {}).get("name")
        provider_away = (teams.get("away") or {}).get("name")
        exact_pair = (
            syncmod.normalized(event.get("home_team")) == syncmod.normalized(provider_home)
            and syncmod.normalized(event.get("away_team")) == syncmod.normalized(provider_away)
        )
        alias_pair = (
            syncmod._canonical_team(event.get("home_team")) == syncmod._canonical_team(provider_home)
            and syncmod._canonical_team(event.get("away_team")) == syncmod._canonical_team(provider_away)
        )
        if exact_pair or alias_pair or (score >= 0.82 and min(home_score, away_score) >= 0.72):
            provider_kickoff = syncmod._datetime(fixture.get("kickoff_utc"))
            # Keep the provider fixture within the same Ecuador Today/Tomorrow
            # window; never cross to an unrelated day just to obtain a price.
            if event_kickoff and provider_kickoff:
                event_day = event_kickoff.astimezone(syncmod.ECUADOR_TZ).date()
                provider_day = provider_kickoff.astimezone(syncmod.ECUADOR_TZ).date()
                if abs((provider_day - event_day).days) > 1:
                    continue
            candidates.append((score, float(delta), fixture))

    # Deduplicate by provider fixture id and demand one clearly best pair.
    unique: dict[int, tuple[float, float, dict[str, Any]]] = {}
    for row in candidates:
        fixture_id = int(row[2].get("id") or 0)
        if fixture_id and (fixture_id not in unique or row[0] > unique[fixture_id][0]):
            unique[fixture_id] = row
    ranked = sorted(unique.values(), key=lambda row: (-row[0], row[1]))
    if not ranked:
        return None, "PROVIDER_NOT_FOUND", 0.0, "no unique same-team provider fixture"
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08:
        return None, "AMBIGUOUS", ranked[0][0], "multiple same-team candidates"
    score, _, fixture = ranked[0]
    return fixture, "RESOLVED_TEAM_PAIR", score, "unique home/away pair with schedule kickoff drift"


def _has_detail(prices: list[dict[str, Any]], market_prefix: str) -> bool:
    return any(str(row.get("key") or "").startswith(market_prefix) for row in prices)


def main() -> int:
    root = ROOT.resolve()
    syncmod._load_env(root)
    key = os.environ.get("FIVE_DOLLAR_FOOTBALL_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Falta FIVE_DOLLAR_FOOTBALL_API_KEY")

    client = syncmod.Client(key)
    now = datetime.now(timezone.utc)
    today_start, tomorrow_start, end = syncmod._day_bounds(now)
    targets = syncmod._target_events(root, today_start, end)
    catalog_bundles = syncmod._schedule_documents(root)

    today_fixtures = syncmod.fetch_fixtures(client, today_start, tomorrow_start, include_odds=True)
    tomorrow_fixtures = syncmod.fetch_fixtures(client, tomorrow_start, end, include_odds=True)
    fixtures = today_fixtures + tomorrow_fixtures

    db_path = root / "data" / "oddshunter.db"
    connection = sqlite3.connect(db_path, timeout=45) if db_path.is_file() else None
    if connection is not None:
        connection.execute("PRAGMA busy_timeout=45000")
        syncmod._ensure_odds_tables(connection)

    saved_mappings: dict[tuple[str, int], int] = {}
    if connection is not None:
        saved_mappings = {
            (str(row[0]), int(row[1])): int(row[2])
            for row in connection.execute(
                "SELECT competition_key,event_id,provider_fixture_id FROM bet365_fixture_odds_sync WHERE provider_fixture_id IS NOT NULL"
            )
        }

    counts = {
        "targets": len(targets),
        "resolved": 0,
        "resolved_team_pair": 0,
        "unresolved": 0,
        "detailed_requests": 0,
        "detailed_with_prices": 0,
        "available": 0,
        "published_docs": 0,
        "goals_priced": 0,
        "btts_priced": 0,
        "corners_priced": 0,
        "cards_priced": 0,
        "first_half_priced": 0,
        "result_priced": 0,
        "errors": 0,
    }
    unresolved: list[dict[str, Any]] = []

    for event in targets:
        competition_key = str(event["competition_key"])
        event_id = int(event["event_id"])
        folder = root / "data" / "analisis" / competition_key / str(event_id)
        bundle = {
            **catalog_bundles.get((competition_key, event_id), {}),
            **syncmod._bundle(folder),
        }
        target_path = folder / "odds_value.json"
        existing = syncmod._read_existing(target_path)
        checked_at = datetime.now(timezone.utc).isoformat()

        fixture, resolution, score, reason = syncmod.resolve_fixture(
            event,
            fixtures,
            saved_fixture_id=saved_mappings.get((competition_key, event_id)),
        )
        if fixture is None:
            fixture, resolution, score, reason = _same_pair_fallback(event, fixtures)
            if fixture is not None:
                counts["resolved_team_pair"] += 1

        if fixture is None:
            counts["unresolved"] += 1
            unresolved.append({
                "event_id": event_id,
                "competition_key": competition_key,
                "home": event.get("home_team"),
                "away": event.get("away_team"),
                "kickoff": event.get("kickoff"),
                "classification": resolution,
                "score": round(score, 4),
                "reason": reason,
            })
            # Preserve any previously valid quote. Never replace it with blanks.
            if existing.get("available_prices"):
                context: dict[str, Any] = {}
                try:
                    from global_match_context import build_global_context
                    context = build_global_context(root, competition_key, event_id, bundle=bundle, match_hint=event)
                except (ImportError, OSError, RuntimeError, TypeError, ValueError):
                    context = {}
                context = {**context, "event": event}
                probabilities = model_probabilities(bundle, context) if bundle else (existing.get("probabilities") or {})
                real_prices = attach_asian_source_values(bundle, list(existing.get("available_prices") or []))
                display_prices = market_anchored_prices(
                    bundle,
                    probabilities,
                    real_prices,
                    context,
                    existing.get("provider_markets") or {},
                )
                all_picks = build_all_picks(probabilities, display_prices)
                ranked = rank_value_picks(probabilities, display_prices, 4, bundle, context)
                top_picks = immutable_top_picks(existing, ranked, checked_at, event)
                doc = {
                    **existing,
                    "generated_at": checked_at,
                    "last_checked_at": checked_at,
                    "odds_status": "AVAILABLE_LAST_KNOWN",
                    "probabilities": probabilities,
                    "all_picks": all_picks,
                    "all_picks_snapshot": immutable_all_picks(existing, all_picks, checked_at, event),
                    "top_picks": top_picks,
                    "top_picks_snapshot": top_picks,
                }
                syncmod._atomic_json(target_path, doc)
                counts["published_docs"] += 1
            continue

        counts["resolved"] += 1
        provider_fixture_id = int(fixture["id"])
        bookmaker = syncmod._embedded_bet365(fixture)

        try:
            counts["detailed_requests"] += 1
            payload = client.get(f"/fixtures/{provider_fixture_id}/odds", bookmakers=syncmod.BET365_SLUG)
            detailed = syncmod._strict_bet365((payload.get("data") or {}).get("bookmakers"))
            if detailed:
                bookmaker = detailed
        except syncmod.ProviderDeferred:
            counts["errors"] += 1
        except Exception:
            counts["errors"] += 1

        markets = bookmaker.get("odds") if isinstance(bookmaker, dict) else {}
        markets = markets if isinstance(markets, dict) else {}
        opening_prices = provider_prices(markets, snapshot_order=("opening", "closing"))
        current_prices = provider_prices(markets, snapshot_order=("closing", "opening"))
        syncmod._reuse_cached_extended(existing, opening_prices, current_prices)
        opening_prices = attach_asian_source_values(bundle, opening_prices)
        current_prices = attach_asian_source_values(bundle, current_prices)

        if not current_prices:
            counts["unresolved"] += 1
            unresolved.append({
                "event_id": event_id,
                "competition_key": competition_key,
                "home": event.get("home_team"),
                "away": event.get("away_team"),
                "kickoff": event.get("kickoff"),
                "classification": "NO_BET365_PRICES",
                "score": round(score, 4),
                "reason": "detailed Bet365 endpoint returned no usable price",
            })
            continue

        counts["detailed_with_prices"] += 1
        available, history, _ = syncmod._merge_prices(existing, opening_prices, current_prices, checked_at)

        context: dict[str, Any] = {}
        try:
            from global_match_context import build_global_context
            context = build_global_context(root, competition_key, event_id, bundle=bundle, match_hint=event)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            context = {}
        context = {**context, "event": event}

        probabilities = model_probabilities(bundle, context)
        provider_markets = {**(existing.get("provider_markets") or {}), **markets}
        display_prices = market_anchored_prices(bundle, probabilities, available, context, provider_markets)
        all_picks = build_all_picks(probabilities, display_prices)
        ranked = rank_value_picks(probabilities, display_prices, 4, bundle, context)
        top_picks = immutable_top_picks(existing, ranked, checked_at, event)
        all_snapshot = immutable_all_picks(existing, all_picks, checked_at, event)

        keys = {str(row.get("key") or "") for row in display_prices}
        counts["result_priced"] += int(any(key.startswith("result_") for key in keys))
        counts["goals_priced"] += int(any(key.startswith("goals_") for key in keys))
        counts["btts_priced"] += int(any(key.startswith("btts_") for key in keys))
        counts["corners_priced"] += int(any(key.startswith("corners_") for key in keys))
        counts["cards_priced"] += int(any(key.startswith("cards_") for key in keys))
        counts["first_half_priced"] += int(any(key.startswith("first_half_") for key in keys))

        document = {
            "schema_version": 2,
            "generated_at": checked_at,
            "event_id": event_id,
            "competition_key": competition_key,
            "provider": "5DollarFootballAPI",
            "bookmaker": "Bet365",
            "provider_fixture_id": provider_fixture_id,
            "odds_status": "AVAILABLE",
            "provider_markets": provider_markets,
            "first_captured_at": min(row["opening"]["captured_at"] for row in history),
            "last_checked_at": checked_at,
            "extended_last_checked_at": checked_at,
            "probabilities": probabilities,
            "available_prices": available,
            "price_history": history,
            "all_picks": all_picks,
            "all_picks_snapshot": all_snapshot,
            "top_picks": top_picks,
            "top_picks_snapshot": top_picks,
            "policy": "Bet365 real; OPENING inmutable; CURRENT=última closing prematch; Kelly 1/4 limitado a 5%.",
        }
        syncmod._atomic_json(target_path, document)
        syncmod._persist_database(connection, event, provider_fixture_id, "AVAILABLE", checked_at, history)
        counts["available"] += 1
        counts["published_docs"] += 1

    if connection is not None:
        connection.close()

    print(json.dumps({
        "ok": counts["errors"] == 0,
        "window": {
            "today": today_start.astimezone(syncmod.ECUADOR_TZ).date().isoformat(),
            "tomorrow": tomorrow_start.astimezone(syncmod.ECUADOR_TZ).date().isoformat(),
        },
        "counts": counts,
        "unresolved": unresolved,
        "provider_requests": client.request_count,
    }, ensure_ascii=False, indent=2))
    return 0 if counts["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
