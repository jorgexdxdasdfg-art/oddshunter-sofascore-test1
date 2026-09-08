"""Small read-only audit of detailed markets for visible, persisted fixtures."""
from __future__ import annotations

import json
import os
from pathlib import Path

from five_dollar_odds_sync import Client, _load_env, _strict_bet365
from odds_value_engine import provider_prices
from urllib.request import urlopen


def main() -> None:
    root = Path(__file__).resolve().parent
    _load_env(root)
    client = Client(os.environ["FIVE_DOLLAR_FOOTBALL_API_KEY"])
    with urlopen("https://oddshunter-mobile.vercel.app/api/day?offset=0&limit=1000", timeout=45) as response:
        events = json.load(response)
    # Select at most three actual app fixtures with saved provider identities.
    # Prefer events without goal prices, the issue this probe investigates.
    targets = []
    for event in events:
        path = root / "data" / "analisis" / event["competition_key"] / str(event["event_id"]) / "odds_value.json"
        if not path.is_file():
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("provider_fixture_id"):
            has_goals = any(str(row.get("key", "")).startswith("goals_") for row in value.get("available_prices", []))
            targets.append((has_goals, event, value))
    targets.sort(key=lambda row: (row[0], -int(row[1]["event_id"])))
    for _, event, saved in targets[:3]:
        provider_id = int(saved["provider_fixture_id"])
        payload = client.get(f"/fixtures/{provider_id}/odds", bookmakers="bet365")
        book = _strict_bet365((payload.get("data") or {}).get("bookmakers"))
        markets = book.get("odds") or {}
        print("REAL_MARKET_AUDIT=" + json.dumps({
            "event_id": event["event_id"], "provider_fixture_id": provider_id,
            "match": f"{event['home_team']} vs {event['away_team']}",
            "markets": markets,
            "exact_price_keys": [row["key"] for row in provider_prices(markets)],
        }, ensure_ascii=False, separators=(",", ":")), flush=True)
    print(f"MARKET_AUDIT_REQUESTS={client.request_count}")


if __name__ == "__main__":
    main()
