from __future__ import annotations

import re
from pathlib import Path


TEAM_RECENT_SCORE_COLUMNS = """                m.home_goals, m.away_goals,
                s.venue, s.goals_for, s.goals_against,"""

TEAM_RECENT_SCORE_COLUMNS_PATCHED = """                m.home_goals, m.away_goals,
                m.home_goals_1h, m.away_goals_1h,
                m.home_goals_2h, m.away_goals_2h,
                s.venue, s.goals_for, s.goals_against,"""

AGGREGATE_ANCHOR = '        "yellow_cards": _avg([m.get("yellow_cards") for m in matches]),\n'
AGGREGATE_PATCH = AGGREGATE_ANCHOR + """        "over_0_5_ht": _frequency(matches, lambda m: (
            None if m.get("home_goals_1h") is None or m.get("away_goals_1h") is None
            else float(m["home_goals_1h"]) + float(m["away_goals_1h"]) > 0.5
        )),
        "over_0_5_st": _frequency(matches, lambda m: (
            None if m.get("home_goals_2h") is None or m.get("away_goals_2h") is None
            else float(m["home_goals_2h"]) + float(m["away_goals_2h"]) > 0.5
        )),
"""

COMPARISON_UNAVAILABLE = """            {"label": "+0.5 HT", "home": None, "away": None, "kind": "percent", "note": "No disponible en la tabla histórica recibida"},
            {"label": "+0.5 ST", "home": None, "away": None, "kind": "percent", "note": "No disponible en la tabla histórica recibida"},"""

COMPARISON_AVAILABLE = """            {"label": "+0.5 HT", "home": hsum.get("over_0_5_ht"), "away": asum.get("over_0_5_ht"), "kind": "percent"},
            {"label": "+0.5 ST", "home": hsum.get("over_0_5_st"), "away": asum.get("over_0_5_st"), "kind": "percent"},"""

EVENT_TABLES_ANCHOR = '        preferred = ["matches", "partidos"]\n'
EVENT_TABLES_PATCHED = '        preferred = ["mobile_events", "matches", "partidos"]\n'

EXPECTED_REAL_SELECT = """            SELECT m.match_id, m.home_goals, m.away_goals,
                   hs.xg_for AS home_xg, as_.xg_for AS away_xg,"""

EXPECTED_REAL_SELECT_PATCHED = """            SELECT m.match_id, m.home_goals, m.away_goals,
                   m.home_goals_1h, m.away_goals_1h,
                   m.home_goals_2h, m.away_goals_2h,
                   hs.xg_for AS home_xg, as_.xg_for AS away_xg,"""

