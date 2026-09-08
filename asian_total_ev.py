from __future__ import annotations

"""Liquidacion y EV de totales asiaticos sobre una PMF ya calculada.

Este modulo no estima medias ni recalibra modelos. Recibe la distribucion de
conteos enteros producida por OddsHunter y aplica la liquidacion de Bet365 a la
linea original .00/.25/.50/.75.
"""

from dataclasses import dataclass
import math
from typing import Any, Mapping


_OUTCOMES = ("full_win", "half_win", "push", "half_loss", "full_loss")
_LINE_TOLERANCE = 1e-8


@dataclass(frozen=True)
class AsianSettlement:
    """Probabilidad de cada resultado posible de una apuesta asiatica."""

    full_win: float = 0.0
    half_win: float = 0.0
    push: float = 0.0
    half_loss: float = 0.0
    full_loss: float = 0.0

    def expected_profit(self, decimal_odds: float) -> float:
        odds = _valid_odds(decimal_odds)
        win_profit = odds - 1.0
        return (
            self.full_win * win_profit
            + self.half_win * (win_profit / 2.0)
            - self.half_loss * 0.5
            - self.full_loss
        )

    def as_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in _OUTCOMES}


def _finite_number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _valid_odds(value: Any) -> float:
    odds = _finite_number(value, "source_odds")
    if odds <= 1.0:
        raise ValueError("source_odds must be decimal odds greater than 1")
    return odds


def _quarter_line(value: Any) -> tuple[float, int, int]:
    line = _finite_number(value, "source_line")
    if line < 0:
        raise ValueError("source_line cannot be negative")
    quarters = round(line * 4)
    if abs(line * 4 - quarters) > _LINE_TOLERANCE:
        raise ValueError("source_line must end in .00, .25, .50 or .75")
    return quarters / 4.0, quarters // 4, quarters % 4


def _distribution_payload(pmf: Mapping[str | int, Any]) -> Mapping[str | int, Any]:
    probabilities = pmf.get("probabilities")
    if isinstance(probabilities, Mapping):
        # Poisson/NB de corners_model.py y cards_model.py guardan los puntos
        # dentro de probabilities y la cola N+ al nivel exterior.
        merged: dict[str | int, Any] = dict(probabilities)
        merged.update(
            (key, value)
            for key, value in pmf.items()
            if str(key).strip().endswith("+")
        )
        return merged
    return pmf


def _parse_pmf(
    pmf: Mapping[str | int, Any],
) -> tuple[dict[int, float], tuple[int, float] | None]:
    if not isinstance(pmf, Mapping):
        raise TypeError("pmf must be a mapping of integer totals to probabilities")

    points: dict[int, float] = {}
    tail: tuple[int, float] | None = None
    for raw_total, raw_probability in _distribution_payload(pmf).items():
        token = str(raw_total).strip()
        is_tail = token.endswith("+")
        numeric_token = token[:-1] if is_tail else token
        try:
            total = int(numeric_token)
        except ValueError:
            # Metadata such as mean/size/family is deliberately ignored.
            continue
        if total < 0:
            raise ValueError("pmf totals cannot be negative")
        probability = _finite_number(raw_probability, f"pmf[{raw_total!r}]")
        if probability < 0:
            raise ValueError("pmf probabilities cannot be negative")
        if is_tail:
            if tail is not None:
                raise ValueError("pmf cannot contain more than one aggregate tail")
            tail = (total, probability)
        else:
            points[total] = points.get(total, 0.0) + probability

    mass = sum(points.values()) + (tail[1] if tail else 0.0)
    if mass <= 0:
        raise ValueError("pmf must contain positive probability mass")
    points = {total: probability / mass for total, probability in points.items()}
    normalized_tail = (tail[0], tail[1] / mass) if tail else None
    return points, normalized_tail


def _outcome(side: str, total: int, integer: int, fraction_quarters: int) -> str:
    if side == "over":
        if fraction_quarters == 0:
            return "full_win" if total >= integer + 1 else "push" if total == integer else "full_loss"
        if fraction_quarters == 1:
            return "full_win" if total >= integer + 1 else "half_loss" if total == integer else "full_loss"
        if fraction_quarters == 2:
            return "full_win" if total >= integer + 1 else "full_loss"
        return "full_win" if total >= integer + 2 else "half_win" if total == integer + 1 else "full_loss"

    if fraction_quarters == 0:
        return "full_win" if total <= integer - 1 else "push" if total == integer else "full_loss"
    if fraction_quarters == 1:
        return "full_win" if total <= integer - 1 else "half_win" if total == integer else "full_loss"
    if fraction_quarters == 2:
        return "full_win" if total <= integer else "full_loss"
    return "full_win" if total <= integer else "half_loss" if total == integer + 1 else "full_loss"


