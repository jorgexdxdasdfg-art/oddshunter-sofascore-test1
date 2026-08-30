from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import requests
except ModuleNotFoundError:
    class _RequestException(Exception):
        pass

    class _UrllibResponse:
        def __init__(self, status_code: int, payload: bytes) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> Any:
            return json.loads(self._payload.decode("utf-8"))

    class _UrllibSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def get(
            self,
            url: str,
            *,
            params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
            timeout: float = 30.0,
        ) -> _UrllibResponse:
            query = urlencode(params or {}, doseq=True)
            target = f"{url}?{query}" if query else url
            try:
                with urlopen(
                    Request(target, headers=dict(self.headers)),
                    timeout=timeout,
                ) as response:
                    return _UrllibResponse(
                        int(getattr(response, "status", 200)),
                        response.read(),
                    )
            except Exception as exc:  # pragma: no cover - solo sin requests
                raise _RequestException(str(exc)) from exc

        def close(self) -> None:
            return None

    class _RequestsCompatibility:
        RequestException = _RequestException
        Session = _UrllibSession

    requests = _RequestsCompatibility()  # type: ignore[assignment]

from match_stats_pipeline import MetricPair
from team_identity_registry import get_default_team_identity_registry
from xg_estimator import AggregateStats
from xg_pipeline import DirectXG, MatchAggregateStats, MatchRef


BASE_URL = "https://api.futbol24.com/api"
MATCH_URL = "https://www.futbol24.com/match/{slug}"
STAT_CODES = {
    "total_shots": "SHOTS_TOTAL",
    "shots_on_target": "SHOTS_ON_TARGET",
    "shots_off_target": "SHOTS_OFF_TARGET",
    "blocked_shots": "SHOTS_BLOCKED",
}
MATCH_STAT_CODES = {
    "shots": "SHOTS_TOTAL",
    "shots_on_target": "SHOTS_ON_TARGET",
    "corners": "CORNERS",
    "yellow_cards": "YELLOWCARDS",
    "red_cards": "REDCARDS",
    "possession": "BALL_POSSESSION",
    "fouls": "FOULS",
    "offsides": "OFFSIDES",
    "big_chances": "BIG_CHANCES",
}
GENERIC_TEAM_WORDS = {
    "afc",
    "cf",
    "club",
    "de",
    "fc",
    "fk",
    "sc",
    "sk",
    "the",
}
MAX_DATE_DELTA_HOURS = 36.0
TEAM_RESULTS_LIMIT = 30
COMPETITION_FAMILIES: dict[str, tuple[str, ...]] = {
    "leagues-cup": (
        "leagues cup",
        "concacaf leagues cup",
        "cncf lc",
    ),
    "usl-championship": (
        "usl championship",
        "united states usl championship",
    ),
    "colombia-primera-a": (
        "liga betplay",
        "liga betplay colombia",
        "colombia primera a",
        "primera a",
    ),
    "spain-la-liga": (
        "laliga",
        "la liga",
        "primera division",
        "primera división",
        "spa d1",
    ),
    "chile-primera": ("liga chile a", "chile primera", "chi d1"),
    "ecuador-ligapro": ("liga pro ec", "ligapro", "ecu d1"),
    "greece-super-league": (
        "greece stoiximan super league", "stoiximan super league", "gre d1"
    ),
    "iceland-besta-deild": ("liga islandia a", "besta deild", "ice d1"),
    "mexico-liga-mx": ("liga mx", "ligamx apertura", "mex d1"),
    "brazil-serie-a": ("brasil serie a", "brazil serie a", "bra d1"),
    "england-championship": ("championship", "eng d2"),
    "saudi-pro-league": ("saudi pro league", "saudi professional league", "ksa d1"),
}

