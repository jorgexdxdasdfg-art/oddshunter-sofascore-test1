from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f'patch target not found: {label}')
    if text.count(old) != 1:
        raise RuntimeError(f'patch target not unique: {label} count={text.count(old)}')
    return text.replace(old, new, 1)


def replace_once_after(text: str, anchor: str, old: str, new: str, label: str) -> str:
    start = text.find(anchor)
    if start < 0:
        raise RuntimeError(f'anchor not found: {label}')
    pos = text.find(old, start)
    if pos < 0:
        if text.find(new, start) >= 0:
            return text
        raise RuntimeError(f'patch target not found after anchor: {label}')
    return text[:pos] + new + text[pos + len(old):]


def patch_builder(path: Path) -> None:
    text = path.read_text(encoding='utf-8')

    old = '''    event_map: dict[tuple[str, int], dict[str, Any]] = {}
    for source in (previous.get("events", []), fresh.get("events", [])):
        for row in source if isinstance(source, list) else []:
            if not isinstance(row, dict) or _event_day(row) not in allowed_days:
                continue
            try:
                identity = (str(row.get("competition_key") or ""), int(row["event_id"]))
            except (KeyError, TypeError, ValueError):
                continue
            event_map[identity] = row
'''
    new = '''    # Fresh provider evidence can explicitly retire a previously published row
    # after a reschedule moved it outside the rolling three-day window. Such
    # rows are not discovery gaps and must never be resurrected from `previous`.
    excluded_event_ids: set[int] = set()
    validation = fresh.get("validation") if isinstance(fresh.get("validation"), dict) else {}
    for item in validation.get("excluded", []) if isinstance(validation.get("excluded"), list) else []:
        if not isinstance(item, dict) or item.get("event_id") is None:
            continue
        try:
            excluded_event_ids.add(int(item["event_id"]))
        except (TypeError, ValueError):
            continue

    event_map: dict[tuple[str, int], dict[str, Any]] = {}
    for source_name, source in (("previous", previous.get("events", [])), ("fresh", fresh.get("events", []))):
        for row in source if isinstance(source, list) else []:
            if not isinstance(row, dict) or _event_day(row) not in allowed_days:
                continue
            try:
                identity = (str(row.get("competition_key") or ""), int(row["event_id"]))
            except (KeyError, TypeError, ValueError):
                continue
            if source_name == "previous" and identity[1] in excluded_event_ids:
                continue
            event_map[identity] = row
'''
    text = replace_once(text, old, new, 'do not resurrect excluded schedule rows')

    old = '''        known_ids = {int(row["event_id"]) for row in db_rows}
        for league_id, event in discovered:
            timestamp = event.get("startTimestamp")
            kickoff = datetime.fromtimestamp(int(timestamp), timezone.utc) if timestamp else None
            if kickoff is None or kickoff.astimezone(ECUADOR_TZ).date() not in allowed_days:
                continue
            event_id = int(event["id"])
            exact[event_id] = event
            if event_id in known_ids:
                continue
'''
    new = '''        known_ids = {int(row["event_id"]) for row in db_rows}
        for league_id, event in discovered:
            timestamp = event.get("startTimestamp")
            kickoff = datetime.fromtimestamp(int(timestamp), timezone.utc) if timestamp else None
            event_id = int(event["id"])
            # Keep exact provider evidence even when a reschedule moved the
            # event outside this rolling window. Existing bootstrap/DB rows can
            # then be corrected and excluded instead of surviving with a stale
            # placeholder kickoff.
            exact[event_id] = event
            if kickoff is None or kickoff.astimezone(ECUADOR_TZ).date() not in allowed_days:
                continue
            if event_id in known_ids:
                continue
'''
    text = replace_once(text, old, new, 'keep out-of-window provider reschedules')

    old = '''            stale_scheduled = (
                remote_status == "NS" and kickoff is not None
                and kickoff <= now - timedelta(minutes=15)
            )
'''
    new = '''            stale_scheduled = (
                remote_status == "NS" and kickoff is not None
                and kickoff <= now - timedelta(minutes=15)
                and (remote_kickoff is None or remote_kickoff <= now - timedelta(minutes=15))
            )
'''
    text = replace_once(text, old, new, 'trust forward reschedules')

    path.write_text(text, encoding='utf-8')


