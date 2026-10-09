#!/usr/bin/env python3
"""Limited, unauthenticated, read-only bookmaker quote audit for MatchesNow.

Strictly a technical feasibility check. No commercial right is assumed.
Do not use as a production OddsHunter integration without written permission.
"""
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup

BASE = "https://matchesnow.co.uk"
AGENT = "OddsHunter-ReadOnly-Research/1.0"
MARKETS = {
    "goals": "Goals over/under",
    "corners": "Corners over/under",
    "cards": "Cards over/under",
    "btts": "Both teams score",
}
PREF_LINE = {"goals": 2.5, "corners": 9.5, "cards": 4.5}
SAMPLES = [
    ("LaLiga", "/leagues/la-liga/2026/malaga-espanyol/odds"),
    ("Premier League", "/leagues/premier-league/2026/arsenal-leeds/odds"),
    ("Bundesliga", "/leagues/bundesliga/2026/borussia-dortmund-werder-bremen/odds"),
    ("Ligue 1", "/leagues/ligue-1/2026/lens-olympique-lyon/odds"),
    ("Serie A", "/leagues/serie-a/2026/inter-parma/odds"),
    ("MLS", "/leagues/mls/2026/minnesota-united-houston-dynamo/odds"),
]
PRICE_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
LINE_RE = re.compile(r"^(over|under)\s+(\d+(?:\.\d+)?)$", re.I)


def download(url: str) -> str:
    req=Request(url,headers={"User-Agent":AGENT,"Accept":"text/html"})
    with urlopen(req,timeout=23) as response:
        if response.status != 200:
            raise RuntimeError("unexpected http code")
        return response.read(2_000_000).decode("utf-8","replace")


def prices_from_table(table, market: str):
    head=table.find("thead")
    head_row=(head.find("tr") if head else table.find("tr"))
    if not head_row: return []
    headers=[cell.get_text(" ",strip=True) for cell in head_row.find_all(["th","td"],recursive=False)]
    valid_headers={}
    for idx,label in enumerate(headers):
        if market=="btts":
            side=label.strip().casefold()
            if side in ("yes","no"):valid_headers[idx]=(side,None)
        else:
            m=LINE_RE.fullmatch(label.strip())
            if m:valid_headers[idx]=(m.group(1).casefold(),float(m.group(2)))
    body=table.find("tbody")
    rows=(body.find_all("tr",recursive=False) if body else table.find_all("tr")[1:])
    candidates=[]
    for row in rows:
        cells=row.find_all(["td","th"],recursive=False)
        if len(cells) != len(headers):continue
        bookmaker=cells[0].get_text(" ",strip=True)
        if bookmaker.casefold() in ("average","avg",""):
            continue
        groups={}
        for idx,(side,line) in valid_headers.items():
            value=cells[idx].get_text(" ",strip=True).replace(",",".")
            if not PRICE_RE.fullmatch(value):continue
            odd=float(value)
            if not 1.0 < odd < 1000:continue
            groups.setdefault(line,{})[side]=odd
        for line,pairs in groups.items():
            if set(pairs)==({"yes","no"} if market=="btts" else {"over","under"}):
                candidates.append({"bookmaker":bookmaker,"line":line,"prices":pairs})
    return candidates


def extract(html: str):
    soup=BeautifulSoup(html,"html.parser")
    found={}
    debug={}
    for key,title in MARKETS.items():
        heading=next((h for h in soup.find_all(["h2","h3","h4"])
                      if h.get_text(" ",strip=True).casefold()==title.casefold()),None)
        if heading is None:
            debug[key]="MISSING_HEADING"
            continue
        table=heading.find_next("table")
        next_heading=heading.find_next(["h2","h3","h4"])
        # Heading and table must belong to the same market section.
        if table is None or (next_heading is not None and list(heading.next_elements).index(table) >
                             list(heading.next_elements).index(next_heading)):
            debug[key]="MISSING_TABLE"
            continue
        candidates=prices_from_table(table,key)
        selected=sorted(candidates,key=lambda q: (
              q["bookmaker"].casefold()!="bet365",
              abs(q["line"]-PREF_LINE[key]) if key!="btts" else 0,
              q["bookmaker"])) if candidates else []
        if selected:found[key]=selected[0]
        else:
            debug[key]="NO_PAIRED_BOOKMAKER_QUOTES"
            head=table.find("thead")
            debug[key+"_headers"]=[x.get_text(" ",strip=True) for x in (head.find_all(["th","td"]) if head else table.find_all(["th","td"])[:8])][:12]
    title=(soup.find("h1") or soup.title)
    body=soup.get_text(" ",strip=True)
    update=re.search(r"Updated at\s+([A-Za-z]+\s+\d{1,2},\s+20\d{2}\s+\d{1,2}:\d{2}\s*[AP]M)",body,re.I)
    return {"title":title.get_text(" ",strip=True) if title else None,
            "updated_at_unzoned":update.group(1) if update else None,
            "markets":found,"missing":[m for m in MARKETS if m not in found],
            "debug":debug,"market_count":len(found),"complete_four":len(found)==4}


def audit():
    report={"source":BASE,"read_only":True,"licensed_for_resale":"UNVERIFIED",
            "run_utc":datetime.now(timezone.utc).isoformat(),
            "matches":[]}
    rp=RobotFileParser()
    try:
        with urlopen(Request(BASE+"/robots.txt",headers={"User-Agent":AGENT}),timeout=15) as response:
            rp.parse(response.read(50000).decode("utf-8","replace").splitlines())
            report["robots_http"]=response.status
    except HTTPError as exc:
        report["robots_http"]=exc.code
        if exc.code!=404:
            report["status"]="FAIL_ROBOTS_UNAVAILABLE"
            return report
        rp=None
    except (URLError,TimeoutError) as exc:
        report["robots_error"]=type(exc).__name__
        report["status"]="FAIL_ROBOTS_UNAVAILABLE"
        return report
    for league,path in SAMPLES:
        url=BASE+path
        row={"league":league,"url":url}
        if rp is not None and not rp.can_fetch(AGENT,url):
            row["status"]="ROBOTS_DISALLOWED"
            report["matches"].append(row)
            continue
        try:
            data=extract(download(url))
            row.update(data)
            row["status"]="FETCH_OK"
        except HTTPError as exc:
            row["status"]="HTTP_ERROR"
            row["http"]=exc.code
        except (URLError,TimeoutError) as exc:
            row["status"]="FETCH_ERROR"
            row["error_type"]=type(exc).__name__
        report["matches"].append(row)
        if row.get("complete_four"):
            break
    report["four_of_four_count"]=sum(x.get("complete_four",False) for x in report["matches"])
    report["technical_gate"]="PASS" if report["four_of_four_count"] else "FAIL"
    report["commercial_gate"]="FAIL_NO_WRITTEN_LICENSE"
    return report

if __name__=="__main__":
    print(json.dumps(audit(),ensure_ascii=False,indent=2))
