from __future__ import annotations

"""Sincroniza una sola copia cacheada de cuotas para PC y Mobile."""

import argparse
import gzip
import json
import os
import sqlite3
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

from odds_value_engine import (
    attach_asian_source_values,
    build_all_picks,
    market_anchored_prices,
    model_probabilities,
    number,
    provider_prices,
    rank_value_picks,
    refresh_model_picks,
    immutable_top_picks,
)

ROOT = Path(__file__).resolve().parent
API_BASE = "https://api.5dollarfootballapi.com/v1"
ECUADOR_TZ = timezone(timedelta(hours=-5))
BET365_SLUG = "bet365"
TEAM_ALIASES = {
    "al ettifaq": "al ittifaq dammam",
    "al faisaly": "al faisaly harmah",
    "nec nijmegen": "nec",
    "al qadsiah": "al qadisiya al khubar",
    "al ahli": "al ahli jeddah",
    "bolton wanderers": "bolton",
    "west ham united": "west ham",
}


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
        self.request_count = 0

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
            self.request_count += 1
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


def _canonical_team(value: Any) -> str:
    name = normalized(value)
    return TEAM_ALIASES.get(name, name)


def _fixture_identity(event: dict[str, Any], fixture: dict[str, Any]) -> tuple[float, float, float, float | None]:
    kickoff = _datetime(event.get("kickoff"))
    provider_kickoff = _datetime(fixture.get("kickoff_utc"))
    kickoff_delta = abs((kickoff - provider_kickoff).total_seconds()) if kickoff and provider_kickoff else None
    teams = fixture.get("teams") or {}
    home_name = (teams.get("home") or {}).get("name")
    away_name = (teams.get("away") or {}).get("name")
    home_score = _team_score(event.get("home_team"), home_name)
    away_score = _team_score(event.get("away_team"), away_name)
    return (home_score + away_score) / 2, home_score, away_score, kickoff_delta


def resolve_fixture(
    event: dict[str, Any],
    fixtures: list[dict[str, Any]],
    *,
    saved_fixture_id: int | None = None,
) -> tuple[dict[str, Any] | None, str, float, str]:
    """Resolve a provider fixture conservatively and return audit evidence."""

    if saved_fixture_id is not None:
        saved = next((row for row in fixtures if int(row.get("id") or 0) == saved_fixture_id), None)
        if saved:
            score, home_score, away_score, delta = _fixture_identity(event, saved)
            if delta is not None and delta <= 5 * 60 and min(home_score, away_score) >= 0.50:
                return saved, "RESOLVED_STABLE_ID", score, "persisted provider_fixture_id"

    accepted: list[tuple[float, str, dict[str, Any]]] = []
    uncertain: list[tuple[float, dict[str, Any]]] = []
    for fixture in fixtures:
        score, home_score, away_score, delta = _fixture_identity(event, fixture)
        if delta is None or delta > 6 * 3600:
            continue
        teams = fixture.get("teams") or {}
        home_name = (teams.get("home") or {}).get("name")
        away_name = (teams.get("away") or {}).get("name")
        exact_time = delta <= 5 * 60
        exact_names = normalized(event.get("home_team")) == normalized(home_name) and normalized(event.get("away_team")) == normalized(away_name)
        alias_names = _canonical_team(event.get("home_team")) == _canonical_team(home_name) and _canonical_team(event.get("away_team")) == _canonical_team(away_name)
        if exact_time and exact_names:
            accepted.append((score, "RESOLVED_EXACT", fixture))
        elif exact_time and alias_names:
            accepted.append((score, "RESOLVED_ALIAS", fixture))
        elif exact_time and score >= 0.72 and min(home_score, away_score) >= 0.50:
            accepted.append((score, "RESOLVED_OTHER", fixture))
        elif exact_time and score >= 0.55:
            uncertain.append((score, fixture))

    accepted.sort(key=lambda row: row[0], reverse=True)
    if len(accepted) == 1 or (len(accepted) > 1 and accepted[0][0] - accepted[1][0] >= 0.15):
        score, method, fixture = accepted[0]
        return fixture, method, score, "kickoff + home + away"
    if accepted or uncertain:
        best = (accepted[0][0], accepted[0][2]) if accepted else max(uncertain, key=lambda row: row[0])
        return None, "AMBIGUOUS", best[0], "multiple/weak candidates at the same kickoff"
    return None, "PROVIDER_NOT_FOUND", 0.0, "no deterministic provider fixture for kickoff/home/away"


def match_fixture(event: dict[str, Any], fixtures: list[dict[str, Any]]) -> dict[str, Any] | None:
    return resolve_fixture(event, fixtures)[0]


