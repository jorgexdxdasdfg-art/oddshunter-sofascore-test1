#!/usr/bin/env python3
"""Comprobacion no autenticada y solo lectura de FieldFunded. Cero llamadas de cuota."""
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from urllib.parse import urljoin
BASE = "https://api.fieldfunded.com"
PAGES = ("/v1/ping", "/v1/health", "/v1/status", "/v1/markets", "/v1/events?sport=soccer")
REPORT={"provider":"FieldFunded", "mode":"READ_ONLY_NO_KEY","time":datetime.now(timezone.utc).isoformat(),"checks":[],"four_market_live_gate":"NOT_TESTABLE_WITHOUT_KEY"}
for path in PAGES:
    req=urllib.request.Request(BASE+path,headers={"User-Agent":"OddsHunter-Public-Audit/1.0","Accept":"application/json"})
    item={"endpoint":path}
    try:
        with urllib.request.urlopen(req,timeout=12) as resp:
            body=resp.read(100000)
            item["http"]=resp.status
            item["content_type"]=resp.headers.get("Content-Type", "")
            try:
                result=json.loads(body)
                if path=="/v1/markets":
                    serialized=json.dumps(result).lower()
                    item["mentions"]={key:key in serialized for key in ("corner","card","btts","total")}
                elif path=="/v1/status":
                    item["fields"]=list(result)[:15] if isinstance(result,dict) else []
                else:
                    item["json_type"]=type(result).__name__
            except (ValueError,TypeError):
                item["json_type"]="not_json"
    except urllib.error.HTTPError as exc:
        item["http"]=exc.code
    except Exception as exc:
        item["error_type"]=type(exc).__name__
    REPORT["checks"].append(item)
print(json.dumps(REPORT,ensure_ascii=False,indent=2))
