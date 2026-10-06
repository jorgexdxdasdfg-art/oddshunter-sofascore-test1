#!/usr/bin/env python3
"""Import the three-day mobile catalog into the SQLite database served by Mobile."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


EVENT_COLUMNS = (
    "competition_key", "event_id", "competition_name", "season_name",
    "round_name", "stage", "kickoff", "status", "status_description",
    "home_team_id", "home_team", "away_team_id", "away_team",
    "home_score", "away_score", "analysis_status", "headline_json",
)
PROTECTED_STATUSES = (
    "FT", "AET", "PEN", "FINISHED", "FINAL", "ENDED", "LIVE",
    "INPROGRESS", "HT", "POSTPONED", "CANCELED", "CANCELLED", "ABANDONED",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--expected-day", required=True)
    parser.add_argument("--expected-count", required=True, type=int)
    return parser.parse_args()


def load_seed(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value.get("events"), list) or not value["events"]:
        raise RuntimeError("CATALOG_WITHOUT_EVENTS")
    return value


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def backup_database(conn: sqlite3.Connection, db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{db_path.stem}.before-catalog-{stamp}.db"
    with sqlite3.connect(target) as out:
        conn.backup(out)
    return target


def event_upsert_sql() -> str:
    placeholders = ",".join("?" for _ in EVENT_COLUMNS)
    protected = ",".join(f"'{status}'" for status in PROTECTED_STATUSES)
    keep = f"UPPER(COALESCE(mobile_events.status,'')) IN ({protected})"
    return (
        f"INSERT INTO mobile_events ({','.join(EVENT_COLUMNS)}) VALUES ({placeholders}) "
        "ON CONFLICT(competition_key,event_id) DO UPDATE SET "
        "competition_name=excluded.competition_name,season_name=excluded.season_name,"
        "round_name=excluded.round_name,stage=excluded.stage,"
        f"kickoff=CASE WHEN {keep} THEN mobile_events.kickoff ELSE excluded.kickoff END,"
        f"status=CASE WHEN {keep} THEN mobile_events.status ELSE excluded.status END,"
        f"status_description=CASE WHEN {keep} THEN mobile_events.status_description ELSE excluded.status_description END,"
        "home_team_id=excluded.home_team_id,home_team=excluded.home_team,"
        "away_team_id=excluded.away_team_id,away_team=excluded.away_team,"
        f"home_score=CASE WHEN {keep} THEN mobile_events.home_score ELSE COALESCE(excluded.home_score,mobile_events.home_score) END,"
        f"away_score=CASE WHEN {keep} THEN mobile_events.away_score ELSE COALESCE(excluded.away_score,mobile_events.away_score) END,"
        "analysis_status=excluded.analysis_status,headline_json=excluded.headline_json"
    )


def doc_upsert(conn: sqlite3.Connection, row: dict) -> None:
    columns = {str(item[1]) for item in conn.execute("PRAGMA table_info(mobile_analysis_docs)")}
    names = ["competition_key", "event_id", "doc_name", "json_text", "source_mtime"]
    values = [row.get(name) for name in names]
    updates = ["json_text=excluded.json_text", "source_mtime=excluded.source_mtime"]
    if "content_hash" in columns:
        names.append("content_hash")
        values.append(hashlib.sha256(str(row.get("json_text") or "").encode("utf-8")).hexdigest())
        updates.append("content_hash=excluded.content_hash")
    placeholders = ",".join("?" for _ in names)
    sql = (
        f"INSERT INTO mobile_analysis_docs ({','.join(names)}) VALUES ({placeholders}) "
        "ON CONFLICT(competition_key,event_id,doc_name) DO UPDATE SET "
        + ",".join(updates)
        + " WHERE COALESCE(julianday(excluded.source_mtime),"
        "julianday(excluded.source_mtime,'unixepoch'),0) "
        ">= COALESCE(julianday(mobile_analysis_docs.source_mtime),"
        "julianday(mobile_analysis_docs.source_mtime,'unixepoch'),0)"
    )
    conn.execute(sql, tuple(values))


def ecuador_day(kickoff: str) -> str:
    parsed = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone(timedelta(hours=-5))).date().isoformat()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).resolve()
    seed_path = Path(args.seed).resolve()
    seed = load_seed(seed_path)
    expected_ids = {
        int(row["event_id"]) for row in seed["events"]
        if ecuador_day(row["kickoff"]) == args.expected_day
    }
    if len(expected_ids) != args.expected_count:
        raise RuntimeError(
            f"SEED_EXPECTED_COUNT_MISMATCH day={args.expected_day} "
            f"expected={args.expected_count} actual={len(expected_ids)}"
        )

    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        for table in ("mobile_events", "mobile_analysis_docs"):
            if not table_exists(conn, table):
                raise RuntimeError(f"MISSING_TABLE:{table}")
        backup = backup_database(conn, db_path, Path(args.backup_dir))
        before = conn.execute("SELECT COUNT(*) FROM mobile_events").fetchone()[0]
        conn.execute("BEGIN IMMEDIATE")
        sql = event_upsert_sql()
        for row in seed["events"]:
            conn.execute(sql, tuple(row.get(column) for column in EVENT_COLUMNS))
        docs_written = 0
        for row in seed.get("docs") or []:
            if row.get("doc_name") == "odds_value":
                continue
            doc_upsert(conn, row)
            docs_written += 1
        if table_exists(conn, "mobile_sync_meta"):
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO mobile_sync_meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("schedule_catalog_last_publish_at", now),
            )
        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"INTEGRITY_CHECK_FAILED:{integrity}")
        placeholders = ",".join("?" for _ in expected_ids)
        present = {
            int(row[0]) for row in conn.execute(
                f"SELECT event_id FROM mobile_events WHERE event_id IN ({placeholders})",
                tuple(sorted(expected_ids)),
            )
        }
        missing = sorted(expected_ids - present)
        if missing:
            raise RuntimeError(f"EXPECTED_EVENTS_MISSING:{missing}")
        after = conn.execute("SELECT COUNT(*) FROM mobile_events").fetchone()[0]
        print(json.dumps({
            "status": "PASS",
            "backup": str(backup),
            "events_in_seed": len(seed["events"]),
            "docs_written": docs_written,
            "rows_before": before,
            "rows_after": after,
            "inserted_rows": after - before,
            "expected_day": args.expected_day,
            "expected_day_count": len(present),
            "expected_day_event_ids": sorted(present),
            "integrity_check": integrity,
        }, ensure_ascii=False, sort_keys=True))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
