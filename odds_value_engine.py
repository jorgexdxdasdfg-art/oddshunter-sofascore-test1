from __future__ import annotations

"""Probabilidades y valor esperado de OddsHunter.

El motor no inventa cuotas: calcula todos los mercados pedidos con el modelo
local, pero solo calcula EV cuando 5DollarFootballAPI entrega exactamente la
misma linea de Bet365.
"""

import math
from typing import Any


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
        over = probability(row.get("negative_binomial_probability", row.get("poisson_probability")))
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


def _snapshot(market: Any) -> dict[str, Any] | None:
    if not isinstance(market, dict):
        return None
    for key in ("closing", "current", "opening"):
        if isinstance(market.get(key), dict):
            return market[key]
    return None


def provider_prices(markets: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    result = _snapshot(markets.get("1x2"))
    if result:
        for selection, key in (("Local", "result_home"), ("Empate", "result_draw"), ("Visitante", "result_away")):
            price = number(result.get(selection.casefold()))
            if price and price > 1:
                rows.append({"key": key, "market": "Resultado 1X2", "selection": selection, "odds": price})

    for source, prefix, label in (("goal_line", "goals", "Goles"), ("corner_line", "corners", "Córners"), ("card_line", "cards", "Tarjetas")):
        snapshot = _snapshot(markets.get(source))
        line = number((snapshot or {}).get("line"))
        # Las lineas asiaticas enteras/cuarto tienen push o medio-push. No se
        # equiparan silenciosamente con las probabilidades X.5 del bot.
        if line is None or abs(line % 1 - 0.5) > 1e-8:
            continue
        token = str(line).replace(".", "_")
        for side, selection in (("over", "Más"), ("under", "Menos")):
            price = number(snapshot.get(side))
            if price and price > 1:
                rows.append({"key": f"{prefix}_{side}_{token}", "market": label, "selection": f"{selection} de {line:g}", "line": line, "odds": price})

    btts = _snapshot(markets.get("btts"))
    for side, selection in (("yes", "Sí"), ("no", "No")):
        price = number((btts or {}).get(side))
        if price and price > 1:
            rows.append({"key": f"btts_{side}", "market": "Ambos marcan", "selection": selection, "odds": price})

    first_half = _snapshot(markets.get("goal_line_half"))
    if first_half and number(first_half.get("line")) == 0.5:
        for side, selection in (("over", "Sí"), ("under", "No")):
            price = number(first_half.get(side))
            if price and price > 1:
                rows.append({"key": f"first_half_{side}_0_5", "market": "Gol en 1.ª mitad", "selection": selection, "line": 0.5, "odds": price})
    return rows


def rank_value_picks(probabilities: dict[str, float], prices: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for quote in prices:
        model_probability = probabilities.get(str(quote.get("key")))
        odds = number(quote.get("odds"))
        if model_probability is None or odds is None or odds <= 1:
            continue
        ev = model_probability * odds - 1.0
        if ev <= 0:
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
