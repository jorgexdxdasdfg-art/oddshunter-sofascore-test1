from __future__ import annotations

"""Probabilidades y valor esperado de OddsHunter.

El motor no inventa cuotas: calcula todos los mercados pedidos con el modelo
local, pero solo calcula EV cuando 5DollarFootballAPI entrega exactamente la
misma linea de Bet365.
"""

import math
from typing import Any

try:
    from asian_total_ev import (
        asian_total_ev,
        cards_total_pmf,
        corners_total_pmf,
        goals_total_pmf,
    )
except ImportError:  # Vercel imports this file as backend.odds_value_engine.
    from .asian_total_ev import (
        asian_total_ev,
        cards_total_pmf,
        corners_total_pmf,
        goals_total_pmf,
    )


TOTAL_MARKETS = {
    "goal_line": ("goals", "Goles", {1.5, 2.5, 3.5}),
    "card_line": ("cards", "Tarjetas", {1.5, 2.5, 3.5}),
    "corner_line": ("corners", "Córners", {5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5}),
}


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def probability(value: Any) -> float | None:
    result = number(value)
    if result is None:
        return None
    if result > 1.000001:
        result /= 100.0
    return min(1.0, max(0.0, result))


def _first_model(bundle: dict[str, Any]) -> dict[str, Any]:
    models = ((bundle.get("goals") or {}).get("models") or {})
    for key in ("MODELO_APRENDIDO", "MODELO_XG", "MODELO_GOLES"):
        if isinstance(models.get(key), dict) and models[key]:
            return models[key]
    return next((row for row in models.values() if isinstance(row, dict)), {})


def _distribution_over(distribution: dict[str, Any], line: float) -> float | None:
    result, found = 0.0, False
    for raw_total, raw_probability in distribution.items():
        item_probability = probability(raw_probability)
        try:
            total = int(str(raw_total).replace("+", ""))
        except ValueError:
            continue
        if item_probability is None:
            continue
        found = True
        if total > line:
            result += item_probability
    return min(1.0, result) if found else None


def _put_thresholds(
    target: dict[str, float], rows: Any, prefix: str, line_field: str
) -> None:
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        raw_line = number(row.get(line_field))
        # The analysis documents keep both fields and explicitly store ``null``
        # for the family that was not selected. ``dict.get(default)`` does not
        # fall back when the key exists with a null value, so Poisson leagues
        # were silently losing every cards/corners probability here.
        over = probability(row.get("negative_binomial_probability"))
        if over is None:
            over = probability(row.get("poisson_probability"))
        if raw_line is None or over is None:
            continue
        line = raw_line - 0.5 if line_field.startswith("minimum_") else raw_line
        token = str(line).replace(".", "_")
        target[f"{prefix}_over_{token}"] = over
        target[f"{prefix}_under_{token}"] = 1.0 - over


def model_probabilities(
    bundle: dict[str, Any], context: dict[str, Any] | None = None
) -> dict[str, float]:
    model = _first_model(bundle)
    outcome = model.get("outcome_probabilities") or {}
    home, draw, away = (probability(outcome.get(key)) for key in ("home_win", "draw", "away_win"))
    result: dict[str, float] = {}
    if None not in (home, draw, away):
        total = float(home) + float(draw) + float(away)
        if total:
            home, draw, away = float(home) / total, float(draw) / total, float(away) / total
            result.update({
                "result_home": home, "result_draw": draw, "result_away": away,
                "double_home_draw": home + draw,
                "double_away_draw": away + draw,
                "double_home_away": home + away,
            })

    distribution = model.get("total_goals_distribution") or {}
    for line in (1.5, 2.5, 3.5):
        over = _distribution_over(distribution, line) if isinstance(distribution, dict) else None
        if over is not None:
            token = str(line).replace(".", "_")
            result[f"goals_over_{token}"] = over
            result[f"goals_under_{token}"] = 1.0 - over

    home_lambda, away_lambda = number(model.get("lambda_home")), number(model.get("lambda_away"))
    if home_lambda is not None and away_lambda is not None:
        yes = (1.0 - math.exp(-home_lambda)) * (1.0 - math.exp(-away_lambda))
        result.update({"btts_yes": yes, "btts_no": 1.0 - yes})

    cards = (((bundle.get("cards") or {}).get("analysis") or {}).get("yellow_thresholds") or [])
    _put_thresholds(result, cards, "cards", "line_equivalent")
    corners = (((bundle.get("corners") or {}).get("analysis") or {}).get("minimum_total_thresholds") or [])
    _put_thresholds(result, corners, "corners", "minimum_total_corners")

    derived = (context or {}).get("derived") or {}
    home_ctx = derived.get("home_relevant") or derived.get("home_general") or {}
    away_ctx = derived.get("away_relevant") or derived.get("away_general") or {}
    halves = [probability(home_ctx.get("first_half_over_0_5")), probability(away_ctx.get("first_half_over_0_5"))]
    halves = [value for value in halves if value is not None]
    if halves:
        first_half = sum(halves) / len(halves)
        result.update({"first_half_over_0_5": first_half, "first_half_under_0_5": 1.0 - first_half})
    return {key: round(value, 8) for key, value in result.items()}


