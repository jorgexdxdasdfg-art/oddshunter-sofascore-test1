#!/usr/bin/env python3
"""Muestreo pequeño y reproducible de 24score; HTTP de solo lectura.

NO publica cuotas, no comparte la base ni consume API de pagos. Valida pares
Over/Under mediante etiquetas explícitas y cuenta cobertura por liga.
"""
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

HOST = "https://m.24score.com"
AGENT = "OddsHunter-Research-Audit/1.0"
SAMPLE = [
    ("Premier League", "854861-arsenal-leeds"),
    ("Premier League", "854863-chelsea-bournemouth"),
    ("LaLiga", "857531-barcelona-getafe"),
    ("LaLiga", "857530-alaves-atl-madrid"),
    ("Serie A", "858356-inter-parma"),
    ("Serie A", "858355-genoa-fiorentina"),
    ("Bundesliga", "856885-augsburg-bayern-munich"),
    ("Ligue 1", "858730-lorient-paris-fc"),
    ("Eredivisie", "862341-feyenoord-az-alkmaar"),
    ("Greece Super League", "871374-aek-athens-ofi-crete"),
    ("Japan J1", "853017-kyoto-machida"),
    ("Mexico Liga MX", "853820-puebla-club-leon"),
]
MARKETS = {"Goals": "goals", "Corners": "corners", "YC": "cards"}


class ExtractText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bits = []
        self.skipping = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skipping += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skipping:
            self.skipping -= 1
    def handle_data(self, data):
        if not self.skipping and data.strip():
            self.bits.append(data.strip())


def extract_pairs(html_text):
    parser = ExtractText()
    parser.feed(html_text)
    text = " ".join(parser.bits)
    occurrences = list(re.finditer(r"\bTotal\s+(Goals|Corners|YC)\s+(\d+(?:\.\d+)?)\b", text, re.I))
    result = {"goals": [], "corners": [], "cards": [], "btts": []}
    for i, m in enumerate(occurrences):
        fragment = text[m.end() : occurrences[i + 1].start() if i + 1 < len(occurrences) else len(text)]
        # Stop at footer if this is last market.
        fragment = fragment.split("Full version")[0][:160]
        price = re.search(r"^\s*Over\s+Under\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\b",fragment,re.I)
        if not price:
            continue
        over, under = float(price.group(1)), float(price.group(2))
        if not (1.0 < over < 1000 and 1.0 < under < 1000):
            continue
        market = MARKETS[m.group(1).title() if m.group(1).lower() != "yc" else "YC"]
        result[market].append({"line":float(m.group(2)), "over":over, "under":under})
    return result


def audit():
    report = {"utc": datetime.now(timezone.utc).isoformat(),
              "source":HOST,"mode":"NON_COMMERCIAL_READONLY",
              "rights":"UNVERIFIED","bookmaker_identity":"UNVERIFIED",
              "counting_unit":"preselected_fixture_url","sample_size":len(SAMPLE),
              "matches":[],"coverage":{}, "overall_4_markets":"FAIL"}
    robots=RobotFileParser()
    req=Request(HOST+"/robots.txt",headers={"User-Agent":AGENT})
    try:
        with urlopen(req,timeout=12) as response:
            robots.parse(response.read(50000).decode("utf-8","replace").splitlines())
    except HTTPError as ex:
        if ex.code != 404: 
            report["robots_error"]=ex.code; return report
        robots=None
    except (URLError,TimeoutError) as ex:
        report["robots_error"]=type(ex).__name__; return report

    by_league=defaultdict(lambda:Counter())
    for league, slug in SAMPLE:
        path="/football/match/"+slug
        row={"league":league,"fixture_url":HOST+path}
        if robots is not None and not robots.can_fetch(AGENT,HOST+path):
            row["status"]="DISALLOWED_BY_ROBOTS"
            report["matches"].append(row)
            continue
        try:
            with urlopen(Request(HOST+path,headers={"User-Agent":AGENT}),timeout=15) as response:
                raw=response.read(1500000).decode("utf-8","replace")
            result=extract_pairs(raw)
            row["markets"]={k: {"lines":len(v),"example":v[0] if v else None}
                            for k,v in result.items()}
            row["present_count"]=sum(bool(v) for v in result.values())
            row["status"]="HTTP_SUCCESS"
            for market, values in result.items():
                if values: by_league[league][market]+=1
            by_league[league]["checked"]+=1
        except (HTTPError,URLError,TimeoutError) as ex:
            row["status"]="FETCH_ERROR"
            row["error_type"]=type(ex).__name__
            if isinstance(ex,HTTPError):
                row["http"]=ex.code
        report["matches"].append(row)
        time.sleep(0.4)

    report["coverage"]={league:dict(counts) for league,counts in by_league.items()}
    report["summary"]={
       "checked":sum(r["status"]=="HTTP_SUCCESS" for r in report["matches"]),
       "markets_with_at_least_one_price_pair":{
           market:sum( bool((r.get("markets") or {}).get(market,{}).get("lines"))
                   for r in report["matches"]) for market in ("goals","corners","cards","btts")
       },
       "complete_4_of_4":sum(r.get("present_count")==4 for r in report["matches"]),
    }
    report["overall_4_markets"]="PASS" if report["summary"]["complete_4_of_4"] else "FAIL"
    return report


if __name__=="__main__":
    print(json.dumps(audit(),ensure_ascii=False,indent=2))
