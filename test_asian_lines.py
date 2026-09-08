from __future__ import annotations

import math

import pytest

from asian_lines import BetSide, equivalent_half_line


@pytest.mark.parametrize(
    ("side", "source_line", "display_line"),
    [
        ("over", 2.00, 1.5), ("over", 2.25, 2.5),
        ("over", 2.50, 2.5), ("over", 2.75, 3.5),
        ("over", 3.00, 2.5), ("over", 3.25, 3.5),
        ("over", 3.50, 3.5), ("over", 3.75, 4.5),
        ("over", 9.00, 8.5), ("over", 9.25, 9.5),
        ("over", 9.50, 9.5), ("over", 9.75, 10.5),
        ("under", 2.00, 1.5), ("under", 2.25, 1.5),
        ("under", 2.50, 2.5), ("under", 2.75, 2.5),
        ("under", 3.00, 2.5), ("under", 3.25, 2.5),
        ("under", 3.50, 3.5), ("under", 3.75, 3.5),
        ("under", 10.00, 9.5), ("under", 10.25, 9.5),
        ("under", 10.50, 10.5), ("under", 10.75, 10.5),
    ],
)
def test_contract_mapping(side, source_line, display_line):
    assert equivalent_half_line(side, source_line) == display_line


@pytest.mark.parametrize("line", [2.1, 2.33, -0.25, math.nan])
def test_invalid_lines_are_rejected(line):
    with pytest.raises(ValueError):
        equivalent_half_line("over", line)


def test_invalid_side_is_rejected():
    with pytest.raises(ValueError):
        equivalent_half_line("home", 2.25)


def test_enum_side_is_accepted():
    assert equivalent_half_line(BetSide.UNDER, 9.25) == 8.5


def test_result_is_always_a_float_half_line():
    result = equivalent_half_line(BetSide.OVER, "4.00")
    assert result == 3.5
    assert isinstance(result, float)
