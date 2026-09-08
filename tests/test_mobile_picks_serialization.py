import sys
import types
from typing import Any

import odds_value_engine
from vercel_backend_data_patch import VALUE_MODEL_FUNCTION


def test_mobile_missing_odds_doc_still_exposes_model_and_observed_first_half(monkeypatch):
    backend = types.ModuleType("backend")
    monkeypatch.setitem(sys.modules, "backend", backend)
    monkeypatch.setitem(sys.modules, "backend.odds_value_engine", odds_value_engine)
    namespace = {"Any": Any, "safe_dict": lambda value: value if isinstance(value, dict) else {}}
    exec(VALUE_MODEL_FUNCTION, namespace)
    docs = {"goals": {"models": {"MODELO_APRENDIDO": {
        "outcome_probabilities": {"home_win": 0.6, "draw": 0.25, "away_win": 0.15},
        "total_goals_distribution": {"0": 0.1, "1": 0.2, "2": 0.3, "3": 0.4},
    }}}}
    comparison = {"home": {"summary": {"over_0_5_ht": 70}}, "away": {"summary": {"over_0_5_ht": 50}}}
    value = namespace["mobile_model_picks"](docs, comparison)
    assert value["probabilities"]["result_home"] == 0.6
    assert value["probabilities"]["first_half_over_0_5"] == 0.6
    assert value["probabilities"]["first_half_under_0_5"] == 0.4
    assert value["all_picks"]
    assert all(pick["odds"] is None and pick["ev"] is None for pick in value["all_picks"])
    docs["odds_value"] = {"probabilities": {"first_half_over_0_5": 0.8, "first_half_under_0_5": 0.2}}
    assert namespace["mobile_model_picks"](docs, comparison)["probabilities"]["first_half_over_0_5"] == 0.8