def _snapshot(
    market: Any,
    snapshot_order: tuple[str, ...] = ("closing", "opening"),
) -> dict[str, Any] | None:
    if not isinstance(market, dict):
        return None
    for key in snapshot_order:
        if isinstance(market.get(key), dict):
            return market[key]
    return None


def asian_display_line(source_line: Any) -> float | None:
    """Map a real Asian source line to the approved visual half-line."""

    line = number(source_line)
    if line is None or line < 0:
        return None
    quarters = round(line * 4)
    if abs(line * 4 - quarters) > 1e-8:
        return None
    integer, fraction = divmod(quarters, 4)
    if fraction == 0:
        return integer - 0.5
    if fraction in (1, 2):
        return integer + 0.5
    return integer + 1.5


def _price_priority(row: dict[str, Any]) -> int:
    return 2 if row.get("price_origin") == "EXACT_HALF_LINE" else 1


def preferred_visual_prices(prices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one quote per visual row, always preferring an exact .5 line."""

    selected: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in prices:
        key = str(row.get("key") or "")
        if not key:
            continue
        if key not in selected:
            selected[key] = row
            order.append(key)
        elif _price_priority(row) > _price_priority(selected[key]):
            selected[key] = row
    return [selected[key] for key in order]


def provider_prices(
    markets: dict[str, Any],
    *,
    snapshot_order: tuple[str, ...] = ("closing", "opening"),
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    result = _snapshot(markets.get("1x2"), snapshot_order)
    if result:
        # 5DollarFootballAPI uses the canonical English keys in both the
        # batch ``include=odds`` expansion and the detailed endpoint.
        for source, selection, key in (
            ("home", "Local", "result_home"),
            ("draw", "Empate", "result_draw"),
            ("away", "Visitante", "result_away"),
        ):
            price = number(result.get(source))
            if price and price > 1:
                rows.append({"key": key, "market": "Resultado 1X2", "selection": selection, "odds": price})

    for source, (prefix, label, catalog) in TOTAL_MARKETS.items():
        snapshot = _snapshot(markets.get(source), snapshot_order)
        source_line = number((snapshot or {}).get("line"))
        display_line = asian_display_line(source_line)
        if source_line is None or display_line not in catalog:
            continue
        exact = abs(source_line % 1 - 0.5) <= 1e-8
        token = str(display_line).replace(".", "_")
        for side, selection in (("over", "Más"), ("under", "Menos")):
            price = number(snapshot.get(side))
            if price and price > 1:
                rows.append({
                    "key": f"{prefix}_{side}_{token}",
                    "market": label,
                    "selection": f"{selection} de {display_line:g}",
                    "line": display_line,
                    "display_line": display_line,
                    "source_market": source,
                    "source_side": side,
                    "source_line": source_line,
                    "source_odds": price,
                    "odds": price,
                    "price_origin": "EXACT_HALF_LINE" if exact else "ASIAN_MAPPED",
                })

    btts = _snapshot(markets.get("btts"), snapshot_order)
    for side, selection in (("yes", "Sí"), ("no", "No")):
        price = number((btts or {}).get(side))
        if price and price > 1:
            rows.append({"key": f"btts_{side}", "market": "Ambos marcan", "selection": selection, "odds": price})

    first_half = _snapshot(markets.get("goal_line_half"), snapshot_order)
    if first_half and number(first_half.get("line")) == 0.5:
        for side, selection in (("over", "Sí"), ("under", "No")):
            price = number(first_half.get(side))
            if price and price > 1:
                rows.append({"key": f"first_half_{side}_0_5", "market": "Gol en 1.ª mitad", "selection": selection, "line": 0.5, "odds": price})
    return preferred_visual_prices(rows)


def _source_pmf(bundle: dict[str, Any], source_market: str) -> Any:
    if source_market == "goal_line":
        return goals_total_pmf(_first_model(bundle))
    analysis = ((bundle.get("corners") or {}).get("analysis") or {})
    if source_market == "corner_line":
        return corners_total_pmf(analysis)
    analysis = ((bundle.get("cards") or {}).get("analysis") or {})
    if source_market == "card_line":
        return cards_total_pmf(analysis)
    raise ValueError(f"unsupported Asian total market: {source_market}")


def attach_asian_source_values(
    bundle: dict[str, Any], prices: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Calculate source EV once, before visual serialization or ranking."""

    result: list[dict[str, Any]] = []
    pmfs: dict[str, Any] = {}
    for original in preferred_visual_prices(prices):
        row = dict(original)
        source_market = str(row.get("source_market") or "")
        source_line = number(row.get("source_line"))
        source_odds = number(row.get("source_odds", row.get("odds")))
        source_side = str(row.get("source_side") or "")
        if source_market in TOTAL_MARKETS and source_line is not None and source_odds is not None:
            try:
                if source_market not in pmfs:
                    pmfs[source_market] = _source_pmf(bundle, source_market)
                row["source_ev"] = round(
                    asian_total_ev(pmfs[source_market], source_side, source_line, source_odds),
                    12,
                )
            except (TypeError, ValueError):
                # Sin una PMF liquidable no se sustituye por la probabilidad
                # de la fila visual: cuota y EV permanecen sin asociar.
                row.pop("source_ev", None)
        result.append(row)
    return result


def _quote_ev(model_probability: float, quote: dict[str, Any], odds: float) -> float | None:
    source_ev = number(quote.get("source_ev"))
    if source_ev is not None:
        return source_ev
    if quote.get("price_origin") == "ASIAN_MAPPED":
        return None
    return model_probability * odds - 1.0


def build_all_picks(
    probabilities: dict[str, float], prices: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_key = {str(row.get("key")): row for row in preferred_visual_prices(prices)}
    rows: list[dict[str, Any]] = []
    for key, model_probability in probabilities.items():
        quote = by_key.get(key) or {}
        odds = number(quote.get("current_odds", quote.get("source_odds", quote.get("odds"))))
        odds = odds if odds is not None and odds > 1 else None
        ev = _quote_ev(model_probability, quote, odds) if odds is not None else None
        source_fields = {
            field: quote[field]
            for field in (
                "display_line", "source_market", "source_side", "source_line",
                "source_odds", "source_ev", "price_origin",
            )
            if quote.get(field) is not None
        }
        rows.append({
            "key": key,
            "probability": round(model_probability * 100, 2),
            "odds": odds,
            "ev": round(ev * 100, 2) if ev is not None else None,
            "odds_status": "AVAILABLE" if odds is not None and ev is not None else "NOT_IN_PROVIDER_RESPONSE",
            **source_fields,
        })
    return rows


def rank_value_picks(probabilities: dict[str, float], prices: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for quote in preferred_visual_prices(prices):
        model_probability = probabilities.get(str(quote.get("key")))
        odds = number(quote.get("current_odds", quote.get("source_odds", quote.get("odds"))))
        if model_probability is None or odds is None or odds <= 1:
            continue
        ev = _quote_ev(model_probability, quote, odds)
        if ev is None or ev <= 0:
            continue
        full_kelly = ev / (odds - 1.0)
        rows.append({
            **quote,
            "probability": round(model_probability * 100, 2),
            "implied_probability": round(100 / odds, 2),
            "ev": round(ev * 100, 2),
            "recommended_bankroll_pct": round(min(0.05, max(0.0, full_kelly * 0.25)) * 100, 2),
        })
    rows.sort(key=lambda row: (row["recommended_bankroll_pct"], row["ev"], row["probability"]), reverse=True)
    return rows[: max(0, int(limit))]


def refresh_model_picks(
    bundle: dict[str, Any], stored: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build every model selection independently of bookmaker coverage.

    Pure calculation: API serialization and odds sync share this function;
    opening either Mobile tab never triggers a provider request.
    """
    existing = stored or {}
    probabilities = {**(existing.get("probabilities") or {}), **model_probabilities(bundle, context)}
    prices = attach_asian_source_values(bundle, existing.get("available_prices") or [])
    all_picks = build_all_picks(probabilities, prices)
    return {
        **existing,
        "odds_status": existing.get("odds_status") or "NOT_AVAILABLE_YET",
        "probabilities": probabilities,
        "available_prices": prices,
        "all_picks": all_picks,
        "top_picks": rank_value_picks(probabilities, prices, 4),
    }