def asian_total_settlement(
    pmf: Mapping[str | int, Any],
    side: str,
    source_line: float,
) -> AsianSettlement:
    """Return exact settlement probabilities for an Asian total bet."""

    normalized_side = str(side).strip().lower()
    if normalized_side not in {"over", "under"}:
        raise ValueError("side must be 'over' or 'under'")
    _, integer, fraction_quarters = _quarter_line(source_line)
    points, tail = _parse_pmf(pmf)

    buckets = {name: 0.0 for name in _OUTCOMES}
    for total, probability in points.items():
        buckets[_outcome(normalized_side, total, integer, fraction_quarters)] += probability

    if tail and tail[1] > 0:
        tail_start, tail_probability = tail
        first = _outcome(normalized_side, tail_start, integer, fraction_quarters)
        after_every_boundary = _outcome(
            normalized_side,
            max(tail_start, integer + 2),
            integer,
            fraction_quarters,
        )
        # En totales, una vez superado el ultimo umbral el resultado ya no
        # cambia. Si cambia entre N y N+1, la cola N+ no tiene suficiente
        # detalle para calcular un EV real y se rechaza explicitamente.
        if first != after_every_boundary:
            raise ValueError(
                f"aggregate PMF tail {tail_start}+ crosses settlement boundary for line {source_line}"
            )
        buckets[first] += tail_probability

    return AsianSettlement(**buckets)


def asian_total_ev(
    pmf: Mapping[str | int, Any],
    side: str,
    source_line: float,
    source_odds: float,
) -> float:
    """Expected unit profit using the real source line and decimal odds."""

    return asian_total_settlement(pmf, side, source_line).expected_profit(source_odds)


def goals_total_pmf(model: Mapping[str, Any]) -> Mapping[str | int, Any]:
    """Expose the existing Poisson/Dixon-Coles total-goals PMF."""

    distribution = model.get("total_goals_distribution")
    if not isinstance(distribution, Mapping):
        raise ValueError("goal model does not expose total_goals_distribution")
    return distribution


def _count_model_pmf(
    analysis: Mapping[str, Any],
    *,
    poisson_key: str,
    negative_binomial_key: str,
) -> Mapping[str | int, Any]:
    dispersion = analysis.get("negative_binomial_dispersion")
    use_negative_binomial = isinstance(dispersion, Mapping) and bool(dispersion.get("available"))
    selected_key = negative_binomial_key if use_negative_binomial else poisson_key
    distribution = analysis.get(selected_key)
    if not isinstance(distribution, Mapping):
        raise ValueError(f"count model does not expose {selected_key}")
    return distribution


def corners_total_pmf(analysis: Mapping[str, Any]) -> Mapping[str | int, Any]:
    """Return the same Poisson/NB PMF selected by the corners model."""

    return _count_model_pmf(
        analysis,
        poisson_key="poisson_total_distribution",
        negative_binomial_key="negative_binomial_total_distribution",
    )


def cards_total_pmf(analysis: Mapping[str, Any]) -> Mapping[str | int, Any]:
    """Return the same Poisson/NB yellow-card PMF selected by the cards model."""

    return _count_model_pmf(
        analysis,
        poisson_key="poisson_total_yellow_distribution",
        negative_binomial_key="negative_binomial_total_yellow_distribution",
    )


def source_value_record(
    pmf: Mapping[str | int, Any],
    *,
    source_market: str,
    source_side: str,
    source_line: float,
    source_odds: float,
) -> dict[str, Any]:
    """Build the immutable source fields expected by future persistence wiring."""

    line, _, _ = _quarter_line(source_line)
    odds = _valid_odds(source_odds)
    return {
        "source_market": source_market,
        "source_side": str(source_side).strip().lower(),
        "source_line": line,
        "source_odds": odds,
        "source_ev": asian_total_ev(pmf, source_side, line, odds),
    }