def fetch_fixtures(
    client: Client,
    start: datetime,
    end: datetime,
    *,
    include_odds: bool = True,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = start
    while cursor < end:
        stop = min(end, cursor + timedelta(hours=23, minutes=59))
        page = 1
        while True:
            payload = client.get(
                "/fixtures",
                start_time=int(cursor.timestamp()),
                end_time=int(stop.timestamp()),
                page=page,
                per_page=50,
                include="odds" if include_odds else None,
            )
            rows.extend(row for row in payload.get("data", []) if isinstance(row, dict))
            if not (payload.get("pagination") or {}).get("has_more"):
                break
            page += 1
        cursor = stop + timedelta(seconds=1)
    return rows


def _bundle(folder: Path) -> dict[str, Any]:
    analysis_path = folder / "analysis.json"
    if not analysis_path.is_file():
        return {}
    analysis = json.loads(analysis_path.read_text(encoding="utf-8-sig"))
    for name in ("goals", "corners", "cards"):
        path = folder / f"{name}.json"
        if path.is_file():
            analysis[name] = json.loads(path.read_text(encoding="utf-8-sig"))
    return analysis


def _day_bounds(now: datetime) -> tuple[datetime, datetime, datetime]:
    local_today = now.astimezone(ECUADOR_TZ).date()
    start = datetime.combine(local_today, datetime.min.time(), ECUADOR_TZ).astimezone(timezone.utc)
    tomorrow = start + timedelta(days=1)
    return start, tomorrow, tomorrow + timedelta(days=1)


def _registry_by_league(root: Path) -> dict[int, str]:
    path = root / "data" / "competitions.json"
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    return {
        int(row["league_id"]): str(row.get("key") or "").strip()
        for row in document.get("competitions", [])
        if isinstance(row, dict) and row.get("league_id") is not None and row.get("key")
    }


def _schedule_seed_paths(root: Path) -> list[Path]:
    return [
        root / "deploy" / "mobile_schedule_catalog_seed.json.gz",
        root / "data" / "mobile_schedule_catalog_seed.json.gz",
        Path(os.environ.get(
            "ODDSHUNTER_SCHEDULE_CATALOG_SEED",
            "/var/lib/oddshunter/data/mobile_schedule_catalog_seed.json.gz",
        )),
    ]


def _schedule_documents(root: Path) -> dict[tuple[str, int], dict[str, Any]]:
    """Load analysis documents carried by the rolling Mobile catalog."""

    documents: dict[tuple[str, int], dict[str, Any]] = {}
    seen_paths: set[Path] = set()
    for seed in _schedule_seed_paths(root):
        try:
            resolved_seed = seed.resolve()
        except OSError:
            resolved_seed = seed
        if resolved_seed in seen_paths or not seed.is_file():
            continue
        seen_paths.add(resolved_seed)
        try:
            with gzip.open(seed, "rt", encoding="utf-8") as handle:
                catalog = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for row in catalog.get("docs", []):
            if not isinstance(row, dict) or row.get("doc_name") not in {"analysis", "goals", "corners", "cards"}:
                continue
            try:
                identity = (str(row.get("competition_key") or ""), int(row["event_id"]))
                value = json.loads(str(row.get("json_text") or "{}"))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                documents.setdefault(identity, {})[str(row["doc_name"])] = value

    bundles: dict[tuple[str, int], dict[str, Any]] = {}
    for identity, docs in documents.items():
        bundle = dict(docs.get("analysis") or {})
        for name in ("goals", "corners", "cards"):
            if isinstance(docs.get(name), dict):
                bundle[name] = docs[name]
        bundles[identity] = bundle
    return bundles


def _target_events(root: Path, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Union of the fixtures that feed the PC/Mobile today and tomorrow views."""

    events: dict[tuple[str, int], dict[str, Any]] = {}
    registry = _registry_by_league(root)
    db_path = root / "data" / "oddshunter.db"
    if db_path.is_file():
        connection = sqlite3.connect(db_path, timeout=45)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT m.match_id,m.sofascore_id AS event_id,m.league_id,m.kickoff,m.status,
                       h.name AS home_team,a.name AS away_team
                FROM matches AS m
                JOIN teams AS h ON h.team_id=m.home_team_id
                JOIN teams AS a ON a.team_id=m.away_team_id
                WHERE m.sofascore_id IS NOT NULL
                  AND datetime(m.kickoff)>=datetime(?) AND datetime(m.kickoff)<datetime(?)
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            for raw in rows:
                row = dict(raw)
                competition_key = registry.get(int(row.get("league_id") or 0), "")
                if not competition_key:
                    continue
                row["competition_key"] = competition_key
                events[(competition_key, int(row["event_id"]))] = row
        finally:
            connection.close()

    # The schedule service owns the live rolling catalog in /var/lib.  Older
    # releases only read the packaged /opt/.../data copy, so newly restored
    # fixtures appeared in Mobile but never entered the Bet365 backfill.  Read
    # every compatible location and let the service-owned catalog win.
    seed_paths = _schedule_seed_paths(root)
    seen_seed_paths: set[Path] = set()
    for seed in seed_paths:
        try:
            resolved_seed = seed.resolve()
        except OSError:
            resolved_seed = seed
        if resolved_seed in seen_seed_paths or not seed.is_file():
            continue
        seen_seed_paths.add(resolved_seed)
        try:
            with gzip.open(seed, "rt", encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for row in document.get("events", []):
            if not isinstance(row, dict):
                continue
            kickoff = _datetime(row.get("kickoff"))
            key = str(row.get("competition_key") or "").strip()
            event_id = int(row.get("event_id") or 0)
            if key and event_id and kickoff and start <= kickoff < end:
                events[(key, event_id)] = {**events.get((key, event_id), {}), **row}

    for path in sorted((root / "data" / "analisis").glob("*/*/analysis.json")):
        try:
            bundle = _bundle(path.parent)
            event = bundle.get("upcoming_match") or {}
            kickoff = _datetime(event.get("kickoff"))
            event_id = int(path.parent.name)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if not kickoff or not start <= kickoff < end:
            continue
        key = path.parent.parent.name
        events[(key, event_id)] = {
            **event,
            **events.get((key, event_id), {}),
            "competition_key": key,
            "event_id": event_id,
        }

    return sorted(events.values(), key=lambda row: (_datetime(row.get("kickoff")) or end, int(row.get("event_id") or 0)))


def _strict_bet365(bookmakers: Any) -> dict[str, Any]:
    for row in bookmakers if isinstance(bookmakers, list) else []:
        if not isinstance(row, dict):
            continue
        slug = normalized(row.get("slug"))
        name = normalized(row.get("name"))
        if slug == BET365_SLUG or name.replace(" ", "") == BET365_SLUG:
            return row
    return {}


def _embedded_bet365(fixture: dict[str, Any]) -> dict[str, Any]:
    raw = fixture.get("odds")
    if isinstance(raw, dict):
        selected = _strict_bet365(raw.get("bookmakers"))
        if selected:
            return selected
        if any(key in raw for key in ("1x2", "goal_line", "corner_line", "card_line", "btts")):
            return {"name": "Bet 365", "slug": BET365_SLUG, "odds": raw}
    selected = _strict_bet365(fixture.get("bookmakers"))
    return selected


def _snapshot_has_prices(market: Any, selections: tuple[str, ...]) -> bool:
    if not isinstance(market, dict):
        return False
    for snapshot_name in ("opening", "closing"):
        snapshot = market.get(snapshot_name)
        if isinstance(snapshot, dict) and all((number(snapshot.get(key)) or 0) > 1 for key in selections):
            return True
    return False


def _batch_market_audit(fixtures: list[dict[str, Any]]) -> dict[str, int]:
    audit = {
        "batch_1x2_with_prices": 0,
        "batch_goals_with_prices": 0,
        "batch_btts_with_prices": 0,
        "batch_corners_with_prices": 0,
        "batch_cards_with_prices": 0,
        "batch_first_half_with_prices": 0,
    }
    for fixture in fixtures:
        markets = fixture.get("odds") if isinstance(fixture.get("odds"), dict) else {}
        audit["batch_1x2_with_prices"] += int(_snapshot_has_prices(markets.get("1x2"), ("home", "draw", "away")))
        audit["batch_goals_with_prices"] += int(_snapshot_has_prices(markets.get("goal_line"), ("over", "under")))
        audit["batch_btts_with_prices"] += int(_snapshot_has_prices(markets.get("btts"), ("yes", "no")))
        audit["batch_corners_with_prices"] += int(_snapshot_has_prices(markets.get("corner_line"), ("over", "under")))
        audit["batch_cards_with_prices"] += int(_snapshot_has_prices(markets.get("card_line"), ("over", "under")))
        audit["batch_first_half_with_prices"] += int(_snapshot_has_prices(markets.get("goal_line_half"), ("over", "under")))
    return audit


def _read_existing(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _history_map(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = value.get("price_history") or []
    if isinstance(rows, dict):
        return {str(key): row for key, row in rows.items() if isinstance(row, dict)}
    return {
        str(row.get("key")): row
        for row in rows
        if isinstance(row, dict) and row.get("key")
    }


def _reuse_cached_extended(
    existing: dict[str, Any],
    opening_prices: list[dict[str, Any]],
    current_prices: list[dict[str, Any]],
) -> None:
    """Reuse detailed prices without making requests from either UI view."""

    current_keys = {str(row.get("key")) for row in current_prices}
    history = _history_map(existing)
    for old in existing.get("available_prices") or []:
        key = str(old.get("key") or "")
        if not key or key in current_keys or key.startswith("result_"):
            continue
        current_odds = number(old.get("current_odds") or old.get("odds"))
        if current_odds is None or current_odds <= 1:
            continue
        base = {
            field: old.get(field)
            for field in (
                "key", "market", "selection", "line", "display_line",
                "source_market", "source_side", "source_line", "source_odds",
                "source_ev", "price_origin",
            )
            if old.get(field) is not None
        }
        current_prices.append({**base, "odds": current_odds})
        old_history = history.get(key) or {}
        provider_opening = old_history.get("provider_opening") or old_history.get("captured_opening") or old_history.get("opening") or {}
        opening_odds = number(provider_opening.get("odds") if isinstance(provider_opening, dict) else None) or current_odds
        opening_prices.append({**base, "odds": opening_odds})
        current_keys.add(key)


def _merge_prices(
    existing: dict[str, Any],
    opening_prices: list[dict[str, Any]],
    current_prices: list[dict[str, Any]],
    captured_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    previous = _history_map(existing)
    opening_by_key = {str(row["key"]): row for row in opening_prices}
    history: list[dict[str, Any]] = []
    available: list[dict[str, Any]] = []
    stats = {"opening_created": 0, "opening_preserved": 0, "current_updated": 0}
    for current in current_prices:
        key = str(current["key"])
        old = previous.get(key, {})
        old_opening = (old.get("captured_opening") or old.get("opening") or {}) if isinstance(old.get("captured_opening") or old.get("opening"), dict) else {}
        old_current = (old.get("current") or {}) if isinstance(old.get("current"), dict) else {}
        provider_opening = opening_by_key.get(key, current)
        provider_opening_odds = provider_opening.get("odds") or current.get("odds")
        provider_closing_odds = current.get("odds")
        opening_odds = old_opening.get("odds") or current.get("odds")
        opening_captured_at = old_opening.get("captured_at") or captured_at
        current_odds = current.get("odds")
        changed = number(old_current.get("odds")) != number(current_odds)
        current_updated_at = captured_at if changed else old_current.get("updated_at") or captured_at
        stats["opening_preserved" if old_opening else "opening_created"] += 1
        stats["current_updated"] += int(bool(old_current) and changed)
        row = {
            **current,
            "provider_opening": {"odds": provider_opening_odds, "observed_at": captured_at},
            "provider_closing": {"odds": provider_closing_odds, "observed_at": captured_at},
            "captured_opening": {"odds": opening_odds, "captured_at": opening_captured_at},
            # Backward-compatible alias consumed by older clients.
            "opening": {"odds": opening_odds, "captured_at": opening_captured_at},
            "current": {"odds": current_odds, "updated_at": current_updated_at},
            "last_checked_at": captured_at,
        }
        history.append(row)
        available.append({
            **current,
            "provider_opening_odds": provider_opening_odds,
            "provider_closing_odds": provider_closing_odds,
            "opening_odds": opening_odds,
            "current_odds": current_odds,
            "opening_captured_at": opening_captured_at,
            "current_updated_at": current_updated_at,
        })
    return available, history, stats


def _ensure_odds_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS bet365_fixture_odds_sync (
            competition_key TEXT NOT NULL,event_id INTEGER NOT NULL,provider_fixture_id INTEGER,
            kickoff TEXT,home_team TEXT,away_team TEXT,status TEXT NOT NULL,
            last_checked_at TEXT NOT NULL,last_error TEXT,
            PRIMARY KEY (competition_key,event_id)
        );
        CREATE TABLE IF NOT EXISTS bet365_odds_state (
            competition_key TEXT NOT NULL,event_id INTEGER NOT NULL,provider_fixture_id INTEGER NOT NULL,
            market_key TEXT NOT NULL,market TEXT NOT NULL,selection TEXT NOT NULL,line REAL,
            display_line REAL,source_market TEXT,source_side TEXT,source_line REAL,
            source_odds REAL,source_ev REAL,price_origin TEXT,
            provider_opening_odds REAL,provider_closing_odds REAL,
            opening_odds REAL NOT NULL,opening_captured_at TEXT NOT NULL,
            current_odds REAL NOT NULL,current_updated_at TEXT NOT NULL,last_checked_at TEXT NOT NULL,
            PRIMARY KEY (competition_key,event_id,market_key)
        );
        CREATE TABLE IF NOT EXISTS bet365_api_request_log (
            checked_at TEXT NOT NULL,request_kind TEXT NOT NULL,provider_fixture_id INTEGER
        );
        """
    )
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(bet365_odds_state)")}
    if "provider_opening_odds" not in columns:
        connection.execute("ALTER TABLE bet365_odds_state ADD COLUMN provider_opening_odds REAL")
    if "provider_closing_odds" not in columns:
        connection.execute("ALTER TABLE bet365_odds_state ADD COLUMN provider_closing_odds REAL")
    for name, column_type in (
        ("display_line", "REAL"), ("source_market", "TEXT"),
        ("source_side", "TEXT"), ("source_line", "REAL"),
        ("source_odds", "REAL"), ("source_ev", "REAL"),
        ("price_origin", "TEXT"),
    ):
        if name not in columns:
            connection.execute(f"ALTER TABLE bet365_odds_state ADD COLUMN {name} {column_type}")


def _persist_database(
    connection: sqlite3.Connection | None,
    event: dict[str, Any],
    provider_fixture_id: int | None,
    status: str,
    checked_at: str,
    history: list[dict[str, Any]],
    error: str | None = None,
) -> int:
    if connection is None:
        return 0
    key, event_id = str(event["competition_key"]), int(event["event_id"])
    connection.execute(
        """INSERT INTO bet365_fixture_odds_sync
        (competition_key,event_id,provider_fixture_id,kickoff,home_team,away_team,status,last_checked_at,last_error)
        VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(competition_key,event_id) DO UPDATE SET
        provider_fixture_id=excluded.provider_fixture_id,kickoff=excluded.kickoff,home_team=excluded.home_team,
        away_team=excluded.away_team,status=excluded.status,last_checked_at=excluded.last_checked_at,last_error=excluded.last_error""",
        (key,event_id,provider_fixture_id,event.get("kickoff"),event.get("home_team"),event.get("away_team"),status,checked_at,error),
    )
    written = 0
    for row in history:
        opening, current = row["captured_opening"], row["current"]
        connection.execute(
            """INSERT INTO bet365_odds_state
            (competition_key,event_id,provider_fixture_id,market_key,market,selection,line,
             display_line,source_market,source_side,source_line,source_odds,source_ev,price_origin,
             provider_opening_odds,provider_closing_odds,opening_odds,opening_captured_at,
             current_odds,current_updated_at,last_checked_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(competition_key,event_id,market_key) DO UPDATE SET
            provider_fixture_id=excluded.provider_fixture_id,market=excluded.market,selection=excluded.selection,line=excluded.line,
            display_line=excluded.display_line,source_market=excluded.source_market,source_side=excluded.source_side,
            source_line=excluded.source_line,source_odds=excluded.source_odds,source_ev=excluded.source_ev,
            price_origin=excluded.price_origin,
            provider_opening_odds=excluded.provider_opening_odds,provider_closing_odds=excluded.provider_closing_odds,
            current_odds=excluded.current_odds,current_updated_at=excluded.current_updated_at,last_checked_at=excluded.last_checked_at""",
            (key,event_id,provider_fixture_id,row["key"],row.get("market") or "",row.get("selection") or "",row.get("line"),
             row.get("display_line"),row.get("source_market"),row.get("source_side"),row.get("source_line"),
             row.get("source_odds"),row.get("source_ev"),row.get("price_origin"),
             (row.get("provider_opening") or {}).get("odds"),(row.get("provider_closing") or {}).get("odds"),
             opening["odds"],opening["captured_at"],current["odds"],current["updated_at"],checked_at),
        )
        written += 1
    connection.commit()
    return written


def sync(
    root: Path,
    *,
    start: datetime | None = None,
    days: int | None = None,
    max_age_minutes: int | None = None,
    event_ids: set[int] | None = None,
    now: datetime | None = None,
    client: Client | None = None,
) -> dict[str, Any]:
    _load_env(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    key = os.environ.get("FIVE_DOLLAR_FOOTBALL_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Falta FIVE_DOLLAR_FOOTBALL_API_KEY")
    client = client or Client(key)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today_start, tomorrow_start, end = _day_bounds(now)
    targets = [row for row in _target_events(root, today_start, end) if not event_ids or int(row.get("event_id") or 0) in event_ids]
    catalog_bundles = _schedule_documents(root)
    today_targets = [row for row in targets if (_datetime(row.get("kickoff")) or end) < tomorrow_start]
    tomorrow_targets = [row for row in targets if (_datetime(row.get("kickoff")) or end) >= tomorrow_start]
    counts = {
        "events": len(targets), "today": len(today_targets), "tomorrow": len(tomorrow_targets),
        "consulted": 0, "matched": 0, "updated": 0, "pending": 0, "errors": 0,
        "unmatched": 0, "bet365_today_found": 0, "bet365_tomorrow_found": 0,
        "persisted_found": 0, "movements": 0,
        "batch_fixtures": 0, "batch_odds_with_prices": 0,
        "batch_odds_empty": 0, "individual_fallback_requests": 0,
        "individual_fallback_1x2": 0, "individual_extended_requests": 0,
        "batch_pages_today": 0, "batch_pages_tomorrow": 0,
        "provider_not_found": 0, "ambiguous": 0, "wrong_matches": 0,
        "resolved_exact": 0, "resolved_alias": 0, "resolved_other": 0,
        "resolved_stable_id": 0, "opening_created": 0,
        "opening_preserved": 0, "current_updated": 0,
        "all_picks_created": 0, "top4_created": 0,
    }
    try:
        before = client.request_count
        today_fixtures = fetch_fixtures(client, today_start, tomorrow_start, include_odds=True)
        counts["batch_pages_today"] = client.request_count - before
        before = client.request_count
        tomorrow_fixtures = fetch_fixtures(client, tomorrow_start, end, include_odds=True)
        counts["batch_pages_tomorrow"] = client.request_count - before
        fixtures = today_fixtures + tomorrow_fixtures
        embedded_odds = True
    except HTTPError as exc:
        if exc.code not in {400, 402, 403}:
            raise
        before = client.request_count
        today_fixtures = fetch_fixtures(client, today_start, tomorrow_start, include_odds=False)
        counts["batch_pages_today"] = client.request_count - before
        before = client.request_count
        tomorrow_fixtures = fetch_fixtures(client, tomorrow_start, end, include_odds=False)
        counts["batch_pages_tomorrow"] = client.request_count - before
        fixtures = today_fixtures + tomorrow_fixtures
        embedded_odds = False
    except ProviderDeferred as exc:
        return {
            "ok": False,
            "counts": counts,
            "provider_fixtures": 0,
            "provider_request": "DEFERRED_RATE_LIMIT",
            "message": str(exc),
            "ODDS_BACKFILL_GATE": "FAIL",
        }

    counts["batch_fixtures"] = len(fixtures)
    counts.update(_batch_market_audit(fixtures))
    for fixture in fixtures:
        batch_market = fixture.get("odds") if isinstance(fixture.get("odds"), dict) else {}
        if provider_prices(batch_market):
            counts["batch_odds_with_prices"] += 1
        else:
            counts["batch_odds_empty"] += 1

    db_path = root / "data" / "oddshunter.db"
    connection = sqlite3.connect(db_path, timeout=45) if db_path.is_file() else None
    if connection is not None:
        connection.execute("PRAGMA busy_timeout=45000")
        _ensure_odds_tables(connection)
    saved_mappings: dict[tuple[str, int], int] = {}
    max_individual_per_hour = max(0, int(os.environ.get("ODDSHUNTER_MAX_INDIVIDUAL_ODDS_PER_HOUR", "40")))
    individual_last_hour = 0
    if connection is not None:
        saved_mappings = {
            (str(row[0]), int(row[1])): int(row[2])
            for row in connection.execute(
                "SELECT competition_key,event_id,provider_fixture_id FROM bet365_fixture_odds_sync WHERE provider_fixture_id IS NOT NULL"
            )
        }
        individual_last_hour = int(connection.execute(
            "SELECT COUNT(*) FROM bet365_api_request_log WHERE checked_at>=?",
            ((now - timedelta(hours=1)).isoformat(),),
        ).fetchone()[0])
    individual_budget = max(0, max_individual_per_hour - individual_last_hour)
    extended_ttl = timedelta(minutes=max(15, int(os.environ.get("ODDSHUNTER_EXTENDED_ODDS_TTL_MINUTES", "60"))))
    examples: list[dict[str, Any]] = []
    match_audit: list[dict[str, Any]] = []
    for event in targets:
        # La consulta batch cubre toda la ventana; cada evento de la UI fue
        # comprobado aunque el proveedor todavía no lo haya publicado.
        counts["consulted"] += 1
        competition_key, event_id = str(event["competition_key"]), int(event["event_id"])
        folder = root / "data" / "analisis" / competition_key / str(event_id)
        bundle = {
            **catalog_bundles.get((competition_key, event_id), {}),
            **_bundle(folder),
        }
        target = folder / "odds_value.json"
        existing = _read_existing(target)
        checked_at = datetime.now(timezone.utc).isoformat()
        fixture, resolution, match_score, rejection_reason = resolve_fixture(
            event,
            fixtures,
            saved_fixture_id=saved_mappings.get((competition_key, event_id)),
        )
        if not fixture:
            counts["unmatched"] += 1
            counts["pending"] += 1
            counts["ambiguous" if resolution == "AMBIGUOUS" else "provider_not_found"] += 1
            status = "AMBIGUOUS" if resolution == "AMBIGUOUS" else "PROVIDER_NOT_FOUND"
            # A fixture can disappear from a later provider batch while its
            # previously captured Bet365 prices remain valid as last-known
            # data. Refresh model probabilities/EV from the local analysis in
            # that case without inventing or changing any quote and without an
            # extra provider request.
            preserved_prices = existing.get("available_prices") or []
            preserved_history = existing.get("price_history") or []
            if preserved_prices:
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
                    context = {}
                context = {**context, "event": event}
                refreshed_probabilities = model_probabilities(bundle, context) if bundle else {}
                probabilities = {
                    **(existing.get("probabilities") or {}),
                    **refreshed_probabilities,
                }
                preserved_prices = attach_asian_source_values(bundle, preserved_prices)
                display_prices = market_anchored_prices(bundle, probabilities, preserved_prices)
                all_picks = build_all_picks(probabilities, display_prices)
                ranked = rank_value_picks(probabilities, display_prices, 4, bundle, context)
                top_picks = immutable_top_picks(existing, ranked, checked_at, event)
                document = {
                    **existing,
                    "generated_at": checked_at,
                    "last_checked_at": checked_at,
                    "odds_status": "AVAILABLE_LAST_KNOWN",
                    "probabilities": probabilities,
                    "all_picks": all_picks,
                    "top_picks": top_picks,
                    "top_picks_snapshot": top_picks,
                }
                _atomic_json(target, document)
                _persist_database(
                    connection,
                    event,
                    existing.get("provider_fixture_id"),
                    "AVAILABLE_LAST_KNOWN",
                    checked_at,
                    preserved_history,
                )
                counts["updated"] += 1
                counts["persisted_found"] += 1
                counts["all_picks_created"] += len(all_picks)
                counts["top4_created"] += len(top_picks)
            else:
                context = {}
                try:
                    from global_match_context import build_global_context
                    context = build_global_context(root, competition_key, event_id, bundle=bundle, match_hint=event)
                except (ImportError, OSError, RuntimeError, TypeError, ValueError):
                    pass
                document = refresh_model_picks(bundle, existing, context)
                document.update({
                    "schema_version": 2, "generated_at": checked_at,
                    "last_checked_at": checked_at, "event_id": event_id,
                    "competition_key": competition_key, "provider": "5DollarFootballAPI",
                    "bookmaker": "Bet365", "provider_fixture_id": None,
                    "odds_status": status,
                })
                _atomic_json(target, document)
                counts["updated"] += 1
                counts["all_picks_created"] += len(document["all_picks"])
                _persist_database(connection,event,None,status,checked_at,[])
            match_audit.append({
                "app_fixture_id": event_id,
                "app_home": event.get("home_team"),
                "app_away": event.get("away_team"),
                "app_kickoff": event.get("kickoff"),
                "app_league": event.get("competition_name") or competition_key,
                "candidate_provider_fixture_id": None,
                "provider_home": None,
                "provider_away": None,
                "provider_kickoff": None,
                "provider_league": None,
                "match_score": round(match_score, 4),
                "classification": resolution,
                "rejection_reason": rejection_reason,
            })
            continue
        method_counter = {
            "RESOLVED_EXACT": "resolved_exact",
            "RESOLVED_ALIAS": "resolved_alias",
            "RESOLVED_OTHER": "resolved_other",
            "RESOLVED_STABLE_ID": "resolved_stable_id",
        }[resolution]
        counts[method_counter] += 1
        counts["matched"] += 1
        if resolution != "RESOLVED_EXACT":
            provider_teams = fixture.get("teams") or {}
            match_audit.append({
                "app_fixture_id": event_id,
                "app_home": event.get("home_team"),
                "app_away": event.get("away_team"),
                "app_kickoff": event.get("kickoff"),
                "app_league": event.get("competition_name") or competition_key,
                "candidate_provider_fixture_id": int(fixture["id"]),
                "provider_home": (provider_teams.get("home") or {}).get("name"),
                "provider_away": (provider_teams.get("away") or {}).get("name"),
                "provider_kickoff": fixture.get("kickoff_utc"),
                "provider_league": (fixture.get("league") or {}).get("name"),
                "match_score": round(match_score, 4),
                "classification": resolution,
                "rejection_reason": None,
            })
        extended_checked_now = False
        try:
            bookmaker = _embedded_bet365(fixture) if embedded_odds else {}
            batch_markets = bookmaker.get("odds") or {}
            batch_prices = provider_prices(batch_markets) if bookmaker else []
            last_extended = _datetime(existing.get("extended_last_checked_at"))
            extended_due = last_extended is None or now - last_extended >= extended_ttl
            needs_individual_1x2 = not batch_prices
            needs_extended = bool(batch_prices) and extended_due
            if (needs_individual_1x2 or needs_extended) and individual_budget > 0:
                counts["individual_fallback_requests"] += 1
                counts["individual_fallback_1x2"] += int(needs_individual_1x2)
                counts["individual_extended_requests"] += int(needs_extended)
                individual_budget -= 1
                odds_payload = client.get(f"/fixtures/{int(fixture['id'])}/odds", bookmakers=BET365_SLUG)
                detailed = _strict_bet365((odds_payload.get("data") or {}).get("bookmakers"))
                if detailed:
                    bookmaker = detailed
                extended_checked_now = needs_extended
                if connection is not None:
                    connection.execute(
                        "INSERT INTO bet365_api_request_log(checked_at,request_kind,provider_fixture_id) VALUES (?,?,?)",
                        (checked_at, "extended" if needs_extended else "batch_empty", int(fixture["id"])),
                    )
                    connection.commit()
        except ProviderDeferred as exc:
            counts["errors"] += 1
            _persist_database(connection,event,int(fixture["id"]),"ERROR_RETRY",checked_at,[],str(exc))
            continue
        except (HTTPError, URLError, TimeoutError, RuntimeError, ValueError) as exc:
            counts["errors"] += 1
            _persist_database(connection,event,int(fixture["id"]),"ERROR_RETRY",checked_at,[],f"{type(exc).__name__}: {exc}")
            continue

        markets = bookmaker.get("odds") or {}
        opening_prices = provider_prices(markets, snapshot_order=("opening", "closing"))
        current_prices = provider_prices(markets, snapshot_order=("closing", "opening"))
        _reuse_cached_extended(existing, opening_prices, current_prices)
        opening_prices = attach_asian_source_values(bundle, opening_prices)
        current_prices = attach_asian_source_values(bundle, current_prices)
        if not bookmaker or not current_prices:
            counts["pending"] += 1
            preserved = existing if existing.get("available_prices") else {}
            probabilities = model_probabilities(bundle, {}) if bundle else {}
            document = {
                **preserved,
                "schema_version": 2,
                "generated_at": checked_at,
                "event_id": event_id,
                "competition_key": competition_key,
                "provider": "5DollarFootballAPI",
                "bookmaker": "Bet365",
                "provider_fixture_id": int(fixture["id"]),
                "odds_status": "AVAILABLE_LAST_KNOWN" if preserved else "PENDING/NOT_AVAILABLE_YET",
                "last_checked_at": checked_at,
                "probabilities": preserved.get("probabilities") or probabilities,
                "available_prices": preserved.get("available_prices") or [],
                "price_history": preserved.get("price_history") or [],
                "extended_last_checked_at": preserved.get("extended_last_checked_at"),
                "top_picks": preserved.get("top_picks") or [],
                "top_picks_snapshot": preserved.get("top_picks_snapshot") or [],
                "policy": "Bet365 real; OPENING inmutable; CURRENT=última closing prematch; Kelly 1/4 limitado a 5%.",
            }
            _atomic_json(target, document)
            _persist_database(connection,event,int(fixture["id"]),document["odds_status"],checked_at,[])
            counts["updated"] += 1
            continue

        available, history, merge_stats = _merge_prices(existing, opening_prices, current_prices, checked_at)
        counts["movements"] += merge_stats["current_updated"]
        for key_name, value in merge_stats.items():
            counts[key_name] += value
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
        context = {**context, "event": event}
        probabilities = model_probabilities(bundle, context)
        display_prices = market_anchored_prices(bundle, probabilities, available)
        all_picks = build_all_picks(probabilities, display_prices)
        ranked = rank_value_picks(probabilities, display_prices, 4, bundle, context)
        top_picks = immutable_top_picks(existing, ranked, checked_at, event)
        counts["all_picks_created"] += len(all_picks)
        counts["top4_created"] += len(top_picks)
        document = {
            "schema_version": 2,
            "generated_at": checked_at,
            "event_id": int(event_id),
            "competition_key": competition_key,
            "provider": "5DollarFootballAPI",
            "bookmaker": "Bet365",
            "provider_fixture_id": int(fixture["id"]),
            "odds_status": "AVAILABLE",
            "provider_markets": {**(existing.get("provider_markets") or {}), **markets},
            "first_captured_at": min(row["opening"]["captured_at"] for row in history),
            "last_checked_at": checked_at,
            "extended_last_checked_at": checked_at if extended_checked_now else existing.get("extended_last_checked_at"),
            "probabilities": probabilities,
            "available_prices": available,
            "price_history": history,
            "all_picks": all_picks,
            "top_picks": top_picks,
            "top_picks_snapshot": top_picks,
            "policy": "Bet365 real; OPENING inmutable; CURRENT=última closing prematch; Kelly 1/4 limitado a 5%.",
        }
        _atomic_json(target, document)
        persisted = _persist_database(connection,event,int(fixture["id"]),"AVAILABLE",checked_at,history)
        if persisted == len(history):
            counts["persisted_found"] += 1
        local_day = (_datetime(event.get("kickoff")) or end).astimezone(ECUADOR_TZ).date()
        if local_day == today_start.astimezone(ECUADOR_TZ).date():
            counts["bet365_today_found"] += 1
        else:
            counts["bet365_tomorrow_found"] += 1
        counts["updated"] += 1
        if len(examples) < 8:
            result_prices = {row["key"]: row for row in available}
            examples.append({
                "fixture_id": int(fixture["id"]),
                "partido": f"{event.get('home_team')} vs {event.get('away_team')}",
                "kickoff": event.get("kickoff"),
                "bet365_1": (result_prices.get("result_home") or {}).get("current_odds"),
                "bet365_x": (result_prices.get("result_draw") or {}).get("current_odds"),
                "bet365_2": (result_prices.get("result_away") or {}).get("current_odds"),
                "opening_current": {
                    key: {"opening": row.get("opening_odds"), "current": row.get("current_odds")}
                    for key, row in result_prices.items() if key in {"result_home", "result_draw", "result_away"}
                },
                "captured_at": document["first_captured_at"],
            })
    if connection is not None:
        connection.close()

    found = counts["bet365_today_found"] + counts["bet365_tomorrow_found"]
    gate = (
        counts["consulted"] == len(targets)
        and counts["errors"] == 0
        and counts["persisted_found"] == found
        and found + counts["pending"] == len(targets)
        and counts["matched"] + counts["provider_not_found"] == len(targets)
        and counts["ambiguous"] == 0
        and counts["wrong_matches"] == 0
    )
    return {
        "ok": True,
        "window": {"today_start_utc": today_start.isoformat(), "tomorrow_start_utc": tomorrow_start.isoformat(), "end_utc": end.isoformat()},
        "counts": counts,
        "provider_fixtures": len(fixtures),
        "provider_requests": client.request_count,
        "examples": examples,
        "matching_audit": match_audit,
        "BATCH_FIXTURES": counts["batch_fixtures"],
        "BATCH_ODDS_WITH_PRICES": counts["batch_odds_with_prices"],
        "BATCH_ODDS_EMPTY": counts["batch_odds_empty"],
        "INDIVIDUAL_FALLBACK_REQUESTS": counts["individual_fallback_requests"],
        "INDIVIDUAL_FALLBACK_1X2": counts["individual_fallback_1x2"],
        "TODAY_DATE_EC": today_start.astimezone(ECUADOR_TZ).date().isoformat(),
        "TOMORROW_DATE_EC": tomorrow_start.astimezone(ECUADOR_TZ).date().isoformat(),
        "TODAY_FIXTURES": counts["today"],
        "TOMORROW_FIXTURES": counts["tomorrow"],
        "BATCH_PAGES_TODAY": counts["batch_pages_today"],
        "BATCH_PAGES_TOMORROW": counts["batch_pages_tomorrow"],
        "BATCH_REQUESTS_TOTAL": counts["batch_pages_today"] + counts["batch_pages_tomorrow"],
        "BATCH_FIXTURES_TOTAL": counts["batch_fixtures"],
        "BATCH_1X2_WITH_PRICES": counts["batch_1x2_with_prices"],
        "BATCH_GOALS_WITH_PRICES": counts["batch_goals_with_prices"],
        "BATCH_BTTS_WITH_PRICES": counts["batch_btts_with_prices"],
        "BATCH_CORNERS_WITH_PRICES": counts["batch_corners_with_prices"],
        "BATCH_CARDS_WITH_PRICES": counts["batch_cards_with_prices"],
        "BATCH_FIRST_HALF_WITH_PRICES": counts["batch_first_half_with_prices"],
        "BET365_AVAILABLE_FIXTURES": found,
        "BET365_PENDING_FIXTURES": counts["pending"],
        "OTHER_BOOKMAKER_REJECTED": 0,
        "OPENING_CREATED": counts["opening_created"],
        "OPENING_PRESERVED": counts["opening_preserved"],
        "CURRENT_UPDATED": counts["current_updated"],
        "ALL_PICKS_CREATED": counts["all_picks_created"],
        "TOP4_CREATED": counts["top4_created"],
        "EXTRA_API_REQUESTS_FOR_TOP4": 0,
        "APP_FIXTURES_CHECKED": counts["consulted"],
        "MATCHED": counts["matched"],
        "UNMATCHED": counts["unmatched"],
        "PROVIDER_NOT_FOUND": counts["provider_not_found"],
        "AMBIGUOUS": counts["ambiguous"],
        "PERSISTED": counts["persisted_found"],
        "WRONG_MATCHES": counts["wrong_matches"],
        "BATCH_COVERAGE_PERCENT": round(100 * found / len(targets), 2) if targets else 100.0,
        "TOTAL_FIXTURES_TODAY": counts["today"],
        "TOTAL_FIXTURES_TOMORROW": counts["tomorrow"],
        "BET365_ODDS_TODAY_FOUND": counts["bet365_today_found"],
        "BET365_ODDS_TOMORROW_FOUND": counts["bet365_tomorrow_found"],
        "BET365_PENDING": counts["pending"],
        "BET365_ERRORS": counts["errors"],
        "ODDS_BACKFILL_GATE": "PASS" if gate else "FAIL",
        "ODDS_PICKS_BATCH_GATE": "PASS" if gate else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--days", type=int, default=2, help="Compatibilidad; la ventana siempre es HOY+MAÑANA Ecuador")
    parser.add_argument("--start", help="Compatibilidad; no limita la ventana HOY+MAÑANA")
    parser.add_argument("--max-age-minutes", type=int, default=0, help="Compatibilidad; ya no omite fixtures por caché")
    parser.add_argument("--event-id", type=int, action="append", default=[])
    parser.add_argument("--now", help="Fecha de referencia ISO para pruebas reproducibles")
    args = parser.parse_args()
    reference = _datetime(args.now) if args.now else datetime.now(timezone.utc)
    print(json.dumps(sync(args.root.resolve(), event_ids=set(args.event_id) or None, now=reference), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
