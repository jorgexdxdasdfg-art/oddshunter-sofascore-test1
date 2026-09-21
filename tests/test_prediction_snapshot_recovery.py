import pytest
from prediction_snapshot_recovery import validate

def fixture():
    event = {'competition_key':'eredivisie','event_id':1,'home_team_id':2,'away_team_id':3,'kickoff':'2026-09-20T10:00:00Z'}
    docs = {'analysis':{'status':'FULL','generated_at':'2026-09-19T10:00:00Z','upcoming_match':event},
            'goals':{'models':{'model':{'outcome_probabilities':{'home_win':.5,'draw':.3,'away_win':.2}}}}}
    return event,docs

def test_accepts_original_pre_match_snapshot():
    validate(*fixture())

def test_rejects_retrospective_model():
    event,docs=fixture()
    docs['analysis']['generated_at']='2026-09-20T11:00:00Z'
    with pytest.raises(ValueError,match='before kickoff'):
        validate(event,docs)

def test_rejects_wrong_event_identity():
    event,docs=fixture()
    docs['analysis']['upcoming_match']={**event,'home_team_id':9}
    with pytest.raises(ValueError,match='team identity'):
        validate(event,docs)

def test_rejects_fake_full_without_probabilities():
    event,docs=fixture()
    docs['goals']['models']={}
    with pytest.raises(ValueError,match='1X2'):
        validate(event,docs)
