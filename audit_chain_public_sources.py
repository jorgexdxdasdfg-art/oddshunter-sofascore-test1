#!/usr/bin/env python3
"""Read-only minimal source reachability audit; no scraping at scale, no API keys.

A market heading on a public site is NOT a verified paired real quote and is
NOT permission to commercially republish. These statuses are distinct.
"""
import json
import re
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from html.parser import HTMLParser


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text=[]
        self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript"): self.skip+=1
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript") and self.skip: self.skip-=1
    def handle_data(self,data):
        if not self.skip and data.strip(): self.text.append(data.strip())


AGENT="OddsHunter-Lab-Public-Audit/1.0"
TARGETS=[
 ("24score","https://m.24score.com","/football/match/854861-arsenal-leeds"),
 ("FindOdds","https://findodds.me","/"),
]


def probe(name, host, path):
    record={"provider":name,"url":host+path,"rights":"UNVERIFIED",
            "supports_four_complete_markets":"NOT_ESTABLISHED"}
    robot=urllib.robotparser.RobotFileParser()
    try:
        with urllib.request.urlopen(urllib.request.Request(host+"/robots.txt",
                headers={"User-Agent":AGENT}),timeout=14) as response:
            robot.parse(response.read(50000).decode("utf-8","replace").splitlines())
    except urllib.error.HTTPError as exc:
        if exc.code!=404:
            record["robots_http"]=exc.code
            return record
        record["robots_http"]=404
    except Exception as exc:
        record["robots_error"]=type(exc).__name__
        return record
    if record.get("robots_http") != 404 and not robot.can_fetch(AGENT,host+path):
        record["robots_allowed"]=False
        return record
    record["robots_allowed"]=True
    try:
        with urllib.request.urlopen(urllib.request.Request(host+path,
                headers={"User-Agent":AGENT,"Accept":"text/html"}),timeout=18) as response:
            record["http"]=response.status
            body=response.read(1000000).decode("utf-8","replace")
        parser=TextOnly()
        parser.feed(body)
        text=" ".join(parser.text)
        if name=="FindOdds":
            checks={
             "goals":"Match goals Over" in text,
             "btts":"Both teams to score Yes" in text,
             "corners":"Corners Over" in text,
             "cards":"Cards Over" in text,
            }
            record["visible_market_headings"]=checks
            record["result"]="FOUR_CATEGORIES_VISIBLE_NOT_FOUR_PAIRED_QUOTES" if all(checks.values()) else "PARTIAL"
        else:
            record["visible_market_headings"]={
             "goals":bool(re.search(r"Total Goals\s+2\.5\s+Over\s+Under",text,re.I)),
             "corners":bool(re.search(r"Total Corners\s+9\.5\s+Over\s+Under",text,re.I)),
             "cards":bool(re.search(r"Total YC\s+\d",text,re.I)),
             "btts":bool(re.search(r"Both Teams to Score",text,re.I)),
            }
            record["result"]="READABLE_HTML_NO_4_OF_4_CLAIM"
    except urllib.error.HTTPError as exc: record["http"]=exc.code
    except Exception as exc: record["fetch_error"]=type(exc).__name__
    return record


if __name__=="__main__":
    print(json.dumps({"run_at":datetime.now(timezone.utc).isoformat(),
       "read_only":True,
       "requests_at_most":4,
       "sources":[probe(*args) for args in TARGETS],
       "commercial_release_gate":"FAIL_PERMISSION_UNVERIFIED",
       "real_4_of_4_fixture_gate":"NOT_TESTED"},ensure_ascii=False,indent=2))
