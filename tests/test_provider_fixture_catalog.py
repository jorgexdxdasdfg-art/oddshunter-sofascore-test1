from datetime import datetime, timezone
from provider_fixture_catalog import extract, FOTMOB_EVENT_BASE

def test_phase_fixture_uses_separate_provider_namespace():
    doc={'leagues':[{'parentLeagueId':246,'name':'Relegation Round','matches':[
        {'id':1000022063,'home':{'id':162922,'name':'Manta','score':2},
         'away':{'id':1014174,'name':'Orense','score':0},
         'status':{'utcTime':'2026-09-21T19:00:00Z','started':True}}]}]}
    registry={239:{'key':'ligapro','league_id':239,'name':'LigaPro'}}
    start=datetime(2026,9,21,tzinfo=timezone.utc)
    end=datetime(2026,9,22,tzinfo=timezone.utc)
    rows,missing=extract(doc,registry,start,end,[])
    assert not missing
    assert rows[0]['event_id']==FOTMOB_EVENT_BASE+1000022063
    assert rows[0]['home_team_id']==33561
    assert rows[0]['away_team_id']==277525
    assert rows[0]['status']=='LIVE'
    assert extract(doc,registry,start,end,[{**rows[0],'event_id':123}])[0]==[]

def test_unknown_team_is_not_guessed():
    doc={'leagues':[{'parentLeagueId':246,'matches':[{'id':1,'home':{'id':7},'away':{'id':8},
         'status':{'utcTime':'2026-09-21T19:00:00Z'}}]}]}
    rows,missing=extract(doc,{239:{'key':'ligapro','league_id':239}},
         datetime(2026,9,21,tzinfo=timezone.utc),datetime(2026,9,22,tzinfo=timezone.utc),[])
    assert not rows and len(missing)==1
