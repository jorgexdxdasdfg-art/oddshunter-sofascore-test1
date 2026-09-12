from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import five_dollar_odds_sync as syncmod

ROOT = Path('/opt/oddshunter/current')
TARGET_IDS = {
    16432039, 16432049, 16432050, 16432051, 16432062, 16432063, 16432065,
    16416328, 16653097, 16285013, 16434027, 16316815, 16317948, 15168418,
    16390736, 16285016, 16285011, 16285012, 16310948, 15502692,
}


def main() -> int:
    syncmod._load_env(ROOT)
    import os
    key = os.environ.get('FIVE_DOLLAR_FOOTBALL_API_KEY', '').strip()
    if not key:
        raise RuntimeError('missing FIVE_DOLLAR_FOOTBALL_API_KEY')
    client = syncmod.Client(key)
    now = datetime.now(timezone.utc)
    today_start, _, end = syncmod._day_bounds(now)
    events = [row for row in syncmod._target_events(ROOT, today_start, end) if int(row.get('event_id') or 0) in TARGET_IDS]
    start = today_start - timedelta(days=2)
    stop = end + timedelta(days=2)
    fixtures = syncmod.fetch_fixtures(client, start, stop, include_odds=False)
    print('DIAG_WINDOW', start.isoformat(), stop.isoformat(), 'fixtures', len(fixtures), 'targets', len(events))
    for event in events:
        scored = []
        for fixture in fixtures:
            score, hs, aws, delta = syncmod._fixture_identity(event, fixture)
            teams = fixture.get('teams') or {}
            home = (teams.get('home') or {}).get('name')
            away = (teams.get('away') or {}).get('name')
            canonical_pair = (
                syncmod._canonical_team(event.get('home_team')) == syncmod._canonical_team(home)
                and syncmod._canonical_team(event.get('away_team')) == syncmod._canonical_team(away)
            )
            if score >= 0.38 or canonical_pair:
                scored.append({
                    'fixture_id': fixture.get('id'),
                    'kickoff_utc': fixture.get('kickoff_utc'),
                    'home': home,
                    'away': away,
                    'score': round(score, 4),
                    'home_score': round(hs, 4),
                    'away_score': round(aws, 4),
                    'delta_h': None if delta is None else round(delta / 3600.0, 3),
                    'canonical_pair': canonical_pair,
                })
        scored.sort(key=lambda r: (-float(r['score']), 9999 if r['delta_h'] is None else abs(float(r['delta_h']))))
        print('DIAG_EVENT=' + json.dumps({
            'event_id': event.get('event_id'),
            'competition_key': event.get('competition_key'),
            'home': event.get('home_team'),
            'away': event.get('away_team'),
            'kickoff': event.get('kickoff'),
            'candidates': scored[:10],
        }, ensure_ascii=False, separators=(',', ':')))
    print('DIAG_REQUESTS', client.request_count)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
