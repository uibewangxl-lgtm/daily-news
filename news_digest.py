#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, sys, time, logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import feedparser, requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SENDKEY = os.environ.get("SENDKEY", "")
if not SENDKEY:
    log.error("环境变量 SENDKEY 未设置"); sys.exit(1)
NO_TRANSLATE = os.environ.get("NO_TRANSLATE", "") == "1"
TZ_CST = timezone(timedelta(hours=8))
SCURL = "https://sctapi.ftqq.com/" + SENDKEY + ".send"

RSS = {
    "\U0001f30d \u65f6\u653f\u00b7\u56fd\u9645": [
        ("ABC News", "https://feeds.abcnews.com/abcnews/topstories"),
        ("ABC News\u00b7\u56fd\u9645", "https://feeds.abcnews.com/abcnews/internationalheadlines"),
    ],
    "\U0001f4bb \u79d1\u6280": [
        ("Hacker News", "https://hnrss.org/frontpage"),
        ("ArsTechnica", "https://feeds.arstechnica.com/arstechnica/index"),
    ],
    "\U0001f4c8 \u8d22\u7ecf\u00b7\u5546\u4e1a": [
        ("TechCrunch", "https://techcrunch.com/feed/"),
    ],
    "\U0001f3d8\ufe0f \u793e\u4f1a\u00b7\u6c11\u751f": [
        ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ],
    "\U0001f52c \u79d1\u5b66\u00b7\u5065\u5eb7": [
        ("Nature", "https://www.nature.com/nature.rss"),
    ],
}
T1 = {"ABC News","ABC News\u00b7\u56fd\u9645","Nature","ArsTechnica","NPR"}
T2 = {"TechCrunch","Hacker News"}
KW_H = ["breakthrough","launch","first","major","crisis","emergency",
        "agreement","sanction","elected","resign","killed","discover",
        "announce","supreme court","president","congress"]
KW_M = ["report","study","found","warn","accuse","record","ban"]
_tl = None

def gtl():
    global _tl
    if not _tl:
        from deep_translator import GoogleTranslator
        _tl = GoogleTranslator(source="auto", target="zh-CN")
    return _tl

def zh(s): return bool(re.search(r"[\u4e00-\u9fff]", s))

def tl(s):
    if not s or zh(s): return s
    if NO_TRANSLATE: return s
    try: return gtl().translate(s[:1500])
    except: return s

def fetch(url):
    try:
        r = requests.get(url, timeout=(5,8), headers={"User-Agent":"Mozilla/5.0"})
        r.raise_for_status()
        f = feedparser.parse(r.content)
        log.info("  %d <- %s", len(f.entries), url.split("/")[2])
        return f.entries
    except Exception as e:
        log.warning("  fail %s", str(e)[:80]); return []

def safe(s):
    if not s: return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s)).strip()

def pub(e):
    for a in ("published_parsed","updated_parsed"):
        p = getattr(e,a,None)
        if p:
            try: return datetime(*p[:6],tzinfo=timezone.utc)
            except: pass
    return datetime.now(timezone.utc)

SW = {"the","a","an","in","on","at","to","for","of","with","and","its","has","was","new"}

def xref(items):
    rr = []
    for it in items:
        w = set(w for w in re.sub(r"[^\w]"," ",it[2][:25]).lower().split()
                if len(w)>2 and w not in SW)
        rr.append((it[0],it[1],w))
    c = [0]*len(items)
    for i in range(len(items)):
        for j in range(i+1,len(items)):
            if rr[i][1]!=rr[j][1] and len(rr[i][2]&rr[j][2])>=3:
                c[i]+=1;c[j]+=1
    return c

def ssc(n):
    if n in T1: return 10
    if n in T2: return 5
    return 2

def kwsc(t):
    lo=t.lower();s=0
    for kw in KW_H:
        if kw.lower() in lo: s+=5
    for kw in KW_M:
        if kw.lower() in lo: s+=2
    return s

