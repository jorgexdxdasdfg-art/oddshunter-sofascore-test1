from __future__ import annotations

"""Rebuild and publish the exact three-day Mobile schedule in the cloud."""

import argparse
import gzip
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB = Path(os.environ.get("ODDSHUNTER_WORK_DB", "/var/lib/oddshunter/data/oddshunter.db"))
SEED = Path(os.environ.get("ODDSHUNTER_SCHEDULE_CATALOG_SEED", "/var/lib/oddshunter/data/mobile_schedule_catalog_seed.json.gz"))
BOOTSTRAP = Path(os.environ.get("ODDSHUNTER_SCHEDULE_BOOTSTRAP", "/var/lib/oddshunter/data/mobile_schedule_bootstrap.json.gz"))
REPORT = DATA / "automation" / "cloud_schedule_refresh" / "last.json"


def run() -> dict[str, Any]:
    command = [
            sys.executable,
            "-u",
            str(ROOT / "mobile_schedule_seed_builder.py"),
            "--db",
            str(DB),
            "--registry",
            str(DATA / "competitions.json"),
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

    env = dict(os.environ)
    env["ODDSHUNTER_FORCE_SCHEDULE_CATALOG"] = "1"
    publish = subprocess.run(
        [sys.executable, "-u", str(ROOT / "cloud_live_status_sync.py"), "--catalog-only"],
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
        timeout=10 * 60,
    )
    print(publish.stdout, flush=True)

    with gzip.open(SEED, "rt", encoding="utf-8") as handle:
        catalog = json.load(handle)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result": "PUBLISHED",
        "counts_by_day": catalog.get("counts_by_day") or {},
        "leagues_by_day": catalog.get("leagues_by_day") or {},
        "validation": catalog.get("validation") or {},
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CLOUD_SCHEDULE_REFRESH=" + json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        required = (ROOT / "mobile_schedule_seed_builder.py", ROOT / "cloud_live_status_sync.py")
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(f"Faltan módulos del refresco: {missing}")
        print("CLOUD_SCHEDULE_REFRESH_SELF_TEST=PASS")
        return 0
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
