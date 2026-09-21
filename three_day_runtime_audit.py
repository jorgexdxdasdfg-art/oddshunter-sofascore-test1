"""Read-only, compact audit of cloud model and actual-statistics coverage."""
import gzip
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from fixture_analysis_queue import has_visible_characteristics
    seed_path = Path("/var/lib/oddshunter/data/mobile_schedule_catalog_seed.json.gz")
    with gzip.open(seed_path, "rt", encoding="utf-8") as stream:
        seed = json.load(stream)
    con = sqlite3.connect(f"file:{root / 'data/oddshunter.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    counts = Counter()
    for event in seed.get("events", []):
        key, event_id = event["competition_key"], int(event["event_id"])
        folder = root / "data/analisis" / key / str(event_id)
        ready = has_visible_characteristics(root / "data/analisis", key, event_id)
        counts["model_ready" if ready else "model_missing"] += 1
        if ready:
            continue
        status_path = folder / "status.json"
        status = json.loads(status_path.read_text(encoding="utf-8-sig")) if status_path.is_file() else {}
        print("MISSING_MODEL", json.dumps({"key": key, "event_id": event_id, "kickoff": event["kickoff"], "status": status}, ensure_ascii=False)[:2500])
        for log in list((folder / "logs").glob("*.log"))[:2]:
            print("MODEL_LOG", str(log), log.read_text(encoding="utf-8", errors="replace")[-1800:])
    print("MODEL_COUNTS", json.dumps(counts))
    stage5 = root / "artifacts/cloud_stage5_cycle.json"
    if stage5.is_file():
        report = json.loads(stage5.read_text(encoding="utf-8"))
        print("LAST_STAGE5", json.dumps({k: report.get(k) for k in ("generated_at", "stage5_pass", "criteria", "analysis_catalog_publish")} )[:2000])
        for item in report.get("analysis", []):
            print("LAST_ANALYSIS", json.dumps(item, ensure_ascii=False)[-2500:])
    discovery = root / "artifacts/cloud_stage5_discovered_staging.json"
    if discovery.is_file():
        report = json.loads(discovery.read_text(encoding="utf-8"))
        print("DISCOVERY_KEYS", list(report))
        for field, value in report.items():
            if isinstance(value, list):
                print("DISCOVERY", field, "COUNT", len(value), "SAMPLE", json.dumps(value[:2], ensure_ascii=False)[:2200])
    con.close()


if __name__ == "__main__":
    main()
