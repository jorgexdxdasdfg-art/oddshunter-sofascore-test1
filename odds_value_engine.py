from __future__ import annotations

"""Probabilidades y valor esperado de OddsHunter.

El motor no inventa cuotas: calcula todos los mercados pedidos con el modelo
local, pero solo calcula EV cuando 5DollarFootballAPI entrega exactamente la
misma linea de Bet365.
"""

import math
from typing import Any, Mapping

try:
    from asian_lines import BetSide, equivalent_half_line
except ImportError:  # Vercel imports this file as backend.odds_value_engine.
    from .asian_lines import BetSide, equivalent_half_line

try:
    from asian_total_ev import (
        asian_total_ev,
        asian_total_settlement,
        cards_total_pmf,
        corners_total_pmf,
        goals_total_pmf,
    )
except ImportError:  # Vercel imports this file as backend.odds_value_engine.
    from .asian_total_ev import (
        asian_total_ev,
        asian_total_settlement,
        cards_total_pmf,
        corners_total_pmf,
        goals_total_pmf,
    )


TOTAL_MARKETS = {
    "goal_line": ("goals", "Goles", {1.5, 2.5, 3.5}),
    "card_line": ("cards", "Tarjetas", {1.5, 2.5, 3.5}),
    "corner_line": ("corners", "Córners", {5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5}),
}

