from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

import import_competition_stats as importer
from flashscore_xg_client import FlashscoreXGClient
from futbol24_client import Futbol24Client
from xg_pipeline import MatchRef


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "oddshunter.db"
REGISTRY_PATH = DATA_DIR / "competitions.json"
REPORT_DIR = DATA_DIR / "automation" / "cloud_incremental_results"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: Any) -> str:
    import re
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} no contiene un objeto JSON.")
    return data


def find_competition(registry: dict[str, Any], key: str) -> dict[str, Any]:
    expected = slugify(key)
    for item in registry.get("competitions", []):
        if isinstance(item, dict) and slugify(item.get("key")) == expected:
            return item
    raise KeyError(f"Competición no configurada: {key}")


def _parse_kickoff(value: Any) -> tuple[str, int]:
    text = str(value or "").strip()
    if not text:
        return "", 0
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(), int(parsed.timestamp())


def _schedule_row(key: str, event_id: int) -> dict[str, Any] | None:
    path = DATA_DIR / "competitions" / key / "matches_upcoming.json"
    if not path.exists():
        return None
    try:
        document = read_json(path)
    except Exception:
        return None
    rows = document.get("matches")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            if int(row.get("event_id")) == int(event_id):
                return dict(row)
        except (TypeError, ValueError):
            continue
    return None


