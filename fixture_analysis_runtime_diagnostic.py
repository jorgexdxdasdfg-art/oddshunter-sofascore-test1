from __future__ import annotations

"""Read-only diagnostics for the production complete-fixture selector."""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from fixture_analysis_queue import _parse_dt, has_visible_characteristics, select_pending_fixture_analyses

    registry = json.loads((root / "data" / "competitions.json").read_text(encoding="utf-8-sig"))
    active = [x for x in registry.get("competitions", []) if isinstance(x, dict) and x.get("active")]
    by_league = {int(x["league_id"]): x for x in active if x.get("league_id") is not None}
    con = sqlite3.connect(root / "data" / "oddshunter.db")
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT m.sofascore_id, m.league_id, m.kickoff, m.status, m.season,
               h.sofascore_id AS home_team_id, h.name AS home_team,
               a.sofascore_id AS away_team_id, a.name AS away_team
        FROM matches m
        JOIN teams h ON h.team_id=m.home_team_id
        JOIN teams a ON a.team_id=m.away_team_id
        WHERE m.sofascore_id IS NOT NULL
          AND h.sofascore_id IS NOT NULL
          AND a.sofascore_id IS NOT NULL
        ORDER BY m.kickoff ASC, m.match_id ASC
        """
    ).fetchall()
    con.close()
    now = datetime.now(timezone.utc)
    pending = select_pending_fixture_analyses(rows, by_league, root / "data" / "analisis", now=now, limit=64)
    nearby = []
    for raw in rows:
        row = dict(raw)
        dt = _parse_dt(row.get("kickoff"))
        if dt and abs((dt - now).total_seconds()) <= 60 * 60 * 48:
            comp = by_league.get(int(row.get("league_id") or 0))
            key = str((comp or {}).get("key") or "")
            nearby.append({
                "event_id": row.get("sofascore_id"),
                "kickoff_raw": row.get("kickoff"),
                "kickoff_parsed": dt.isoformat(),
                "league_id": row.get("league_id"),
                "registry_match": bool(comp),
                "competition_key": key,
                "visible_bundle": has_visible_characteristics(root / "data" / "analisis", key, int(row.get("sofascore_id") or 0)) if key else None,
                "match": f'{row.get("home_team")} vs {row.get("away_team")}',
            })
    print(json.dumps({"now": now.isoformat(), "active_leagues": len(by_league), "rows": len(rows), "pending": pending, "nearby": nearby}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
