from __future__ import annotations

"""Build the exact Mobile catalog for Ecuador yesterday/today/tomorrow.

The desktop working database is the source of the competition catalog and
analysis documents. SofaScore's exact event endpoint is used only to correct
reschedules, status and scores before the snapshot is published.
"""

import argparse
import gzip
import json
import re
import sqlite3
import subprocess
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fixture_status import fixture_state
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ECUADOR_TZ = timezone(timedelta(hours=-5))
FINAL_TYPES = {"finished", "afterextra", "afterpenalties"}
SPECIAL_TYPES = {"canceled", "cancelled", "postponed", "abandoned"}


def parse_dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalized(value: Any) -> str:
    plain = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join(
        "".join(char if char.isalnum() else " " for char in plain if not unicodedata.combining(char))
        .casefold()
        .split()
    )


def slugify(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def pct(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number * 100 if 0 <= number <= 1 else number, 1)


def headline(goals: dict[str, Any]) -> dict[str, Any]:
    models = goals.get("models") if isinstance(goals.get("models"), dict) else {}
    learned: dict[str, Any] = {}
    for name in ("MODELO_APRENDIDO", "MODELO_GOLES", "MODELO_XG"):
        if isinstance(models.get(name), dict):
            learned = models[name]
            break
    outcome = learned.get("outcome_probabilities") if isinstance(learned.get("outcome_probabilities"), dict) else {}
    return {
        "home_win": pct(outcome.get("home_win")),
        "draw": pct(outcome.get("draw")),
        "away_win": pct(outcome.get("away_win")),
        "model": learned.get("model_name"),
    }


def read_documents(folder: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    parsed: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    if not folder.is_dir():
        return parsed, rows
    for path in sorted(folder.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        parsed[path.stem] = value
        rows.append(
            {
                "doc_name": path.stem,
                "json_text": json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                "source_mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            }
        )
    return parsed, rows


def load_schedule_bootstrap(
    path: Path | None,
    competitions: dict[int, dict[str, Any]],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Load the season calendar shipped to the VPS by the Desktop release.

    This is fixture metadata only. It lets the cloud select each rolling
    yesterday/today/tomorrow window without depending on the user's PC or on a
    successful tournament-cursor request during that specific refresh.
    """

    if path is None or not path.is_file():
        return []
    try:
        with gzip.open(path, "rt", encoding="utf-8-sig") as handle:
            document = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    source = document.get("events", []) if isinstance(document, dict) else document
    if not isinstance(source, list):
        return []
    rows: list[dict[str, Any]] = []
    for raw in source:
        if not isinstance(raw, dict):
            continue
        kickoff = parse_dt(raw.get("kickoff"))
        try:
            league_id = int(raw.get("league_id") or 0)
            event_id = int(raw.get("event_id") or 0)
        except (TypeError, ValueError):
            continue
        if (
            event_id <= 0
            or league_id not in competitions
            or kickoff is None
            or kickoff < start
            or kickoff >= end
        ):
            continue
        row = dict(raw)
        row["event_id"] = event_id
        row["league_id"] = league_id
        row["kickoff"] = kickoff.isoformat()
        rows.append(row)
    return rows


def provider_event(event_id: int) -> dict[str, Any] | None:
    url = f"https://api.sofascore.com/api/v1/event/{event_id}"
    for attempt in range(3):
        try:
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 OddsHunter/1.0"})
            with urlopen(request, timeout=25) as response:
                payload = json.load(response)
            event = payload.get("event")
            return event if isinstance(event, dict) else None
        except HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code == 403:
                completed = subprocess.run(
                    [
                        "curl", "-fsSL", "--max-time", "25",
                        "-H", "Accept: application/json",
                        "-H", "User-Agent: Mozilla/5.0",
                        url,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                payload = json.loads(completed.stdout)
                event = payload.get("event")
                return event if isinstance(event, dict) else None
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (TimeoutError, URLError):
            if attempt == 2:
                raise
        time.sleep(1.5 * (attempt + 1))
    return None


def provider_competition_events(competition: dict[str, Any]) -> list[dict[str, Any]]:
    """Read both sides of the current fixture cursor for one active league."""
    tournament_id = int(competition["source_competition_id"])
    season_id = int(competition["season_id"])
    found: dict[int, dict[str, Any]] = {}
    for direction in ("last", "next"):
        # The bare API host rejects tournament cursors from the cloud runtime
        # (HTTP 403), while SofaScore's public web API host serves the same
        # fixture document and is already used by the live-status pipeline.
        url = (
            f"https://www.sofascore.com/api/v1/unique-tournament/{tournament_id}/"
            f"season/{season_id}/events/{direction}/0"
        )
        completed = subprocess.run(
            ["curl", "-fsSL", "--max-time", "25", "-H", "User-Agent: Mozilla/5.0", url],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(completed.stdout)
        for event in payload.get("events", []):
            if isinstance(event, dict) and event.get("id") is not None:
                found[int(event["id"])] = event
    return list(found.values())


def provider_status(event: dict[str, Any], fallback: str) -> tuple[str, str]:
    status = event.get("status") if isinstance(event.get("status"), dict) else {}
    kind = str(status.get("type") or "").strip().casefold()
    description = str(status.get("description") or kind or fallback)
    state = fixture_state(kind or description)
    if state == "finished":
        return "FT", description
    if state == "terminal":
        return kind.upper(), description
    if state == "live":
        return "LIVE", description
    if state == "scheduled":
        return "NS", description
    return fallback or "NS", description


def _event_day(row: dict[str, Any]) -> str | None:
    kickoff = parse_dt(row.get("kickoff"))
    return kickoff.astimezone(ECUADOR_TZ).date().isoformat() if kickoff else None


def preserve_previous_coverage(
    fresh: dict[str, Any],
    previous: dict[str, Any],
    allowed_days: set[str],
) -> dict[str, Any]:
    """Never shrink a valid Mobile day because one refresh discovered less.

    The VPS working database is intentionally incremental and may temporarily
    contain fewer fixtures than the desktop catalog.  Provider requests can
    also fail for one league.  A refresh therefore merges the last published
    three-day snapshot with the newly discovered rows.  Fresh rows win so
    scores, statuses and reschedules continue to update; previous rows only
    fill genuine discovery gaps.  Dates outside the rolling Ecuador window are
    discarded, so this does not retain the rest of the week.
    """

    event_map: dict[tuple[str, int], dict[str, Any]] = {}
    for source in (previous.get("events", []), fresh.get("events", [])):
        for row in source if isinstance(source, list) else []:
            if not isinstance(row, dict) or _event_day(row) not in allowed_days:
                continue
            try:
                identity = (str(row.get("competition_key") or ""), int(row["event_id"]))
            except (KeyError, TypeError, ValueError):
                continue
            event_map[identity] = row

    allowed_ids = set(event_map)
    doc_map: dict[tuple[str, int, str], dict[str, Any]] = {}
    for source in (previous.get("docs", []), fresh.get("docs", [])):
        for row in source if isinstance(source, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                event_identity = (str(row.get("competition_key") or ""), int(row["event_id"]))
                identity = (*event_identity, str(row["doc_name"]))
            except (KeyError, TypeError, ValueError):
                continue
            if event_identity in allowed_ids:
                doc_map[identity] = row

    events = sorted(event_map.values(), key=lambda row: (str(row.get("kickoff")), int(row["event_id"])))
    counts_by_day: dict[str, int] = {}
    leagues_by_day: dict[str, set[str]] = {}
    event_ids_by_day: dict[str, list[int]] = {}
    for row in events:
        day = _event_day(row)
        if day is None:
            continue
        counts_by_day[day] = counts_by_day.get(day, 0) + 1
        leagues_by_day.setdefault(day, set()).add(str(row.get("competition_key") or ""))
        event_ids_by_day.setdefault(day, []).append(int(row["event_id"]))

    result = dict(fresh)
    result.update({
        "events": events,
        "docs": list(doc_map.values()),
        "counts_by_day": counts_by_day,
        "leagues_by_day": {day: sorted(keys) for day, keys in leagues_by_day.items()},
        "event_ids_by_day": {day: sorted(ids) for day, ids in event_ids_by_day.items()},
        "coverage_policy": "rolling_three_day_union_fresh_wins",
    })
    result.setdefault("validation", {})["preserved_previous_events"] = max(
        0, len(events) - len(fresh.get("events", []))
    )
    return result


def build(args: argparse.Namespace) -> dict[str, Any]:
    now = parse_dt(args.now) if args.now else datetime.now(timezone.utc)
    assert now is not None
    today = now.astimezone(ECUADOR_TZ).date()
    allowed_days = {today - timedelta(days=1), today, today + timedelta(days=1)}
    start = datetime.combine(today - timedelta(days=1), datetime.min.time(), ECUADOR_TZ).astimezone(timezone.utc)
    end = datetime.combine(today + timedelta(days=2), datetime.min.time(), ECUADOR_TZ).astimezone(timezone.utc)

    registry_doc = json.loads(args.registry.read_text(encoding="utf-8-sig"))
    competitions = {
        int(row["league_id"]): row
        for row in registry_doc.get("competitions", [])
        if isinstance(row, dict) and row.get("active") and row.get("league_id") is not None
    }
    con = sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    db_rows = [dict(row) for row in con.execute(
        """
        SELECT m.sofascore_id AS event_id,m.league_id,m.kickoff,m.status,m.home_goals,m.away_goals,
               m.season AS season_name,l.name AS competition_name,
               h.sofascore_id AS home_team_id,h.name AS home_team,
               a.sofascore_id AS away_team_id,a.name AS away_team
        FROM matches m JOIN leagues l ON l.league_id=m.league_id
        JOIN teams h ON h.team_id=m.home_team_id JOIN teams a ON a.team_id=m.away_team_id
        WHERE m.sofascore_id IS NOT NULL AND datetime(m.kickoff)>=datetime(?) AND datetime(m.kickoff)<datetime(?)
        ORDER BY datetime(m.kickoff),m.sofascore_id
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall() if int(row["league_id"]) in competitions]
    con.close()

    # The bootstrap contains the complete season schedule already known by
    # Desktop. SQLite remains authoritative for rows it has; bootstrap rows
    # only fill fixtures absent from the incremental VPS working database.
    known_db_ids = {int(row["event_id"]) for row in db_rows}
    bootstrap_rows = load_schedule_bootstrap(
        args.bootstrap, competitions, start, end
    )
    for row in bootstrap_rows:
        if int(row["event_id"]) not in known_db_ids:
            db_rows.append(row)
            known_db_ids.add(int(row["event_id"]))

    exact: dict[int, dict[str, Any] | None] = {}
    errors: dict[int, str] = {}
    if not args.skip_provider:
        # The database can lag behind a newly announced/reprogrammed fixture.
        # Augment it with each active league's exact current provider cursor.
        discovered: list[tuple[int, dict[str, Any]]] = []
        with ThreadPoolExecutor(max_workers=max(1, min(6, args.workers))) as pool:
            pending_competitions = {
                pool.submit(provider_competition_events, competition): (league_id, competition)
                for league_id, competition in competitions.items()
                if competition.get("source_competition_id") and competition.get("season_id")
            }
            for future in as_completed(pending_competitions):
                league_id, competition = pending_competitions[future]
                try:
                    discovered.extend((league_id, event) for event in future.result())
                except Exception as exc:
                    errors[-league_id] = f"{competition.get('key')}: {type(exc).__name__}: {exc}"

        known_ids = {int(row["event_id"]) for row in db_rows}
        for league_id, event in discovered:
            timestamp = event.get("startTimestamp")
            kickoff = datetime.fromtimestamp(int(timestamp), timezone.utc) if timestamp else None
            if kickoff is None or kickoff.astimezone(ECUADOR_TZ).date() not in allowed_days:
                continue
            event_id = int(event["id"])
            exact[event_id] = event
            if event_id in known_ids:
                continue
            home = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
            away = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
            season = event.get("season") if isinstance(event.get("season"), dict) else {}
            competition = competitions[league_id]
            db_rows.append({
                "event_id": event_id,
                "league_id": league_id,
                "kickoff": kickoff.isoformat(),
                "status": "NS",
                "home_goals": None,
                "away_goals": None,
                "season_name": season.get("name"),
                "competition_name": competition.get("name") or competition.get("key"),
                "home_team_id": home.get("id"),
                "home_team": home.get("name"),
                "away_team_id": away.get("id"),
                "away_team": away.get("name"),
            })
            known_ids.add(event_id)

        with ThreadPoolExecutor(max_workers=max(1, min(8, args.workers))) as pool:
            pending = {
                pool.submit(provider_event, int(row["event_id"])): int(row["event_id"])
                for row in db_rows if int(row["event_id"]) not in exact
            }
            for future in as_completed(pending):
                event_id = pending[future]
                try:
                    exact[event_id] = future.result()
                except Exception as exc:  # Preserve the PC row on transient provider failure.
                    errors[event_id] = f"{type(exc).__name__}: {exc}"

    events: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    corrected: list[int] = []
    missing_analysis: list[str] = []
    for row in db_rows:
        event_id = int(row["event_id"])
        competition = competitions[int(row["league_id"])]
        key = slugify(competition.get("key"))
        remote = exact.get(event_id)
        kickoff = parse_dt(row.get("kickoff"))
        status = str(row.get("status") or "NS")
        status_description = status
        home_score, away_score = row.get("home_goals"), row.get("away_goals")

        if remote:
            remote_home = remote.get("homeTeam") if isinstance(remote.get("homeTeam"), dict) else {}
            remote_away = remote.get("awayTeam") if isinstance(remote.get("awayTeam"), dict) else {}
            same_identity = (
                int(remote_home.get("id") or 0) == int(row.get("home_team_id") or 0)
                and int(remote_away.get("id") or 0) == int(row.get("away_team_id") or 0)
            ) or (
                normalized(remote_home.get("name")) == normalized(row.get("home_team"))
                and normalized(remote_away.get("name")) == normalized(row.get("away_team"))
            )
            if not same_identity:
                excluded.append({"event_id": event_id, "reason": "IDENTITY_MISMATCH"})
                continue
            remote_kickoff = datetime.fromtimestamp(int(remote.get("startTimestamp")), timezone.utc) if remote.get("startTimestamp") else None
            remote_status, remote_description = provider_status(remote, status)
            stale_scheduled = (
                remote_status == "NS" and kickoff is not None
                and kickoff <= now - timedelta(minutes=15)
            )
            if remote_kickoff and remote_kickoff != kickoff and not stale_scheduled:
                corrected.append(event_id)
                kickoff = remote_kickoff
            if not stale_scheduled:
                status, status_description = remote_status, remote_description
            home_score_doc = remote.get("homeScore") if isinstance(remote.get("homeScore"), dict) else {}
            away_score_doc = remote.get("awayScore") if isinstance(remote.get("awayScore"), dict) else {}
            home_score = home_score_doc.get("current", home_score)
            away_score = away_score_doc.get("current", away_score)

        if kickoff is None or kickoff.astimezone(ECUADOR_TZ).date() not in allowed_days:
            excluded.append({"event_id": event_id, "reason": "OUTSIDE_THREE_DAY_WINDOW", "kickoff": kickoff.isoformat() if kickoff else None})
            continue

        folder = args.data_root / "analisis" / key / str(event_id)
        parsed, event_docs = read_documents(folder)
        if not event_docs:
            missing_analysis.append(f"{key}/{event_id}")
        docs.extend({"competition_key": key, "event_id": event_id, **item} for item in event_docs)
        input_doc = parsed.get("input_match") or {}
        analysis_doc = parsed.get("analysis") or {}
        status_doc = parsed.get("status") or {}
        source_event = input_doc.get("upcoming_match") or input_doc.get("evento") or analysis_doc.get("upcoming_match") or {}
        events.append({
            "competition_key": key,
            "event_id": event_id,
            "competition_name": row.get("competition_name") or source_event.get("competition_name") or key,
            "season_name": row.get("season_name") or source_event.get("season_name"),
            "round_name": source_event.get("round_name"),
            "stage": source_event.get("stage"),
            "kickoff": kickoff.isoformat(),
            "status": status,
            "status_description": status_description,
            "home_team_id": row.get("home_team_id"),
            "home_team": row.get("home_team"),
            "away_team_id": row.get("away_team_id"),
            "away_team": row.get("away_team"),
            "home_score": home_score,
            "away_score": away_score,
            "analysis_status": status_doc.get("status") or analysis_doc.get("status") or ("READY" if event_docs else "pending"),
            "headline_json": json.dumps(headline(parsed.get("goals") or {}), ensure_ascii=False, separators=(",", ":")),
        })

    events.sort(key=lambda row: (str(row["kickoff"]), int(row["event_id"])))
    counts_by_day: dict[str, int] = {}
    leagues_by_day: dict[str, set[str]] = {}
    event_ids_by_day: dict[str, list[int]] = {}
    for row in events:
        day = parse_dt(row["kickoff"]).astimezone(ECUADOR_TZ).date().isoformat()
        counts_by_day[day] = counts_by_day.get(day, 0) + 1
        leagues_by_day.setdefault(day, set()).add(str(row["competition_key"]))
        event_ids_by_day.setdefault(day, []).append(int(row["event_id"]))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"timezone": "America/Guayaquil", "start": start.isoformat(), "end_exclusive": end.isoformat()},
        "events": events,
        "docs": docs,
        "missing_analysis": sorted(missing_analysis),
        "counts_by_day": counts_by_day,
        "leagues_by_day": {day: sorted(keys) for day, keys in leagues_by_day.items()},
        "event_ids_by_day": {day: sorted(ids) for day, ids in event_ids_by_day.items()},
        "validation": {
            "input_events": len(db_rows),
            "bootstrap_events_in_window": len(bootstrap_rows),
            "corrected_event_ids": sorted(corrected),
            "excluded": excluded,
            "provider_errors": errors,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--now")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--skip-provider", action="store_true")
    parser.add_argument("--bootstrap", type=Path)
    args = parser.parse_args()
    previous: dict[str, Any] = {}
    if args.output.is_file():
        try:
            with gzip.open(args.output, "rt", encoding="utf-8") as handle:
                loaded = json.load(handle)
            previous = loaded if isinstance(loaded, dict) else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            previous = {}

    document = build(args)
    now = parse_dt(args.now) if args.now else datetime.now(timezone.utc)
    assert now is not None
    today = now.astimezone(ECUADOR_TZ).date()
    allowed_days = {
        (today + timedelta(days=offset)).isoformat()
        for offset in (-1, 0, 1)
    }
    if previous:
        document = preserve_previous_coverage(document, previous, allowed_days)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({key: document[key] for key in ("generated_at", "counts_by_day", "leagues_by_day", "validation")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
