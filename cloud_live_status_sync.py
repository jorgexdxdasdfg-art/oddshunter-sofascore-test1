from __future__ import annotations

"""Refresh current/recent match states and publish them to the mobile API.

This is deliberately separate from the heavy final-result/statistics pipeline:
live scores must be cheap and frequent, while complete statistics are imported
only after a match is final.
"""

import argparse
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
        "AND d.doc_name='expected_real_actuals' LIMIT 1) AS final_actuals_json "
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
        pending_state = status not in SPECIAL_STATUSES and (score_debt or actuals_debt)
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
    competition_key = slugify(competition.get("key"))
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

    report: dict[str, Any] = {
        "generated_at": iso_utc(now),
        "dry_run": dry_run,
        "candidate_count": len(candidates),
        "reconcile_count": len(local_finals),
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
