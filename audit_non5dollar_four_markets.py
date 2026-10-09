#!/usr/bin/env python3
"""Investigación puntual y READ ONLY: alternativas a 5DollarFootballAPI.

NO accede a 5Dollar. NO modifica OddsHunter ni servidores. No guarda contenido HTML.
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from html.parser import HTMLParser


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.words = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.suppressed += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.suppressed:
            self.suppressed -= 1

    def handle_data(self, data):
        if not self.suppressed and data.strip():
            self.words.append(data.strip())


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "OddsHunter-ReadOnly-Alternative-Audit/1.0"})
    with urllib.request.urlopen(req, timeout=18) as resp:
        return json.load(resp)


def explain_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP_{exc.code}"
    return type(exc).__name__


def is_price(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 1.0 < value < 1000


def parse_odds_markets(data):
    result = {"goals": None, "btts": None, "corners": None, "cards": None}
    names = {"goals": {"totals", "alternate_totals"}, "btts": {"btts"},
             "corners": {"alternate_totals_corners"}, "cards": {"alternate_totals_cards"}}
    for book in data.get("bookmakers", []):
        for m in book.get("markets", []):
            category = next((n for n, aliases in names.items() if m.get("key") in aliases), None)
            if category is None or result[category] is not None:
                continue
            byline = {}
            for o in m.get("outcomes", []):
                side = str(o.get("name", "")).casefold()
                side = {"yes": "yes", "no": "no", "over": "over", "under": "under"}.get(side)
                price = o.get("price")
                if not side or not is_price(price):
                    continue
                line = o.get("point") if category != "btts" else None
                if category != "btts" and (not isinstance(line, (int, float)) or not 0 <= line <= 50):
                    continue
                byline.setdefault(line, {})[side] = price
            for line, pair in byline.items():
                expected = {"yes", "no"} if category == "btts" else {"over", "under"}
                if expected.issubset(pair):
                    result[category] = {
                        "bookmaker": book.get("title"), "market": m.get("key"),
                        "line": line, "prices": pair, "updated": m.get("last_update"),
                    }
                    break
    return result


def probe_the_odds_api():
    key = (os.getenv("THE_ODDS_API_KEY") or os.getenv("ODDS_API_KEY") or "").strip()
    report = {"provider": "the-odds-api.com", "authenticated_key_available": bool(key),
              "requests": 0, "status": "NO_KEY", "fixtures": [], "four_markets_one_fixture": False}
    if not key:
        return report
    leagues = ("soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga", "soccer_italy_serie_a")
    base = "https://api.the-odds-api.com/v4/sports/"
    now = datetime.now(timezone.utc)
    for league in leagues:
        try:
            q = urllib.parse.urlencode({"apiKey": key})
            report["requests"] += 1
            events = get_json(f"{base}{league}/events?{q}")
            if not isinstance(events, list):
                report["status"] = "INVALID_EVENT_SCHEMA"
                continue
            upcoming = [ev for ev in events if isinstance(ev, dict) and ev.get("id")
                        and ev.get("commence_time", "") > now.isoformat().replace("+00:00", "Z")]
            if not upcoming:
                continue
            ev = upcoming[0]
            q = urllib.parse.urlencode({
                "apiKey": key, "regions": "eu", "markets":
                    "totals,btts,alternate_totals_corners,alternate_totals_cards",
                "oddsFormat": "decimal",
            })
            report["requests"] += 1
            data = get_json(f"{base}{league}/events/{ev['id']}/odds?{q}")
            if not isinstance(data, dict):
                report["status"] = "INVALID_ODDS_SCHEMA"
                continue
            found = parse_odds_markets(data)
            fixture = {"league": league, "home": ev.get("home_team"), "away": ev.get("away_team"),
                       "kickoff": ev.get("commence_time"), "markets": found,
                       "count": sum(v is not None for v in found.values())}
            report["fixtures"].append(fixture)
            if fixture["count"] == 4:
                report["four_markets_one_fixture"] = True
                report["status"] = "PASS"
                break
            report["status"] = "PARTIAL_MARKETS"
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            report["status"] = explain_error(exc)
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 402, 403, 429):
                break
    return report


def parse_public_text(raw):
    parser = HTMLText()
    parser.feed(raw)
    content = " ".join(parser.words)
    result = {}
    for category, name in (("goals", "Goals"), ("corners", "Corners"), ("cards", "YC")):
        found = []
        pattern = re.compile(
            rf"Total {name}\s+(\d+(?:\.\d+)?)\s+Over\s+Under\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)",
            re.I,
        )
        for line, over, under in pattern.findall(content):
            if all(1 < float(x) < 1000 for x in (over, under)):
                found.append({"line": float(line), "over": float(over), "under": float(under)})
        result[category] = found[:4]
    result["btts"] = []  # Esta página no muestra un mercado BTTS verificable.
    return result


def public_page_probe():
    agent = "OddsHunter-ReadOnly-Alternative-Audit/1.0"
    host = "https://m.24score.com"
    paths = ("/football/match/854861-arsenal-leeds",
             "/football/match/874290-switzerland-north-macedonia")
    report = {"provider": "m.24score.com", "purpose": "research-only",
              "commercial_rights": "NOT_VERIFIED", "robots": "UNKNOWN", "samples": []}
    try:
        robot_req = urllib.request.Request(host + "/robots.txt", headers={"User-Agent": agent})
        try:
            with urllib.request.urlopen(robot_req, timeout=12) as r:
                body = r.read(50000).decode("utf-8", "replace")
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(body.splitlines())
            report["robots"] = "CHECKED"
            if not rp.can_fetch(agent, paths[0]):
                report["robots"] = "DENIED"
                return report
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                report["robots"] = explain_error(exc)
                return report
            report["robots"] = "HTTP_404_NO_ROBOTS_FILE"
    except (urllib.error.URLError, TimeoutError) as exc:
        report["robots"] = explain_error(exc)
        return report

    for path in paths:
        try:
            req = urllib.request.Request(host + path, headers={"User-Agent": agent})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read(1_500_000).decode("utf-8", "replace")
            parsed = parse_public_text(raw)
            report["samples"].append({"url_path": path, "markets": parsed,
                                      "four_markets": all(bool(x) for x in parsed.values())})
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            report["samples"].append({"url_path": path, "error": explain_error(exc)})
    return report


def main():
    report = {
        "audit": "ALTERNATIVE_SOURCES_NO_5DOLLAR",
        "read_only": True,
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "api": probe_the_odds_api(),
        "public_html": public_page_probe(),
    }
    report["gate_4_of_4"] = "PASS" if report["api"]["four_markets_one_fixture"] else "FAIL"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["gate_4_of_4"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
