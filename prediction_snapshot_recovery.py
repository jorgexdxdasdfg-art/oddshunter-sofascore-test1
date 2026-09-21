"""Recover original PC pre-kickoff bundles, never retrospectively train models."""
from __future__ import annotations
import argparse
import gzip
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

NAMES = ('input_match', 'status', 'ratings', 'goals', 'corners', 'cards', 'shots', 'odds_value', 'analysis')

def dt(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

def validate(event, docs):
    key, eid = event['competition_key'], int(event['event_id'])
    if not re.fullmatch(r'[a-z0-9-]+', key) or eid <= 0:
        raise ValueError('Unsafe event identity')
    analysis = docs['analysis']
    if analysis.get('status') not in {'FULL', 'PARTIAL_WITH_FALLBACK'}:
        raise ValueError('Incomplete source bundle')
    if dt(analysis['generated_at']) >= dt(event['kickoff']):
        raise ValueError('Source prediction was not generated before kickoff')
    for name, doc in docs.items():
        if name not in NAMES:
            raise ValueError('Unexpected document')
        match = doc.get('upcoming_match') or doc.get('evento') or {}
        if match:
            if int(match.get('event_id') or 0) != eid:
                raise ValueError('Mismatched source event')
            for side in ('home', 'away'):
                if int(match.get(side+'_team_id') or 0) != int(event.get(side+'_team_id') or 0):
                    raise ValueError('Mismatched team identity')
        if doc.get('event_id') and int(doc['event_id']) != eid:
            raise ValueError('Mismatched document identity')
        if name not in {'status', 'odds_value'} and doc.get('generated_at'):
            if dt(doc['generated_at']) >= dt(event['kickoff']):
                raise ValueError('Post-kickoff model document')
    models = docs['goals'].get('models') or {}
    valid = False
    for model in models.values():
        outcome = model.get('outcome_probabilities') or {}
        if all(outcome.get(k) is not None for k in ('home_win', 'draw', 'away_win')):
            values = [float(outcome[k]) for k in ('home_win', 'draw', 'away_win')]
            valid |= all(0 <= v <= 1 for v in values) and abs(sum(values)-1) < .02
    if not valid:
        raise ValueError('Missing valid 1X2')

def export(root, output):
    entries, rejected = [], []
    for offset in (-1, 0, 1):
        with urlopen(f'https://oddshunter-mobile.vercel.app/api/day?offset={offset}&limit=1000', timeout=30) as response:
            events = json.load(response)
        for event in events:
            folder = root / event['competition_key'] / str(event['event_id'])
            try:
                docs = {name: json.loads((folder/(name+'.json')).read_text(encoding='utf-8-sig'))
                        for name in NAMES if (folder/(name+'.json')).is_file()}
                validate(event, docs)
                # Only genuine pre-match odds snapshots travel with recovered models.
                odds = docs.get('odds_value')
                if odds and (not odds.get('generated_at') or dt(odds['generated_at']) >= dt(event['kickoff'])):
                    docs.pop('odds_value')
                entries.append({'event': event, 'docs': docs})
            except (ValueError, KeyError, OSError) as exc:
                rejected.append({'event_id':event['event_id'], 'error':str(exc)})
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, 'wt', encoding='utf-8') as handle:
        json.dump({'created_at':datetime.now(timezone.utc).isoformat(), 'entries':entries,
                   'rejected':rejected},handle,ensure_ascii=False,separators=(',',':'))
    print(json.dumps({'exported':len(entries),'rejected':rejected,'bytes':output.stat().st_size}))

def restore(root, archive):
    from fixture_analysis_queue import has_visible_characteristics
    with gzip.open(archive, 'rt', encoding='utf-8') as handle:
        payload = json.load(handle)
    # Validate the entire archive before writing any event.
    for entry in payload['entries']:
        validate(entry['event'], entry['docs'])
    recovered, preserved = [], []
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backups = root.parent / 'automation' / 'prediction_recovery_backups' / stamp
    for entry in payload['entries']:
        e, docs = entry['event'], entry['docs']
        key, eid = e['competition_key'], int(e['event_id'])
        if has_visible_characteristics(root, key, eid):
            preserved.append(eid)
            continue
        folder = root/key/str(eid)
        folder.mkdir(parents=True, exist_ok=True)
        for name in NAMES:
            if name not in docs:
                continue
            path = folder/(name+'.json')
            if name == 'odds_value' and path.exists():
                continue  # Keep live provider updates; recovery is not an odds rewind.
            if path.exists():
                backup = backups/key/str(eid)/path.name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
            temp = path.with_suffix('.recovery.tmp')
            temp.write_text(json.dumps(docs[name],ensure_ascii=False),encoding='utf-8')
            temp.replace(path)
        recovered.append(eid)
    report = {'restored':recovered,'preserved':preserved,'backup_path':str(backups)}
    report_path = root.parent/'automation'/'prediction_recovery_last.json'
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['export','restore'])
    parser.add_argument('root',type=Path)
    parser.add_argument('archive',type=Path)
    args=parser.parse_args()
    (export if args.mode=='export' else restore)(args.root,args.archive)
