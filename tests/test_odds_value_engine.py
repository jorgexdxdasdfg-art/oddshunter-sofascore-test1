from __future__ import annotations

from odds_value_engine import model_probabilities, provider_prices, rank_value_picks, refresh_model_picks


def bundle():
    return {
        "goals": {"models": {"MODELO_APRENDIDO": {
            "lambda_home": 1.8,
            "lambda_away": 1.1,
            "outcome_probabilities": {"home_win": 52, "draw": 25, "away_win": 23},
            "total_goals_distribution": {"0": .03, "1": .12, "2": .21, "3": .24, "4": .2, "5": .2},
        }}},
        "cards": {"analysis": {"yellow_thresholds": [
            {"line_equivalent": line, "negative_binomial_probability": value}
            for line, value in ((1.5, .88), (2.5, .72), (3.5, .55))
        ]}},
        "corners": {"analysis": {"minimum_total_thresholds": [
            {"minimum_total_corners": 10, "negative_binomial_probability": .62}
        ]}},
    }


def test_all_requested_probabilities_are_exposed():
    probabilities = model_probabilities(bundle(), {"derived": {
        "home_relevant": {"first_half_over_0_5": .7},
        "away_relevant": {"first_half_over_0_5": .6},
    }})
    expected = {
        "result_home", "result_draw", "result_away",
        "double_home_draw", "double_away_draw", "double_home_away",
        "goals_over_1_5", "goals_under_1_5", "goals_over_2_5",
        "goals_under_2_5", "goals_over_3_5", "goals_under_3_5",
        "cards_over_1_5", "cards_under_1_5", "cards_over_2_5",
        "cards_under_2_5", "cards_over_3_5", "cards_under_3_5",
        "btts_yes", "btts_no", "first_half_over_0_5",
        "first_half_under_0_5", "corners_over_9_5", "corners_under_9_5",
    }
    assert expected <= probabilities.keys()


def test_poisson_thresholds_survive_null_negative_binomial_field():
    value = bundle()
    value["cards"]["analysis"]["yellow_thresholds"] = [
        {
            "line_equivalent": 3.5,
            "poisson_probability": 0.49663969,
            "negative_binomial_probability": None,
        }
    ]

    probabilities = model_probabilities(value)

    assert probabilities["cards_over_3_5"] == 0.49663969
    assert probabilities["cards_under_3_5"] == 0.50336031


def test_only_exact_positive_ev_lines_reach_top_four():
    probabilities = model_probabilities(bundle())
    markets = {
        "1x2": {"closing": {"home": 2.2, "draw": 3.1, "away": 4.8}},
        "goal_line": {"closing": {"line": 2.5, "over": 2.1, "under": 1.7}},
        "corner_line": {"closing": {"line": 9.5, "over": 2.0, "under": 1.8}},
        "card_line": {"closing": {"line": 3.5, "over": 2.1, "under": 1.7}},
        "btts": {"closing": {"yes": 2.0, "no": 1.8}},
    }
    picks = rank_value_picks(probabilities, provider_prices(markets))
    assert len(picks) <= 4
    assert picks and all(pick["ev"] > 0 for pick in picks)
    assert all(0 <= pick["recommended_bankroll_pct"] <= 5 for pick in picks)


def test_quarter_line_is_not_mislabeled_as_half_line():
    prices = provider_prices({"goal_line": {"closing": {"line": 2.25, "over": 2.0, "under": 1.8}}})
    assert prices == []


def test_batch_1x2_uses_documented_home_draw_away_keys():
    markets = {
        "1x2": {
            "opening": {"home": 2.15, "draw": 3.4, "away": 3.0},
            "closing": {"home": 2.1, "draw": 3.5, "away": 3.1},
            "inplay": None,
        }
    }
    opening = {row["key"]: row["odds"] for row in provider_prices(markets, snapshot_order=("opening",))}
    current = {row["key"]: row["odds"] for row in provider_prices(markets, snapshot_order=("closing",))}
    assert opening == {"result_home": 2.15, "result_draw": 3.4, "result_away": 3.0}
    assert current == {"result_home": 2.1, "result_draw": 3.5, "result_away": 3.1}


def test_model_picks_exist_without_a_provider_match_or_quotes():
    value = refresh_model_picks(bundle(), {"odds_status": "PROVIDER_NOT_FOUND"})
    assert len(value["all_picks"]) == len(model_probabilities(bundle()))
    assert value["probabilities"]["result_home"] == 0.52
    assert all(pick["odds"] is None and pick["ev"] is None for pick in value["all_picks"])
    assert value["top_picks"] == []
    assert value["odds_status"] == "PROVIDER_NOT_FOUND"


def test_model_refresh_recalculates_ev_without_touching_opening_or_current():
    stored = {
        "available_prices": [{"key": "result_home", "odds": 2.2, "current_odds": 2.2, "opening_odds": 2.5}],
        "price_history": [{"opening": {"odds": 2.5}, "current": {"odds": 2.2}}],
        "probabilities": {"first_half_over_0_5": 0.7},
    }
    value = refresh_model_picks(bundle(), stored)
    home = next(p for p in value["all_picks"] if p["key"] == "result_home")
    assert home["ev"] == 14.4
    assert value["price_history"] == stored["price_history"]
    assert value["available_prices"] == stored["available_prices"]
    assert value["probabilities"]["first_half_over_0_5"] == 0.7
