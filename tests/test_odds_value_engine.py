from __future__ import annotations

import pytest

from asian_total_ev import asian_total_ev
from odds_value_engine import (
    asian_display_line,
    attach_asian_source_values,
    build_all_picks,
    freeze_all_picks,
    high_probability_pick_results,
    immutable_all_picks,
    market_anchored_prices,
    model_probabilities,
    preferred_visual_prices,
    provider_prices,
    rank_value_picks,
    refresh_model_picks,
)


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


def test_quarter_line_keeps_source_identity_when_mapped_to_visual_half_line():
    prices = provider_prices({"goal_line": {"closing": {"line": 2.25, "over": 2.0, "under": 1.8}}})
    assert prices == [
        {
            "key": "goals_over_2_5", "market": "Goles", "selection": "Más de 2.5",
            "line": 2.5, "display_line": 2.5, "source_market": "goal_line",
            "source_side": "over", "source_line": 2.25, "source_odds": 2.0,
            "odds": 2.0, "price_origin": "ASIAN_MAPPED",
        },
        {
            "key": "goals_under_1_5", "market": "Goles", "selection": "Menos de 1.5",
            "line": 1.5, "display_line": 1.5, "source_market": "goal_line",
            "source_side": "under", "source_line": 2.25, "source_odds": 1.8,
            "odds": 1.8, "price_origin": "ASIAN_MAPPED",
        },
    ]


def test_approved_asian_to_half_mapping_examples():
    expected = {
        2.00: 1.5, 2.25: 2.5, 2.50: 2.5, 2.75: 3.5,
        3.00: 2.5, 3.25: 3.5, 3.50: 3.5, 3.75: 4.5,
        9.00: 8.5, 9.25: 9.5, 9.50: 9.5, 9.75: 10.5,
    }
    assert {line: asian_display_line("over", line) for line in expected} == expected


def test_under_mapping_is_side_aware_for_quarter_lines():
    expected = {
        2.00: 1.5, 2.25: 1.5, 2.50: 2.5, 2.75: 2.5,
        3.00: 2.5, 3.25: 2.5, 3.50: 3.5, 3.75: 3.5,
        10.00: 9.5, 10.25: 9.5, 10.50: 10.5, 10.75: 10.5,
    }
    assert {line: asian_display_line("under", line) for line in expected} == expected


def test_same_source_line_maps_over_and_under_to_their_contract_rows():
    prices = provider_prices({"goal_line": {"closing": {"line": 2.75, "over": 2.0, "under": 1.8}}})
    assert [(row["source_side"], row["display_line"]) for row in prices] == [
        ("over", 3.5), ("under", 2.5),
    ]


def test_persisted_under_row_is_normalized_without_new_provider_data():
    stale = {
        "key": "goals_under_3_5", "market": "Goles", "selection": "Menos de 3.5",
        "line": 3.5, "display_line": 3.5, "source_market": "goal_line",
        "source_side": "under", "source_line": 2.75, "source_odds": 1.825,
        "odds": 1.825, "source_ev": -0.103283825, "price_origin": "ASIAN_MAPPED",
    }

    normalized = preferred_visual_prices([stale])

    assert normalized[0]["key"] == "goals_under_2_5"
    assert normalized[0]["selection"] == "Menos de 2.5"
    assert normalized[0]["display_line"] == 2.5
    assert normalized[0]["source_line"] == 2.75
    assert normalized[0]["source_odds"] == 1.825
    assert normalized[0]["source_ev"] == -0.103283825


def test_lines_outside_each_visual_catalog_are_not_created():
    assert provider_prices({"goal_line": {"closing": {"line": 3.75, "over": 2.0}}}) == []
    assert provider_prices({"card_line": {"closing": {"line": 4.25, "over": 2.0}}}) == []
    assert provider_prices({"corner_line": {"closing": {"line": 12.25, "over": 2.0}}}) == []


def test_exact_half_line_has_priority_over_asian_mapping():
    mapped = {
        "key": "goals_over_2_5", "price_origin": "ASIAN_MAPPED",
        "source_line": 2.25, "source_odds": 1.8,
    }
    exact = {
        "key": "goals_over_2_5", "price_origin": "EXACT_HALF_LINE",
        "source_line": 2.5, "source_odds": 1.9,
    }
    assert preferred_visual_prices([mapped, exact]) == [exact]
    assert preferred_visual_prices([exact, mapped]) == [exact]


def asian_bundle():
    value = bundle()
    value["corners"]["analysis"].update({
        "negative_binomial_dispersion": {"available": False},
        "poisson_total_distribution": {
            "probabilities": {str(i): probability for i, probability in enumerate(
                (0.01, 0.01, 0.02, 0.03, 0.05, 0.07, 0.09, 0.12, 0.14, 0.14, 0.12, 0.09)
            )},
            "12+": 0.11,
        },
    })
    value["cards"]["analysis"].update({
        "negative_binomial_dispersion": {"available": False},
        "poisson_total_yellow_distribution": {
            "probabilities": {"0": .04, "1": .12, "2": .22, "3": .25, "4": .19, "5": .11, "6": .05},
            "7+": .02,
        },
    })
    return value


