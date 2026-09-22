"""Recover only Manta-Orense's existing September 16 pre-match analysis.

Explicit alias: SofaScore 17102430 -> FotMob-namespaced 1001000022063.
No predictions are recalculated and no result/fixture fields are overwritten.
"""
import argparse
import copy
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from prediction_snapshot_recovery import NAMES, dt, validate

SOURCE = 17102430
TARGET = 1001000022063
KEY = 'ligapro'


def prepare(root):
    folder = root / KEY / str(SOURCE)
    docs = {name: json.loads((folder / (name + '.json')).read_text(encoding='utf-8-sig'))
            for name in NAMES if (folder / (name + '.json')).exists()}
    event = dict(docs['input_match']['upcoming_match'], competition_key=KEY)
    assert event['event_id'] == SOURCE
    assert event['home_team_id'] == 33561 and event['away_team_id'] == 277525
    assert event['season_id'] == 89674 and event['round'] == 1
    assert 'Relegation' in event['stage']
    validate(event, docs)
    # Odds missing at source remain missing; do not overwrite current prices.
    docs.pop('odds_value', None)
    return {'event': event, 'docs': docs}


def publish(payload, root, runtime):
    event, originals = payload['event'], payload['docs']
    validate(event, originals)
    assert event['event_id'] == SOURCE and event['competition_key'] == KEY
    assert event['home_team_id'] == 33561 and event['away_team_id'] == 277525
    sys.path.insert(0, str(runtime))
    from cloud_live_status_sync import turso_client, reconcile_catalog_analysis
    client = turso_client()
    rows = client.query('SELECT * FROM mobile_events WHERE competition_key=? AND event_id=?', [KEY, TARGET])
    if len(rows) != 1:
        raise ValueError('Target fixture missing or ambiguous')
    target = rows[0]
    assert int(target['home_team_id']) == 33561 and int(target['away_team_id']) == 277525
    assert 'Relegation' in str(target.get('stage'))
    assert target['season_name'] == event['season_name']
    assert abs((dt(target['kickoff']) - dt(event['kickoff'])).total_seconds()) <= 36 * 3600
    stamp = datetime.now(timezone.utc)
    backup = root.parent / 'automation' / 'manta_recovery_backups' / stamp.strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True, exist_ok=True)
    before = client.query('SELECT * FROM mobile_analysis_docs WHERE competition_key=? AND event_id=?', [KEY, TARGET])
    (backup / 'remote_before.json').write_text(json.dumps({'event': target, 'docs': before}), encoding='utf-8')
    folder = root / KEY / str(TARGET)
    folder.mkdir(parents=True, exist_ok=True)

    def remap(value):
        if isinstance(value, dict):
            return {k: TARGET if k == 'event_id' and v == SOURCE else remap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [remap(v) for v in value]
        return value

    writes = []
    for name, original in originals.items():
        if name not in NAMES or name == 'odds_value':
            raise ValueError('Unexpected document')
        doc = remap(copy.deepcopy(original))
        doc['prediction_recovery'] = {'source_event_id': SOURCE, 'target_event_id': TARGET,
                                      'source_kickoff': event['kickoff'],
                                      'reason': 'Explicit same teams/season/relegation round fixture alias',
                                      'recovered_at': stamp.isoformat()}
        encoded = json.dumps(doc, ensure_ascii=False)
        path = folder / (name + '.json')
        if path.exists():
            (backup / path.name).write_bytes(path.read_bytes())
        temp = path.with_suffix('.recovery.tmp')
        temp.write_text(encoded, encoding='utf-8')
        temp.replace(path)
        writes.append(('INSERT INTO mobile_analysis_docs (competition_key,event_id,doc_name,json_text,source_mtime) '
                       'VALUES (?,?,?,?,?) ON CONFLICT (competition_key,event_id,doc_name) DO UPDATE SET '
                       'json_text=excluded.json_text,source_mtime=excluded.source_mtime',
                       [KEY, TARGET, name, encoded, stamp.timestamp()]))
    client.execute_many(writes, chunk=12)
    assert reconcile_catalog_analysis(client, [TARGET]) == 1
    print(json.dumps({'restored_event': TARGET, 'source_event': SOURCE, 'documents': len(writes),
                      'backup': str(backup), 'result_and_odds_unchanged': True}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['export', 'publish'])
    p.add_argument('root', type=Path)
    p.add_argument('archive', type=Path)
    p.add_argument('--runtime', type=Path)
    args = p.parse_args()
    if args.mode == 'export':
        payload = prepare(args.root)
        with gzip.open(args.archive, 'wt', encoding='utf-8') as out:
            json.dump(payload, out, ensure_ascii=False)
        print('Validated original pre-match bundle:', SOURCE)
    else:
        with gzip.open(args.archive, 'rt', encoding='utf-8') as src:
            publish(json.load(src), args.root, args.runtime)
