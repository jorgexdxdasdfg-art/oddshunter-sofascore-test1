from __future__ import annotations

"""Presentation-only mapping from real Asian totals to visual half-lines."""

import math
from enum import Enum
from typing import Any


class BetSide(str, Enum):
    OVER = "over"
    UNDER = "under"


def equivalent_half_line(side: BetSide | str, source_line: Any) -> float:
    """Return the approved visual .5 line without changing the source wager."""

    try:
        bet_side = side if isinstance(side, BetSide) else BetSide(str(side).lower())
        line = float(source_line)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Asian side or line") from exc
    if not math.isfinite(line) or line < 0:
        raise ValueError("Asian line must be finite and non-negative")

    quarters = round(line * 4)
    if abs(line * 4 - quarters) > 1e-8:
        raise ValueError("Asian line must use a .00/.25/.50/.75 increment")
    integer, fraction = divmod(quarters, 4)

    if bet_side is BetSide.OVER:
        return float(integer - 0.5 if fraction == 0 else integer + 0.5 if fraction in (1, 2) else integer + 1.5)
    return float(integer - 0.5 if fraction in (0, 1) else integer + 0.5)