def test_real_market_examples_preserve_source_ev_after_visual_mapping():
    value = asian_bundle()
    markets = {
        # Casos reales observados en el audit de 5DollarFootballAPI.
        "goal_line": {"closing": {"line": 3.25, "over": 1.80}},
        "corner_line": {"closing": {"line": 9.00, "over": 1.875}},
        "card_line": {"closing": {"line": 3.00, "over": 1.90}},
    }
    prices = attach_asian_source_values(value, provider_prices(markets))
    by_key = {row["key"]: row for row in prices}
    probabilities = {
        "goals_over_3_5": .30,
        "corners_over_8_5": .58,
        "cards_over_2_5": .67,
    }
    all_picks = {row["key"]: row for row in build_all_picks(probabilities, prices)}

    cases = (
        ("goals_over_3_5", value["goals"]["models"]["MODELO_APRENDIDO"]["total_goals_distribution"]),
        ("corners_over_8_5", value["corners"]["analysis"]["poisson_total_distribution"]),
        ("cards_over_2_5", value["cards"]["analysis"]["poisson_total_yellow_distribution"]),
    )
    for key, pmf in cases:
        price = by_key[key]
        pick = all_picks[key]
        reference = asian_total_ev(pmf, "over", price["source_line"], price["source_odds"])
        assert price["source_ev"] == pytest.approx(reference)
        assert pick["odds"] == price["source_odds"]
        assert pick["source_ev"] == price["source_ev"]
        assert pick["ev"] == pytest.approx(round(price["source_ev"] * 100, 2))
        assert pick["display_line"] == price["line"]
        assert pick["price_origin"] == "ASIAN_MAPPED"


def test_top_four_uses_source_ev_not_display_probability_formula():
    probabilities = {"goals_over_2_5": .10}
    quote = {
        "key": "goals_over_2_5", "market": "Goles", "selection": "Más de 2.5",
        "odds": 2.0, "source_odds": 2.0, "source_line": 2.25,
        "source_ev": .15, "price_origin": "ASIAN_MAPPED",
    }
    assert probabilities["goals_over_2_5"] * quote["odds"] - 1 == -.8
    picks = rank_value_picks(probabilities, [quote])
    assert len(picks) == 1
    assert picks[0]["ev"] == 15.0
    assert picks[0]["source_ev"] == .15


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


def test_double_chance_estimates_use_real_1x2_anchor_and_observed_margin():
    probabilities = model_probabilities(bundle())
    real = provider_prices({"1x2": {"closing": {"home": 2.05, "draw": 3.2, "away": 4.0}}})
    prices = {row["key"]: row for row in market_anchored_prices(bundle(), probabilities, real)}
    overround = 1 / 2.05 + 1 / 3.2 + 1 / 4.0
    fair_home = (1 / 2.05) / overround
    fair_draw = (1 / 3.2) / overround

    quote = prices["double_home_draw"]
    assert quote["estimated_odds"] == pytest.approx(round(1 / ((fair_home + fair_draw) * overround), 3))
    assert quote["estimated_ev"] == pytest.approx(
        probabilities["double_home_draw"] * quote["estimated_odds"] - 1
    )
    assert quote["estimated_from_market"] == "1X2_BET365"
    assert quote["price_origin"] == "BET365_ANCHORED_ESTIMATE"


def test_real_total_anchor_fills_full_visual_ladders_without_replacing_real_rows():
    value = asian_bundle()
    probabilities = model_probabilities(value)
    corner_points = value["corners"]["analysis"]["poisson_total_distribution"]
    corner_mass = {
        int(key): amount for key, amount in corner_points["probabilities"].items()
    }
    corner_mass[12] = corner_points["12+"]
    for line in (5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5):
        token = str(line).replace(".", "_")
        over = sum(amount for total, amount in corner_mass.items() if total > line)
        probabilities[f"corners_over_{token}"] = over
        probabilities[f"corners_under_{token}"] = 1 - over
    markets = {
        "goal_line": {"closing": {"line": 2.5, "over": 1.875, "under": 1.975}},
        "card_line": {"closing": {"line": 3.5, "over": 1.95, "under": 1.85}},
        "corner_line": {"closing": {"line": 9.5, "over": 1.95, "under": 1.85}},
    }
    real = attach_asian_source_values(value, provider_prices(markets))
    prices = {row["key"]: row for row in market_anchored_prices(value, probabilities, real)}

    expected = {
        *(f"goals_{side}_{line}_5" for side in ("over", "under") for line in (1, 2, 3)),
        *(f"cards_{side}_{line}_5" for side in ("over", "under") for line in (1, 2, 3)),
        *(f"corners_{side}_{line}_5" for side in ("over", "under") for line in range(5, 12)),
    }
    assert expected <= prices.keys()
    assert prices["goals_over_2_5"]["price_origin"] == "EXACT_HALF_LINE"
    assert prices["goals_over_2_5"]["source_odds"] == 1.875
    assert prices["goals_over_1_5"]["price_origin"] == "BET365_ANCHORED_ESTIMATE"
    assert prices["cards_under_2_5"]["anchor_market"] == "card_line O3.5/U3.5 BET365"
    assert prices["corners_over_11_5"]["estimated_ev"] == pytest.approx(
        probabilities["corners_over_11_5"] * prices["corners_over_11_5"]["estimated_odds"] - 1
    )


