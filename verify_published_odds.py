from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import cloud_stage6_publish as stage6
import five_dollar_odds_sync as syncmod

ROOT = Path("/opt/oddshunter/current")
CATEGORIES = ("result", "double", "goals", "btts", "first_half", "cards", "corners", "other")


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def category(key: object) -> str:
    value = str(key or "")
    for prefix, name in (
        ("result_", "result"), ("double_", "double"), ("goals_", "goals"),
        ("btts_", "btts"), ("first_half_", "first_half"), ("cards_", "cards"),
        ("corners_", "corners"),
    ):
        if value.startswith(prefix):
            return name
    return "other"


def valid_pick(row: dict) -> bool:
    odds = number(row.get("odds"))
    ev = number(row.get("ev"))
    return odds is not None and odds > 1 and ev is not None


def real_price(row: dict) -> bool:
    odds = number(row.get("current_odds", row.get("source_odds", row.get("odds"))))
    return odds is not None and odds > 1


def main() -> int:
    now = datetime.now(timezone.utc)
    today_start, tomorrow_start, end = syncmod._day_bounds(now)
    targets = syncmod._target_events(ROOT, today_start, end)

    client = stage6.TursoClient(
        os.environ.get("TURSO_DATABASE_URL", ""),
        os.environ.get("TURSO_AUTH_TOKEN", ""),
        timeout=30,
    )
    if not client.health():
        raise RuntimeError("Turso no respondió saludable")

    remote = {}
    for row in client.query(
        "SELECT competition_key,event_id,json_text FROM mobile_analysis_docs WHERE doc_name='odds_value'", []
    ):
        try:
            key = str(row.get("competition_key") or "")
            event_id = int(row.get("event_id"))
            doc = json.loads(str(row.get("json_text") or "{}"))
        except Exception:
            continue
        if key and isinstance(doc, dict):
            remote[(key, event_id)] = doc

    summary = {
        "target_events": len(targets),
        "today": {"events": 0, "docs": 0, "any_ev": 0, "detailed_ev": 0},
        "tomorrow": {"events": 0, "docs": 0, "any_ev": 0, "detailed_ev": 0},
        "remote_docs": 0,
        "fixtures_any_real_price": 0,
        "fixtures_non_1x2_real_price": 0,
        "fixtures_any_odds_ev": 0,
        "fixtures_detailed_odds_ev": 0,
        "priced_pick_rows": 0,
        "ev_pick_rows": 0,
        "real_price_rows": 0,
        "real_non_1x2_price_rows": 0,
        "ev_rows_by_category": {name: 0 for name in CATEGORIES},
        "fixtures_by_category": {name: 0 for name in CATEGORIES},
        "odds_status": {},
    }
    missing_docs = []
    without_any_ev = []
    without_detailed_ev = []
    samples = []

    for event in targets:
        key = str(event.get("competition_key") or "")
        event_id = int(event.get("event_id"))
        kickoff = syncmod._datetime(event.get("kickoff"))
        day = "today" if kickoff and kickoff < tomorrow_start else "tomorrow"
        summary[day]["events"] += 1
        label = f"{event.get('home_team')} vs {event.get('away_team')}"
        doc = remote.get((key, event_id))
        if not doc:
            missing_docs.append({"key": key, "event_id": event_id, "match": label})
            continue

        summary["remote_docs"] += 1
        summary[day]["docs"] += 1
        status = str(doc.get("odds_status") or "UNKNOWN")
        summary["odds_status"][status] = summary["odds_status"].get(status, 0) + 1

        prices = [row for row in (doc.get("available_prices") or []) if isinstance(row, dict) and real_price(row)]
        picks = [row for row in (doc.get("all_picks") or []) if isinstance(row, dict)]
        valid = [row for row in picks if valid_pick(row)]
        detailed_valid = [row for row in valid if category(row.get("key")) != "result"]
        detailed_prices = [row for row in prices if category(row.get("key")) != "result"]

        summary["real_price_rows"] += len(prices)
        summary["real_non_1x2_price_rows"] += len(detailed_prices)
        summary["priced_pick_rows"] += sum(1 for row in picks if (number(row.get("odds")) or 0) > 1)
        summary["ev_pick_rows"] += len(valid)
        summary["fixtures_any_real_price"] += bool(prices)
        summary["fixtures_non_1x2_real_price"] += bool(detailed_prices)

        if valid:
            summary["fixtures_any_odds_ev"] += 1
            summary[day]["any_ev"] += 1
        else:
            without_any_ev.append({"key": key, "event_id": event_id, "match": label, "status": status})
        if detailed_valid:
            summary["fixtures_detailed_odds_ev"] += 1
            summary[day]["detailed_ev"] += 1
        else:
            without_detailed_ev.append({"key": key, "event_id": event_id, "match": label, "status": status})

        seen = set()
        for row in valid:
            name = category(row.get("key"))
            summary["ev_rows_by_category"][name] += 1
            seen.add(name)
        for name in seen:
            summary["fixtures_by_category"][name] += 1

        if len(samples) < 8 and detailed_valid:
            samples.append({
                "key": key,
                "event_id": event_id,
                "match": label,
                "status": status,
                "real_price_keys": [str(row.get("key")) for row in prices[:20]],
                "ev_keys": [str(row.get("key")) for row in valid[:30]],
                "top_picks": [
                    {"key": row.get("key"), "odds": row.get("odds"), "ev": row.get("ev"), "price_origin": row.get("price_origin")}
                    for row in (doc.get("top_picks") or [])[:4] if isinstance(row, dict)
                ],
            })

    total = max(1, len(targets))
    summary["missing_remote_docs"] = len(missing_docs)
    summary["without_any_odds_ev"] = len(without_any_ev)
    summary["without_detailed_odds_ev"] = len(without_detailed_ev)
    summary["coverage_any_odds_ev_pct"] = round(100 * summary["fixtures_any_odds_ev"] / total, 2)
    summary["coverage_detailed_odds_ev_pct"] = round(100 * summary["fixtures_detailed_odds_ev"] / total, 2)

    print("VERIFY_ODDS_SUMMARY=" + json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    print("VERIFY_MISSING_DOCS=" + json.dumps(missing_docs, ensure_ascii=False, separators=(",", ":")))
    print("VERIFY_WITHOUT_ANY_EV=" + json.dumps(without_any_ev, ensure_ascii=False, separators=(",", ":")))
    print("VERIFY_WITHOUT_DETAILED_EV=" + json.dumps(without_detailed_ev, ensure_ascii=False, separators=(",", ":")))
    print("VERIFY_SAMPLES=" + json.dumps(samples, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