def patch_odds_sync(path: Path) -> None:
    text = path.read_text(encoding='utf-8')

    alias_anchor = '    "willem ii tilburg": "willem ii",\n'
    aliases = '''    "willem ii tilburg": "willem ii",
    "real racing": "racing santander",
    "real racing club": "racing santander",
    "deportivo alaves": "cd alaves",
    "al taawoun": "al taawon buraidah",
    "al hilal": "al hilal riyadh",
    "1 fc koln": "cologne",
    "sv werder bremen": "werder bremen",
    "sc cambuur": "cambuur leeuwarden",
    "sporting kansas city": "kansas city",
    "los angeles": "lafc",
    "los angeles fc": "lafc",
    "alianza valledupar": "alianza",
    "junior barranquilla": "junior",
    "vitoria sc": "guimaraes",
    "ldu": "ldu quito",
    "cs maritimo": "maritimo",
    "sporting braga": "braga",
    "estoril praia": "estoril",
    "cf estrela amadora": "estrela amadora",
    "sporting cp": "sporting",
    "as roma": "roma",
'''
    if '    "real racing club": "racing santander",\n' not in text:
        text = replace_once(text, alias_anchor, aliases, 'fixture aliases')

    old = '''    seed_paths = _schedule_seed_paths(root)
    seen_seed_paths: set[Path] = set()
    for seed in seed_paths:
'''
    new = '''    seed_paths = _schedule_seed_paths(root)
    seen_seed_paths: set[Path] = set()
    service_seed = seed_paths[-1]
    try:
        service_seed_resolved = service_seed.resolve()
    except OSError:
        service_seed_resolved = service_seed
    explicitly_excluded_event_ids: set[int] = set()
    for seed in seed_paths:
'''
    text = replace_once(text, old, new, 'track authoritative schedule exclusions')

    old = '''        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for row in document.get("events", []):
'''
    new = '''        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if resolved_seed == service_seed_resolved:
            validation = document.get("validation") if isinstance(document.get("validation"), dict) else {}
            for item in validation.get("excluded", []) if isinstance(validation.get("excluded"), list) else []:
                if not isinstance(item, dict) or item.get("event_id") is None:
                    continue
                try:
                    explicitly_excluded_event_ids.add(int(item["event_id"]))
                except (TypeError, ValueError):
                    continue
        for row in document.get("events", []):
'''
    text = replace_once_after(
        text,
        '    service_seed = seed_paths[-1]\n',
        old,
        new,
        'read service seed exclusions',
    )

    old = '''            if key and event_id and kickoff and start <= kickoff < end:
                events[(key, event_id)] = {**events.get((key, event_id), {}), **row}

    for path in sorted((root / "data" / "analisis").glob("*/*/analysis.json")):
'''
    new = '''            if key and event_id and kickoff and start <= kickoff < end:
                events[(key, event_id)] = {**events.get((key, event_id), {}), **row}

    # The live schedule builder records rows it positively excluded after a
    # reschedule. Remove matching stale DB/bootstrap entries from the odds
    # target set so they cannot reappear as fake Today/Tomorrow fixtures.
    if explicitly_excluded_event_ids:
        events = {
            identity: row for identity, row in events.items()
            if identity[1] not in explicitly_excluded_event_ids
        }

    for path in sorted((root / "data" / "analisis").glob("*/*/analysis.json")):
'''
    text = replace_once(text, old, new, 'prune stale odds targets')

    path.write_text(text, encoding='utf-8')


def main() -> int:
    patch_builder(Path('mobile_schedule_seed_builder.py'))
    patch_odds_sync(Path('five_dollar_odds_sync.py'))
    print('SCHEDULE_ODDS_PATCH=PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
