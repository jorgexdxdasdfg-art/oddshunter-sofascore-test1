from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mobile_uses_pc_primary_lambdas_and_never_history_fallbacks() -> None:
    script = (ROOT / "vercel_assets" / "match_summary_v2.js").read_text(
        encoding="utf-8"
    )
    assert "expected.goals_home??expected.xg_home" in script
    assert "expected.goals_away??expected.xg_away" in script
    assert "expected.corners_home??homeHistory.corners" not in script
    assert "expected.yellow_cards_home??homeHistory.yellow_cards" not in script


def test_summary_uses_the_same_desktop_prediction_payload() -> None:
    script = (ROOT / "vercel_assets" / "match_summary_v2.js").read_text(
        encoding="utf-8"
    )
    assert 'const expected=p.expected_real?.expected||{};' in script
    assert 'expected.goals_home??expected.xg_home??s.xg_home' in script
    assert 'expected.corners_home,expected.corners_away' in script
    assert 'expected.yellow_cards_home,expected.yellow_cards_away' in script
    assert 'homeHistory.corners,awayHistory.corners' not in script
    assert 'homeHistory.yellow_cards,awayHistory.yellow_cards' not in script


def test_backend_contract_exposes_each_predicted_market_side() -> None:
    patcher = (ROOT / "vercel_backend_data_patch.py").read_text(encoding="utf-8")
    for field in (
        "corners_home",
        "corners_away",
        "yellow_cards_home",
        "yellow_cards_away",
        "shots_home",
        "shots_away",
    ):
        assert f'"{field}"' in patcher
