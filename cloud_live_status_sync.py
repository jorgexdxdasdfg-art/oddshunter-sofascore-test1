from __future__ import annotations

"""Refresh current/recent match states and publish them to the mobile API.

This is deliberately separate from the heavy final-result/statistics pipeline:
live scores must be cheap and frequent, while complete statistics are imported
only after a match is final.
"""

import argparse
import gzip
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from futbol24_client import Futbol24Client
from sofascore_event_client import SofaScoreEventClient
from xg_pipeline import MatchRef


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB = Path(os.environ.get("ODDSHUNTER_WORK_DB", str(DATA / "oddshunter.db")))
REGISTRY = DATA / "competitions.json"
REPORT = DATA / "automation" / "cloud_live_status" / "last.json"
ECUADOR_TZ = timezone(timedelta(hours=-5))
SCHEDULE_CATALOG_INTERVAL_MINUTES = 15
SCHEDULE_CATALOG_SEED = Path(
    os.environ.get("ODDSHUNTER_SCHEDULE_CATALOG_SEED", str(DB.parent / "mobile_schedule_catalog_seed.json.gz"))
)

FINAL_STATUSES = {"FT", "AET", "PEN", "FINISHED", "FINAL"}
SPECIAL_STATUSES = {"CANCELED", "CANCELLED", "POSTPONED", "ABANDONED"}