def _db_row(event_id: int) -> dict[str, Any] | None:
    if not DB_PATH.exists():
        return None
    uri = f"file:{DB_PATH.resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    try:
        row = con.execute(
            """
            SELECT
                m.sofascore_id AS event_id,
                m.kickoff,
                m.home_goals,
                m.away_goals,
                m.status,
                h.sofascore_id AS home_team_id,
                h.name AS home_team,
                a.sofascore_id AS away_team_id,
                a.name AS away_team
            FROM matches AS m
            JOIN teams AS h ON h.team_id=m.home_team_id
            JOIN teams AS a ON a.team_id=m.away_team_id
            WHERE m.sofascore_id=?
            LIMIT 1
            """,
            (int(event_id),),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        con.close()


def load_match(competition: dict[str, Any], event_id: int) -> dict[str, Any]:
    key = slugify(competition["key"])
    # A persisted match may already have a protected, validated identity.  The
    # schedule cache can be older (or point at another league row), so it must
    # never override the database identity during a result-only update.
    row = _db_row(event_id) or _schedule_row(key, event_id)
    if not isinstance(row, dict):
        raise KeyError(
            f"No existe identidad local para event_id={event_id}. "
            "Stage1 no inventa partidos nuevos."
        )

    kickoff, timestamp = _parse_kickoff(
        row.get("kickoff")
        or (
            datetime.fromtimestamp(
                int(row.get("start_timestamp") or 0),
                tz=timezone.utc,
            ).isoformat()
            if int(row.get("start_timestamp") or 0) > 0
            else ""
        )
    )
    if timestamp <= 0:
        raise ValueError(f"event_id={event_id}: kickoff inválido.")

    row.update(
        {
            "event_id": int(event_id),
            "kickoff": kickoff,
            "start_timestamp": timestamp,
            "competition_id": (
                row.get("competition_id")
                or competition.get("source_competition_id")
            ),
            "competition_name": (
                row.get("competition_name")
                or competition.get("name")
            ),
            "season_id": row.get("season_id") or competition.get("season_id"),
            "season_name": (
                row.get("season_name")
                or competition.get("season_name")
                or competition.get("season")
                or ""
            ),
            "_competition_key": key,
            "_competition_country": str(competition.get("country") or ""),
            "_registry_name": str(competition.get("name") or ""),
            "_registry_season": str(
                competition.get("season_name")
                or competition.get("season")
                or ""
            ),
            "_registry_tournament_id": competition.get("source_competition_id"),
            "_registry_season_id": competition.get("season_id"),
        }
    )
    return row


def match_ref(match: dict[str, Any]) -> MatchRef:
    return MatchRef(
        match_id=None,
        kickoff=str(match["kickoff"]),
        home_team=str(match["home_team"]),
        away_team=str(match["away_team"]),
        competition=str(match["competition_name"]),
        season=str(match.get("season_name") or ""),
        sofascore_event_id=int(match["event_id"]),
        competition_id=(
            int(match["competition_id"])
            if match.get("competition_id") is not None
            else None
        ),
        season_id=(
            int(match["season_id"])
            if match.get("season_id") is not None
            else None
        ),
        home_goals=match.get("home_goals"),
        away_goals=match.get("away_goals"),
        flashscore_url=(
            str(match["flashscore_url"]) if match.get("flashscore_url") else None
        ),
    )


def require_cloud_write_gate() -> None:
    if str(os.environ.get("ODDSHUNTER_RUNTIME_MODE") or "").strip().lower() != "cloud":
        raise RuntimeError(
            "WRITE GATE cerrado: define ODDSHUNTER_RUNTIME_MODE=cloud."
        )
    if str(os.environ.get("ODDSHUNTER_ALLOW_WORK_DB_WRITE") or "").strip() != "1":
        raise RuntimeError(
            "WRITE GATE cerrado: define ODDSHUNTER_ALLOW_WORK_DB_WRITE=1."
        )
    if not DB_PATH.exists():
        raise FileNotFoundError(
            "No existe data/oddshunter.db dentro del runtime cloud."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "OddsHunter cloud Stage1: Futbol24 para estado/marcador y métricas, "
            "Flashscore solo para residuales. SofaScore está desactivado."
        )
    )
    parser.add_argument("--key", required=True)
    parser.add_argument("--event-id", type=int, action="append", required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No escribe SQLite aunque el partido haya terminado.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    registry = read_json(REGISTRY_PATH)
    competition = find_competition(registry, args.key)
    event_ids = sorted(set(int(x) for x in args.event_id))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "generated_at": utc_now(),
        "source_policy": {
            "sofascore": "OFF",
            "status_score": ["futbol24"],
            "metrics": ["futbol24", "flashscore"],
        },
        "competition_key": slugify(competition["key"]),
        "dry_run": bool(args.dry_run),
        "events": [],
    }

    if not args.dry_run:
        require_cloud_write_gate()

    f24 = Futbol24Client(
        project_root=BASE_DIR,
        logger=lambda msg: print(f"F24> {msg}"),
    )
    try:
        for event_id in event_ids:
            item: dict[str, Any] = {"event_id": event_id}
            try:
                match = load_match(competition, event_id)
                reference = match_ref(match)
                snapshot = f24.get_match_snapshot(reference)
                item["snapshot"] = snapshot

                if not isinstance(snapshot, dict):
                    item["result"] = "SOURCE_UNAVAILABLE"
                    report["events"].append(item)
                    continue

                state = str(snapshot.get("state") or "unknown")
                item["state"] = state

                if state != "finished":
                    item["result"] = (
                        "TERMINAL" if state == "terminal" else "NOT_FINISHED"
                    )
                    report["events"].append(item)
                    continue

                if snapshot.get("home_goals") is None or snapshot.get("away_goals") is None:
                    item["result"] = "SOURCE_UNAVAILABLE_SCORE"
                    report["events"].append(item)
                    continue

                match["home_goals"] = snapshot["home_goals"]
                match["away_goals"] = snapshot["away_goals"]
                match["status"] = "FT"
                match["futbol24_url"] = snapshot.get("futbol24_url")

                stats_json: dict[str, Any] = {"statistics": []}

                # Flashscore/Chromium is created only after Futbol24 has
                # positively resolved the match. This avoids spawning a
                # browser for SOURCE_UNAVAILABLE candidates and removes the
                # Playwright pending-task warnings seen in Stage5 V3.
                with sync_playwright() as playwright:
                    flash = FlashscoreXGClient(
                        playwright,
                        project_root=BASE_DIR,
                        logger=lambda msg: print(f"FLASH> {msg}"),
                    )
                    try:
                        xg_result = importer.recuperar_xg_partido(
                            match,
                            None,
                            stats_json,
                            f24,
                            flash,
                            DATA_DIR / "raw_cloud" / slugify(competition["key"]),
                        )
                        metric_result = importer.recuperar_metricas_partido(
                            match,
                            None,
                            stats_json,
                            f24,
                            flash,
                            DATA_DIR / "raw_cloud" / slugify(competition["key"]),
                        )
                    finally:
                        flash.close()

                item["xg"] = xg_result.to_dict()
                item["metrics"] = metric_result.to_dict()

                if args.dry_run:
                    item["result"] = "DRY_RUN_READY"
                else:
                    match_id, quality = importer.guardar_partido(
                        match,
                        None,
                        stats_json,
                        xg_result,
                        metric_result,
                    )
                    item["match_id"] = int(match_id)
                    item["quality"] = quality
                    item["result"] = "COMMITTED"
            except Exception as exc:
                item["result"] = "TECHNICAL_ERROR"
                item["error"] = f"{type(exc).__name__}: {exc}"
            report["events"].append(item)
    finally:
        f24.close()

    out = REPORT_DIR / "last.json"
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"REPORT={out}")
    return 0 if all(
        row.get("result") not in {"TECHNICAL_ERROR"}
        for row in report["events"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