# Verified provider spellings. These are identities, never scores or match
# states: Futbol24 uses a different club name from the schedule source for a
# handful of teams. The normal resolver still discovers results dynamically.
FUTBOL24_TEAM_ALIASES: dict[str, tuple[str, ...]] = {
    "krc genk": ("Racing Genk", "RC Genk"),
    "real racing club": ("Racing Santander", "Racing de Santander"),
    "nps volos": ("Volos NFC", "Volos"),
    "pot iraklis": ("Iraklis Salonica", "Iraklis"),
    "new england revolution": ("New England Revs",),
    "universidad catolica del ecuador": ("Univ. Católica Quito",),
    "louisville city fc": ("Louisville City",),
    "detroit city fc": ("Detroit City",),
    "atletico mineiro": ("Atlético Mineiro/MG", "Atletico Mineiro/MG"),
    "vitoria": ("Vitória/BA", "Vitoria/BA"),
    "sao paulo": ("São Paulo/SP", "Sao Paulo/SP"),
    "red bull bragantino": ("RB Bragantino/SP",),
    "al ittihad": ("Ittihad Jeddah", "Al Ittihad Jeddah"),
    "al fateh": ("Al Fateh (KSA)",),
}


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _team_tokens(value: Any) -> set[str]:
    return {
        token
        for token in _normalize(value).split()
        if token not in GENERIC_TEAM_WORDS
    }


def _name_score(expected: Any, candidate: Any) -> float:
    left = _normalize(expected)
    right = _normalize(candidate)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens = _team_tokens(left)
    right_tokens = _team_tokens(right)
    token_score = (
        len(left_tokens & right_tokens)
        / max(len(left_tokens | right_tokens), 1)
    )
    containment = 0.92 if left in right or right in left else 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(token_score, containment, sequence)


def _competition_family(value: Any) -> str | None:
    normalized = _normalize(value)
    for family, aliases in COMPETITION_FAMILIES.items():
        if any(_normalize(alias) in normalized for alias in aliases):
            return family
    return None


