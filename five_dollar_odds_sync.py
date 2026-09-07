from __future__ import annotations

"""Sincroniza una sola copia cacheada de cuotas para PC y Mobile."""

import argparse
import json
import os
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from odds_value_engine import model_probabilities, provider_prices, rank_value_picks

ROOT = Path(__file__).resolve().parent
API_BASE = "https://api.5dollarfootballapi.com/v1"
EXCLUDED_COMPETITIONS = {"copa-colombia", "leagues-cup"}


class ProviderDeferred(RuntimeError):
    """Temporary provider saturation; existing cached picks stay valid."""


def _load_env(root: Path) -> None:
    path = root / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        name, value = raw.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


class Client:
    def __init__(self, key: str, min_interval: float = 6.1) -> None:
        self.key, self.min_interval, self.last_request = key, min_interval, 0.0

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        url = f"{API_BASE}{path}"
        query = urlencode({key: value for key, value in params.items() if value is not None})
        request = Request(url + (f"?{query}" if query else ""), headers={"Authorization": f"Bearer {self.key}", "User-Agent": "OddsHunter/1.0"})
        payload: dict[str, Any] | None = None
        for attempt in range(3):
            wait = self.min_interval - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            self.last_request = time.monotonic()
            try:
                with urlopen(request, timeout=30) as response:
                    payload = json.load(response)
                break
            except HTTPError as exc:
                if exc.code == 429:
                    retry_after = float(exc.headers.get("Retry-After") or 15)
                    if attempt == 2:
                        raise ProviderDeferred(
                            "Proveedor de cuotas temporalmente saturado; se conserva el caché anterior"
                        ) from exc
                    time.sleep(max(retry_after, 15 * (attempt + 1)))
                    continue
                if exc.code not in {500, 502, 503, 504} or attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
            except (TimeoutError, URLError):
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
        if payload is None:
            raise ProviderDeferred("Proveedor de cuotas no disponible; se conserva el caché anterior")
        if not payload.get("success"):
            raise RuntimeError(json.dumps(payload.get("error", payload), ensure_ascii=False))
        return payload


def normalized(value: Any) -> str:
    plain = unicodedata.normalize("NFKD", str(value or ""))
    result = "".join(char for char in plain if not unicodedata.combining(char)).casefold()
    for token in (" fc", " cf", " sc", " afc", "club", "deportivo", "futbol"):
        result = result.replace(token, " ")
    return " ".join("".join(char if char.isalnum() else " " for char in result).split())


