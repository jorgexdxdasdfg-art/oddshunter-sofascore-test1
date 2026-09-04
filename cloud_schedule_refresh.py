from __future__ import annotations

"""Refresh every active competition schedule on the isolated cloud database."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORT = DATA / "automation" / "cloud_schedule_refresh" / "last.json"


def active_competitions() -> list[dict[str, Any]]:
    document = json.loads((DATA / "competitions.json").read_text(encoding="utf-8-sig"))
    return [
        row for row in document.get("competitions", [])
        if isinstance(row, dict)
        and row.get("active")
        and row.get("source_competition_id") is not None
        and row.get("season_id") is not None
        and row.get("league_id") is not None
    ]


def run() -> dict[str, Any]:
    from playwright.sync_api import sync_playwright
    import sync_upcoming_matches as upcoming

    rows: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(locale="es-ES")
        try:
            for competition in active_competitions():
                try:
                    result = upcoming.bootstrap_competition_schedule(page, competition)
                    rows.append(result)
                    print(
                        f"SCHEDULE key={competition.get('key')} status={result.get('status')} "
                        f"events={len(result.get('event_ids') or [])}",
                        flush=True,
                    )
                except Exception as exc:
                    rows.append({
                        "competition_key": competition.get("key"),
                        "status": "ERROR",
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    print(f"SCHEDULE_ERROR key={competition.get('key')} error={exc}", flush=True)
        finally:
            browser.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "competition_count": len(rows),
        "successful_competitions": sum(1 for row in rows if row.get("status") == "OK"),
        "event_count": sum(len(row.get("event_ids") or []) for row in rows),
        "results": rows,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["successful_competitions"] == 0 or report["event_count"] == 0:
        raise RuntimeError("Ningún calendario activo pudo actualizarse")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        compile(Path(__file__).read_text(encoding="utf-8"), __file__, "exec")
        print("CLOUD_SCHEDULE_REFRESH_SELF_TEST=PASS")
        return 0
    report = run()
    print("CLOUD_SCHEDULE_REFRESH=" + json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
