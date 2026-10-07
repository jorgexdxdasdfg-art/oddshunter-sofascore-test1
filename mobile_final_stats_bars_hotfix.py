#!/usr/bin/env python3
"""One-time verified final-statistics and 1X2 repair for 2026-10-06."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


NATIONS = "uefa-nations-league"
MODEL = "NATIONS_CONTEXT_ELO_50_50_STRICT_CUTOFF"
PATCHES = {
    15534082: {"key": NATIONS, "prob": [14.9816, 16.2347, 68.7837], "score": [1, 2], "stats": [[28, 72], [1.02, 1.15], [10, 10], [5, 3], [4, 4], [1, 2], [3, 6], [0, 2], [1, 0], [12, 10]]},
    15534091: {"key": NATIONS, "prob": [75.8000, 13.1535, 11.0464], "score": [3, 0], "stats": [[64, 36], [2.05, 0.17], [17, 5], [3, 0], [4, 0], [1, 2], [6, 2], [0, 0], [0, 0], [10, 17]]},
    15534108: {"key": NATIONS, "prob": [45.9933, 26.6094, 27.3972], "score": [1, 2], "stats": [[54, 46], [2.17, 1.33], [12, 10], [6, 3], [2, 4], [2, 4], [1, 4], [0, 1], [0, 0], [11, 16]]},
    15534114: {"key": NATIONS, "prob": [69.0125, 17.6102, 13.3773], "score": [3, 0], "stats": [[57, 43], [1.54, 0.31], [20, 3], [7, 0], [4, 1], [0, 1], [8, 3], [1, 2], [0, 0], [12, 14]]},
    15534144: {"key": NATIONS, "prob": [82.2565, 11.6401, 6.1034], "score": [2, 1], "stats": [[70, 30], [2.70, 0.55], [26, 8], [7, 3], [3, 1], [1, 4], [10, 1], [0, 1], [0, 0], [12, 21]]},
    15534148: {"key": NATIONS, "prob": [34.5656, 29.3666, 36.0678], "score": [1, 0], "stats": [[26, 74], [1.02, 0.65], [6, 14], [2, 2], [1, 1], [4, 2], [1, 5], [0, 1], [0, 0], [17, 11]]},
    15534236: {"key": NATIONS, "prob": [31.1598, 27.7273, 41.1128], "score": [0, 0], "stats": [[38, 62], [1.10, 0.58], [13, 12], [3, 1], [1, 1], [1, 1], [3, 7], [1, 0], [0, 0], [10, 9]]},
    15537771: {"key": NATIONS, "prob": [41.5991, 28.9717, 29.4292], "score": [0, 2], "stats": [[62, 38], [1.88, 0.87], [17, 13], [7, 5], [2, 2], [1, 3], [5, 4], [2, 1], [0, 0], [15, 15]]},
    15534189: {"key": NATIONS, "score": [2, 2], "stats": [[67, 33], [2.12, 1.20], [24, 15], [4, 4], [2, 1], [1, 1], [5, 8], [3, 1], [1, 1], [8, 9]]},
    15534198: {"key": NATIONS, "score": [0, 4], "stats": [[46, 54], [1.15, 2.14], [17, 14], [5, 6], [1, 5], [2, 0], [8, 3], [2, 4], [0, 0], [15, 9]]},
    16547921: {"key": "mls", "source": "verified_match_feed", "score": [3, 1], "stats": [[48, 52], [None, None], [22, 15], [7, 2], [None, None], [2, 1], [2, 8], [3, 5], [0, 0], [8, 11]]},
}


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--backup-dir", required=True)
    return parser.parse_args()


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def actual_doc(spec: dict, verified_at: str) -> dict:
    possession, xg, shots, sot, big, yellow, corners, offsides, red, fouls = spec["stats"]
    score = spec["score"]
    return {
        "available": True,
        "source": spec.get("source", "fotmob"),
        "verified": True,
        "verified_at": verified_at,
        "real": {
            "home_goals": score[0], "away_goals": score[1],
            "home_possession": possession[0], "away_possession": possession[1],
            "home_xg": xg[0], "away_xg": xg[1],
            "home_shots": shots[0], "away_shots": shots[1],
            "home_sot": sot[0], "away_sot": sot[1],
            "home_big_chances": big[0], "away_big_chances": big[1],
            "home_yellow_cards": yellow[0], "away_yellow_cards": yellow[1],
            "home_corners": corners[0], "away_corners": corners[1],
            "home_offsides": offsides[0], "away_offsides": offsides[1],
            "home_red_cards": red[0], "away_red_cards": red[1],
            "home_fouls": fouls[0], "away_fouls": fouls[1],
        },
        "temporal_xg_available": False,
        "xg_zone_map_available": False,
    }


def upsert_doc(conn: sqlite3.Connection, key: str, event_id: int, payload: dict, stamp: str) -> None:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(mobile_analysis_docs)")}
    names = ["competition_key", "event_id", "doc_name", "json_text", "source_mtime"]
    values = [key, event_id, "expected_real_actuals", text, stamp]
    updates = ["json_text=excluded.json_text", "source_mtime=excluded.source_mtime"]
    if "content_hash" in columns:
        names.append("content_hash")
        values.append(hashlib.sha256(text.encode("utf-8")).hexdigest())
        updates.append("content_hash=excluded.content_hash")
    conn.execute(
        f"INSERT INTO mobile_analysis_docs({','.join(names)}) VALUES({','.join('?' for _ in names)}) "
        "ON CONFLICT(competition_key,event_id,doc_name) DO UPDATE SET " + ",".join(updates),
        values,
    )


def main() -> int:
    options = args()
    db = Path(options.db).resolve()
    backup_dir = Path(options.backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    backup = backup_dir / f"{db.stem}.before-final-stats-bars-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.db"
    conn = sqlite3.connect(db, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    try:
        for table in ("mobile_events", "mobile_analysis_docs"):
            if not table_exists(conn, table):
                raise RuntimeError(f"MISSING_TABLE:{table}")
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        missing = []
        for event_id, spec in PATCHES.items():
            if conn.execute(
                "SELECT 1 FROM mobile_events WHERE competition_key=? AND event_id=?",
                (spec["key"], event_id),
            ).fetchone() is None:
                missing.append(event_id)
        if missing:
            raise RuntimeError(f"MISSING_EVENTS:{missing}")
        conn.execute("BEGIN IMMEDIATE")
        for event_id, spec in PATCHES.items():
            if "prob" in spec:
                home, draw, away = spec["prob"]
                headline = json.dumps({
                    "home_win": round(home, 1), "draw": round(draw, 1), "away_win": round(away, 1),
                    "model": MODEL, "reconstructed_after_match": True, "strict_pre_kickoff_cutoff": True,
                }, ensure_ascii=False, separators=(",", ":"))
                conn.execute(
                    "UPDATE mobile_events SET analysis_status='DATOS REALES',headline_json=? "
                    "WHERE competition_key=? AND event_id=?",
                    (headline, spec["key"], event_id),
                )
            else:
                conn.execute(
                    "UPDATE mobile_events SET analysis_status='DATOS REALES' WHERE competition_key=? AND event_id=?",
                    (spec["key"], event_id),
                )
            upsert_doc(conn, spec["key"], event_id, actual_doc(spec, stamp), stamp)
            if table_exists(conn, "mobile_match_payloads"):
                conn.execute(
                    "DELETE FROM mobile_match_payloads WHERE competition_key=? AND event_id=?",
                    (spec["key"], event_id),
                )
        conn.commit()
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("INTEGRITY_CHECK_FAILED")
        doc_count = conn.execute(
            "SELECT COUNT(*) FROM mobile_analysis_docs WHERE doc_name='expected_real_actuals' "
            f"AND event_id IN ({','.join('?' for _ in PATCHES)})",
            tuple(PATCHES),
        ).fetchone()[0]
        bar_count = 0
        for event_id, spec in PATCHES.items():
            if "prob" not in spec:
                continue
            row = conn.execute(
                "SELECT headline_json FROM mobile_events WHERE competition_key=? AND event_id=?",
                (spec["key"], event_id),
            ).fetchone()
            head = json.loads(row[0] or "{}")
            bar_count += int(all(head.get(name) is not None for name in ("home_win", "draw", "away_win")))
        result = {
            "status": "PASS", "backup": str(backup), "events": len(PATCHES),
            "actual_docs": int(doc_count), "reconstructed_bars": bar_count,
            "integrity_check": "ok",
        }
        if doc_count != len(PATCHES) or bar_count != 8:
            raise RuntimeError(f"POST_VERIFY_FAILED:{result}")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
