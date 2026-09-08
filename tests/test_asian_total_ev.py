from __future__ import annotations

import math

import pytest

from asian_total_ev import (
    asian_total_ev,
    asian_total_settlement,
    cards_total_pmf,
    corners_total_pmf,
    goals_total_pmf,
    source_value_record,
)


LINES = (2.00, 2.25, 2.50, 2.75, 3.00, 3.25, 3.50, 3.75)
SIDES = ("over", "under")


def poisson_pmf(mean: float, maximum: int) -> dict[str, float]:
    points = {
        str(total): math.exp(-mean) * mean**total / math.factorial(total)
        for total in range(maximum + 1)
    }
    points[f"{maximum + 1}+"] = 1.0 - sum(points.values())
    return points


def ordinary_leg_profit(total: int, side: str, line: float, odds: float) -> float:
    integer_line = math.isclose(line, round(line), abs_tol=1e-12)
    if side == "over":
        if total > line:
            return odds - 1.0
        if integer_line and total == int(line):
            return 0.0
        return -1.0
    if total < line:
        return odds - 1.0
    if integer_line and total == int(line):
        return 0.0
    return -1.0


def split_lines(line: float) -> tuple[float, ...]:
    quarters = round(line * 4)
    fraction = quarters % 4
    integer = quarters // 4
    if fraction == 1:
        return (float(integer), integer + 0.5)
    if fraction == 3:
        return (integer + 0.5, float(integer + 1))
    return (line,)


def split_bet_reference(
    pmf: dict[str, float], side: str, line: float, odds: float
) -> float:
    legs = split_lines(line)
    expected = 0.0
    for raw_total, probability in pmf.items():
        if raw_total.endswith("+"):
            # The test tail starts far above every tested line, so every
            # represented result has the same payout as its lower bound.
            total = int(raw_total[:-1])
        else:
            total = int(raw_total)
        expected += probability * sum(
            ordinary_leg_profit(total, side, leg, odds) for leg in legs
        ) / len(legs)
    return expected


GOALS_PMF = poisson_pmf(2.72, 12)
CORNERS_POINTS = poisson_pmf(9.35, 20)
CORNERS_PMF = {
    "mean": 9.35,
    "probabilities": {key: value for key, value in CORNERS_POINTS.items() if not key.endswith("+")},
    "21+": CORNERS_POINTS["21+"],
}
CARDS_POINTS = poisson_pmf(4.45, 14)
CARDS_PMF = {
    "mean": 4.45,
    "size": 3.1,
    "probabilities": {key: value for key, value in CARDS_POINTS.items() if not key.endswith("+")},
    "15+": CARDS_POINTS["15+"],
}


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("line", LINES)
@pytest.mark.parametrize(
    "pmf",
    (GOALS_PMF, CORNERS_POINTS, CARDS_POINTS),
    ids=("goals", "corners", "cards"),
)
def test_direct_asian_ev_equals_independent_split_bet_reference(pmf, side, line):
    odds = 1.93
    direct = asian_total_ev(pmf, side, line, odds)
    reference = split_bet_reference(pmf, side, line, odds)
    assert direct == pytest.approx(reference, abs=1e-12)


@pytest.mark.parametrize(
    ("side", "line", "total", "expected"),
    (
        ("over", 2.00, 2, "push"),
        ("over", 2.25, 2, "half_loss"),
        ("over", 2.50, 3, "full_win"),
        ("over", 2.75, 3, "half_win"),
        ("under", 2.00, 2, "push"),
        ("under", 2.25, 2, "half_win"),
        ("under", 2.50, 2, "full_win"),
        ("under", 2.75, 3, "half_loss"),
    ),
)
def test_each_settlement_class_is_explicit(side, line, total, expected):
    result = asian_total_settlement({str(total): 1.0}, side, line).as_dict()
    assert result[expected] == 1.0
    assert sum(result.values()) == 1.0


def test_existing_goal_distribution_is_reused_without_recalibration():
    model = {"lambda_home": 1.7, "lambda_away": 1.02, "total_goals_distribution": GOALS_PMF}
    assert goals_total_pmf(model) is GOALS_PMF
    assert asian_total_ev(goals_total_pmf(model), "over", 2.25, 1.91) == pytest.approx(
        split_bet_reference(GOALS_PMF, "over", 2.25, 1.91), abs=1e-12
    )


def test_existing_corners_selected_family_pmf_is_reused():
    poisson = {"probabilities": {"0": 1.0}}
    analysis = {
        "negative_binomial_dispersion": {"available": True},
        "poisson_total_distribution": poisson,
        "negative_binomial_total_distribution": CORNERS_PMF,
    }
    assert corners_total_pmf(analysis) is CORNERS_PMF


def test_existing_cards_poisson_fallback_pmf_is_reused():
    analysis = {
        "negative_binomial_dispersion": {"available": False},
        "poisson_total_yellow_distribution": CARDS_PMF,
        "negative_binomial_total_yellow_distribution": {"probabilities": {"0": 1.0}},
    }
    assert cards_total_pmf(analysis) is CARDS_PMF


def test_source_fields_keep_real_line_odds_and_ev():
    record = source_value_record(
        GOALS_PMF,
        source_market="goal_line",
        source_side="over",
        source_line=2.25,
        source_odds=1.93,
    )
    assert record == {
        "source_market": "goal_line",
        "source_side": "over",
        "source_line": 2.25,
        "source_odds": 1.93,
        "source_ev": pytest.approx(split_bet_reference(GOALS_PMF, "over", 2.25, 1.93)),
    }


def test_aggregate_tail_that_crosses_the_line_is_rejected():
    with pytest.raises(ValueError, match="aggregate PMF tail"):
        asian_total_ev({"0": 0.2, "2+": 0.8}, "over", 2.25, 1.9)
    with pytest.raises(ValueError, match="aggregate PMF tail"):
        asian_total_ev({"0": 0.2, "1+": 0.8}, "under", 3.25, 1.9)


@pytest.mark.parametrize("line", (2.1, 2.33, -0.25))
def test_invalid_lines_are_rejected(line):
    with pytest.raises(ValueError):
        asian_total_ev(GOALS_PMF, "over", line, 1.9)


def test_invalid_side_and_odds_are_rejected():
    with pytest.raises(ValueError):
        asian_total_ev(GOALS_PMF, "home", 2.25, 1.9)
    with pytest.raises(ValueError):
        asian_total_ev(GOALS_PMF, "over", 2.25, 1.0)