LINEUP_FUNCTION = '''# OH_LINEUP_LATEST_TEAM_FALLBACK_V2
def _database_lineup_payload(event_id: int) -> dict[str, Any] | None:
    try:
        conn = read_only_conn()
    except Exception:
        return None
    try:
        required = ("matches", "match_lineups", "players")
        if not all(_table_exists(conn, table) for table in required):
            return None
        match = conn.execute(
            "SELECT match_id, home_team_id, away_team_id FROM matches WHERE sofascore_id=? LIMIT 1;",
            (int(event_id),),
        ).fetchone()
        if match is None:
            return None

        has_player_stats = _table_exists(conn, "player_match_stats")

        def side_payload(team_id: int) -> dict[str, Any]:
            selected = conn.execute(
                """
                SELECT ml.match_id
                FROM match_lineups ml
                JOIN matches historical ON historical.match_id=ml.match_id
                JOIN matches current_event ON current_event.match_id=?
                WHERE ml.team_id=? AND historical.kickoff<=current_event.kickoff
                GROUP BY ml.match_id
                ORDER BY CASE WHEN ml.match_id=? THEN 0 ELSE 1 END,
                         MAX(historical.kickoff) DESC, ml.match_id DESC
                LIMIT 1;
                """,
                (int(match["match_id"]), int(team_id), int(match["match_id"])),
            ).fetchone()
            if selected is None:
                return {
                    "team_id": int(team_id), "source_match_id": None,
                    "is_current_event_lineup": False, "formation": None,
                    "starters": [], "substitutes": [],
                }
            selected_match_id = int(selected["match_id"])
            stats_columns = (
                "ps.minutes_played, ps.shots, ps.shots_on_target"
                if has_player_stats
                else "NULL AS minutes_played, NULL AS shots, NULL AS shots_on_target"
            )
            stats_join = (
                "LEFT JOIN player_match_stats ps "
                "ON ps.match_id=l.match_id AND ps.team_id=l.team_id AND ps.player_id=l.player_id"
                if has_player_stats
                else ""
            )
            side_rows = [dict(row) for row in conn.execute(
                f"""
                SELECT l.team_id, l.player_id, p.canonical_name AS player_name,
                       l.is_starter, l.is_substitute, l.position, l.shirt_number,
                       l.formation, l.lineup_order, l.source,
                       {stats_columns}
                FROM match_lineups l
                JOIN players p ON p.player_id=l.player_id
                {stats_join}
                WHERE l.match_id=? AND l.team_id=?
                ORDER BY CASE WHEN l.is_starter=1 THEN 0 ELSE 1 END,
                         COALESCE(l.lineup_order,999), p.canonical_name ASC;
                """,
                (selected_match_id, int(team_id)),
            ).fetchall()]
            formation = next((row.get("formation") for row in side_rows if row.get("formation")), None)
            player_sot_values: dict[int, list[float]] = {}
            if has_player_stats and side_rows:
                player_ids = sorted({int(row["player_id"]) for row in side_rows if row.get("player_id") is not None})
                placeholders = ",".join("?" for _ in player_ids)
                stats_rows = conn.execute(
                    f"""
                    SELECT ps.player_id, ps.shots_on_target, historical.kickoff
                    FROM player_match_stats ps
                    JOIN matches historical ON historical.match_id=ps.match_id
                    WHERE ps.team_id=? AND ps.player_id IN ({placeholders})
                      AND COALESCE(ps.appeared,1)=1
                      AND historical.kickoff<=(SELECT kickoff FROM matches WHERE match_id=?)
                    ORDER BY historical.kickoff DESC, ps.match_id DESC;
                    """,
                    (int(team_id), *player_ids, int(match["match_id"])),
                ).fetchall()
                for stat in stats_rows:
                    player_id = int(stat["player_id"])
                    values = player_sot_values.setdefault(player_id, [])
                    if len(values) < 10 and stat["shots_on_target"] is not None:
                        values.append(float(stat["shots_on_target"]))

            def player(row: dict[str, Any]) -> dict[str, Any]:
                values = player_sot_values.get(int(row["player_id"]), []) if row.get("player_id") is not None else []
                return {
                    "player_id": row.get("player_id"),
                    "name": row.get("player_name"),
                    "position": row.get("position"),
                    "shirt_number": row.get("shirt_number"),
                    "lineup_order": row.get("lineup_order"),
                    "minutes_played": row.get("minutes_played"),
                    "shots": row.get("shots"),
                    "shots_on_target": row.get("shots_on_target"),
                    "avg_shots_on_target": round(sum(values) / len(values), 2) if values else None,
                    "sot_sample": len(values),
                }

            return {
                "team_id": int(team_id),
                "source_match_id": selected_match_id,
                "is_current_event_lineup": selected_match_id == int(match["match_id"]),
                "formation": formation,
                "starters": [player(row) for row in side_rows if int(row.get("is_starter") or 0) == 1],
                "substitutes": [player(row) for row in side_rows if int(row.get("is_substitute") or 0) == 1],
            }

        home = side_payload(int(match["home_team_id"]))
        away = side_payload(int(match["away_team_id"]))
        if not home["starters"] and not home["substitutes"] and not away["starters"] and not away["substitutes"]:
            return None
        return {
            "event_id": int(event_id),
            "match_id": int(match["match_id"]),
            "home": home,
            "away": away,
        }
    finally:
        conn.close()


def _cloud_latest_lineup_payload(event_id: int) -> dict[str, Any] | None:
    if not CLOUD_MODE:
        return None
    try:
        conn = read_only_conn()
    except Exception:
        return None
    try:
        if not _table_exists(conn, "mobile_events") or not _table_exists(conn, "mobile_sync_meta"):
            return None
        event = conn.execute(
            "SELECT home_team_id,away_team_id FROM mobile_events WHERE event_id=? LIMIT 1",
            (int(event_id),),
        ).fetchone()
        if event is None:
            return None

        sides: dict[str, dict[str, Any]] = {}
        source_events: list[int] = []
        for name, column in (("home", "home_team_id"), ("away", "away_team_id")):
            team_id = event[column]
            value = None
            if team_id is not None:
                value = conn.execute(
                    "SELECT value FROM mobile_sync_meta WHERE key=? LIMIT 1",
                    (f"lineup_latest:{int(team_id)}",),
                ).fetchone()
            document = {}
            if value is not None:
                try:
                    document = safe_dict(json.loads(str(value["value"] or "{}")))
                except (TypeError, ValueError, json.JSONDecodeError):
                    document = {}
            side = dict(safe_dict(document.get("side")))
            if side:
                side["is_current_event_lineup"] = False
                source_event = document.get("source_event_id")
                if source_event is not None:
                    side["source_event_id"] = source_event
                    source_events.append(int(source_event))
            else:
                side = {
                    "team_id": int(team_id) if team_id is not None else None,
                    "source_match_id": None,
                    "source_event_id": None,
                    "is_current_event_lineup": False,
                    "formation": None,
                    "starters": [],
                    "substitutes": [],
                }
            sides[name] = side

        if not any(
            sides[name].get(bucket)
            for name in ("home", "away")
            for bucket in ("starters", "substitutes")
        ):
            return None
        return {
            "event_id": int(event_id),
            "match_id": None,
            "source_event_ids": sorted(set(source_events)),
            "home": sides["home"],
            "away": sides["away"],
        }
    finally:
        conn.close()


def lineup_payload(competition_key: str, event_id: int) -> dict[str, Any]:
    database_payload = _database_lineup_payload(event_id)
    if database_payload:
        current = all(
            safe_dict(database_payload.get(side)).get("is_current_event_lineup")
            for side in ("home", "away")
        )
        return {
            "available": True,
            "confirmed": bool(current),
            "source": "sqlite_current" if current else "sqlite_latest",
            "data": database_payload,
        }

    if CLOUD_MODE:
        docs = _cloud_docs_for_event(competition_key, event_id)
        for name in ("lineups", "lineup", "alineaciones"):
            doc = safe_dict(docs.get(name))
            if doc:
                return {
                    "available": True,
                    "confirmed": True,
                    "source": f"{name}.json",
                    "data": doc,
                }
        latest = _cloud_latest_lineup_payload(event_id)
        if latest:
            return {
                "available": True,
                "confirmed": False,
                "source": "latest_team_lineups",
                "data": latest,
            }
        return {
            "available": False,
            "source": None,
            "data": None,
            "reason": "Las alineaciones todavía no están disponibles para este evento.",
        }

    base = event_dir(competition_key, event_id)
    candidates = [
        base / "lineups.json",
        base / "lineup.json",
        base / "alineaciones.json",
    ]
    for path in candidates:
        if path.is_file():
            doc = read_json(path)
            if doc:
                return {"available": True, "source": path.name, "data": doc}
    return {
        "available": False,
        "source": None,
        "data": None,
        "reason": "Las alineaciones todavía no están disponibles para este evento.",
    }


'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Parche {label} esperaba 1 coincidencia y encontró {count}")
    return text.replace(old, new, 1)


def patch_backend(root: Path) -> list[str]:
    candidates = sorted(root.glob("**/backend/reader.py"))
    primary = [path for path in candidates if "/backups/" not in path.as_posix()]
    if len(primary) != 1:
        raise RuntimeError(f"Se esperaba un backend/reader.py activo; encontrados={primary}")

    path = primary[0]
    text = path.read_text(encoding="utf-8")
    original_text = text
    if EVENT_TABLES_PATCHED not in text:
        text = replace_once(
            text,
            EVENT_TABLES_ANCHOR,
            EVENT_TABLES_PATCHED,
            "estado móvil en detalle",
        )
    if EXPECTED_REAL_SELECT_PATCHED not in text:
        text = replace_once(
            text,
            EXPECTED_REAL_SELECT,
            EXPECTED_REAL_SELECT_PATCHED,
            "parciales reales en esperado/real",
        )
    patched_signals = (
        TEAM_RECENT_SCORE_COLUMNS_PATCHED,
        '"over_0_5_ht": _frequency',
        COMPARISON_AVAILABLE,
        "def _database_lineup_payload(event_id: int)",
    )
    present = [signal in text for signal in patched_signals]
    if all(present):
        if "OH_LINEUP_LATEST_TEAM_FALLBACK_V2" not in text:
            pattern = re.compile(
                r"def _database_lineup_payload\(event_id: int\) -> dict\[str, Any\] \| None:\n.*?(?=def list_teams\()",
                re.DOTALL,
            )
            text, count = pattern.subn(LINEUP_FUNCTION, text, count=1)
            if count != 1:
                raise RuntimeError(f"Actualización de alineación histórica esperaba 1 bloque y encontró {count}")
            compile(text, str(path), "exec")
            path.write_text(text, encoding="utf-8", newline="\n")
        compile(text, str(path), "exec")
        if text != original_text:
            path.write_text(text, encoding="utf-8", newline="\n")
        return [path.relative_to(root).as_posix()]
    if any(present):
        raise RuntimeError(f"El backend contiene un parche de datos incompleto: {path}")

    text = replace_once(
        text,
        TEAM_RECENT_SCORE_COLUMNS,
        TEAM_RECENT_SCORE_COLUMNS_PATCHED,
        "columnas de parciales",
    )
    text = replace_once(text, AGGREGATE_ANCHOR, AGGREGATE_PATCH, "frecuencias HT/ST")
    text = replace_once(
        text,
        COMPARISON_UNAVAILABLE,
        COMPARISON_AVAILABLE,
        "filas comparativas HT/ST",
    )

    pattern = re.compile(
        r"def lineup_payload\(competition_key: str, event_id: int\) -> dict\[str, Any\]:\n.*?(?=def list_teams\()",
        re.DOTALL,
    )
    text, count = pattern.subn(LINEUP_FUNCTION, text, count=1)
    if count != 1:
        raise RuntimeError(f"Parche de alineaciones esperaba 1 función y encontró {count}")

    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8", newline="\n")
    return [path.relative_to(root).as_posix()]
