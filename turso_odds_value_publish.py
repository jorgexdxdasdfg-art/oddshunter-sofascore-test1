from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cloud_stage6_publish as stage6


ROOT = Path(__file__).resolve().parent


def main() -> int:
    client = stage6.TursoClient(
        os.environ.get("TURSO_DATABASE_URL", ""),
        os.environ.get("TURSO_AUTH_TOKEN", ""),
        timeout=30,
    )
    if not client.health():
        raise RuntimeError("Turso no respondió saludable")
    columns = ["competition_key", "event_id", "doc_name", "json_text", "source_mtime"]
    sql = stage6.upsert_sql("mobile_analysis_docs", columns, ["competition_key", "event_id", "doc_name"])
    statements: list[tuple[str, list[Any]]] = []
    expected: list[tuple[str, int]] = []
    for path in sorted((ROOT / "data" / "analisis").glob("*/*/odds_value.json")):
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            continue
        key, event_id = path.parent.parent.name, int(path.parent.name)
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        statements.append((sql, [key, event_id, "odds_value", json.dumps(value, ensure_ascii=False, separators=(",", ":")), modified]))
        expected.append((key, event_id))
    if not statements:
        print("ODDS_VALUE_DOCS=0")
        return 0
    written = client.execute_many(statements, chunk=20)
    for key, event_id in expected:
        rows = client.query("SELECT 1 AS ok FROM mobile_analysis_docs WHERE competition_key=? AND event_id=? AND doc_name='odds_value' LIMIT 1", [key, event_id])
        if not rows:
            raise RuntimeError(f"Falta documento remoto {key}/{event_id}")
    print("ODDS_VALUE_EVENTS=" + ",".join(f"{key}/{event_id}" for key, event_id in expected))
    print(f"ODDS_VALUE_DOCS={written}")
    print("ODDS_VALUE_TURSO_PUBLISH=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
