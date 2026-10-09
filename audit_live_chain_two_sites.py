#!/usr/bin/env python3
"""Two-site LIVE cascade read-only proof: 24score => MatchesNow.

No paid API; NO production DB change; NO commercial redistribution permission.
Arsenal-Leeds selected from both sites' live fixture pages. A single call per
provider, with each provider filling only markets still unavailable.
"""
from __future__ import annotations
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from odds_cascade_lab import Fixture, Provider, Quote, collect_chain, norm_name
from odds_24score_adapter_lab import parse_24score_fixture
from audit_matchesnow_four_markets import extract as parse_matchesnow
from audit_24score_coverage_lab import extract_pairs

UA = "OddsHunter-ReadOnly-Research/1.0"
URLS = {
    "24score-lab": "https://m.24score.com/football/match/854861-arsenal-leeds",
    "MatchesNow-lab": "https://matchesnow.co.uk/leagues/premier-league/2026/arsenal-leeds/odds",
}
# External schedule time for this known fixture, used solely to exercise
# the engine's identifier/time-window consistency checks.
KICKOFF = datetime(2026,10,10,11,30,tzinfo=timezone.utc)


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept":"text/html"})
    with urllib.request.urlopen(request, timeout=25) as response:
        if response.status != 200:
            raise RuntimeError("HTTP_NOT_OK")
        return response.read(1_500_000).decode("utf-8","replace")


def page_fixture_matches(html, fixture):
    soup = BeautifulSoup(html,"html.parser")
    title = soup.title.get_text(" ",strip=True) if soup.title else ""
    # Require both teams in page title, not just our manually constructed URL.
    normalized = norm_name(title)
    return norm_name(fixture.home) in normalized and norm_name(fixture.away) in normalized


def provider_matchesnow(fixture, html, captured):
    if not page_fixture_matches(html,fixture):
        raise ValueError("PAGE_TEAMS_MISMATCH")
    parsed = parse_matchesnow(html)
    rows=[]
    for market, item in parsed["markets"].items():
        line = item["line"]
        for side, price in item["prices"].items():
            rows.append(Quote(fixture.id,fixture.home,fixture.away,fixture.kickoff,
               market,side,line,price,item["bookmaker"],"MatchesNow-lab",
               captured,URLS["MatchesNow-lab"]))
    return rows


def live_cascade():
    now=datetime.now(timezone.utc)
    fixture=Fixture("ARS_LEE_2026_10_10","Arsenal","Leeds",KICKOFF)
    report={"utc":now.isoformat(),"fixture":fixture.id,"sources":{},"research_only":True,
            "commercial_permission":False}
    if KICKOFF <= now:
        report["status"]="FAIL_PAST_FIXTURE"
        return report
    pages={}
    for source,url in URLS.items():
        try:
            body=download(url)
            if not page_fixture_matches(body,fixture):
                report["sources"][source]={"status":"FAIL_MATCH_TITLE"}
                continue
            pages[source]=body
            report["sources"][source]={"status":"HTTP_200_MATCH_TITLE",
              "url":url}
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,ValueError) as exc:
            report["sources"][source]={"status":"ERROR","exception":type(exc).__name__,
                                      "http":getattr(exc,"code",None)}
    providers=[]
    if "24score-lab" in pages:
        providers.append(Provider("24score-lab",
            lambda f: parse_24score_fixture(pages["24score-lab"],f,
                     retrieved_at=now,url=URLS["24score-lab"])))
    if "MatchesNow-lab" in pages:
        providers.append(Provider("MatchesNow-lab",
            lambda f: provider_matchesnow(f,pages["MatchesNow-lab"],now)))
    chain=collect_chain(fixture,providers,now=now,commercial=False)
    report["market_sources"]={m:{"source":q["source"],"bookmaker":q["bookmaker"],
         "line":q["line"],"prices":q["prices"]} for m,q in chain["markets"].items()}
    report["status"]=chain["status"]
    report["missing"]=chain["missing"]
    report["research_chain_captured_all"]=chain["status"]=="PASS_4_OF_4"
    # Source attribution of 24score is unknown. Do not treat as a commercial quote.
    report["license_and_bookmaker_gate"]="FAIL"
    report["publish"]=False
    return report


if __name__=="__main__":
    result=live_cascade()
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
    sys.exit(0 if result.get("research_chain_captured_all") else 1)
