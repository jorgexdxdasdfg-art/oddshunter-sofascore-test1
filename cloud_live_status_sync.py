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
from xg_pipeline import MatchRef


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB = DATA / "oddshunter.db"
REGISTRY = DATA / "competitions.json"
REPORT = DATA / "automation" / "cloud_live_status" / "last.json"

FINAL_STATUSES = {"FT", "AET", "PEN", "FINISHED", "FINAL"}
SPECIAL_STATUSES = {"CANCELED", "CANCELLED", "POSTPONED", "ABANDONED"}


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


def _pending(row: sqlite3.Row) -> bool:
    status = str(row["status"] or "").upper()
    if status in SPECIAL_STATUSES:
        return False
    return status not in FINAL_STATUSES or row["home_goals"] is None or row["away_goals"] is None


def select_candidates(
    con: sqlite3.Connection,
    now: datetime,
    *,
    near_limit: int,
    overdue_limit: int,
) -> list[dict[str, Any]]:
    floor = now - timedelta(hours=48)
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

    chosen = recent[:near_limit] + fair_overdue[:overdue_limit]
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

    if state == "live":
        return {
            "status": "LIVE",
            "status_description": provider or "live",
            "home_score": int(home) if home is not None else None,
            "away_score": int(away) if away is not None else None,
            "state": state,
        }
    if state == "finished" and home is not None and away is not None:
        return {
            "status": "FT",
            "status_description": provider or "finished",
            "home_score": int(home),
            "away_score": int(away),
            "state": state,
        }
    if state == "terminal":
        token = provider.upper().replace(" ", "_") or "CANCELED"
        return {
            "status": token,
            "status_description": provider or token.lower(),
            "home_score": int(home) if home is not None else None,
            "away_score": int(away) if away is not None else None,
            "state": state,
        }
    return None


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
        updated_at,
        event_id,
    ]
    client.execute(
        "UPDATE matches SET status=?,home_goals=COALESCE(?,home_goals),"
        "away_goals=COALESCE(?,away_goals),updated_at=? WHERE sofascore_id=?",
        params,
    )
    client.execute(
        "UPDATE mobile_events SET status=?,status_description=?,"
        "home_score=COALESCE(?,home_score),away_score=COALESCE(?,away_score) "
        "WHERE event_id=?",
        [
            update["status"],
            update["status_description"],
            update["home_score"],
            update["away_score"],
            event_id,
        ],
    )

    remote = client.query(
        "SELECT competition_key,event_id,status,status_description,home_score,away_score "
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
            "SELECT competition_key,event_id,status,status_description,home_score,away_score "
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
    return len(remote)


def update_local(row: dict[str, Any], update: dict[str, Any], updated_at: str) -> None:
    con = connect_db(read_only=False)
    try:
        con.execute("BEGIN IMMEDIATE")
        changed = con.execute(
            "UPDATE matches SET status=?,home_goals=COALESCE(?,home_goals),"
            "away_goals=COALESCE(?,away_goals),updated_at=? "
            "WHERE match_id=? AND sofascore_id=?",
            [
                update["status"],
                update["home_score"],
                update["away_score"],
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
    with connect_db(read_only=True) as con:
        candidates = select_candidates(
            con,
            now,
            near_limit=near_limit,
            overdue_limit=overdue_limit,
        )
        explicit = select_event_ids(con, event_ids)
        candidates = list(
            {
                int(row["event_id"]): row
                for row in [*explicit, *candidates]
            }.values()
        )
        local_finals = reconcile_local_finals(
            con,
            now,
            reconcile_hours,
            reconcile_limit,
        )

    report: dict[str, Any] = {
        "generated_at": iso_utc(now),
        "dry_run": dry_run,
        "candidate_count": len(candidates),
        "reconcile_count": len(local_finals),
        "events": [],
    }
    client = None if dry_run else turso_client()
    f24 = Futbol24Client(project_root=ROOT, logger=lambda msg: print(f"F24-LIVE> {msg}"))
    try:
        for row in candidates:
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
                snapshot = f24.get_match_snapshot(match_ref(row, competition))
                item["snapshot"] = snapshot
                if not isinstance(snapshot, dict):
                    item["result"] = "SOURCE_UNAVAILABLE"
                else:
                    update = normalized_update(snapshot)
                    if update is None:
                        item["result"] = "NO_ACTION"
                    elif dry_run:
                        item["update"] = update
                        item["result"] = "DRY_RUN_READY"
                    else:
                        stamp = iso_utc(utc_now())
                        publish_remote(client, row, competition, update, stamp)
                        update_local(row, update, stamp)
                        item["update"] = update
                        item["result"] = "PUBLISHED"
            except Exception as exc:
                item["result"] = "TECHNICAL_ERROR"
                item["error"] = f"{type(exc).__name__}: {exc}"
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
        default=int(os.environ.get("ODDSHUNTER_LIVE_NEAR_LIMIT", "24")),
    )
    parser.add_argument(
        "--overdue-limit",
        type=int,
        default=int(os.environ.get("ODDSHUNTER_LIVE_OVERDUE_LIMIT", "12")),
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