HIDDEN_VISUAL_PICK_KEYS = {
    "cards_over_0_5", "cards_under_0_5",
    "corners_over_5_5", "corners_under_5_5",
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


def asian_display_line(source_side: Any, source_line: Any) -> float | None:
    """Map a real Asian source line to the approved visual half-line."""

    try:
        return equivalent_half_line(BetSide(str(source_side).lower()), source_line)
    except (TypeError, ValueError):
        return None


def _price_priority(row: dict[str, Any]) -> int:
    return {
        "EXACT_HALF_LINE": 3,
        "ASIAN_MAPPED": 2,
        "BET365_ANCHORED_ESTIMATE": 1,
    }.get(str(row.get("price_origin") or ""), 2)


def _remap_persisted_source_price(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize previously persisted Asian rows without fetching new odds."""

    source_market = str(row.get("source_market") or "")
    if source_market not in TOTAL_MARKETS:
        return row
    prefix, label, catalog = TOTAL_MARKETS[source_market]
    source_side = str(row.get("source_side") or "").lower()
    source_line = number(row.get("source_line"))
    display_line = asian_display_line(source_side, source_line)
    if source_side not in {"over", "under"} or display_line not in catalog:
        return None
    token = str(display_line).replace(".", "_")
    return {
        **row,
        "key": f"{prefix}_{source_side}_{token}",
        "market": label,
        "selection": f"{'Más' if source_side == 'over' else 'Menos'} de {display_line:g}",
        "line": display_line,
        "display_line": display_line,
    }


def preferred_visual_prices(prices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one quote per visual row, always preferring an exact .5 line."""

    selected: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for original in prices:
        row = _remap_persisted_source_price(dict(original))
        if row is None:
            continue
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
        if source_line is None:
            continue
        exact = abs(source_line % 1 - 0.5) <= 1e-8
        for side, selection in (("over", "Más"), ("under", "Menos")):
            display_line = asian_display_line(side, source_line)
            if display_line not in catalog:
                continue
            token = str(display_line).replace(".", "_")
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


def _pmf_points(pmf: Mapping[str | int, Any]) -> dict[int, float]:
    """Flatten an existing OddsHunter PMF for market-shape calibration."""

    payload = pmf.get("probabilities") if isinstance(pmf.get("probabilities"), Mapping) else pmf
    rows: dict[int, float] = {}
    for raw_total, raw_value in payload.items():
        token = str(raw_total).strip()
        if token in {"probabilities", "mean", "size", "family"}:
            continue
        try:
            total = int(token[:-1] if token.endswith("+") else token)
        except ValueError:
            continue
        value = number(raw_value)
        if value is not None and value >= 0:
            rows[total] = rows.get(total, 0.0) + value
    if payload is not pmf:
        for raw_total, raw_value in pmf.items():
            token = str(raw_total).strip()
            if not token.endswith("+"):
                continue
            try:
                total = int(token[:-1])
            except ValueError:
                continue
            value = number(raw_value)
            if value is not None and value >= 0:
                rows[total] = rows.get(total, 0.0) + value
    mass = sum(rows.values())
    if mass <= 0:
        raise ValueError("PMF without positive mass")
    return {total: value / mass for total, value in rows.items()}


def _tilted_pmf(points: Mapping[int, float], theta: float) -> dict[int, float]:
    center = sum(total * value for total, value in points.items())
    weighted = {
        total: value * math.exp(max(-700.0, min(700.0, theta * (total - center))))
        for total, value in points.items()
    }
    mass = sum(weighted.values())
    return {total: value / mass for total, value in weighted.items()}


def _asian_over_score(pmf: Mapping[str | int, Any], line: float) -> float:
    """Return the complementary 0..1 settlement score of the Over side."""

    try:
        from asian_total_ev import asian_total_settlement
    except ImportError:
        from .asian_total_ev import asian_total_settlement

    settlement = asian_total_settlement(pmf, "over", line)
    return (
        settlement.full_win
        + 0.75 * settlement.half_win
        + 0.5 * settlement.push
        + 0.25 * settlement.half_loss
    )


def _calibrated_market_pmf(
    pmf: Mapping[str | int, Any], source_line: float, market_over_probability: float
) -> dict[int, float]:
    """Exponentially tilt the existing PMF to the de-vigged Bet365 anchor."""

    points = _pmf_points(pmf)
    target = min(1.0 - 1e-10, max(1e-10, market_over_probability))
    low, high = -12.0, 12.0
    for _ in range(100):
        middle = (low + high) / 2.0
        score = _asian_over_score(_tilted_pmf(points, middle), source_line)
        if score < target:
            low = middle
        else:
            high = middle
    return _tilted_pmf(points, (low + high) / 2.0)


def _real_total_identity(row: dict[str, Any]) -> tuple[str, str, float, float] | None:
    if row.get("price_origin") == "BET365_ANCHORED_ESTIMATE":
        return None
    key = str(row.get("key") or "")
    source_market = str(row.get("source_market") or "")
    if source_market not in TOTAL_MARKETS:
        source_market = next(
            (market for market, (prefix, _, _) in TOTAL_MARKETS.items() if key.startswith(f"{prefix}_")),
            "",
        )
    if source_market not in TOTAL_MARKETS:
        return None
    source_side = str(row.get("source_side") or "").lower()
    if source_side not in {"over", "under"}:
        source_side = "over" if "_over_" in key else "under" if "_under_" in key else ""
    source_line = number(row.get("source_line", row.get("line")))
    source_odds = number(row.get("source_odds", row.get("current_odds", row.get("odds"))))
    if source_side not in {"over", "under"} or source_line is None or source_odds is None or source_odds <= 1:
        return None
    return source_market, source_side, source_line, source_odds


def _estimated_quote(
    *, key: str, market: str, selection: str, line: float | None,
    odds: float, model_probability: float, anchor_market: str,
    anchor_line: float | None = None,
) -> dict[str, Any] | None:
    if not math.isfinite(odds) or odds <= 1:
        return None
    rounded_odds = round(odds, 3)
    estimated_ev = model_probability * rounded_odds - 1.0
    return {
        "key": key,
        "market": market,
        "selection": selection,
        **({"line": line, "display_line": line} if line is not None else {}),
        "odds": rounded_odds,
        "estimated_odds": rounded_odds,
        "estimated_ev": round(estimated_ev, 12),
        "estimated_from_market": anchor_market,
        "anchor_market": anchor_market,
        **({"anchor_line": anchor_line} if anchor_line is not None else {}),
        "price_origin": "BET365_ANCHORED_ESTIMATE",
    }


def market_anchored_prices(
    bundle: dict[str, Any], probabilities: dict[str, float], prices: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fill missing visual rows from real cached Bet365 anchor markets.

    This is a pure calculation over already fetched prices. Real quotes remain
    authoritative and are never replaced by a derived estimate.
    """

    real_prices = [dict(row) for row in preferred_visual_prices(prices)]
    estimates: list[dict[str, Any]] = []
    by_key = {str(row.get("key") or ""): row for row in real_prices}

    result_odds = {
        key: number((by_key.get(key) or {}).get("current_odds", (by_key.get(key) or {}).get("odds")))
        for key in ("result_home", "result_draw", "result_away")
    }
    if all(value is not None and value > 1 for value in result_odds.values()):
        inverse = {key: 1.0 / float(value) for key, value in result_odds.items()}
        overround = sum(inverse.values())
        fair = {key: value / overround for key, value in inverse.items()}
        for key, selection, component_keys in (
            ("double_home_draw", "Local o empate", ("result_home", "result_draw")),
            ("double_away_draw", "Empate o visitante", ("result_draw", "result_away")),
            ("double_home_away", "Local o visitante", ("result_home", "result_away")),
        ):
            model_probability = probabilities.get(key)
            market_probability = sum(fair[item] for item in component_keys)
            if model_probability is None or market_probability <= 0:
                continue
            quote = _estimated_quote(
                key=key, market="Doble oportunidad", selection=selection, line=None,
                odds=1.0 / (market_probability * overround),
                model_probability=model_probability, anchor_market="1X2_BET365",
            )
            if quote:
                estimates.append(quote)

    anchors: dict[tuple[str, float], dict[str, float]] = {}
    for row in real_prices:
        identity = _real_total_identity(row)
        if identity:
            source_market, side, source_line, source_odds = identity
            anchors.setdefault((source_market, source_line), {})[side] = source_odds

    for (source_market, source_line), sides in anchors.items():
        if set(sides) != {"over", "under"}:
            continue
        inverse_over, inverse_under = 1.0 / sides["over"], 1.0 / sides["under"]
        overround = inverse_over + inverse_under
        try:
            market_pmf = _calibrated_market_pmf(
                _source_pmf(bundle, source_market), source_line, inverse_over / overround
            )
        except (TypeError, ValueError, OverflowError):
            continue
        prefix, market_label, catalog = TOTAL_MARKETS[source_market]
        anchor_market = f"{source_market} O{source_line:g}/U{source_line:g} BET365"
        for line in sorted(catalog):
            market_over = sum(value for total, value in market_pmf.items() if total > line)
            for side, selection, market_probability in (
                ("over", "Más", market_over),
                ("under", "Menos", 1.0 - market_over),
            ):
                token = str(line).replace(".", "_")
                key = f"{prefix}_{side}_{token}"
                model_probability = probabilities.get(key)
                if model_probability is None or market_probability <= 0:
                    continue
                quote = _estimated_quote(
                    key=key, market=market_label, selection=f"{selection} de {line:g}", line=line,
                    odds=1.0 / (market_probability * overround),
                    model_probability=model_probability, anchor_market=anchor_market,
                    anchor_line=source_line,
                )
                if quote:
                    estimates.append(quote)

    return preferred_visual_prices(real_prices + estimates)


def _quote_ev(model_probability: float, quote: dict[str, Any], odds: float) -> float | None:
    source_ev = number(quote.get("source_ev"))
    if source_ev is not None:
        return source_ev
    estimated_ev = number(quote.get("estimated_ev"))
    if estimated_ev is not None:
        return estimated_ev
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
                "source_odds", "source_ev", "estimated_odds", "estimated_ev",
                "estimated_from_market", "anchor_market", "price_origin",
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


def _pick_parts(key: str) -> tuple[str, str, float | None]:
    parts = key.split("_")
    if len(parts) >= 4 and parts[0] in {"goals", "corners", "cards"} and parts[1] in {"over", "under"}:
        try:
            return parts[0], parts[1], float(f"{parts[2]}.{parts[3]}")
        except ValueError:
            pass
    if key.startswith("first_half_over_"):
        return "first_half", "over", 0.5
    if key.startswith("first_half_under_"):
        return "first_half", "under", 0.5
    if key == "btts_yes":
        return "btts", "yes", None
    if key == "btts_no":
        return "btts", "no", None
    return key.split("_", 1)[0], key.rsplit("_", 1)[-1], None


def _expected_total(bundle: dict[str, Any], market: str) -> float | None:
    if market == "goals":
        model = _first_model(bundle)
        total = number(model.get("expected_total_goals"))
        if total is None:
            home, away = number(model.get("lambda_home")), number(model.get("lambda_away"))
            total = home + away if home is not None and away is not None else None
        return total
    analysis = ((bundle.get(market) or {}).get("analysis") or {})
    if market == "corners":
        total = number(analysis.get("expected_total_corners"))
        field = "expected_corners"
    elif market == "cards":
        total = number(analysis.get("expected_total_yellow_cards"))
        field = "expected_yellow_cards"
    else:
        return None
    if total is not None:
        return total
    home = number((analysis.get("home_team") or {}).get(field))
    away = number((analysis.get("away_team") or {}).get(field))
    return home + away if home is not None and away is not None else None


def _coherence_score(key: str, bundle: dict[str, Any]) -> float:
    market, side, line = _pick_parts(key)
    if market not in {"goals", "corners", "cards"} or line is None:
        return 50.0
    expected = _expected_total(bundle, market)
    if expected is None:
        return 50.0
    signed_distance = expected - line if side == "over" else line - expected
    if signed_distance >= 1.0:
        return 100.0
    if signed_distance >= 0.5:
        return 75.0
    if signed_distance > -0.5:
        return 50.0
    if signed_distance > -1.0:
        return 25.0
    return 0.0


def _comparison_average(context: dict[str, Any] | None, field: str) -> float | None:
    comparison = (context or {}).get("comparison") or {}
    values = []
    for side in ("home", "away"):
        value = number((((comparison.get(side) or {}).get("summary") or {}).get(field)))
        if value is not None:
            values.append(value if value > 1.000001 else value * 100.0)
    return sum(values) / len(values) if values else None


def _tendency_score(key: str, context: dict[str, Any] | None) -> float:
    market, side, line = _pick_parts(key)
    field = None
    if market == "goals" and line in {1.5, 2.5}:
        field = f"over_{int(line)}_5"
    elif market == "cards" and line == 3.5:
        field = "over_3_5_cards"
    elif market == "corners" and line == 9.5:
        field = "over_9_5_corners"
    elif market == "first_half":
        field = "over_0_5_ht"
    elif market == "btts":
        field = "btts"
    over = _comparison_average(context, field) if field else None
    if over is None:
        return 50.0
    return min(100.0, max(0.0, 100.0 - over if side in {"under", "no"} else over))


def _origin_confidence(quote: dict[str, Any]) -> float:
    origin = str(quote.get("price_origin") or "")
    if origin in {"BET365_ANCHORED_ESTIMATE"}:
        return 0.80
    if origin in {"ASIAN_MAPPED", "REAL_ASIAN_MAPPED"}:
        return 0.95
    return 1.0


def _distance_confidence(quote: dict[str, Any]) -> float:
    if str(quote.get("price_origin") or "") != "BET365_ANCHORED_ESTIMATE":
        return 1.0
    display_line = number(quote.get("display_line", quote.get("line")))
    anchor_line = number(quote.get("anchor_line"))
    if display_line is None or anchor_line is None:
        return 1.0
    return math.exp(-0.12 * abs(display_line - anchor_line))


def top_pick_score(
    key: str,
    model_probability: float,
    ev: float,
    quote: dict[str, Any],
    bundle: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Return ranking-only signals; displayed probability and EV are untouched."""

    probability_score = model_probability * 100.0
    ev_percent = ev * 100.0
    ev_score = 100.0 * (1.0 - math.exp(-max(ev_percent, 0.0) / 20.0))
    expected_score = _coherence_score(key, bundle or {})
    tendency_score = _tendency_score(key, context)
    base_score = (
        0.55 * probability_score
        + 0.25 * ev_score
        + 0.12 * expected_score
        + 0.08 * tendency_score
    )
    origin_confidence = _origin_confidence(quote)
    distance_confidence = _distance_confidence(quote)
    return {
        "probability_score": round(probability_score, 6),
        "ev_score": round(ev_score, 6),
        "expected_score": round(expected_score, 6),
        "tendency_score": round(tendency_score, 6),
        "base_score": round(base_score, 6),
        "origin_confidence": origin_confidence,
        "distance_confidence": round(distance_confidence, 8),
        "top_pick_score": round(base_score * origin_confidence * distance_confidence, 6),
    }


def rank_value_picks(
    probabilities: dict[str, float], prices: list[dict[str, Any]], limit: int = 4,
    bundle: dict[str, Any] | None = None, context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for quote in preferred_visual_prices(prices):
        key = str(quote.get("key"))
        if key in HIDDEN_VISUAL_PICK_KEYS:
            continue
        model_probability = probabilities.get(key)
        odds = number(quote.get("current_odds", quote.get("source_odds", quote.get("odds"))))
        if model_probability is None or odds is None or odds <= 1:
            continue
        ev = _quote_ev(model_probability, quote, odds)
        if ev is None or ev <= 0:
            continue
        score = top_pick_score(str(quote.get("key")), model_probability, ev, quote, bundle, context)
        full_kelly = ev / (odds - 1.0)
        rows.append({
            **quote,
            "probability": round(model_probability * 100, 2),
            "implied_probability": round(100 / odds, 2),
            "ev": round(ev * 100, 2),
            "recommended_bankroll_pct": round(min(0.05, max(0.0, full_kelly * 0.25)) * 100, 2),
            **score,
        })
    rows.sort(key=lambda row: (row["top_pick_score"], row["probability"], row["ev"]), reverse=True)
    return rows[: max(0, int(limit))]


def freeze_all_picks(all_picks: list[dict[str, Any]], captured_at: str) -> list[dict[str, Any]]:
    """Freeze the complete pre-match probability catalogue, odds optional."""

    frozen: list[dict[str, Any]] = []
    for original in all_picks:
        row = dict(original)
        key = str(row.get("key") or row.get("pick_id") or "")
        if not key:
            continue
        market, side, parsed_line = _pick_parts(key)
        frozen.append({
            **row,
            "pick_id": str(row.get("pick_id") or key),
            "market": row.get("market") or market,
            "side": row.get("side") or side,
            "display_side": row.get("display_side") or side,
            "display_line": number(row.get("display_line", row.get("line", parsed_line))),
            "probability_at_recommendation": number(
                row.get("probability_at_recommendation", row.get("probability"))
            ),
            "odds_at_recommendation": number(
                row.get("odds_at_recommendation", row.get("odds"))
            ),
            "ev_at_recommendation": number(
                row.get("ev_at_recommendation", row.get("ev"))
            ),
            "recommended_at": row.get("recommended_at") or captured_at,
        })
    return frozen


def immutable_all_picks(
    existing: dict[str, Any], all_picks: list[dict[str, Any]], captured_at: str,
    event: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Keep the first full pre-match catalogue; never reconstruct it after FT."""

    snapshot = existing.get("all_picks_snapshot")
    if isinstance(snapshot, list) and snapshot:
        return [dict(row) for row in snapshot if isinstance(row, dict)]
    legacy = existing.get("all_picks")
    if isinstance(legacy, list) and legacy:
        source = legacy
    elif _terminal_status(event or {}):
        source = []
    else:
        source = all_picks
    return freeze_all_picks(source, captured_at) if source else []


def freeze_top_picks(top_picks: list[dict[str, Any]], recommended_at: str) -> list[dict[str, Any]]:
    """Create the immutable recommendation snapshot used after kickoff."""

    frozen: list[dict[str, Any]] = []
    for original in top_picks:
        row = dict(original)
        key = str(row.get("key") or row.get("pick_id") or "")
        market, side, parsed_line = _pick_parts(key)
        odds = number(row.get("current_odds", row.get("source_odds", row.get("estimated_odds", row.get("odds")))))
        display_line = number(row.get("display_line", row.get("line", parsed_line)))
        frozen.append({
            **row,
            "pick_id": str(row.get("pick_id") or key),
            "market": row.get("market") or market,
            "side": row.get("side") or side,
            "display_side": row.get("display_side") or side,
            "display_line": display_line,
            "source_line": number(row.get("source_line")),
            "source_side": row.get("source_side"),
            "probability_at_recommendation": number(row.get("probability_at_recommendation", row.get("probability"))),
            "odds_at_recommendation": number(row.get("odds_at_recommendation", odds)),
            "ev_at_recommendation": number(row.get("ev_at_recommendation", row.get("ev"))),
            "top_pick_score_at_recommendation": number(row.get("top_pick_score_at_recommendation", row.get("top_pick_score"))),
            "recommended_at": row.get("recommended_at") or recommended_at,
        })
    return frozen


def immutable_top_picks(
    existing: dict[str, Any], ranked: list[dict[str, Any]], recommended_at: str,
    event: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    snapshot = existing.get("top_picks_snapshot")
    if isinstance(snapshot, list) and snapshot:
        return [dict(row) for row in snapshot if isinstance(row, dict)]
    legacy = existing.get("top_picks")
    if isinstance(legacy, list) and legacy:
        source = legacy
    elif _terminal_status(event or {}):
        # Never manufacture a historical recommendation after the result.
        source = []
    else:
        source = ranked
    return freeze_top_picks(source, recommended_at) if source else []


def _terminal_status(event: dict[str, Any]) -> bool:
    token = str(event.get("status") or event.get("status_description") or "").strip().lower()
    return token in {"ft", "final", "finished", "ended", "completed", "finalizado", "terminado"}


def _actual_number(actual: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = number(actual.get(key))
        if value is not None:
            return value
    return None


def _actual_total(market: str, event: dict[str, Any], actual: dict[str, Any]) -> int | None:
    aliases = {
        "goals": (("home_goals", "goals_home"), ("away_goals", "goals_away")),
        "first_half": (("home_goals_1h", "home_score_1h"), ("away_goals_1h", "away_score_1h")),
        "corners": (("home_corners", "corners_home", "home_corner_kicks"), ("away_corners", "corners_away", "away_corner_kicks")),
        "cards": (("home_yellow_cards", "yellow_cards_home"), ("away_yellow_cards", "yellow_cards_away")),
    }
    if market not in aliases:
        return None
    home = _actual_number(actual, *aliases[market][0])
    away = _actual_number(actual, *aliases[market][1])
    if market == "goals":
        home = home if home is not None else number(event.get("home_score"))
        away = away if away is not None else number(event.get("away_score"))
    return int(home + away) if home is not None and away is not None else None


def _binary_result(condition: bool, estimated: bool) -> str:
    if estimated:
        return "CUMPLIDO" if condition else "NO CUMPLIDO"
    return "WIN" if condition else "LOSS"


def _settle_recommended_pick(snapshot: dict[str, Any], event: dict[str, Any], actual: dict[str, Any]) -> str:
    key = str(snapshot.get("key") or snapshot.get("pick_id") or "")
    market, side, parsed_line = _pick_parts(key)
    estimated = str(snapshot.get("price_origin") or "") == "BET365_ANCHORED_ESTIMATE"
    home = _actual_number(actual, "home_goals", "goals_home")
    away = _actual_number(actual, "away_goals", "goals_away")
    home = home if home is not None else number(event.get("home_score"))
    away = away if away is not None else number(event.get("away_score"))
    if key.startswith("result_") or key.startswith("double_") or key.startswith("btts_"):
        if home is None or away is None:
            return "PENDIENTE DE RESULTADO"
        conditions = {
            "result_home": home > away, "result_draw": home == away, "result_away": away > home,
            "double_home_draw": home >= away, "double_away_draw": away >= home,
            "double_home_away": home != away,
            "btts_yes": home > 0 and away > 0, "btts_no": home == 0 or away == 0,
        }
        return _binary_result(bool(conditions.get(key)), estimated)
    total = _actual_total(market, event, actual)
    if total is None:
        return "PENDIENTE DE RESULTADO"
    if estimated:
        line = number(snapshot.get("display_line", parsed_line))
        if line is None:
            return "PENDIENTE DE RESULTADO"
        return _binary_result(total > line if side == "over" else total < line, True)
    source_line = number(snapshot.get("source_line", snapshot.get("display_line", parsed_line)))
    source_side = str(snapshot.get("source_side") or side)
    if source_line is None or source_side not in {"over", "under"}:
        return "PENDIENTE DE RESULTADO"
    settlement = asian_total_settlement({str(total): 1.0}, source_side, source_line)
    return next((label for field, label in (
        ("full_win", "WIN"), ("half_win", "HALF_WIN"), ("push", "PUSH"),
        ("half_loss", "HALF_LOSS"), ("full_loss", "LOSS"),
    ) if getattr(settlement, field) > 0.999999), "PENDIENTE DE RESULTADO")


def final_pick_results(
    snapshot: list[dict[str, Any]], event: dict[str, Any], actual: dict[str, Any] | None,
) -> dict[str, Any]:
    if not _terminal_status(event):
        return {"available": False, "picks": [], "summary": {}}
    rows = []
    for original in snapshot:
        row = dict(original)
        if str(row.get("key") or row.get("pick_id") or "") in HIDDEN_VISUAL_PICK_KEYS:
            continue
        row["result"] = _settle_recommended_pick(row, event, actual or {})
        rows.append(row)
    labels = ("WIN", "HALF_WIN", "PUSH", "HALF_LOSS", "LOSS", "CUMPLIDO", "NO CUMPLIDO", "PENDIENTE DE RESULTADO")
    counts = {label: sum(row["result"] == label for row in rows) for label in labels}
    return {"available": True, "picks": rows, "summary": counts}


def _settle_display_pick(snapshot: dict[str, Any], event: dict[str, Any], actual: dict[str, Any]) -> str:
    """Evaluate prediction accuracy using the displayed selection, never source odds."""

    key = str(snapshot.get("key") or snapshot.get("pick_id") or "")
    market, side, parsed_line = _pick_parts(key)
    home = _actual_number(actual, "home_goals", "goals_home")
    away = _actual_number(actual, "away_goals", "goals_away")
    home = home if home is not None else number(event.get("home_score"))
    away = away if away is not None else number(event.get("away_score"))
    if key.startswith("result_") or key.startswith("double_") or key.startswith("btts_"):
        if home is None or away is None:
            return "PENDIENTE"
        conditions = {
            "result_home": home > away, "result_draw": home == away, "result_away": away > home,
            "double_home_draw": home >= away, "double_away_draw": away >= home,
            "double_home_away": home != away,
            "btts_yes": home > 0 and away > 0, "btts_no": home == 0 or away == 0,
        }
        return "ACERTADO" if bool(conditions.get(key)) else "FALLADO"
    total = _actual_total(market, event, actual)
    line = number(snapshot.get("display_line", parsed_line))
    display_side = str(snapshot.get("display_side") or side)
    if total is None or line is None or display_side not in {"over", "under"}:
        return "PENDIENTE"
    happened = total > line if display_side == "over" else total < line
    return "ACERTADO" if happened else "FALLADO"


def high_probability_pick_results(
    snapshot: list[dict[str, Any]], event: dict[str, Any], actual: dict[str, Any] | None,
    threshold: float = 60.0,
) -> dict[str, Any]:
    if not _terminal_status(event):
        return {"available": False, "threshold": threshold, "picks": [], "summary": {}}
    rows: list[dict[str, Any]] = []
    for original in snapshot:
        row = dict(original)
        key = str(row.get("key") or row.get("pick_id") or "")
        if key in HIDDEN_VISUAL_PICK_KEYS:
            continue
        model_probability = number(row.get("probability_at_recommendation", row.get("probability")))
        if model_probability is None or model_probability < threshold:
            continue
        row["probability_at_recommendation"] = model_probability
        row["result"] = _settle_display_pick(row, event, actual or {})
        rows.append(row)
    rows.sort(key=lambda row: number(row.get("probability_at_recommendation")) or 0.0, reverse=True)
    hits = sum(row["result"] == "ACERTADO" for row in rows)
    misses = sum(row["result"] == "FALLADO" for row in rows)
    pending = sum(row["result"] == "PENDIENTE" for row in rows)
    decided = hits + misses
    precision = round(hits * 100.0 / decided, 1) if decided else None
    return {
        "available": True,
        "threshold": threshold,
        "picks": rows,
        "summary": {"ACERTADO": hits, "FALLADO": misses, "PENDIENTE": pending, "precision": precision},
    }


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
    display_prices = market_anchored_prices(bundle, probabilities, prices)
    all_picks = build_all_picks(probabilities, display_prices)
    ranked = rank_value_picks(probabilities, display_prices, 4, bundle, context)
    snapshot = existing.get("top_picks_snapshot")
    terminal = _terminal_status((context or {}).get("event") or {})
    if isinstance(snapshot, list) and snapshot:
        top_picks = snapshot
    elif terminal and isinstance(existing.get("top_picks"), list):
        top_picks = existing.get("top_picks") or []
    else:
        top_picks = ranked
    return {
        **existing,
        "odds_status": existing.get("odds_status") or "NOT_AVAILABLE_YET",
        "probabilities": probabilities,
        "available_prices": prices,
        "all_picks": all_picks,
        "all_picks_snapshot": existing.get("all_picks_snapshot") or [],
        "top_picks": top_picks,
    }