def _candidate_competition_names(candidate: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for field in ("league", "league_sub", "category"):
        document = candidate.get(field)
        if not isinstance(document, Mapping):
            continue
        for key in ("name", "name_short", "label", "slug"):
            value = str(document.get(key) or "").strip()
            if value:
                names.append(value)
    return list(dict.fromkeys(names))


def _to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.search(r"-?\d+(?:[.,]\d+)?", str(value).replace("%", ""))
        if match is None:
            return None
        try:
            number = float(match.group().replace(",", "."))
        except ValueError:
            return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class Futbol24Client:
    """Fuente principal del runtime cloud; resuelve identidad y métricas reales."""

    name = "futbol24"

    def __init__(
        self,
        *,
        project_root: str | Path,
        timeout_seconds: float = 30.0,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.timeout_seconds = float(timeout_seconds)
        self.logger = logger or (lambda _message: None)
        self.identity_registry = get_default_team_identity_registry(
            self.project_root
        )
        self.session = requests.Session()
        self.session.headers.clear()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Origin": "https://www.futbol24.com",
                "Referer": "https://www.futbol24.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0 Safari/537.36"
                ),
            }
        )
        # Solo memoria: no escribe cache ni altera históricos.
        self._prepared: dict[str, dict[str, Any] | None] = {}
        self.last_identity_validation: dict[str, Any] | None = None

    @property
    def available(self) -> bool:
        return True

    def _request(
        self,
        endpoint: str,
        params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
    ) -> Any | None:
        for attempt in range(3):
            try:
                response = self.session.get(
                    f"{BASE_URL}{endpoint}",
                    params=params,
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 200:
                    return response.json()
                retryable = response.status_code == 429 or response.status_code >= 500
                if retryable and attempt < 2:
                    delay = 2.0 * (attempt + 1)
                    self.logger(
                        f"Futbol24 limitó temporalmente ({response.status_code}); "
                        f"reintento en {delay:.0f}s."
                    )
                    time.sleep(delay)
                    continue
                self.logger(
                    "Futbol24 no respondió correctamente "
                    f"({response.status_code})."
                )
                return None
            except (requests.RequestException, ValueError) as exc:
                if attempt < 2:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                self.logger(f"Futbol24: {type(exc).__name__}: {exc}")
                return None
        return None

    @staticmethod
    def _match_key(match: MatchRef) -> str:
        identity = match.sofascore_event_id or match.match_id or "none"
        kickoff = _parse_datetime(match.kickoff)
        date = kickoff.date().isoformat() if kickoff else str(match.kickoff)
        return "|".join(
            (
                str(identity),
                _normalize(match.competition),
                _normalize(match.season),
                date,
                _normalize(match.home_team),
                _normalize(match.away_team),
            )
        )

    def _expected_names(self, value: Any) -> list[str]:
        # Futbol24-specific verified names remain first. When those do not
        # exist yet, reuse already-verified canonical/provider aliases from
        # OddsHunter's central identity registry before falling back to the
        # raw SQLite name. This is read-only and does not learn new aliases.
        verified = self.identity_registry.futbol24_variants(value)
        record = self.identity_registry.get(value) or {}
        fallback: list[str] = []
        for field in (
            "canonical_name",
            "aliases",
            "sofascore_names",
            "flashscore_names",
            "flashscore_aliases",
        ):
            variants = record.get(field)
            if isinstance(variants, list):
                fallback.extend(
                    str(item).strip()
                    for item in variants
                    if str(item).strip()
                )
            elif isinstance(variants, str) and variants.strip():
                fallback.append(variants.strip())
        return list(
            dict.fromkeys(
                [
                    *verified,
                    *FUTBOL24_TEAM_ALIASES.get(_normalize(value), ()),
                    *fallback,
                    str(value or "").strip(),
                ]
            )
        )

    def _team_search_score(self, expected: Any, candidate: Mapping[str, Any]) -> float:
        return max(
            _name_score(variant, candidate_name)
            for variant in self._expected_names(expected)
            for candidate_name in (
                candidate.get("name"),
                candidate.get("name_short"),
                candidate.get("name_full"),
                str(candidate.get("slug") or "").rsplit("/", 1)[-1],
            )
        )

    def _resolve_team(self, expected: Any) -> dict[str, Any] | None:
        rows_by_identity: dict[str, dict[str, Any]] = {}
        variants = self._expected_names(expected)[:6]
        queries = list(
            dict.fromkeys(
                [
                    *variants,
                    *(" ".join(sorted(_team_tokens(value))) for value in variants),
                ]
            )
        )
        for query in queries:
            self.logger(f"Futbol24 team query: {query!r}")
            document = self._request("/search/team", {"query": query})
            if not isinstance(document, list):
                continue
            for row in document:
                if not isinstance(row, dict):
                    continue
                identity = str(row.get("id") or row.get("slug") or "")
                if identity:
                    rows_by_identity[identity] = row
            if any(
                self._team_search_score(expected, row) >= 0.95
                for row in rows_by_identity.values()
            ):
                break

        candidates = sorted(
            (
                (self._team_search_score(expected, row), row)
                for row in rows_by_identity.values()
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if not candidates or candidates[0][0] < 0.82:
            self.logger(f"Futbol24 no resolvio el equipo {expected!r}.")
            return None
        score, selected = candidates[0]
        self.logger(
            "Futbol24 team selected: "
            f"expected={expected!r} name={selected.get('name')!r} "
            f"slug={selected.get('slug')!r} score={score:.4f}"
        )
        return selected

    def _team_results(self, team: Mapping[str, Any]) -> list[dict[str, Any]]:
        slug = str(team.get("slug") or "").strip()
        if not slug:
            return []
        meta = self._request("/stats/team/meta", {"slug": slug})
        if not isinstance(meta, dict):
            return []
        required = ("id", "expire", "sign")
        if any(meta.get(field) in (None, "") for field in required):
            self.logger(f"Futbol24 team meta incompleto para {slug!r}.")
            return []

        # Futbol24 firma estos parametros en orden alfabetico. Cambiar el orden
        # produce HTTP 422 aunque los valores sean correctos.
        params = [
            ("expire", meta["expire"]),
            ("hostGuest", "all"),
            ("id", meta["id"]),
            ("lang", "en"),
            ("limit", TEAM_RESULTS_LIMIT),
            ("sign", meta["sign"]),
        ]
        document = self._request("/stats/team/results/latest", params)
        if not isinstance(document, list):
            return []

        rows: list[dict[str, Any]] = []
        for raw in document:
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            home, away = self._score_pair(row)
            if home is not None and away is not None and not isinstance(row.get("status"), dict):
                row["status"] = {
                    "name": "FT",
                    "name_short": "FT",
                    "is_ended": True,
                    "in_play": False,
                }
            row["_futbol24_origin"] = "stats/team/results/latest"
            rows.append(row)
        return rows

    def _team_result_candidates(self, match: MatchRef) -> list[dict[str, Any]]:
        rows_by_identity: dict[str, dict[str, Any]] = {}
        for expected in (match.home_team, match.away_team):
            team = self._resolve_team(expected)
            if team is None:
                continue
            for row in self._team_results(team):
                identity = str(
                    row.get("id")
                    or row.get("slug")
                    or json.dumps(row, sort_keys=True, default=str)
                )
                rows_by_identity[identity] = row
        return list(rows_by_identity.values())

    def _candidate_score(
        self,
        match: MatchRef,
        candidate: dict[str, Any],
    ) -> float:
        validation = self._candidate_validation(
            match,
            candidate,
            require_score=False,
        )
        if not validation["valid"]:
            return -1.0
        home_score = float(validation["home_score"])
        away_score = float(validation["away_score"])
        hours = float(validation["date_delta_hours"])
        competition_score = float(validation["competition_score"])
        score = home_score * 4.0 + away_score * 4.0
        score += max(0.0, 1.5 - hours / 24.0)
        score += competition_score

        league = candidate.get("league") or {}
        expected_year = re.search(r"\d{4}", str(match.season or ""))
        league_slug = str(league.get("slug") or "")
        if expected_year is not None and expected_year.group() in league_slug:
            score += 0.5
        return score

    @staticmethod
    def _score_pair(candidate: dict[str, Any]) -> tuple[float | None, float | None]:
        actual = candidate.get("match") if isinstance(candidate.get("match"), dict) else candidate
        team1 = actual.get("team1") if isinstance(actual.get("team1"), dict) else {}
        team2 = actual.get("team2") if isinstance(actual.get("team2"), dict) else {}

        def first_number(*values: Any) -> float | None:
            for value in values:
                number = _to_number(value)
                if number is not None:
                    return number
            return None

        # Futbol24 puede devolver el marcador completo en un único campo
        # (por ejemplo score1="0-1"). Antes de tratar score1/score2 como
        # números individuales, intenta extraer el par completo.
        for key in (
            "score",
            "score1",
            "result",
            "result_score",
            "full_score",
            "ft_score",
        ):
            raw = actual.get(key)
            if isinstance(raw, str):
                match_score = re.search(r"(\d+)\s*[-:]\s*(\d+)", raw)
                if match_score is not None:
                    return float(match_score.group(1)), float(match_score.group(2))

        home = first_number(
            actual.get("team1_score"),
            actual.get("home_score"),
            actual.get("score1"),
            actual.get("goals1"),
            team1.get("score"),
            team1.get("goals"),
        )
        away = first_number(
            actual.get("team2_score"),
            actual.get("away_score"),
            actual.get("score2"),
            actual.get("goals2"),
            team2.get("score"),
            team2.get("goals"),
        )
        if home is None or away is None:
            for key in ("score", "score1", "result", "result_score", "full_score", "ft_score"):
                raw_score = str(actual.get(key) or "")
                match_score = re.search(r"(\d+)\s*[-:]\s*(\d+)", raw_score)
                if match_score is not None:
                    home = float(match_score.group(1))
                    away = float(match_score.group(2))
                    break
        return home, away

    def _candidate_validation(
        self,
        match: MatchRef,
        candidate: dict[str, Any],
        *,
        require_score: bool,
    ) -> dict[str, Any]:
        team1 = candidate.get("team1") or {}
        team2 = candidate.get("team2") or {}

        def side_score(expected: Any, actual: Mapping[str, Any]) -> float:
            return max(
                _name_score(variant, candidate_name)
                for variant in self._expected_names(expected)
                for candidate_name in (
                    actual.get("name"),
                    actual.get("name_short"),
                    str(actual.get("slug") or "").rsplit("/", 1)[-1],
                )
            )

        forward_home = side_score(match.home_team, team1)
        forward_away = side_score(match.away_team, team2)
        reverse_home = side_score(match.home_team, team2)
        reverse_away = side_score(match.away_team, team1)
        forward_rank = (min(forward_home, forward_away), forward_home + forward_away)
        reverse_rank = (min(reverse_home, reverse_away), reverse_home + reverse_away)
        reversed_order = reverse_rank > forward_rank
        if reversed_order:
            home_score, away_score = reverse_home, reverse_away
        else:
            home_score, away_score = forward_home, forward_away

        expected_date = _parse_datetime(match.kickoff)
        candidate_date = _parse_datetime(candidate.get("date"))
        competition_names = _candidate_competition_names(candidate)
        expected_family = _competition_family(match.competition)
        candidate_families = {
            family
            for value in competition_names
            if (family := _competition_family(value)) is not None
        }
        expected_competition_names = [str(match.competition or "")]
        if expected_family is not None:
            expected_competition_names.extend(COMPETITION_FAMILIES[expected_family])
        competition_score = max(
            (
                _name_score(expected, actual)
                for expected in expected_competition_names
                for actual in competition_names
            ),
            default=0.0,
        )
        hours = (
            abs((candidate_date - expected_date).total_seconds()) / 3600.0
            if expected_date is not None and candidate_date is not None
            else float("inf")
        )
        # Futbol24 can expose the fixture using the competition/local
        # calendar date while OddsHunter stores kickoff in UTC. For evening
        # matches in the Americas this legitimately crosses midnight UTC.
        # Identity therefore uses an absolute kickoff/date tolerance rather
        # than requiring the same calendar day.
        date_pass = bool(
            expected_date is not None
            and candidate_date is not None
            and hours <= MAX_DATE_DELTA_HOURS
        )
        expected_score_known = (
            _to_number(match.home_goals) is not None
            and _to_number(match.away_goals) is not None
        )
        actual_home, actual_away = self._score_pair(candidate)
        if reversed_order:
            actual_home, actual_away = actual_away, actual_home
        score_pass = True
        if require_score and expected_score_known:
            score_pass = bool(
                actual_home == _to_number(match.home_goals)
                and actual_away == _to_number(match.away_goals)
            )
        competition_pass = bool(
            expected_family in candidate_families
            if expected_family is not None
            else competition_score >= 0.55
        )
        # Some schedule rows carry only a generic localized league label.  If
        # both club identities and kickoff are exact, a strong competition
        # name score is enough; this remains stricter than team-name matching.
        if (
            not competition_pass
            and home_score >= 0.95
            and away_score >= 0.95
            and hours <= 3.0
            and bool(candidate_families)
            and competition_score >= 0.50
        ):
            competition_pass = True
        # If one side is an exact identity, the kickoff is almost exact and the
        # competition agrees, allow a conservative contextual match for the
        # other side. This covers provider naming differences while still
        # requiring four independent fixture signals.
        rescheduled_pass = bool(
            home_score >= 0.95
            and away_score >= 0.95
            and competition_pass
            and hours <= 168.0
        )
        date_pass = bool(date_pass or rescheduled_pass)
        contextual_fixture = bool(date_pass and hours <= 3.0 and competition_pass)
        home_pass = bool(
            home_score >= 0.82
            or (contextual_fixture and home_score >= 0.40 and away_score >= 0.95)
        )
        away_pass = bool(
            away_score >= 0.82
            or (contextual_fixture and away_score >= 0.40 and home_score >= 0.95)
        )
        checks = {
            "home_score": round(home_score, 4),
            "away_score": round(away_score, 4),
            "date_delta_hours": round(hours, 3) if math.isfinite(hours) else None,
            "competition_score": round(competition_score, 4),
            "orientation": "reversed" if reversed_order else "forward",
            "home_pass": home_pass,
            "away_pass": away_pass,
            "date_pass": date_pass,
            "rescheduled_pass": rescheduled_pass,
            "competition_pass": competition_pass,
            "expected_competition_family": expected_family,
            "candidate_competition_families": sorted(candidate_families),
            "score_required": bool(require_score and expected_score_known),
            "score_pass": score_pass,
            "expected_score": [match.home_goals, match.away_goals],
            "actual_score": [actual_home, actual_away],
        }
        checks["valid"] = all(
            checks[key]
            for key in (
                "home_pass",
                "away_pass",
                "date_pass",
                "competition_pass",
                "score_pass",
            )
        )
        return checks

    def _find_match(self, match: MatchRef) -> dict[str, Any] | None:
        rows_by_identity: dict[str, dict[str, Any]] = {}
        for row in self._team_result_candidates(match):
            identity = str(
                row.get("id")
                or row.get("slug")
                or json.dumps(row, sort_keys=True, default=str)
            )
            rows_by_identity[identity] = row

        candidates = [
            (self._candidate_score(match, row), row)
            for row in rows_by_identity.values()
        ]
        candidates = [item for item in candidates if item[0] >= 6.0]
        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]

        # Search/match remains useful for scheduled/live fixtures. It is not
        # reliable for historical results, hence the signed team-results path
        # above is authoritative for completed matches.
        home_names = self._expected_names(match.home_team)[:3]
        away_names = self._expected_names(match.away_team)[:3]
        query_plan = list(
            dict.fromkeys(
                [
                    *(f"{home} {away}" for home in home_names for away in away_names),
                    *home_names,
                    *away_names,
                ]
            )
        )
        for query in query_plan:
            self.logger(f"Futbol24 match query: {query!r}")
            document = self._request("/search/match", {"query": query})
            if not isinstance(document, list):
                continue
            for row in document:
                if not isinstance(row, dict):
                    continue
                identity = str(
                    row.get("id")
                    or row.get("slug")
                    or json.dumps(row, sort_keys=True, default=str)
                )
                rows_by_identity[identity] = row
            if any(
                self._candidate_score(match, row) >= 6.0
                for row in rows_by_identity.values()
            ):
                break
        candidates = [
            (self._candidate_score(match, row), row)
            for row in rows_by_identity.values()
        ]
        candidates = [item for item in candidates if item[0] >= 6.0]
        if not candidates:
            # Leave an actionable reason in the normal runtime log. This
            # prevents opaque SOURCE_UNAVAILABLE loops if provider naming or
            # date conventions change again.
            diagnostics: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
            for row in rows_by_identity.values():
                validation = self._candidate_validation(
                    match,
                    row,
                    require_score=False,
                )
                rough = (
                    float(validation.get("home_score") or 0.0)
                    + float(validation.get("away_score") or 0.0)
                    + float(validation.get("competition_score") or 0.0)
                )
                diagnostics.append((rough, row, validation))
            diagnostics.sort(key=lambda item: item[0], reverse=True)
            if diagnostics:
                _rough, best_row, best = diagnostics[0]
                self.logger(
                    "Futbol24 rechazo mejor candidato: "
                    f"team1={((best_row.get('team1') or {}).get('name'))!r} "
                    f"team2={((best_row.get('team2') or {}).get('name'))!r} "
                    f"date={best_row.get('date')!r} "
                    f"league={((best_row.get('league') or {}).get('name'))!r} "
                    f"home_score={best.get('home_score')} "
                    f"away_score={best.get('away_score')} "
                    f"date_delta_hours={best.get('date_delta_hours')} "
                    f"competition_score={best.get('competition_score')} "
                    f"orientation={best.get('orientation')} "
                    f"home_pass={best.get('home_pass')} "
                    f"away_pass={best.get('away_pass')} "
                    f"date_pass={best.get('date_pass')} "
                    f"competition_pass={best.get('competition_pass')}"
                )
            self.logger(
                "Futbol24 no encontró una coincidencia segura para "
                f"{match.home_team} - {match.away_team}."
            )
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _details_match_expected(
        self,
        match: MatchRef,
        details: dict[str, Any],
    ) -> bool:
        actual = details.get("match") or {}
        candidate = {
            "date": actual.get("date"),
            "team1": actual.get("team1"),
            "team2": actual.get("team2"),
            "league": details.get("league"),
            "match": actual,
        }
        validation = self._candidate_validation(
            match,
            candidate,
            require_score=True,
        )
        self.last_identity_validation = validation
        self.logger(
            "Futbol24 identity: "
            f"orientation={validation['orientation']} "
            f"home={'PASS' if validation['home_pass'] else 'FAIL'} "
            f"away={'PASS' if validation['away_pass'] else 'FAIL'} "
            f"date={'PASS' if validation['date_pass'] else 'FAIL'} "
            f"competition={'PASS' if validation['competition_pass'] else 'FAIL'} "
            f"score={'PASS' if validation['score_pass'] else 'FAIL'}"
        )
        return bool(validation["valid"])

    def _prepare(self, match: MatchRef) -> dict[str, Any] | None:
        key = self._match_key(match)
        if key in self._prepared:
            return self._prepared[key]
        candidate = self._find_match(match)
        slug = candidate.get("slug") if isinstance(candidate, dict) else None
        if not slug:
            self._prepared[key] = None
            return None
        document = self._request("/match/details", {"slug": slug})
        details = document.get("details") if isinstance(document, dict) else None
        if not isinstance(details, dict) or not self._details_match_expected(match, details):
            self.logger(
                "Futbol24 descartó los detalles porque no corresponden "
                "inequívocamente al partido solicitado."
            )
            self._prepared[key] = None
            return None
        self._prepared[key] = details
        return details

    @staticmethod
    def _stats_by_code(details: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        if not isinstance(details, dict):
            return {}
        return {
            str(row.get("code") or "").upper(): row
            for row in details.get("stats") or []
            if isinstance(row, dict) and row.get("code")
        }

    @staticmethod
    def _identity(details: dict[str, Any]) -> dict[str, Any]:
        match = details.get("match") or {}
        slug = str(match.get("slug") or "")
        return {
            "futbol24_match_id": details.get("id"),
            "futbol24_slug": slug or None,
            "futbol24_url": MATCH_URL.format(slug=slug) if slug else None,
        }

    @staticmethod
    def _status_snapshot(candidate: dict[str, Any]) -> tuple[str, str | None]:
        status = candidate.get("status") if isinstance(candidate.get("status"), dict) else {}
        raw_name = str(
            status.get("name")
            or status.get("type")
            or status.get("description")
            or ""
        ).strip()
        normalized = _normalize(raw_name)
        ended = bool(status.get("is_ended") or status.get("ended"))
        in_play = bool(status.get("in_play") or status.get("inPlay"))

        if ended or normalized in {
            "ft", "finished", "final", "after extra time", "after penalties"
        }:
            return "finished", raw_name or None
        if in_play or normalized in {
            "live", "in play", "1st half", "2nd half", "halftime", "extra time"
        }:
            return "live", raw_name or None
        if any(
            marker in normalized
            for marker in (
                "cancel",
                "postpon",
                "abandon",
                "suspend",
                "walkover",
            )
        ):
            return "terminal", raw_name or None
        return "scheduled", raw_name or None

    def get_match_snapshot(self, match: MatchRef) -> dict[str, Any] | None:
        """Estado/marcador verificado desde la búsqueda real de Futbol24.

        No usa SofaScore y no escribe disco. La identidad exige equipos,
        competición y fecha antes de aceptar el candidato.
        """

        candidate = self._find_match(match)
        if not isinstance(candidate, dict):
            return None

        validation = self._candidate_validation(
            match,
            candidate,
            require_score=False,
        )
        if not bool(validation.get("valid")):
            self.logger(
                "Futbol24 snapshot descartado: identidad de búsqueda no segura."
            )
            return None

        slug = str(candidate.get("slug") or "").strip()
        details: dict[str, Any] | None = None
        if slug:
            document = self._request("/match/details", {"slug": slug})
            possible = document.get("details") if isinstance(document, dict) else None
            if isinstance(possible, dict):
                actual = possible.get("match") or {}
                detail_candidate = {
                    "date": actual.get("date"),
                    "team1": actual.get("team1"),
                    "team2": actual.get("team2"),
                    "league": possible.get("league"),
                    "match": actual,
                }
                detail_validation = self._candidate_validation(
                    match,
                    detail_candidate,
                    require_score=False,
                )
                if bool(detail_validation.get("valid")):
                    details = possible

        home_score, away_score = self._score_pair(candidate)
        if validation.get("orientation") == "reversed":
            home_score, away_score = away_score, home_score
        state, provider_status = self._status_snapshot(candidate)
        kickoff = _parse_datetime(candidate.get("date"))

        return {
            "source": "futbol24",
            "state": state,
            "provider_status": provider_status,
            "home_goals": (
                int(home_score) if home_score is not None and home_score.is_integer()
                else home_score
            ),
            "away_goals": (
                int(away_score) if away_score is not None and away_score.is_integer()
                else away_score
            ),
            "kickoff": kickoff.isoformat() if kickoff is not None else None,
            "futbol24_match_id": candidate.get("id"),
            "futbol24_slug": slug or None,
            "futbol24_url": MATCH_URL.format(slug=slug) if slug else None,
            "identity_validation": validation,
            "details_available": details is not None,
        }

    def get_direct_xg(self, match: MatchRef) -> DirectXG | None:
        details = self._prepare(match)
        stats = self._stats_by_code(details)
        row = stats.get("EXPECTED_GOALS")
        if not isinstance(row, dict) or not isinstance(details, dict):
            return None
        home = _to_number(row.get("home"))
        away = _to_number(row.get("away"))
        if home is None or away is None or home > 15 or away > 15:
            return None
        return DirectXG(
            home=round(home, 2),
            away=round(away, 2),
            details={**self._identity(details), "field": row.get("name")},
        )

    @staticmethod
    def _aggregate(
        stats: dict[str, dict[str, Any]],
        side: str,
    ) -> AggregateStats | None:
        values = {
            field: _to_number((stats.get(code) or {}).get(side))
            for field, code in STAT_CODES.items()
        }
        if values["total_shots"] is None or values["shots_on_target"] is None:
            return None
        return AggregateStats(**values)

    def get_aggregate_stats(self, match: MatchRef) -> MatchAggregateStats | None:
        details = self._prepare(match)
        stats = self._stats_by_code(details)
        home = self._aggregate(stats, "home")
        away = self._aggregate(stats, "away")
        if home is None or away is None or not isinstance(details, dict):
            return None
        return MatchAggregateStats(
            home=home,
            away=away,
            details=self._identity(details),
        )

    def get_match_stats(
        self,
        match: MatchRef,
        *,
        missing_fields: Sequence[str] | None = None,
    ) -> dict[str, MetricPair]:
        details = self._prepare(match)
        stats = self._stats_by_code(details)
        requested = set(missing_fields or MATCH_STAT_CODES)
        return {
            metric: MetricPair(
                _to_number((stats.get(code) or {}).get("home")),
                _to_number((stats.get(code) or {}).get("away")),
            )
            for metric, code in MATCH_STAT_CODES.items()
            if metric in requested
        }

    def close(self) -> None:
        self.session.close()