# Correcciones de calendario verificadas cuando el proveedor que originó el
# evento conserva una fecha antigua. No se inventa un resultado: se exige que
# la identidad de ambos equipos siga coincidiendo antes de aplicar el cambio.
VERIFIED_SCHEDULE_CORRECTIONS: dict[int, dict[str, Any]] = {
    16690997: {
        "home_team": "Barranquilla FC",
        "away_team": "Millonarios",
        # Miércoles 16 de septiembre de 2026, 20:30 en Colombia/Ecuador.
        "kickoff": "2026-09-17T01:30:00+00:00",
        "provider_status": "rescheduled",
    },
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def slugify(value: Any) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def require_write_gates() -> None:
    required = {
        "ODDSHUNTER_RUNTIME_MODE": "cloud",
        "ODDSHUNTER_ALLOW_WORK_DB_WRITE": "1",
        "ODDSHUNTER_STAGE6_ALLOW_TURSO_WRITE": "1",
    }
    wrong = {
        key: os.environ.get(key)
        for key, expected in required.items()
        if str(os.environ.get(key) or "").strip().lower() != expected
    }
    if wrong:
        raise RuntimeError(f"WRITE GATE cerrado: {sorted(wrong)}")
    if not DB.is_file():
        raise FileNotFoundError(f"Falta working SQLite: {DB}")


def registry_by_league() -> dict[int, dict[str, Any]]:
    document = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    rows: dict[int, dict[str, Any]] = {}
    for item in document.get("competitions", []):
        if not isinstance(item, dict) or item.get("league_id") is None:
            continue
        rows[int(item["league_id"])] = item
    return rows


def connect_db(*, read_only: bool) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{DB.resolve().as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=45)
        con.execute("PRAGMA query_only=ON")
    else:
        con = sqlite3.connect(DB, timeout=45)
        con.execute("PRAGMA busy_timeout=45000")
    con.row_factory = sqlite3.Row
    return con


MATCH_SELECT = """
SELECT
    m.match_id, m.sofascore_id AS event_id, m.league_id, m.kickoff,
    m.status, m.home_goals, m.away_goals, m.season AS season_name,
    l.name AS competition_name,
    h.sofascore_id AS home_team_id, h.name AS home_team,
    a.sofascore_id AS away_team_id, a.name AS away_team
FROM matches AS m
JOIN leagues AS l ON l.league_id=m.league_id
JOIN teams AS h ON h.team_id=m.home_team_id
JOIN teams AS a ON a.team_id=m.away_team_id
WHERE m.sofascore_id IS NOT NULL
  AND datetime(m.kickoff)>=datetime(?) AND datetime(m.kickoff)<=datetime(?)
"""


FINAL_ACTUAL_CORE_FIELDS = (
    "home_corners",
    "away_corners",
    "home_yellow_cards",
    "away_yellow_cards",
    "home_shots",
    "away_shots",
)

# Los proveedores suelen corregir xG, remates y tarjetas durante las horas
# posteriores al pitido final. Aunque el primer box score ya esté completo,
# se vuelve a consultar durante esta ventana para que Mobile converja al mismo
# documento definitivo que usa OddsHunter PC.
FINAL_ACTUALS_REFRESH_HOURS = 24
FINAL_ACTUALS_REFRESH_INTERVAL_MINUTES = 15


def final_actuals_core_complete(payload: Any) -> bool:
    """Return whether the real FT box score is complete enough for the app.

    xG is deliberately not required: several competitions publish a complete
    match box score without xG, and keeping those events in the retry queue
    would not make that provider data appear. The remaining fields back every
    non-xG card shown in the Expected/Real view.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return False
    if not isinstance(payload, dict):
        return False
    real = payload.get("real")
    if not isinstance(real, dict):
        return False
    return all(real.get(field) is not None for field in FINAL_ACTUAL_CORE_FIELDS)


def merge_final_actuals_payload(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Merge provider revisions without replacing useful values with blanks.

    Some competitions temporarily return xG as 0-0 after previously exposing
    a non-zero pair. That provider regression must not erase a verified value,
    while corrected counts such as shots and cards should still replace the
    earlier snapshot.
    """
    previous = existing if isinstance(existing, dict) else {}
    old_real = previous.get("real") if isinstance(previous.get("real"), dict) else {}
    new_real = incoming.get("real") if isinstance(incoming.get("real"), dict) else {}
    merged_real = dict(old_real)
    merged_real.update({key: value for key, value in new_real.items() if value is not None})

    old_xg = (old_real.get("home_xg"), old_real.get("away_xg"))
    new_xg = (new_real.get("home_xg"), new_real.get("away_xg"))
    try:
        old_has_signal = any(float(value or 0) > 0 for value in old_xg)
        new_is_zero_pair = all(value is not None and float(value) == 0 for value in new_xg)
    except (TypeError, ValueError):
        old_has_signal = False
        new_is_zero_pair = False
    if old_has_signal and new_is_zero_pair:
        merged_real["home_xg"], merged_real["away_xg"] = old_xg

    return {**previous, **incoming, "real": merged_real}


def _pending(row: sqlite3.Row) -> bool:
    status = str(row["status"] or "").upper()
    if status in SPECIAL_STATUSES:
        return False
    return status not in FINAL_STATUSES or row["home_goals"] is None or row["away_goals"] is None


def _rotated_batch(
    rows: list[Any],
    now: datetime,
    limit: int,
) -> list[Any]:
    """Return a bounded minute-rotating window without starving fixtures.

    The live timer intentionally polls a small provider-safe batch.  Taking
    the first N recent fixtures every minute permanently starves the remaining
    simultaneous matches.  Advancing by one full batch per minute guarantees
    that every pending fixture is revisited quickly while keeping the same
    request ceiling.
    """
    size = len(rows)
    cap = max(0, int(limit))
    if size == 0 or cap == 0:
        return []
    if size <= cap:
        return list(rows)
    start = (int(now.timestamp() // 60) * cap) % size
    rotated = rows[start:] + rows[:start]
    return list(rotated[:cap])


def select_candidates(
    con: sqlite3.Connection,
    now: datetime,
    *,
    near_limit: int,
    overdue_limit: int,
) -> list[dict[str, Any]]:
    # Keep three complete match days in the repair window. A shorter fixed
    # window can permanently strand fixtures when the provider is temporarily
    # unavailable around full time.
    floor = now - timedelta(hours=72)
    ceiling = now + timedelta(minutes=5)
    rows = con.execute(MATCH_SELECT, (iso_utc(floor), iso_utc(ceiling))).fetchall()
    pending = [row for row in rows if _pending(row) and parse_dt(row["kickoff"]) is not None]

    recent_floor = now - timedelta(hours=8)
    recent = [row for row in pending if parse_dt(row["kickoff"]) >= recent_floor]
    overdue = [row for row in pending if parse_dt(row["kickoff"]) < recent_floor]

    recent.sort(key=lambda row: abs((now - parse_dt(row["kickoff"])).total_seconds()))
    # Alternate newest/oldest overdue rows so old score debt cannot starve.
    overdue.sort(key=lambda row: parse_dt(row["kickoff"]), reverse=True)
    fair_overdue: list[sqlite3.Row] = []
    left, right = 0, len(overdue) - 1
    while left <= right:
        fair_overdue.append(overdue[left])
        left += 1
        if left <= right:
            fair_overdue.append(overdue[right])
            right -= 1

    # Rotate both windows. Simultaneous fixtures are common and the service
    # deliberately uses a small near_limit; without rotation, rows beyond that
    # fixed prefix can remain NS throughout the whole match.
    chosen = _rotated_batch(recent, now, near_limit) + _rotated_batch(
        fair_overdue, now, overdue_limit
    )
    return [dict(row) for row in chosen]


def select_event_ids(con: sqlite3.Connection, event_ids: Iterable[int]) -> list[dict[str, Any]]:
    ids = sorted({int(value) for value in event_ids if int(value) > 0})
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    sql = MATCH_SELECT.replace(
        "  AND datetime(m.kickoff)>=datetime(?) AND datetime(m.kickoff)<=datetime(?)",
        f"  AND m.sofascore_id IN ({placeholders})",
    )
    return [dict(row) for row in con.execute(sql, ids).fetchall()]


def select_remote_candidates(
    client: Any,
    now: datetime,
    competitions: dict[int, dict[str, Any]],
    *,
    event_ids: Iterable[int],
    near_limit: int,
    overdue_limit: int,
) -> list[dict[str, Any]]:
    """Select app-visible fixtures with score or final-statistics debt."""
    by_key = {
        slugify(item.get("key")): item
        for item in competitions.values()
        if item.get("league_id") is not None
    }
    rows = client.query(
        "SELECT competition_key,event_id,competition_name,season_name,kickoff,status,"
        "home_team_id,home_team,away_team_id,away_team,home_score,away_score,"
        "(SELECT json_text FROM mobile_analysis_docs AS d "
        "WHERE d.competition_key=mobile_events.competition_key "
        "AND d.event_id=mobile_events.event_id "
        "AND d.doc_name='expected_real_actuals' LIMIT 1) AS final_actuals_json, "
        "(SELECT source_mtime FROM mobile_analysis_docs AS d "
        "WHERE d.competition_key=mobile_events.competition_key "
        "AND d.event_id=mobile_events.event_id "
        "AND d.doc_name='expected_real_actuals' LIMIT 1) AS final_actuals_mtime "
        "FROM mobile_events WHERE datetime(kickoff)>=datetime(?) "
        "AND datetime(kickoff)<=datetime(?)",
        [iso_utc(now - timedelta(hours=72)), iso_utc(now + timedelta(minutes=5))],
    )
    pending: list[dict[str, Any]] = []
    for raw in rows:
        kickoff = parse_dt(raw.get("kickoff"))
        competition = by_key.get(slugify(raw.get("competition_key")))
        status = str(raw.get("status") or "").upper()
        score_debt = (
            status not in FINAL_STATUSES
            or raw.get("home_score") is None
            or raw.get("away_score") is None
        )
        actuals_debt = (
            status in FINAL_STATUSES
            and raw.get("home_score") is not None
            and raw.get("away_score") is not None
            and not final_actuals_core_complete(raw.get("final_actuals_json"))
        )
        try:
            actuals_updated_at = datetime.fromtimestamp(
                float(raw.get("final_actuals_mtime")), tz=timezone.utc
            )
        except (TypeError, ValueError, OSError):
            actuals_updated_at = None
        actuals_refresh = (
            status in FINAL_STATUSES
            and raw.get("home_score") is not None
            and raw.get("away_score") is not None
            and kickoff is not None
            and kickoff >= now - timedelta(hours=FINAL_ACTUALS_REFRESH_HOURS)
            and (
                actuals_updated_at is None
                or actuals_updated_at
                <= now - timedelta(minutes=FINAL_ACTUALS_REFRESH_INTERVAL_MINUTES)
            )
        )
        pending_state = status not in SPECIAL_STATUSES and (
            score_debt or actuals_debt or actuals_refresh
        )
        if kickoff is None or competition is None or not pending_state:
            continue
        event_id = int(raw.get("event_id") or 0)
        if event_id <= 0:
            continue
        pending.append(
            {
                "match_id": event_id,
                "event_id": event_id,
                "league_id": int(competition["league_id"]),
                "kickoff": str(raw.get("kickoff") or ""),
                "status": raw.get("status"),
                "home_goals": raw.get("home_score"),
                "away_goals": raw.get("away_score"),
                "season_name": raw.get("season_name"),
                "competition_name": raw.get("competition_name") or competition.get("name"),
                "home_team_id": raw.get("home_team_id"),
                "home_team": raw.get("home_team"),
                "away_team_id": raw.get("away_team_id"),
                "away_team": raw.get("away_team"),
                "remote_only": True,
                "actuals_debt": actuals_debt,
                "actuals_refresh": actuals_refresh,
            }
        )

    priorities = {int(value) for value in event_ids if int(value) > 0}
    explicit = [row for row in pending if int(row["event_id"]) in priorities]
    pool = [row for row in pending if int(row["event_id"]) not in priorities]
    recent_floor = now - timedelta(hours=8)
    recent = [row for row in pool if parse_dt(row["kickoff"]) >= recent_floor]
    overdue = [row for row in pool if parse_dt(row["kickoff"]) < recent_floor]
    recent.sort(key=lambda row: abs((now - parse_dt(row["kickoff"])).total_seconds()))
    overdue.sort(key=lambda row: parse_dt(row["kickoff"]), reverse=True)
    return explicit + _rotated_batch(recent, now, near_limit) + _rotated_batch(
        overdue, now, overdue_limit
    )

def match_ref(row: dict[str, Any], competition: dict[str, Any]) -> MatchRef:
    return MatchRef(
        match_id=int(row["match_id"]),
        kickoff=str(row["kickoff"]),
        home_team=str(row["home_team"]),
        away_team=str(row["away_team"]),
        competition=str(row["competition_name"]),
        season=str(row.get("season_name") or ""),
        sofascore_event_id=int(row["event_id"]),
        competition_id=(
            int(competition["source_competition_id"])
            if competition.get("source_competition_id") is not None
            else None
        ),
        season_id=(
            int(competition["season_id"])
            if competition.get("season_id") is not None
            else None
        ),
        home_goals=row.get("home_goals"),
        away_goals=row.get("away_goals"),
    )


def normalized_update(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    state = str(snapshot.get("state") or "").strip().lower()
    provider = str(snapshot.get("provider_status") or "").strip()
    home = snapshot.get("home_goals")
    away = snapshot.get("away_goals")
    kickoff = snapshot.get("kickoff")

    if state == "live":
        return {
            "status": "LIVE",
            "status_description": provider or "live",
            "home_score": int(home) if home is not None else None,
            "away_score": int(away) if away is not None else None,
            "state": state,
            "kickoff": kickoff,
        }
    if state == "finished" and home is not None and away is not None:
        return {
            "status": "FT",
            "status_description": provider or "finished",
            "home_score": int(home),
            "away_score": int(away),
            "state": state,
            "kickoff": kickoff,
        }
    if state == "scheduled" and kickoff:
        return {
            "status": "NS",
            "status_description": provider or "scheduled",
            "home_score": int(home) if home is not None else None,
            "away_score": int(away) if away is not None else None,
            "state": state,
            "kickoff": kickoff,
        }
    if state == "terminal":
        token = provider.upper().replace(" ", "_") or "CANCELED"
        return {
            "status": token,
            "status_description": provider or token.lower(),
            "home_score": int(home) if home is not None else None,
            "away_score": int(away) if away is not None else None,
            "state": state,
            "kickoff": kickoff,
        }
    return None


def verified_schedule_snapshot(row: dict[str, Any]) -> dict[str, Any] | None:
    """Devuelve una reprogramación manual solo si la identidad es exacta."""
    event_id = int(row.get("event_id") or 0)
    correction = VERIFIED_SCHEDULE_CORRECTIONS.get(event_id)
    if correction is None:
        return None
    if slugify(row.get("home_team")) != slugify(correction["home_team"]):
        return None
    if slugify(row.get("away_team")) != slugify(correction["away_team"]):
        return None
    return {
        "state": "scheduled",
        "provider_status": correction["provider_status"],
        "home_goals": None,
        "away_goals": None,
        "kickoff": correction["kickoff"],
    }


def turso_client() -> Any:
    # The certified Stage6 publisher owns the Turso protocol implementation.
    # Import lazily so unit tests and dry-runs do not require the Stage6 archive.
    import cloud_stage6_publish as stage6

    return stage6.TursoClient(
        os.environ.get("TURSO_DATABASE_URL", ""),
        os.environ.get("TURSO_AUTH_TOKEN", ""),
    )


def _schedule_pct(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 0 <= number <= 1:
        number *= 100
    return round(number, 1)


def _schedule_headline(goals: dict[str, Any]) -> dict[str, Any]:
    models = goals.get("models") if isinstance(goals.get("models"), dict) else {}
    learned = models.get("MODELO_APRENDIDO") if isinstance(models.get("MODELO_APRENDIDO"), dict) else {}
    if not learned:
        learned = models.get("MODELO_GOLES") if isinstance(models.get("MODELO_GOLES"), dict) else {}
    if not learned:
        learned = models.get("MODELO_XG") if isinstance(models.get("MODELO_XG"), dict) else {}
    outcome = learned.get("outcome_probabilities") if isinstance(learned.get("outcome_probabilities"), dict) else {}
    return {
        "home_win": _schedule_pct(outcome.get("home_win")),
        "draw": _schedule_pct(outcome.get("draw")),
        "away_win": _schedule_pct(outcome.get("away_win")),
        "model": learned.get("model_name"),
    }


def _schedule_status(value: Any) -> str:
    normalized = str(value or "NS").strip().upper()
    if normalized in {"NS", "SCHEDULED", "NOTSTARTED", "NOT_STARTED"}:
        return "notstarted"
    if normalized in {"INPROGRESS", "IN_PROGRESS", "LIVE"}:
        return "inprogress"
    return normalized.lower()


def _read_analysis_documents(folder: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
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


def build_schedule_catalog(
    con: sqlite3.Connection,
    now: datetime,
    competitions: dict[int, dict[str, Any]],
    *,
    data_dir: Path = DATA,
) -> dict[str, Any]:
    """Build every PC fixture for yesterday, today and tomorrow in Ecuador time.

    Stage6 historically published only the analysis targets touched by its
    latest micro-cycle.  That made complete PC schedules appear as one or two
    leagues in Mobile.  This catalog is derived from the same working SQLite
    and the same analysis JSONs as PC, so no fixture or probability is guessed.
    """
    local_today = now.astimezone(ECUADOR_TZ).date()
    start = datetime.combine(local_today - timedelta(days=1), datetime.min.time(), ECUADOR_TZ)
    end = start + timedelta(days=3)
    rows = con.execute(MATCH_SELECT, (iso_utc(start), iso_utc(end))).fetchall()
    events: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []
    missing_analysis: list[str] = []
    counts_by_day: dict[str, int] = {}
    leagues_by_day: dict[str, set[str]] = {}
    event_ids_by_day: dict[str, list[int]] = {}

    for raw in rows:
        row = dict(raw)
        competition = competitions.get(int(row["league_id"]))
        if not competition:
            continue
        key = slugify(competition.get("key"))
        event_id = int(row["event_id"])
        folder = data_dir / "analisis" / key / str(event_id)
        parsed, event_docs = _read_analysis_documents(folder)
        if not event_docs:
            missing_analysis.append(f"{key}/{event_id}")
        for item in event_docs:
            docs.append({"competition_key": key, "event_id": event_id, **item})

        input_doc = parsed.get("input_match") or {}
        analysis_doc = parsed.get("analysis") or {}
        status_doc = parsed.get("status") or {}
        source_event = input_doc.get("upcoming_match") or input_doc.get("evento") or analysis_doc.get("upcoming_match") or {}
        goals = parsed.get("goals") or {}
        headline = _schedule_headline(goals)
        local_day = parse_dt(row.get("kickoff")).astimezone(ECUADOR_TZ).date().isoformat()
        counts_by_day[local_day] = counts_by_day.get(local_day, 0) + 1
        leagues_by_day.setdefault(local_day, set()).add(key)
        event_ids_by_day.setdefault(local_day, []).append(event_id)
        events.append(
            {
                "competition_key": key,
                "event_id": event_id,
                "competition_name": row.get("competition_name") or source_event.get("competition_name") or key,
                "season_name": row.get("season_name") or source_event.get("season_name"),
                "round_name": source_event.get("round_name"),
                "stage": source_event.get("stage"),
                "kickoff": iso_utc(parse_dt(row.get("kickoff"))),
                "status": _schedule_status(row.get("status")),
                "status_description": _schedule_status(row.get("status")),
                "home_team_id": row.get("home_team_id"),
                "home_team": row.get("home_team"),
                "away_team_id": row.get("away_team_id"),
                "away_team": row.get("away_team"),
                "home_score": row.get("home_goals"),
                "away_score": row.get("away_goals"),
                "analysis_status": status_doc.get("status") or analysis_doc.get("status") or ("READY" if event_docs else "pending"),
                "headline_json": json.dumps(headline, ensure_ascii=False, separators=(",", ":")),
            }
        )

    return {
        "events": events,
        "docs": docs,
        "missing_analysis": missing_analysis,
        "counts_by_day": counts_by_day,
        "leagues_by_day": {day: sorted(keys) for day, keys in leagues_by_day.items()},
        "event_ids_by_day": {day: sorted(ids) for day, ids in event_ids_by_day.items()},
    }


def _schedule_catalog_due(client: Any, now: datetime) -> bool:
    if os.environ.get("ODDSHUNTER_FORCE_SCHEDULE_CATALOG") == "1":
        return True
    rows = client.query("SELECT value FROM mobile_sync_meta WHERE key=? LIMIT 1", ["schedule_catalog_last_publish_at"])
    previous = parse_dt(rows[0].get("value")) if rows else None
    return previous is None or previous <= now - timedelta(minutes=SCHEDULE_CATALOG_INTERVAL_MINUTES)


def publish_schedule_catalog(
    client: Any,
    now: datetime,
    competitions: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Publish the complete three-day PC catalog to Mobile/Turso."""
    if not _schedule_catalog_due(client, now):
        return {"result": "SKIPPED_INTERVAL"}
    with connect_db(read_only=True) as con:
        catalog = build_schedule_catalog(con, now, competitions)
    if SCHEDULE_CATALOG_SEED.is_file():
        with gzip.open(SCHEDULE_CATALOG_SEED, "rt", encoding="utf-8") as handle:
            seeded = json.load(handle)
        local_today = now.astimezone(ECUADOR_TZ).date()
        allowed_days = {
            (local_today - timedelta(days=1)).isoformat(),
            local_today.isoformat(),
            (local_today + timedelta(days=1)).isoformat(),
        }
        seeded_events = [
            row for row in seeded.get("events", [])
            if parse_dt(row.get("kickoff"))
            and parse_dt(row.get("kickoff")).astimezone(ECUADOR_TZ).date().isoformat() in allowed_days
        ]
        allowed_ids = {(str(row.get("competition_key")), int(row.get("event_id"))) for row in seeded_events}
        seeded_docs = [
            row for row in seeded.get("docs", [])
            if (str(row.get("competition_key")), int(row.get("event_id"))) in allowed_ids
        ]
        event_map = {
            (str(row.get("competition_key")), int(row.get("event_id"))): row
            for row in catalog.get("events", [])
            if parse_dt(row.get("kickoff"))
            and parse_dt(row.get("kickoff")).astimezone(ECUADOR_TZ).date().isoformat() not in allowed_days
        }
        event_map.update({
            (str(row.get("competition_key")), int(row.get("event_id"))): row
            for row in seeded_events
        })
        allowed_local_ids = {
            (str(row.get("competition_key")), int(row.get("event_id")))
            for row in event_map.values()
        }
        doc_map = {
            (str(row.get("competition_key")), int(row.get("event_id")), str(row.get("doc_name"))): row
            for row in catalog.get("docs", [])
            if (str(row.get("competition_key")), int(row.get("event_id"))) in allowed_local_ids
        }
        doc_map.update({
            (str(row.get("competition_key")), int(row.get("event_id")), str(row.get("doc_name"))): row
            for row in seeded_docs
        })
        merged_events = sorted(event_map.values(), key=lambda row: (str(row.get("kickoff")), int(row.get("event_id"))))
        merged_docs = list(doc_map.values())
        counts_by_day: dict[str, int] = {}
        leagues_by_day: dict[str, set[str]] = {}
        event_ids_by_day: dict[str, list[int]] = {}
        for row in merged_events:
            day = parse_dt(row.get("kickoff")).astimezone(ECUADOR_TZ).date().isoformat()
            counts_by_day[day] = counts_by_day.get(day, 0) + 1
            leagues_by_day.setdefault(day, set()).add(str(row["competition_key"]))
            event_ids_by_day.setdefault(day, []).append(int(row["event_id"]))
        catalog = {
            "events": merged_events,
            "docs": merged_docs,
            "missing_analysis": sorted(set(catalog.get("missing_analysis", [])) - {
                f"{key}/{event_id}" for key, event_id in allowed_ids
            }),
            "counts_by_day": counts_by_day,
            "leagues_by_day": {day: sorted(keys) for day, keys in leagues_by_day.items()},
            "event_ids_by_day": {day: sorted(ids) for day, ids in event_ids_by_day.items()},
            "source": "desktop_catalog_seed+cloud_db",
        }
    events = catalog["events"]
    docs = catalog["docs"]
    if not events:
        raise RuntimeError("El catálogo PC de ayer/hoy/mañana quedó vacío")

    local_today = now.astimezone(ECUADOR_TZ).date()
    schedule_start = datetime.combine(local_today - timedelta(days=1), datetime.min.time(), ECUADOR_TZ)
    schedule_end = schedule_start + timedelta(days=3)
    expected_ids = sorted({int(row["event_id"]) for row in events})
    placeholders = ",".join("?" for _ in expected_ids)
    client.execute(
        f"DELETE FROM mobile_events WHERE datetime(kickoff)>=datetime(?) AND datetime(kickoff)<datetime(?) "
        f"AND event_id NOT IN ({placeholders})",
        [iso_utc(schedule_start), iso_utc(schedule_end), *expected_ids],
    )

    event_sql = (
        "INSERT INTO mobile_events (competition_key,event_id,competition_name,season_name,round_name,stage,"
        "kickoff,status,status_description,home_team_id,home_team,away_team_id,away_team,home_score,away_score,"
        "analysis_status,headline_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT (competition_key,event_id) DO UPDATE SET competition_name=excluded.competition_name,"
        "season_name=excluded.season_name,round_name=excluded.round_name,stage=excluded.stage,kickoff=excluded.kickoff,"
        "status=excluded.status,status_description=excluded.status_description,home_team_id=excluded.home_team_id,"
        "home_team=excluded.home_team,away_team_id=excluded.away_team_id,away_team=excluded.away_team,"
        "home_score=excluded.home_score,away_score=excluded.away_score,analysis_status=excluded.analysis_status,"
        "headline_json=excluded.headline_json"
    )
    event_columns = (
        "competition_key", "event_id", "competition_name", "season_name", "round_name", "stage", "kickoff",
        "status", "status_description", "home_team_id", "home_team", "away_team_id", "away_team", "home_score",
        "away_score", "analysis_status", "headline_json",
    )
    client.execute_many([(event_sql, [row.get(column) for column in event_columns]) for row in events], chunk=12)

    doc_sql = (
        "INSERT INTO mobile_analysis_docs (competition_key,event_id,doc_name,json_text,source_mtime) VALUES (?,?,?,?,?) "
        "ON CONFLICT (competition_key,event_id,doc_name) DO UPDATE SET json_text=excluded.json_text,"
        "source_mtime=excluded.source_mtime"
    )
    if docs:
        client.execute_many(
            [
                (doc_sql, [row["competition_key"], row["event_id"], row["doc_name"], row["json_text"], row["source_mtime"]])
                for row in docs
            ],
            chunk=12,
        )
    client.execute(
        "INSERT INTO mobile_sync_meta (key,value) VALUES (?,?) ON CONFLICT (key) DO UPDATE SET value=excluded.value",
        ["schedule_catalog_last_publish_at", iso_utc(now)],
    )

    remote = client.query(f"SELECT event_id FROM mobile_events WHERE event_id IN ({placeholders})", expected_ids)
    remote_ids = {int(row["event_id"]) for row in remote}
    missing_remote = sorted(set(expected_ids) - remote_ids)
    if missing_remote:
        raise RuntimeError(f"Turso no publicó eventos del catálogo: {missing_remote}")
    return {
        "result": "PUBLISHED",
        "event_count": len(events),
        "doc_count": len(docs),
        "event_ids": expected_ids,
        "missing_analysis": catalog["missing_analysis"],
        "counts_by_day": catalog["counts_by_day"],
        "leagues_by_day": catalog["leagues_by_day"],
        "event_ids_by_day": catalog["event_ids_by_day"],
    }


def seed_schedule_coverage() -> tuple[set[str], set[int]]:
    if not SCHEDULE_CATALOG_SEED.is_file():
        return set(), set()
    with gzip.open(SCHEDULE_CATALOG_SEED, "rt", encoding="utf-8") as handle:
        seeded = json.load(handle)
    days: set[str] = set()
    event_ids: set[int] = set()
    for row in seeded.get("events", []):
        kickoff = parse_dt(row.get("kickoff"))
        if kickoff is None:
            continue
        days.add(kickoff.astimezone(ECUADOR_TZ).date().isoformat())
        event_ids.add(int(row["event_id"]))
    return days, event_ids


def publish_remote(
    client: Any,
    row: dict[str, Any],
    competition: dict[str, Any],
    update: dict[str, Any],
    updated_at: str,
) -> int:
    event_id = int(row["event_id"])
    params = [
        update["status"],
        update["home_score"],
        update["away_score"],
        update.get("kickoff"),
        updated_at,
        event_id,
    ]
    client.execute(
        "UPDATE matches SET status=?,home_goals=COALESCE(?,home_goals),"
        "away_goals=COALESCE(?,away_goals),kickoff=COALESCE(?,kickoff),"
        "updated_at=? WHERE sofascore_id=?",
        params,
    )
    client.execute(
        "UPDATE mobile_events SET status=?,status_description=?,"
        "home_score=COALESCE(?,home_score),away_score=COALESCE(?,away_score),"
        "kickoff=COALESCE(?,kickoff) "
        "WHERE event_id=?",
        [
            update["status"],
            update["status_description"],
            update["home_score"],
            update["away_score"],
            update.get("kickoff"),
            event_id,
        ],
    )

    remote = client.query(
        "SELECT competition_key,event_id,status,status_description,home_score,away_score,kickoff "
        "FROM mobile_events WHERE event_id=?",
        [event_id],
    )
    if not remote:
        key = slugify(competition.get("key"))
        client.execute(
            "INSERT INTO mobile_events (competition_key,event_id,competition_name,"
            "season_name,round_name,stage,kickoff,status,status_description,"
            "home_team_id,home_team,away_team_id,away_team,home_score,away_score,"
            "analysis_status,headline_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                key,
                event_id,
                row["competition_name"],
                row.get("season_name"),
                None,
                None,
                row["kickoff"],
                update["status"],
                update["status_description"],
                row.get("home_team_id"),
                row["home_team"],
                row.get("away_team_id"),
                row["away_team"],
                update["home_score"],
                update["away_score"],
                "pending",
                "{}",
            ],
        )
        remote = client.query(
            "SELECT competition_key,event_id,status,status_description,home_score,away_score,kickoff "
            "FROM mobile_events WHERE event_id=?",
            [event_id],
        )

    if not remote:
        raise RuntimeError(f"Turso no contiene mobile_event después del upsert: {event_id}")
    for got in remote:
        if str(got.get("status") or "").upper() != str(update["status"]).upper():
            raise RuntimeError(f"Estado Turso no verificado para event_id={event_id}: {got}")
        if update["home_score"] is not None and int(got.get("home_score")) != update["home_score"]:
            raise RuntimeError(f"Marcador local Turso no verificado: event_id={event_id}")
        if update["away_score"] is not None and int(got.get("away_score")) != update["away_score"]:
            raise RuntimeError(f"Marcador visitante Turso no verificado: event_id={event_id}")
        if update.get("kickoff") and parse_dt(got.get("kickoff")) != parse_dt(update["kickoff"]):
            raise RuntimeError(f"Kickoff Turso no verificado: event_id={event_id}")
    return len(remote)


def normalized_lineup_payload(
    row: dict[str, Any],
    snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Convierte la alineación verificada de Futbol24 al contrato móvil.

    El documento se guarda separado de las estadísticas originales: no inventa
    SOT ni altera los históricos. Cuando no haya alineación nueva, el móvil usa
    el último documento real guardado para cada equipo.
    """
    raw_lineups = snapshot.get("lineups") if isinstance(snapshot, dict) else None
    if not isinstance(raw_lineups, dict):
        return None

    event_id = int(row["event_id"])

    def side(name: str, team_id: Any) -> dict[str, Any]:
        raw_side = raw_lineups.get(name)
        if not isinstance(raw_side, dict):
            raw_side = {}

        def players(key: str) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for index, raw in enumerate(raw_side.get(key) or [], start=1):
                if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
                    continue
                order = raw.get("position") if key == "lineups" else raw.get("order")
                result.append(
                    {
                        "player_id": None,
                        "name": str(raw.get("name") or "").strip(),
                        "position": raw.get("position_name") or raw.get("position"),
                        "shirt_number": raw.get("jersey"),
                        "lineup_order": order if order is not None else index,
                        "minutes_played": None,
                        "shots": None,
                        "shots_on_target": None,
                        "avg_shots_on_target": None,
                        "sot_sample": 0,
                    }
                )
            return result

        return {
            "team_id": int(team_id) if team_id is not None else None,
            "source_match_id": event_id,
            "source_event_id": event_id,
            "is_current_event_lineup": True,
            "formation": raw_side.get("formation"),
            "starters": players("lineups"),
            "substitutes": players("bench"),
        }

    payload = {
        "event_id": event_id,
        "match_id": row.get("match_id"),
        "home": side("home", row.get("home_team_id")),
        "away": side("away", row.get("away_team_id")),
    }
    if not any(
        payload[name][bucket]
        for name in ("home", "away")
        for bucket in ("starters", "substitutes")
    ):
        return None
    return payload


def publish_lineup_snapshot(
    client: Any,
    row: dict[str, Any],
    competition: dict[str, Any],
    payload: dict[str, Any],
    updated_at: str,
) -> None:
    event_id = int(row["event_id"])
    competition_key = slugify(competition.get("key"))
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    client.execute(
        "INSERT INTO mobile_analysis_docs "
        "(competition_key,event_id,doc_name,json_text,source_mtime) VALUES (?,?,?,?,?) "
        "ON CONFLICT (competition_key,event_id,doc_name) DO UPDATE SET "
        "json_text=excluded.json_text,source_mtime=excluded.source_mtime",
        [competition_key, event_id, "lineups", encoded, utc_now().timestamp()],
    )

    for side_name in ("home", "away"):
        side = payload.get(side_name)
        if not isinstance(side, dict) or not (side.get("starters") or side.get("substitutes")):
            continue
        team_id = side.get("team_id")
        if team_id is None:
            continue
        latest = json.dumps(
            {
                "source_event_id": event_id,
                "kickoff": row.get("kickoff"),
                "updated_at": updated_at,
                "side": side,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        client.execute(
            "INSERT INTO mobile_sync_meta (key,value) VALUES (?,?) "
            "ON CONFLICT (key) DO UPDATE SET value=excluded.value",
            [f"lineup_latest:{int(team_id)}", latest],
        )

    check = client.query(
        "SELECT doc_name FROM mobile_analysis_docs "
        "WHERE competition_key=? AND event_id=? AND doc_name='lineups'",
        [competition_key, event_id],
    )
    if len(check) != 1:
        raise RuntimeError(f"Alineación Turso no verificada: event_id={event_id}")


def normalized_final_actuals_payload(
    row: dict[str, Any],
    snapshot: dict[str, Any] | None,
    updated_at: str,
) -> dict[str, Any] | None:
    if str((snapshot or {}).get("state") or "").lower() != "finished":
        return None
    raw = snapshot.get("final_actuals") if isinstance(snapshot, dict) else None
    real = raw.get("real") if isinstance(raw, dict) else None
    if not isinstance(real, dict):
        return None
    return {
        **raw,
        "event_id": int(row["event_id"]),
        "match_id": row.get("match_id"),
        "updated_at": updated_at,
    }


def publish_final_actuals(
    client: Any,
    row: dict[str, Any],
    competition: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    event_id = int(row["event_id"])
    competition_key = slugify(competition.get("key"))
    existing_rows = client.query(
        "SELECT json_text FROM mobile_analysis_docs WHERE competition_key=? "
        "AND event_id=? AND doc_name='expected_real_actuals' LIMIT 1",
        [competition_key, event_id],
    )
    existing: dict[str, Any] = {}
    if existing_rows:
        try:
            existing = json.loads(str(existing_rows[0].get("json_text") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            existing = {}
    payload = merge_final_actuals_payload(existing, payload)
    real = payload.get("real") or {}
    client.execute(
        "UPDATE matches SET home_goals_1h=COALESCE(?,home_goals_1h),"
        "away_goals_1h=COALESCE(?,away_goals_1h),"
        "home_goals_2h=COALESCE(?,home_goals_2h),"
        "away_goals_2h=COALESCE(?,away_goals_2h) WHERE sofascore_id=?",
        [
            real.get("home_goals_1h"),
            real.get("away_goals_1h"),
            real.get("home_goals_2h"),
            real.get("away_goals_2h"),
            event_id,
        ],
    )
    client.execute(
        "INSERT INTO mobile_analysis_docs "
        "(competition_key,event_id,doc_name,json_text,source_mtime) VALUES (?,?,?,?,?) "
        "ON CONFLICT (competition_key,event_id,doc_name) DO UPDATE SET "
        "json_text=excluded.json_text,source_mtime=excluded.source_mtime",
        [
            competition_key,
            event_id,
            "expected_real_actuals",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            utc_now().timestamp(),
        ],
    )
    check = client.query(
        "SELECT doc_name FROM mobile_analysis_docs WHERE competition_key=? "
        "AND event_id=? AND doc_name='expected_real_actuals'",
        [competition_key, event_id],
    )
    if len(check) != 1:
        raise RuntimeError(f"Estadísticas finales Turso no verificadas: event_id={event_id}")


def publish_exact_actuals_file(client: Any, path_value: str) -> int:
    """Publish exact-ID statistics fetched by an allowed deployment runner."""
    path = Path(str(path_value or "").strip())
    if not str(path_value or "").strip() or not path.is_file():
        return 0
    document = json.loads(path.read_text(encoding="utf-8"))
    items = document.get("events") if isinstance(document, dict) else None
    if not isinstance(items, list):
        return 0
    published = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        event_id = int(item.get("event_id") or 0)
        competition_key = slugify(item.get("competition_key"))
        payload = item.get("final_actuals")
        if event_id <= 0 or not competition_key or not isinstance(payload, dict):
            continue
        if not final_actuals_core_complete(payload):
            continue
        payload = {
            **payload,
            "event_id": event_id,
            "updated_at": str(item.get("updated_at") or iso_utc(utc_now())),
        }
        publish_final_actuals(
            client,
            {"event_id": event_id, "match_id": event_id},
            {"key": competition_key},
            payload,
        )
        published += 1
    return published


def update_local_final_actuals(row: dict[str, Any], payload: dict[str, Any]) -> None:
    real = payload.get("real") or {}
    con = connect_db(read_only=False)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "UPDATE matches SET home_goals_1h=COALESCE(?,home_goals_1h),"
            "away_goals_1h=COALESCE(?,away_goals_1h),"
            "home_goals_2h=COALESCE(?,home_goals_2h),"
            "away_goals_2h=COALESCE(?,away_goals_2h) "
            "WHERE match_id=? AND sofascore_id=?",
            [
                real.get("home_goals_1h"), real.get("away_goals_1h"),
                real.get("home_goals_2h"), real.get("away_goals_2h"),
                int(row["match_id"]), int(row["event_id"]),
            ],
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def update_local(row: dict[str, Any], update: dict[str, Any], updated_at: str) -> None:
    con = connect_db(read_only=False)
    try:
        con.execute("BEGIN IMMEDIATE")
        changed = con.execute(
            "UPDATE matches SET status=?,home_goals=COALESCE(?,home_goals),"
            "away_goals=COALESCE(?,away_goals),kickoff=COALESCE(?,kickoff),updated_at=? "
            "WHERE match_id=? AND sofascore_id=?",
            [
                update["status"],
                update["home_score"],
                update["away_score"],
                update.get("kickoff"),
                updated_at,
                int(row["match_id"]),
                int(row["event_id"]),
            ],
        ).rowcount
        if changed != 1:
            raise RuntimeError(f"Identidad local cambió para event_id={row['event_id']}")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def reconcile_local_finals(
    con: sqlite3.Connection,
    now: datetime,
    hours: int,
    limit: int,
) -> list[dict[str, Any]]:
    if hours <= 0 or limit <= 0:
        return []
    rows = con.execute(
        MATCH_SELECT + " ORDER BY m.kickoff DESC LIMIT ?",
        (iso_utc(now - timedelta(hours=hours)), iso_utc(now), limit),
    ).fetchall()
    return [
        dict(row)
        for row in rows
        if str(row["status"] or "").upper() in FINAL_STATUSES
        and row["home_goals"] is not None
        and row["away_goals"] is not None
    ]


def run(
    *,
    now: datetime,
    dry_run: bool,
    near_limit: int,
    overdue_limit: int,
    reconcile_hours: int,
    reconcile_limit: int,
    event_ids: Iterable[int] = (),
) -> dict[str, Any]:
    competitions = registry_by_league()
    priority_ids = tuple(event_ids)
    client = None if dry_run else turso_client()
    schedule_catalog = (
        publish_schedule_catalog(client, now, competitions)
        if client is not None
        else {"result": "DRY_RUN"}
    )
    exact_actuals_published = (
        publish_exact_actuals_file(
            client, os.environ.get("ODDSHUNTER_EXACT_ACTUALS_FILE", "")
        )
        if client is not None
        else 0
    )
    with connect_db(read_only=True) as con:
        candidates = select_candidates(
            con,
            now,
            near_limit=near_limit,
            overdue_limit=overdue_limit,
        )
        explicit = select_event_ids(con, priority_ids)
        local_finals = reconcile_local_finals(
            con,
            now,
            reconcile_hours,
            reconcile_limit,
        )
    remote = (
        select_remote_candidates(
            client,
            now,
            competitions,
            event_ids=priority_ids,
            near_limit=near_limit,
            overdue_limit=overdue_limit,
        )
        if client is not None
        else []
    )
    merged: dict[int, dict[str, Any]] = {}
    for row in [*explicit, *candidates, *remote]:
        merged.setdefault(int(row["event_id"]), row)
    candidates = list(merged.values())
    seed_days, seed_event_ids = seed_schedule_coverage()
    candidates = [
        row for row in candidates
        if (
            parse_dt(row.get("kickoff")) is None
            or parse_dt(row.get("kickoff")).astimezone(ECUADOR_TZ).date().isoformat() not in seed_days
            or int(row["event_id"]) in seed_event_ids
        )
    ]

    report: dict[str, Any] = {
        "generated_at": iso_utc(now),
        "dry_run": dry_run,
        "schedule_catalog": schedule_catalog,
        "candidate_count": len(candidates),
        "reconcile_count": len(local_finals),
        "exact_actuals_published": exact_actuals_published,
        "events": [],
    }
    provider_messages: list[str] = []

    def provider_logger(message: str) -> None:
        print(f"LIVE-SOURCE> {message}")
        provider_messages.append(str(message))

    sofa = SofaScoreEventClient(logger=provider_logger)
    f24 = Futbol24Client(project_root=ROOT, logger=provider_logger)
    try:
        for row in candidates:
            message_start = len(provider_messages)
            item: dict[str, Any] = {
                "event_id": int(row["event_id"]),
                "match": f"{row['home_team']} vs {row['away_team']}",
                "kickoff": row["kickoff"],
            }
            competition = competitions.get(int(row["league_id"]))
            if not competition:
                item["result"] = "SKIP_UNKNOWN_COMPETITION"
                report["events"].append(item)
                continue
            try:
                snapshot = verified_schedule_snapshot(row)
                update = normalized_update(snapshot) if snapshot is not None else None
                if snapshot is not None:
                    item["source"] = "verified-schedule-correction"
                else:
                    try:
                        snapshot = sofa.get_match_snapshot(row)
                        update = normalized_update(snapshot)
                        item["source"] = "sofascore-event-id"
                    except Exception as exc:
                        provider_logger(f"SofaScore exacto falló event_id={row['event_id']}; respaldo Futbol24: {exc}")
                    if update is None:
                        snapshot = f24.get_match_snapshot(match_ref(row, competition))
                        update = normalized_update(snapshot) if isinstance(snapshot, dict) else None
                        item["source"] = "futbol24-name-fallback"
                if (
                    update is not None
                    and update.get("state") == "finished"
                    and isinstance(snapshot, dict)
                    and not final_actuals_core_complete(snapshot.get("final_actuals"))
                ):
                    enrichment = f24.get_match_snapshot(match_ref(row, competition))
                    if (
                        isinstance(enrichment, dict)
                        and enrichment.get("home_goals") == update.get("home_score")
                        and enrichment.get("away_goals") == update.get("away_score")
                    ):
                        snapshot = {
                            **snapshot,
                            "lineups": enrichment.get("lineups") or snapshot.get("lineups"),
                            "final_actuals": enrichment.get("final_actuals"),
                        }
                        item["source"] = f"{item.get('source')}+futbol24-final-actuals"
                item["snapshot"] = snapshot
                if not isinstance(snapshot, dict):
                    item["result"] = "SOURCE_UNAVAILABLE"
                else:
                    lineup = normalized_lineup_payload(row, snapshot)
                    final_actuals = normalized_final_actuals_payload(
                        row, snapshot, iso_utc(utc_now())
                    )
                    if update is None:
                        item["result"] = "NO_ACTION"
                    elif dry_run:
                        item["update"] = update
                        item["result"] = "DRY_RUN_READY"
                    else:
                        stamp = iso_utc(utc_now())
                        publish_remote(client, row, competition, update, stamp)
                        if not row.get("remote_only"):
                            update_local(row, update, stamp)
                        if final_actuals is not None:
                            publish_final_actuals(
                                client, row, competition, final_actuals
                            )
                            if not row.get("remote_only"):
                                update_local_final_actuals(row, final_actuals)
                            item["final_actuals"] = "PUBLISHED"
                        item["update"] = update
                        item["result"] = "PUBLISHED"
                    if lineup is not None:
                        if dry_run:
                            item["lineup"] = "DRY_RUN_READY"
                        else:
                            stamp = iso_utc(utc_now())
                            publish_lineup_snapshot(
                                client, row, competition, lineup, stamp
                            )
                            item["lineup"] = "PUBLISHED"
            except Exception as exc:
                item["result"] = "TECHNICAL_ERROR"
                item["error"] = f"{type(exc).__name__}: {exc}"
            item["provider_log"] = provider_messages[message_start:][-30:]
            report["events"].append(item)
    finally:
        f24.close()

    # One-time/local reconciliation: no provider request is necessary because
    # these rows already passed the final-result identity/score gates.
    for row in local_finals:
        item = {
            "event_id": int(row["event_id"]),
            "match": f"{row['home_team']} vs {row['away_team']}",
            "reconciliation": True,
        }
        competition = competitions.get(int(row["league_id"]))
        if not competition:
            item["result"] = "SKIP_UNKNOWN_COMPETITION"
        else:
            update = {
                "status": "FT",
                "status_description": "finished",
                "home_score": int(row["home_goals"]),
                "away_score": int(row["away_goals"]),
                "state": "finished",
            }
            try:
                if dry_run:
                    item["result"] = "DRY_RUN_RECONCILE"
                else:
                    publish_remote(client, row, competition, update, iso_utc(utc_now()))
                    item["result"] = "RECONCILED"
            except Exception as exc:
                item["result"] = "TECHNICAL_ERROR"
                item["error"] = f"{type(exc).__name__}: {exc}"
        report["events"].append(item)

    if client is not None and schedule_catalog.get("result") == "PUBLISHED":
        expected_ids = [int(value) for value in schedule_catalog.get("event_ids", [])]
        if expected_ids:
            local_today = now.astimezone(ECUADOR_TZ).date()
            schedule_start = datetime.combine(local_today - timedelta(days=1), datetime.min.time(), ECUADOR_TZ)
            schedule_end = schedule_start + timedelta(days=3)
            placeholders = ",".join("?" for _ in expected_ids)
            client.execute(
                f"DELETE FROM mobile_events WHERE datetime(kickoff)>=datetime(?) AND datetime(kickoff)<datetime(?) "
                f"AND event_id NOT IN ({placeholders})",
                [iso_utc(schedule_start), iso_utc(schedule_end), *expected_ids],
            )

    counts: dict[str, int] = {}
    for item in report["events"]:
        result = str(item.get("result") or "UNKNOWN")
        counts[result] = counts.get(result, 0) + 1
    report["counts"] = counts
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OddsHunter live/final score publisher")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--near-limit",
        type=int,
        default=int(os.environ.get("ODDSHUNTER_LIVE_NEAR_LIMIT", "48")),
    )
    parser.add_argument(
        "--overdue-limit",
        type=int,
        default=int(os.environ.get("ODDSHUNTER_LIVE_OVERDUE_LIMIT", "24")),
    )
    parser.add_argument(
        "--reconcile-terminal-hours",
        type=int,
        default=int(os.environ.get("ODDSHUNTER_LIVE_RECONCILE_HOURS", "0")),
    )
    parser.add_argument(
        "--reconcile-terminal-limit",
        type=int,
        default=int(os.environ.get("ODDSHUNTER_LIVE_RECONCILE_LIMIT", "200")),
    )
    priority_ids = [
        int(part.strip())
        for part in os.environ.get("ODDSHUNTER_LIVE_PRIORITY_EVENT_IDS", "").split(",")
        if part.strip()
    ]
    parser.add_argument("--event-id", type=int, action="append", default=priority_ids)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.dry_run:
        require_write_gates()
    report = run(
        now=utc_now(),
        dry_run=bool(args.dry_run),
        near_limit=max(1, min(80, int(args.near_limit))),
        overdue_limit=max(1, min(40, int(args.overdue_limit))),
        reconcile_hours=max(0, min(168, int(args.reconcile_terminal_hours))),
        reconcile_limit=max(0, min(1000, int(args.reconcile_terminal_limit))),
        event_ids=args.event_id,
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    errors = int(report.get("counts", {}).get("TECHNICAL_ERROR", 0))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
