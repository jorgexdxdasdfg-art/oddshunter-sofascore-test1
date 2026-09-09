from __future__ import annotations

import math

import pytest

from odds_value_engine import (
    final_pick_results,
    freeze_top_picks,
    immutable_top_picks,
    rank_value_picks,
    top_pick_score,
)


def test_top_pick_score_uses_the_approved_formula_without_mutating_ev():
    quote = {
        "key": "goals_over_2_5",
        "display_line": 2.5,
        "anchor_line": 2.5,
        "price_origin": "EXACT_HALF_LINE",
    }
    score = top_pick_score("goals_over_2_5", 0.60, 0.20, quote)
    expected_ev_score = 100 * (1 - math.exp(-1))
    expected = 0.55 * 60 + 0.25 * expected_ev_score + 0.12 * 50 + 0.08 * 50

    assert score["probability_score"] == 60
    assert score["ev_score"] == pytest.approx(expected_ev_score, abs=1e-6)
    assert score["top_pick_score"] == pytest.approx(expected, abs=1e-6)


def test_extreme_distant_estimate_does_not_automatically_beat_strong_exact_pick():
    probabilities = {"corners_under_5_5": 0.205, "corners_under_9_5": 0.696}
    prices = [
        {
            "key": "corners_under_5_5", "selection": "Menos de 5.5", "odds": 9.164,
            "estimated_odds": 9.164, "estimated_ev": 0.875, "display_line": 5.5,
            "anchor_line": 9.5, "price_origin": "BET365_ANCHORED_ESTIMATE",
        },
        {
            "key": "corners_under_9_5", "selection": "Menos de 9.5", "odds": 1.85,
            "source_odds": 1.85, "source_ev": 0.288, "display_line": 9.5,
            "source_line": 9.5, "source_side": "under", "price_origin": "EXACT_HALF_LINE",
        },
    ]

    ranked = rank_value_picks(probabilities, prices)

    assert [row["key"] for row in ranked] == ["corners_under_9_5"]
    assert ranked[0]["ev"] == 28.8


def test_snapshot_preserves_original_values_and_is_immutable_on_refresh():
    ranked = [{
        "key": "goals_over_3_5", "market": "Goles", "selection": "Más de 3.5",
        "display_line": 3.5, "source_line": 2.75, "source_side": "over",
        "probability": 45.7, "source_odds": 1.90, "ev": 6.3,
        "price_origin": "ASIAN_MAPPED", "top_pick_score": 54.2,
    }]
    frozen = freeze_top_picks(ranked, "2026-09-08T10:00:00Z")
    replacement = [{**ranked[0], "probability": 99, "ev": 99, "source_odds": 9.9}]

    preserved = immutable_top_picks({"top_picks_snapshot": frozen}, replacement, "later")

    assert preserved[0]["probability_at_recommendation"] == 45.7
    assert preserved[0]["odds_at_recommendation"] == 1.90
    assert preserved[0]["ev_at_recommendation"] == 6.3
    assert preserved[0]["top_pick_score_at_recommendation"] == 54.2
    assert preserved[0]["recommended_at"] == "2026-09-08T10:00:00Z"


def test_finished_match_without_prematch_snapshot_does_not_create_new_top_four():
    ranked = [{"key": "result_home", "probability": 90, "odds": 2, "ev": 80}]

    assert immutable_top_picks({}, ranked, "after", {"status": "FINAL"}) == []


@pytest.mark.parametrize(
    ("source_side", "source_line", "total", "expected"),
    [
        ("over", 2.75, 3, "HALF_WIN"),
        ("under", 3.0, 3, "PUSH"),
        ("under", 2.75, 3, "HALF_LOSS"),
        ("over", 2.5, 3, "WIN"),
        ("under", 2.5, 3, "LOSS"),
    ],
)
def test_final_asian_settlement_uses_real_source_line(source_side, source_line, total, expected):
    pick = freeze_top_picks([{
        "key": "goals_over_3_5" if source_side == "over" else "goals_under_2_5",
        "selection": "visual row", "display_line": 3.5 if source_side == "over" else 2.5,
        "source_line": source_line, "source_side": source_side, "source_odds": 1.9,
        "probability": 55.0, "ev": 7.0, "price_origin": "ASIAN_MAPPED",
    }], "before")[0]
    result = final_pick_results(
        [pick], {"status": "FINAL", "home_score": total, "away_score": 0}, {}
    )

    assert result["picks"][0]["result"] == expected


def test_estimated_pick_uses_visual_line_and_missing_stats_are_pending():
    estimated = freeze_top_picks([{
        "key": "corners_over_9_5", "selection": "Más de 9.5", "display_line": 9.5,
        "anchor_line": 11.0, "estimated_odds": 2.1, "probability": 61.0, "ev": 28.1,
        "price_origin": "BET365_ANCHORED_ESTIMATE",
    }], "before")[0]
    actual = {"home_corners": 6, "away_corners": 5}

    complete = final_pick_results([estimated], {"status": "FINAL"}, actual)
    missing = final_pick_results([estimated], {"status": "FINAL"}, {})

    assert complete["picks"][0]["result"] == "CUMPLIDO"
    assert missing["picks"][0]["result"] == "PENDIENTE DE RESULTADO"


def test_result_double_chance_and_btts_are_evaluated_from_final_score():
    picks = freeze_top_picks([
        {"key": "result_home", "probability": 60, "odds": 1.8, "ev": 8},
        {"key": "double_away_draw", "probability": 55, "odds": 2.0, "ev": 10},
        {"key": "btts_yes", "probability": 52, "odds": 2.0, "ev": 4},
    ], "before")

    final = final_pick_results(picks, {"status": "FINAL", "home_score": 2, "away_score": 1}, {})

    assert [row["result"] for row in final["picks"]] == ["WIN", "LOSS", "WIN"]
