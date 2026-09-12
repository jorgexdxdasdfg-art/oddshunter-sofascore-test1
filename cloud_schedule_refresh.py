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
REPORT = DATA / "automation" / "cloud_schedule_refresh" / "last.json"
MOBILE_REGISTRY = DATA / "automation" / "cloud_schedule_refresh" / "mobile_competitions.json"

# Exact certified OddsHunter Mobile roster.  Mobile schedule visibility must not
# silently depend on an automation flag such as `active`; those flags can be
# changed independently from the 28-league product catalog.
MOBILE_CERTIFIED_KEYS = {
    "belgium-pro-league",
    "besta-deild",
    "brasil-serie-a",
    "bundesliga",
    "canada-canadian-premier-league",
    "championship",
    "chile-primera",
    "conmebol-sudamericana",
    "copa-colombia",
    "eredivisie",
    "greece-stoiximan-super-league",
    "j1-league",
    "laliga",
    "liga-betplay-colombia",
    "liga-portugal",
    "ligamx-apertura",
    "ligapro",
    "ligue-1",
    "leagues-cup",
    "mls",
    "premier-league",
    "saudi-pro-league",
    "serie-a",
    "turkey-super-lig",
    "uefa-champions-league",
    "uefa-conference-league",
    "uefa-europa-league",
    "usa-usl-championship",
}


def _build_mobile_registry() -> Path:
    source = DATA / "competitions.json"
    document = json.loads(source.read_text(encoding="utf-8-sig"))
    rows = document.get("competitions") or []
    if not isinstance(rows, list):
        raise RuntimeError("competitions.json no contiene una lista competitions válida")

    found: set[str] = set()
    patched: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        key = str(row.get("key") or "").strip()
        if key in MOBILE_CERTIFIED_KEYS:
            found.add(key)
            # The existing seed builder intentionally filters by `active`.
            # Feed it a Mobile-only registry where the certified roster is the
            # authority, without mutating the production registry on disk.
            row["active"] = True
            patched.append(row)

    missing = sorted(MOBILE_CERTIFIED_KEYS - found)
    if missing:
        raise RuntimeError(f"MOBILE_CERTIFIED_KEYS_MISSING={missing}")
    if len(patched) != len(MOBILE_CERTIFIED_KEYS):
        duplicates: dict[str, int] = {}
        for row in patched:
            key = str(row.get("key") or "")
            duplicates[key] = duplicates.get(key, 0) + 1
        bad = {key: count for key, count in duplicates.items() if count != 1}
        raise RuntimeError(
            f"MOBILE_CERTIFIED_REGISTRY_NOT_1_TO_1 rows={len(patched)} duplicates={bad}"
        )

    output = dict(document)
    output["competitions"] = patched
    MOBILE_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    MOBILE_REGISTRY.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "MOBILE_CERTIFIED_REGISTRY=PASS "
        + json.dumps({"count": len(patched), "keys": sorted(found)}, ensure_ascii=False),
        flush=True,
    )
    return MOBILE_REGISTRY


def run() -> dict[str, Any]:
    registry = _build_mobile_registry()
    command = [
            sys.executable,
            "-u",
            str(ROOT / "mobile_schedule_seed_builder.py"),
            "--db",
            str(DB),
            "--registry",
            str(registry),
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
        "mobile_certified_count": len(MOBILE_CERTIFIED_KEYS),
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
        required = (
            ROOT / "mobile_schedule_seed_builder.py",
            ROOT / "cloud_live_status_sync.py",
            DATA / "competitions.json",
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(f"Faltan módulos del refresco: {missing}")
        _build_mobile_registry()
        print("CLOUD_SCHEDULE_REFRESH_SELF_TEST=PASS")
        return 0
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
