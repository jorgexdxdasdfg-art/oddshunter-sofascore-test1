from __future__ import annotations

import importlib
import sqlite3
import sys
import types
import unittest


class FakeClient:
    def __init__(self, ids: list[int]) -> None:
        self.ids = ids

    def query(self, _sql: str, params: list[int]) -> list[dict[str, int]]:
        cursor, limit = params
        return [
            {"stat_id": stat_id}
            for stat_id in self.ids
            if stat_id > cursor
        ][:limit]


class Stage6ReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        fake_base = types.ModuleType("cloud_stage6_publish")

        def original(_con, _stage5, _client):
            return {"team_match_stats": [{"stat_id": 3, "value": "new"}]}, {}

        def fetch(con, sql, params):
            con.row_factory = sqlite3.Row
            return [dict(row) for row in con.execute(sql, params).fetchall()]

        fake_base.collect_core_rows = original
        fake_base.fetch_local_rows = fetch
        fake_base.main = lambda: 0
        sys.modules["cloud_stage6_publish"] = fake_base
        sys.modules.pop("cloud_stage6_publish_reconciled", None)
        self.module = importlib.import_module("cloud_stage6_publish_reconciled")
        self.con = sqlite3.connect(":memory:")
        self.con.execute(
            "CREATE TABLE team_match_stats (stat_id INTEGER PRIMARY KEY, value TEXT)"
        )
        self.con.executemany(
            "INSERT INTO team_match_stats VALUES (?,?)",
            [(1, "a"), (2, "b"), (3, "c")],
        )

    def tearDown(self) -> None:
        self.con.close()
        sys.modules.pop("cloud_stage6_publish_reconciled", None)
        sys.modules.pop("cloud_stage6_publish", None)

    def test_adds_only_remote_missing_rows_without_duplicates(self) -> None:
        rows, meta = self.module.collect_core_rows_reconciled(
            self.con, {}, FakeClient([1])
        )
        self.assertEqual([2, 3], [row["stat_id"] for row in rows["team_match_stats"]])
        self.assertEqual([2, 3], meta["stats_reconciliation"]["missing_remote_stat_ids"])
        self.assertEqual(1, meta["stats_reconciliation"]["extra_rows_added"])
        self.assertFalse(meta["stats_reconciliation"]["delete_invoked"])

    def test_stops_if_remote_contains_nonlocal_rows(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no pertenecen"):
            self.module.collect_core_rows_reconciled(
                self.con, {}, FakeClient([1, 2, 99])
            )


if __name__ == "__main__":
    unittest.main()
