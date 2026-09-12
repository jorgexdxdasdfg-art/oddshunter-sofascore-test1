from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import five_dollar_odds_sync as syncmod
from sofascore_event_client import SofaScoreEventClient

ROOT = Path('/opt/oddshunter/current')
TARGET_IDS = {
    16432039, 16432049, 16432050, 16432051, 16432062, 16432063, 16432065,
    16416328, 16653097, 16285013, 16434027, 16316815, 16317948, 15168418,
    16390736, 16285016, 16285011, 16285012, 16310948, 15502692,
}


def main() -> int:
    now = datetime.now(timezone.utc)
    today_start, _, end = syncmod._day_bounds(now)
    events = [row for row in syncmod._target_events(ROOT, today_start, end) if int(row.get('event_id') or 0) in TARGET_IDS]
    client = SofaScoreEventClient(timeout=12, retries=2)
    print('SOFA_TARGETS', len(events))
    for event in events:
        payload = {
            'event_id': int(event.get('event_id')),
            'competition_key': event.get('competition_key'),
            'home': event.get('home_team'),
            'away': event.get('away_team'),
            'seed_kickoff': event.get('kickoff'),
        }
        try:
            snap = client.get_match_snapshot(event)
            payload['sofa_kickoff'] = snap.get('kickoff')
            payload['state'] = snap.get('state')
            payload['provider_status'] = snap.get('provider_status')
            seed_dt = syncmod._datetime(event.get('kickoff'))
            sofa_dt = syncmod._datetime(snap.get('kickoff'))
            payload['delta_h'] = None if not seed_dt or not sofa_dt else round((sofa_dt-seed_dt).total_seconds()/3600.0, 3)
        except Exception as exc:
            payload['error'] = str(exc)
        print('SOFA_EVENT=' + json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
