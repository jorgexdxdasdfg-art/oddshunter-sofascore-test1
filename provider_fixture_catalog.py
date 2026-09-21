"""Namespaced alternate fixtures for phases absent from the primary calendar.

Never put a FotMob id into SofaScore's namespace. Explicit team bridges below
were verified against both source identities and the working database.
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

FOTMOB_EVENT_BASE = 1_000_000_000_000
LEAGUES = {246: 'ligapro'}
TEAMS = {
    ('ligapro',162922): (33561,'Manta FC'),
    ('ligapro',1014174): (277525,'Orense SC'),
}

def fetch_day(day):
    request=Request('https://www.fotmob.com/api/data/matches?date='+day,
                    headers={'Accept':'application/json','User-Agent':'OddsHunter/1.0'})
    with urlopen(request,timeout=15) as response:
        return json.load(response)

def dt(value):
    return datetime.fromisoformat(str(value).replace('Z','+00:00'))

def extract(document, competitions, start, end, existing):
    by_key={c['key']:c for c in competitions.values()}
    events, unresolved=[],[]
    for league in document.get('leagues',[]):
        key=LEAGUES.get(int(league.get('parentLeagueId') or league.get('id') or 0))
        if key not in by_key:
            continue
        for match in league.get('matches',[]):
            status=match.get('status') or {}
            kickoff=dt(status['utcTime']) if status.get('utcTime') else None
            if kickoff is None or not start <= kickoff < end:
                continue
            home,away=match.get('home') or {},match.get('away') or {}
            home_bridge=TEAMS.get((key,int(home.get('id') or 0)))
            away_bridge=TEAMS.get((key,int(away.get('id') or 0)))
            if not home_bridge or not away_bridge:
                unresolved.append({'league':key,'id':match.get('id'),'home':home.get('name'),'away':away.get('name')})
                continue
            # The same physical match keeps its canonical primary id if known.
            same=[e for e in existing if e.get('competition_key')==key
                  and int(e.get('home_team_id') or 0)==home_bridge[0]
                  and int(e.get('away_team_id') or 0)==away_bridge[0]
                  and abs((dt(e['kickoff'])-kickoff).total_seconds()) < 6*3600]
            if same:
                continue
            mid=int(match['id'])
            state='FT' if status.get('finished') else ('LIVE' if status.get('started') or status.get('ongoing') else 'NS')
            if status.get('cancelled'):
                state='CANCELLED'
            comp=by_key[key]
            events.append({'competition_key':key,'event_id':FOTMOB_EVENT_BASE+mid,
                'competition_name':comp.get('name'),'season_name':comp.get('season_name'),
                'round_name':None,'stage':league.get('name'),'kickoff':kickoff.isoformat(),
                'status':state,'status_description':state,
                'home_team_id':home_bridge[0],'home_team':home_bridge[1],
                'away_team_id':away_bridge[0],'away_team':away_bridge[1],
                'home_score':home.get('score') if state in {'LIVE','FT'} else None,
                'away_score':away.get('score') if state in {'LIVE','FT'} else None,
                'analysis_status':'pending','headline_json':'{}',
                'provider':'fotmob','provider_event_id':mid,'league_id':comp['league_id']})
    return events,unresolved

def supplement(path, competitions, now, existing):
    tz=timezone(timedelta(hours=-5))
    start=datetime.combine(now.astimezone(tz).date()-timedelta(days=1),datetime.min.time(),tz)
    end=start+timedelta(days=3)
    saved={}
    if path.exists():
        saved=json.loads(path.read_text(encoding='utf-8'))
    events={int(e['event_id']):e for e in saved.get('events',[]) if start<=dt(e['kickoff'])<end}
    errors=[]
    unresolved=[]
    day=start.astimezone(timezone.utc).date()
    while day<=end.astimezone(timezone.utc).date():
        try:
            rows,missing=extract(fetch_day(day.strftime('%Y%m%d')),competitions,start,end,existing)
            unresolved.extend(missing)
            for e in rows:
                events[e['event_id']]=e
        except Exception as exc:
            errors.append(type(exc).__name__+': '+str(exc))
        day+=timedelta(days=1)
    result={'generated_at':now.isoformat(),'events':list(events.values()),'errors':errors,'unresolved':unresolved}
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    temp.replace(path)
    return result
