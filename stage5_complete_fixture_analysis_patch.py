from __future__ import annotations

"""Mechanical patch for the deployed Stage5 analysis queue."""

import argparse
import re
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
    # Resolve the registry beside the queue selection.  Some deployed Stage5
    # revisions build ``by_league`` later in main(), so depending on that local
    # variable makes the service fail before it can process any fixture.
    def new_call(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            f'{indent}analysis_registry, _analysis_active = active_registry()\n'
            f'{indent}analysis_targets = future_analysis_targets(\n'
            f'{indent}    con, analysis_registry,\n'
            f'{indent}    int(os.environ.get("ODDSHUNTER_ANALYSIS_TARGET_LIMIT", "64")),\n'
            f'{indent})'
        )

    call_patterns = (
        re.compile(
            r"^(?P<indent>[ \t]*)(?:analysis_registry\s*,\s*_analysis_active\s*=\s*"
            r"active_registry\(\)[ \t]*\r?\n(?P=indent))?"
            r"analysis_targets\s*=\s*future_analysis_targets\(\s*"
            r"con\s*,\s*[A-Za-z_]\w*\s*,\s*"
            r"int\(os\.environ\.get\(\"ODDSHUNTER_ANALYSIS_TARGET_LIMIT\",\s*\"64\"\)\)\s*,?\s*\)",
            re.MULTILINE,
        ),
        re.compile(
            r"^(?P<indent>[ \t]*)analysis_targets\s*=\s*future_analysis_targets\([^\n]*\)",
            re.MULTILINE,
        ),
    )
    for call_pattern in call_patterns:
        if call_pattern.search(patched):
            patched = call_pattern.sub(new_call, patched, count=1)
            break
    else:
        raise RuntimeError("STAGE5_ANALYSIS_LIMIT_CALL_NOT_FOUND")
    return patched


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        patched = patch_source(args.source.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"::error title=Stage5 patch contract failed::{type(exc).__name__}: {exc}")
        raise
    args.output.write_text(patched, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