def rank(news):
    xr = xref(news)
    nw = datetime.now(timezone.utc)
    out = []
    for i,(c,s,t,l,su,p) in enumerate(news):
        tt = ssc(s)+kwsc(t)+xr[i]*3
        if (nw-p).total_seconds()/3600<24: tt+=5
        out.append((tt,c,s,t,l,su,p,xr[i]))
    out.sort(key=lambda x:x[0],reverse=True)
    return out

def sel(sc,n=20):
    bc = defaultdict(list)
    for it in sc: bc[it[1]].append(it)
    for c in bc: bc[c].sort(key=lambda x:x[0],reverse=True)
    q = sorted(bc,key=lambda c:sum(x[0] for x in bc[c]),reverse=True)
    s = []
    while q and len(s)<n:
        c = q.pop(0)
        if bc[c]:
            s.append(bc[c].pop(0))
            if bc[c]: q.append(c)
    return s

def tr(s,n=80):
    return s[:n].rstrip()+".." if len(s)>n else s

def focus(top):
    _,c,s,t,l,su,p,r = top[0]
    a = ["**"+tl(t)+"**"]
    if su: a.append(tl(tr(su,120)))
    if r>=2: a.append("(多家媒体)")
    return " | ".join(a)

def fmt(items):
    nw = datetime.now(TZ_CST)
    ls = ["\U0001f4f0 **\u6bcf\u65e5\u65b0\u95fb\u901f\u89c8 - " + nw.strftime("%Y\u5e74%m\u6708%d\u65e5") + "**","",
          "\u5171 " + str(len(items)) + " \u6761 | \U0001f550 " + nw.strftime("%H:%M"),"","---",""]
    for i,(sc,c,s,t,l,su,p,r) in enumerate(items,1):
        tc = tl(t)
        sc2 = tl(su) if su else ""
        rt = " (x"+str(r)+")" if r>=2 else ""
        ls.append(str(i)+". "+c+" **"+tr(tc,60)+"**"+rt)
        ls.append("   "+ (tr(sc2,90) if sc2 else tr(tc,60)))
        ls.append("")
    ls.extend(["---","","\U0001f4cc **\u4eca\u65e5\u7126\u70b9**："+focus(items),"",""])
    return "\n".join(ls)

def push(title,body):
    r = requests.post(SCURL, data={"title":title,"desp":body}, timeout=20)
    j = r.json()
    if j.get("code")==0:
        log.info("OK push %s", j.get("data",{}).get("pushid","")); return True
    log.error("FAIL: %s", j.get("message","")); return False

def main():
    t0 = time.time()
    today = datetime.now(TZ_CST).strftime("%Y-%m-%d")
    log.info("="*40)
    log.info("start %s", today)
    raw = []
    for cat,sources in RSS.items():
        for name,url in sources:
            for e in fetch(url):
                ti = safe(e.get("title",""))
                if not ti: continue
                raw.append((cat,name,ti,e.get("link",""),
                    safe(e.get("summary","") or e.get("description",""))[:200],pub(e)))
    log.info("raw %d", len(raw))
    seen,ded = set(),[]
    for it in raw:
        k = it[2][:20].lower().strip()
        if k and k not in seen: seen.add(k); ded.append(it)
    log.info("dedup %d", len(ded))
    scored = rank(ded)
    if scored: log.info("top %.0f - %s",scored[0][0],scored[0][3][:60])
    top = sel(scored,20)
    for i,it in enumerate(top,1):
        log.info("  %2d. [%3.0f] %s",i,it[0],it[3][:60])
    body = fmt(top)
    title = "\U0001f4f0 \u6bcf\u65e5\u65b0\u95fb\u901f\u89c8 - "+today
    with open(today+".md","w",encoding="utf-8") as f: f.write(body)
    log.info("saved %s.md", today)
    ok = push(title,body)
    log.info("done %.1fs", time.time()-t0)
    if not ok: sys.exit(1)

if __name__=="__main__":
    main()
