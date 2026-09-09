from __future__ import annotations

"""Mechanical patch for the deployed Stage5 analysis queue."""

import argparse
from pathlib import Path


START = "def future_analysis_targets("
END = "\ndef write_schedule("
REPLACEMENT = '''def future_analysis_targets(
    con: sqlite3.Connection,
    by_league: dict[int, dict[str, Any]],
    limit: int = 64,
) -> list[dict[str, Any]]:
    from fixture_analysis_queue import select_pending_fixture_analyses

    rows = con.execute(
        """
        SELECT
            m.sofascore_id, m.league_id, m.kickoff, m.status, m.season,
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
    return select_pending_fixture_analyses(
        rows,
        by_league,
        DATA / "analisis",
        now=datetime.now(timezone.utc),
        limit=limit,
    )

'''


def patch_source(source: str) -> str:
    start = source.find(START)
    end = source.find(END, start)
    if start < 0 or end < 0:
        raise RuntimeError("STAGE5_ANALYSIS_QUEUE_ANCHOR_NOT_FOUND")
    patched = source[:start] + REPLACEMENT + source[end + 1 :]
    old_call = "analysis_targets = future_analysis_targets(con, by_league, 2)"
    new_call = (
        'analysis_targets = future_analysis_targets(\n'
        '            con, by_league,\n'
        '            int(os.environ.get("ODDSHUNTER_ANALYSIS_TARGET_LIMIT", "64")),\n'
        '        )'
    )
    if old_call in patched:
        patched = patched.replace(old_call, new_call, 1)
    elif "ODDSHUNTER_ANALYSIS_TARGET_LIMIT" not in patched:
        raise RuntimeError("STAGE5_ANALYSIS_LIMIT_CALL_NOT_FOUND")
    return patched


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(patch_source(args.source.read_text(encoding="utf-8")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