def _datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _team_score(left: Any, right: Any) -> float:
    a, b = normalized(left), normalized(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return max(SequenceMatcher(None, a, b).ratio(), SequenceMatcher(None, "".join(sorted(a.split())), "".join(sorted(b.split()))).ratio())


def match_fixture(event: dict[str, Any], fixtures: list[dict[str, Any]]) -> dict[str, Any] | None:
    kickoff = _datetime(event.get("kickoff"))
    candidates: list[tuple[float, dict[str, Any]]] = []
    for fixture in fixtures:
        provider_kickoff = _datetime(fixture.get("kickoff_utc"))
        if kickoff and provider_kickoff and abs((kickoff - provider_kickoff).total_seconds()) > 6 * 3600:
            continue
        teams = fixture.get("teams") or {}
        score = (_team_score(event.get("home_team"), (teams.get("home") or {}).get("name")) + _team_score(event.get("away_team"), (teams.get("away") or {}).get("name"))) / 2
        if score >= 0.72:
            candidates.append((score, fixture))
    return max(candidates, key=lambda row: row[0])[1] if candidates else None


def fetch_fixtures(client: Client, start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = start
    while cursor < end:
        stop = min(end, cursor + timedelta(hours=23, minutes=59))
        page = 1
        while True:
            payload = client.get("/fixtures", start_time=int(cursor.timestamp()), end_time=int(stop.timestamp()), page=page, per_page=100)
            rows.extend(row for row in payload.get("data", []) if isinstance(row, dict))
            if not (payload.get("pagination") or {}).get("has_more"):
                break
            page += 1
        cursor = stop + timedelta(seconds=1)
    return rows


def _bundle(folder: Path) -> dict[str, Any]:
    analysis = json.loads((folder / "analysis.json").read_text(encoding="utf-8-sig"))
    for name in ("goals", "corners", "cards"):
        path = folder / f"{name}.json"
        if path.is_file():
            analysis[name] = json.loads(path.read_text(encoding="utf-8-sig"))
    return analysis


def sync(
    root: Path,
    *,
    start: datetime,
    days: int,
    max_age_minutes: int = 45,
    event_ids: set[int] | None = None,
) -> dict[str, Any]:
    _load_env(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    key = os.environ.get("FIVE_DOLLAR_FOOTBALL_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Falta FIVE_DOLLAR_FOOTBALL_API_KEY")
    client = Client(key)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    counts = {"events": 0, "matched": 0, "updated": 0, "cached": 0, "unmatched": 0}
    pending: list[tuple[Path, str, int, dict[str, Any], dict[str, Any]]] = []
    for path in sorted((root / "data" / "analisis").glob("*/*/analysis.json")):
        competition_key, event_id = path.parent.parent.name, path.parent.name
        if competition_key in EXCLUDED_COMPETITIONS:
            continue
        if event_ids and int(event_id) not in event_ids:
            continue
        bundle = _bundle(path.parent)
        event = bundle.get("upcoming_match") or {}
        kickoff = _datetime(event.get("kickoff"))
        if not kickoff or not start <= kickoff < start + timedelta(days=days):
            continue
        counts["events"] += 1
        target = path.parent / "odds_value.json"
        if target.is_file() and datetime.fromtimestamp(target.stat().st_mtime, timezone.utc) >= cutoff:
            counts["cached"] += 1
            continue
        pending.append((path, competition_key, int(event_id), bundle, event))

    # Do not spend even one provider request when every eligible event already
    # has a fresh cache. The 24x7 runtime is the single owner of these calls.
    if not pending:
        return {"ok": True, "counts": counts, "provider_fixtures": 0, "provider_request": "SKIPPED_FRESH_CACHE"}
    try:
        fixtures = fetch_fixtures(client, start, start + timedelta(days=days))
    except ProviderDeferred as exc:
        return {
            "ok": True,
            "counts": counts,
            "provider_fixtures": 0,
            "provider_request": "DEFERRED_RATE_LIMIT",
            "message": str(exc),
        }

    for path, competition_key, event_id, bundle, event in pending:
        fixture = match_fixture(event, fixtures)
        if not fixture:
            counts["unmatched"] += 1
            continue
        counts["matched"] += 1
        try:
            odds_payload = client.get(f"/fixtures/{int(fixture['id'])}/odds")
        except ProviderDeferred as exc:
            # Keep the last good document. A later cloud cycle will retry.
            return {
                "ok": True,
                "counts": counts,
                "provider_fixtures": len(fixtures),
                "provider_request": "DEFERRED_RATE_LIMIT",
                "message": str(exc),
            }
        bookmakers = (odds_payload.get("data") or {}).get("bookmakers") or []
        bookmaker = next((row for row in bookmakers if str(row.get("slug", "")).casefold() == "bet365"), bookmakers[0] if bookmakers else {})
        context: dict[str, Any] = {}
        try:
            from global_match_context import build_global_context

            context = build_global_context(
                root,
                competition_key,
                int(event_id),
                bundle=bundle,
                match_hint=event,
            )
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            # El resto de mercados sigue siendo válido aunque el historial de
            # primera mitad todavía no exista para un evento nuevo.
            context = {}
        probabilities = model_probabilities(bundle, context)
        prices = provider_prices(bookmaker.get("odds") or {})
        document = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "event_id": int(event_id),
            "competition_key": competition_key,
            "provider": "5DollarFootballAPI",
            "bookmaker": bookmaker.get("name") or "Bet365",
            "provider_fixture_id": int(fixture["id"]),
            "probabilities": probabilities,
            "available_prices": prices,
            "top_picks": rank_value_picks(probabilities, prices, 4),
            "policy": "EV solo con cuota real de la misma linea; Kelly 1/4 limitado a 5% del bank.",
        }
        target.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        counts["updated"] += 1
    return {"ok": True, "counts": counts, "provider_fixtures": len(fixtures)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--start")
    parser.add_argument("--max-age-minutes", type=int, default=45)
    parser.add_argument("--event-id", type=int, action="append", default=[])
    args = parser.parse_args()
    start = _datetime(args.start) if args.start else datetime.now(timezone.utc) - timedelta(hours=6)
    print(json.dumps(sync(args.root.resolve(), start=start, days=max(1, args.days), max_age_minutes=max(1, args.max_age_minutes), event_ids=set(args.event_id) or None), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
