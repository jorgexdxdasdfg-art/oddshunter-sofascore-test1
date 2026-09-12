from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: se esperaba una coincidencia y hubo {text.count(old)}")
    return text.replace(old, new, 1)


def patch(root: Path) -> None:
    sync_file = root / "five_dollar_odds_sync.py"
    if not sync_file.is_file():
        raise RuntimeError("five_dollar_odds_sync.py no existe")

    text = sync_file.read_text(encoding="utf-8")
    if "ODDS_FULL_FIELDS_RECOVERY_V2_RUNTIME" in text:
        return

    # Normalizaciones únicamente de identidad. No alteran probabilidades ni precios.
    text = replace_once(
        text,
        '}\n\n\nclass ProviderDeferred',
        '''}\nTEAM_ALIASES.update({
    "cardiff city": "cardiff",
    "deportivo alaves": "alaves",
    "real racing club": "racing santander",
    "al taawoun": "al taawoun buraidah",
    "al hilal": "al hilal riyadh",
    "1 fc koln": "koln",
    "sv werder bremen": "werder bremen",
    "paris fc": "paris fc",
    "olympique lyonnais": "lyon",
    "manchester city": "man city",
    "coventry city": "coventry",
    "brighton hove albion": "brighton",
    "sporting kansas city": "sporting kansas city",
    "los angeles fc": "lafc",
    "stade brestois": "brest",
    "ssc napoli": "napoli",
    "as roma": "roma",
    "ac milan": "milan",
    "fc augsburg": "augsburg",
    "1 fsv mainz 05": "mainz",
    "borussia monchengladbach": "borussia mgladbach",
})

# ODDS_FULL_FIELDS_RECOVERY_V2_RUNTIME
class ProviderDeferred''',
        "aliases de identidad",
    )

    # Persisted provider ids can survive schedule-catalog kickoff drift when both
    # teams still identify the same fixture strongly.
    text = replace_once(
        text,
        '            if delta is not None and delta <= 5 * 60 and min(home_score, away_score) >= 0.50:\n                return saved, "RESOLVED_STABLE_ID", score, "persisted provider_fixture_id"\n',
        '            if delta is not None and delta <= 18 * 3600 and min(home_score, away_score) >= 0.50:\n                return saved, "RESOLVED_STABLE_ID", score, "persisted provider_fixture_id"\n',
        "persisted provider fixture",
    )

    text = replace_once(
        text,
        '    accepted: list[tuple[float, str, dict[str, Any]]] = []\n    uncertain: list[tuple[float, dict[str, Any]]] = []\n',
        '    accepted: list[tuple[float, str, dict[str, Any]]] = []\n    uncertain: list[tuple[float, dict[str, Any]]] = []\n    wide: list[tuple[float, dict[str, Any]]] = []\n',
        "wide candidates",
    )
    text = replace_once(
        text,
        '        if delta is None or delta > 6 * 3600:\n            continue\n',
        '        if delta is None or delta > 18 * 3600:\n            continue\n',
        "fixture search window",
    )
    text = replace_once(
        text,
        '        elif exact_time and score >= 0.55:\n            uncertain.append((score, fixture))\n\n    accepted.sort(key=lambda row: row[0], reverse=True)\n',
        '''        elif exact_time and score >= 0.55:
            uncertain.append((score, fixture))
        elif delta <= 18 * 3600 and (
            exact_names
            or alias_names
            or (score >= 0.65 and min(home_score, away_score) >= 0.55)
        ):
            wide.append((score, fixture))

    accepted.sort(key=lambda row: row[0], reverse=True)
''',
        "wide identity candidates",
    )
    text = replace_once(
        text,
        '    if len(accepted) == 1 or (len(accepted) > 1 and accepted[0][0] - accepted[1][0] >= 0.15):\n        score, method, fixture = accepted[0]\n        return fixture, method, score, "kickoff + home + away"\n    if accepted or uncertain:\n',
        '''    if len(accepted) == 1 or (len(accepted) > 1 and accepted[0][0] - accepted[1][0] >= 0.15):
        score, method, fixture = accepted[0]
        return fixture, method, score, "kickoff + home + away"
    wide.sort(key=lambda row: row[0], reverse=True)
    if len(wide) == 1 or (len(wide) > 1 and wide[0][0] - wide[1][0] >= 0.12):
        score, fixture = wide[0]
        return fixture, "RESOLVED_OTHER", score, "unique strong home/away pair with kickoff drift"
    uncertain.extend(wide)
    if accepted or uncertain:
''',
        "resolve wide identity",
    )

    # Critical recovery rule: the provider batch response currently exposes 1X2
    # only. Read the detailed Bet365 endpoint for EVERY resolved Today/Tomorrow
    # fixture so goals, BTTS, HT, corners and cards can be anchored when Bet365
    # actually supplies them. Existing engine remains responsible for ladders/EV.
    text = replace_once(
        text,
        '            last_extended = _datetime(existing.get("extended_last_checked_at"))\n            extended_due = last_extended is None or now - last_extended >= extended_ttl\n            needs_individual_1x2 = not batch_prices\n            needs_extended = bool(batch_prices) and extended_due\n',
        '''            last_extended = _datetime(existing.get("extended_last_checked_at"))
            extended_due = last_extended is None or now - last_extended >= extended_ttl
            needs_individual_1x2 = not batch_prices
            needs_extended = bool(batch_prices)
''',
        "force detailed Bet365 reads",
    )

    compile(text, str(sync_file), "exec")
    sync_file.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    patch(Path(sys.argv[1]).resolve())
    print("STAGE8_ODDS_PATCH=PASS")
