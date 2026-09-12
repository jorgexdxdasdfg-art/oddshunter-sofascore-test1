from __future__ import annotations

"""Rebuild and publish the exact three-day Mobile schedule in the cloud."""

import argparse
import gzip
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB = Path(os.environ.get("ODDSHUNTER_WORK_DB", "/var/lib/oddshunter/data/oddshunter.db"))
SEED = Path(os.environ.get("ODDSHUNTER_SCHEDULE_CATALOG_SEED", "/var/lib/oddshunter/data/mobile_schedule_catalog_seed.json.gz"))
BOOTSTRAP = Path(os.environ.get("ODDSHUNTER_SCHEDULE_BOOTSTRAP", "/var/lib/oddshunter/data/mobile_schedule_bootstrap.json.gz"))
MOBILE_REGISTRY = Path(os.environ.get("ODDSHUNTER_MOBILE_REGISTRY", "/var/lib/oddshunter/data/mobile_certified_competitions.json"))
REPORT = DATA / "automation" / "cloud_schedule_refresh" / "last.json"


def _validate_mobile_registry() -> dict[str, Any]:
    document = json.loads(MOBILE_REGISTRY.read_text(encoding="utf-8-sig"))
    rows = document.get("competitions") or []
    if not isinstance(rows, list):
        raise RuntimeError("mobile certified registry has no competitions list")
    keys = [str(row.get("key") or "").strip() for row in rows if isinstance(row, dict)]
    league_ids = [int(row.get("league_id") or 0) for row in rows if isinstance(row, dict)]
    if len(rows) != 28 or len(set(keys)) != 28 or len(set(league_ids)) != 28:
        raise RuntimeError(
            f"MOBILE_CERTIFIED_REGISTRY_INVALID rows={len(rows)} keys={len(set(keys))} league_ids={len(set(league_ids))}"
        )
    if "turkey-super-lig" not in keys:
        raise RuntimeError("MOBILE_CERTIFIED_REGISTRY_MISSING_TURKEY")
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("MOBILE_CERTIFIED_REGISTRY_BAD_ROW")
        for field in ("key", "league_id", "source_competition_id", "season_id"):
            if not row.get(field):
                raise RuntimeError(f"MOBILE_CERTIFIED_REGISTRY_MISSING_FIELD={field} row={row}")
        if not row.get("active"):
            raise RuntimeError(f"MOBILE_CERTIFIED_REGISTRY_INACTIVE={row.get('key')}")
    print(
        "MOBILE_CERTIFIED_REGISTRY=PASS "
        + json.dumps({"count": len(rows), "turkey": True}, ensure_ascii=False),
        flush=True,
    )
    return document


def run() -> dict[str, Any]:
    _validate_mobile_registry()
    command = [
            sys.executable,
            "-u",
            str(ROOT / "mobile_schedule_seed_builder.py"),
            "--db",
            str(DB),
            "--registry",
            str(MOBILE_REGISTRY),
            "--data-root",
            str(DATA),
            "--output",
            str(SEED),
            "--workers",
            "6",
        ]
    if BOOTSTRAP.is_file():
        command.extend(["--bootstrap", str(BOOTSTRAP)])
    build = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        timeout=20 * 60,
    )
    print(build.stdout, flush=True)
    if build.stderr:
        print(build.stderr, file=sys.stderr, flush=True)

    env = dict(os.environ)
    env["ODDSHUNTER_FORCE_SCHEDULE_CATALOG"] = "1"
    publish: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, 4):
        publish = subprocess.run(
            [sys.executable, "-u", str(ROOT / "cloud_live_status_sync.py"), "--catalog-only"],
            cwd=ROOT,
            env=env,
            check=False,
            text=True,
            capture_output=True,
            timeout=10 * 60,
        )
        print(publish.stdout, flush=True)
        if publish.stderr:
            print(publish.stderr, file=sys.stderr, flush=True)
        if publish.returncode == 0:
            break
        print(f"SCHEDULE_CATALOG_PUBLISH_RETRY={attempt}/3 rc={publish.returncode}", flush=True)
        if attempt < 3:
            time.sleep(2 * attempt)
    if publish is None or publish.returncode != 0:
        raise RuntimeError(
            "No se pudo publicar el catálogo después de 3 intentos; "
            f"returncode={getattr(publish, 'returncode', None)}"
        )

    with gzip.open(SEED, "rt", encoding="utf-8") as handle:
        catalog = json.load(handle)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result": "PUBLISHED",
        "counts_by_day": catalog.get("counts_by_day") or {},
        "leagues_by_day": catalog.get("leagues_by_day") or {},
        "validation": catalog.get("validation") or {},
        "mobile_certified_count": 28,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CLOUD_SCHEDULE_REFRESH=" + json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    required = (
        ROOT / "mobile_schedule_seed_builder.py",
        ROOT / "cloud_live_status_sync.py",
        MOBILE_REGISTRY,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Faltan módulos del refresco: {missing}")
    _validate_mobile_registry()
    if args.self_test:
        print("CLOUD_SCHEDULE_REFRESH_SELF_TEST=PASS")
        return 0
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
