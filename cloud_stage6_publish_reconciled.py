from __future__ import annotations

"""Safe Stage 6 entrypoint with bounded core-stat reconciliation.

The V1.2 publisher only includes stats belonging to the same-run committed
matches, but later requires the complete remote stats count to equal SQLite.
This wrapper keeps the original publisher and its gates intact while adding
only locally-owned rows that are missing remotely. It never deletes remote
data and stops on divergent ownership or an unexpectedly large delta.
"""

import sqlite3
from typing import Any

import cloud_stage6_publish as base


REMOTE_PAGE_SIZE = 1_000
MAX_MISSING_STATS = 500


def _remote_stat_ids(client: Any) -> set[int]:
    remote_ids: set[int] = set()
    cursor = -1

    while True:
        rows = client.query(
            "SELECT stat_id FROM team_match_stats "
            "WHERE stat_id>? ORDER BY stat_id LIMIT ?",
            [cursor, REMOTE_PAGE_SIZE],
        )
        if not rows:
            break

        page = [int(row["stat_id"]) for row in rows]
        if page != sorted(page) or page[0] <= cursor:
            raise RuntimeError("Turso devolvió una página stat_id no monotónica")

        remote_ids.update(page)
        cursor = page[-1]
        if len(page) < REMOTE_PAGE_SIZE:
            break

    return remote_ids


def _rows_for_stat_ids(
    con: sqlite3.Connection,
    stat_ids: list[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for start in range(0, len(stat_ids), 400):
        chunk = stat_ids[start : start + 400]
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(
            base.fetch_local_rows(
                con,
                f"SELECT * FROM team_match_stats WHERE stat_id IN ({placeholders}) "
                "ORDER BY stat_id",
                chunk,
            )
        )
    return rows


def collect_core_rows_reconciled(
    con: sqlite3.Connection,
    stage5: dict[str, Any],
    client: Any,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    rows_by_table, meta = base._collect_core_rows_original(con, stage5, client)

    local_ids = {
        int(row[0])
        for row in con.execute(
            "SELECT stat_id FROM team_match_stats ORDER BY stat_id"
        ).fetchall()
    }
    remote_ids = _remote_stat_ids(client)
    remote_only = sorted(remote_ids - local_ids)
    if remote_only:
        raise RuntimeError(
            "Turso contiene team_match_stats que no pertenecen a la working SQLite; "
            f"no se borra a ciegas: count={len(remote_only)} sample={remote_only[:20]}"
        )

    missing_ids = sorted(local_ids - remote_ids)
    if len(missing_ids) > MAX_MISSING_STATS:
        raise RuntimeError(
            "Delta team_match_stats excede el límite de reconciliación segura: "
            f"missing={len(missing_ids)} limit={MAX_MISSING_STATS}"
        )

    existing = {
        int(row["stat_id"])
        for row in rows_by_table.get("team_match_stats", [])
    }
    extra_ids = [stat_id for stat_id in missing_ids if stat_id not in existing]
    extra_rows = _rows_for_stat_ids(con, extra_ids)
    if len(extra_rows) != len(extra_ids):
        raise RuntimeError(
            "No se pudieron cargar exactamente las estadísticas faltantes: "
            f"rows={len(extra_rows)} ids={len(extra_ids)}"
        )

    rows_by_table.setdefault("team_match_stats", []).extend(extra_rows)
    rows_by_table["team_match_stats"].sort(key=lambda row: int(row["stat_id"]))
    meta["stats_reconciliation"] = {
        "mode": "local_missing_upsert_only",
        "remote_rows_before": len(remote_ids),
        "local_rows": len(local_ids),
        "missing_remote_stat_ids": missing_ids,
        "extra_rows_added": len(extra_rows),
        "remote_only_rows": 0,
        "delete_invoked": False,
    }
    print(
        "STAGE6_STATS_RECONCILIATION "
        f"remote={len(remote_ids)} local={len(local_ids)} "
        f"missing={len(missing_ids)} extra={len(extra_rows)}"
    )
    return rows_by_table, meta


base._collect_core_rows_original = base.collect_core_rows
base.collect_core_rows = collect_core_rows_reconciled


if __name__ == "__main__":
    raise SystemExit(base.main())
