#!/usr/bin/env python3
"""Read-only check of publisher T&C and verified contact routes.
No inference that publicly accessible odds can be resold.
"""
import json,re,urllib.request,urllib.error
from bs4 import BeautifulSoup
from datetime import datetime,timezone

SITES={
  "matchesnow":["https://matchesnow.co.uk/terms","https://matchesnow.co.uk/faq","https://matchesnow.co.uk/"],
  "findodds":["https://findodds.me/contact/"],
}
terms={"scraping","scrape","robot","automated","commercial","redistribution","reproduce","copy","license","licence","permission","written consent"}
result={"at":datetime.now(timezone.utc).isoformat(),"rights":"NOT_ASSUMED","pages":[]}
for name,urls in SITES.items():
  for url in urls:
    rec={"site":name,"url":url}
    try:
      with urllib.request.urlopen(urllib.request.Request(url,headers={
        "User-Agent":"OddsHunter-ReadOnly-Research/1.0"}),timeout=15) as r:
        body=r.read(500000).decode("utf8","replace")
        rec["http"]=r.status
        rec["final_url"]=r.url
      soup=BeautifulSoup(body,"html.parser")
      title=soup.find("title")
      rec["title"]=title.get_text(" ",strip=True) if title else ""
      rec["mailto"]=sorted({a.get("href") for a in soup.select("a[href^='mailto:']")})[:10]
      cf=[]
      for tag in soup.select("a[data-cfemail]"):
        code=tag.get("data-cfemail","")
        try:
          raw=bytes.fromhex(code)
          cf.append(bytes(b^raw[0] for b in raw[1:]).decode("utf8"))
        except Exception:pass
      rec["cloudflare_emails"]=sorted(set(cf))
      rec["terms_links"]=[a.get("href") for a in soup.select("a[href]")
                          if any(k in a.get_text(" ",strip=True).casefold()
                                 for k in ("terms","contact","privacy"))][:15]
      plain=soup.get_text(" ",strip=True)
      if name=="matchesnow" and "terms" in url:
        snippets=[]
        for m in re.finditer(r"(?i)\b(scraping|scrape|automated|commercial|reproduce|redistribution|consent|license|licence|copyright)\b",plain):
          snippets.append(plain[max(0,m.start()-65):min(len(plain),m.end()+110)])
        rec["terms_relevant_excerpts"]=snippets[:25]
        rec["terms_text_length"]=len(plain)
    except urllib.error.HTTPError as e:rec["http"]=e.code
    except Exception as e:rec["error"]=type(e).__name__
    result["pages"].append(rec)
print(json.dumps(result,ensure_ascii=False,indent=2))