def test_real_quotes_always_beat_anchored_estimates():
    estimated = {
        "key": "goals_over_2_5", "odds": 2.2,
        "price_origin": "BET365_ANCHORED_ESTIMATE",
    }
    mapped = {
        "key": "goals_over_2_5", "source_line": 2.25, "source_odds": 1.8,
        "odds": 1.8, "price_origin": "ASIAN_MAPPED",
    }
    exact = {
        "key": "goals_over_2_5", "source_line": 2.5, "source_odds": 1.9,
        "odds": 1.9, "price_origin": "EXACT_HALF_LINE",
    }
    assert preferred_visual_prices([estimated, mapped])[0] == mapped
    assert preferred_visual_prices([estimated, mapped, exact])[0] == exact


def test_refresh_persists_estimate_fields_only_in_picks_not_real_price_cache():
    stored = {
        "available_prices": provider_prices({
            "1x2": {"closing": {"home": 2.05, "draw": 3.2, "away": 4.0}},
            "goal_line": {"closing": {"line": 2.5, "over": 1.9, "under": 1.95}},
        })
    }
    value = refresh_model_picks(asian_bundle(), stored)
    estimated = next(row for row in value["all_picks"] if row["key"] == "double_home_draw")
    assert estimated["price_origin"] == "BET365_ANCHORED_ESTIMATE"
    assert estimated["estimated_odds"] == estimated["odds"]
    assert estimated["estimated_ev"] * 100 == pytest.approx(estimated["ev"])
    assert all(row.get("price_origin") != "BET365_ANCHORED_ESTIMATE" for row in value["available_prices"])


def test_high_probability_results_ignore_odds_ev_and_use_display_selection():
    snapshot = freeze_all_picks([
        {"key": "corners_over_8_5", "probability": 85.1, "odds": 1.142, "ev": -2.8, "display_line": 8.5},
        {"key": "cards_over_1_5", "probability": 90.2, "odds": None, "ev": None, "display_line": 1.5},
        {"key": "goals_under_3_5", "probability": 75.4, "odds": 1.36, "ev": -19.0, "display_line": 3.5},
        {"key": "btts_yes", "probability": 59.9, "odds": 2.0, "ev": 19.8},
        {"key": "corners_over_5_5", "probability": 99.0, "odds": 1.01, "ev": 0.0, "display_line": 5.5},
        {"key": "cards_over_0_5", "probability": 98.0, "odds": None, "ev": None, "display_line": 0.5},
    ], "2026-09-08T20:00:00Z")
    result = high_probability_pick_results(
        snapshot,
        {"status": "FT", "home_score": 2, "away_score": 0},
        {"home_corners": 5, "away_corners": 5, "home_yellow_cards": 1, "away_yellow_cards": 1},
    )
    assert [row["key"] for row in result["picks"]] == [
        "cards_over_1_5", "corners_over_8_5", "goals_under_3_5",
    ]
    assert [row["result"] for row in result["picks"]] == ["ACERTADO", "ACERTADO", "ACERTADO"]
    assert result["summary"] == {"ACERTADO": 3, "FALLADO": 0, "PENDIENTE": 0, "precision": 100.0}


def test_high_probability_pending_stats_are_not_assumed_zero():
    snapshot = freeze_all_picks([
        {"key": "cards_under_3_5", "probability": 72.0, "display_line": 3.5},
    ], "2026-09-08T20:00:00Z")
    result = high_probability_pick_results(snapshot, {"status": "FT", "home_score": 0, "away_score": 0}, {})
    assert result["picks"][0]["result"] == "PENDIENTE"
    assert result["summary"]["precision"] is None


def test_all_pick_snapshot_is_immutable_and_not_created_after_final():
    original = freeze_all_picks([{"key": "result_home", "probability": 61.0, "odds": 2.1, "ev": 28.1}], "before")
    existing = {"all_picks_snapshot": original}
    assert immutable_all_picks(existing, [{"key": "result_home", "probability": 10.0}], "after", {"status": "FT"}) == original
    assert immutable_all_picks({}, [{"key": "result_home", "probability": 61.0}], "after", {"status": "FT"}) == []


def test_corner_5_5_never_competes_for_top_four():
    probabilities = {"corners_over_5_5": .99, "goals_over_1_5": .70}
    prices = [
        {"key": "corners_over_5_5", "odds": 2.0},
        {"key": "goals_over_1_5", "odds": 2.0},
    ]
    assert [row["key"] for row in rank_value_picks(probabilities, prices)] == ["goals_over_1_5"]
