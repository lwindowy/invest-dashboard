"""미국 SEC 공시(EDGAR)에서 받는 데이터: 최근 공시 목록, 내부자 매매(Form 4), 13F 보유 종목.

- 키가 필요 없는 공개 데이터다. SEC 안내에 따라 요청 사이에 잠깐 쉬고, 하루 한 번만 받는다.
- 이미 읽은 문서는 접수번호(accession)로 기억해 다시 받지 않는다.
- 한 종목·한 운용사가 실패해도 나머지는 계속한다.
"""
import datetime as dt
import sys
import time
import xml.etree.ElementTree as ET

import requests

HEADERS = {"User-Agent": "personal-dashboard-bot/1.0"}
ARCHIVE = "https://www.sec.gov/Archives/edgar/data"
PAUSE = 0.15

# 보여 줄 공시 종류와 한글 이름
FORMS = {
    "10-K": "연간보고서", "10-Q": "분기보고서", "8-K": "수시공시", "20-F": "연간보고서 (외국기업)", "6-K": "수시공시 (외국기업)",
    "S-1": "증권 신고서", "S-3": "증권 발행 신고", "S-3ASR": "증권 발행 신고", "F-3": "증권 발행 신고", "F-3ASR": "증권 발행 신고",
    "424B2": "증권 발행 (투자설명서)", "424B3": "증권 발행 (투자설명서)", "424B4": "증권 발행 (투자설명서)",
    "424B5": "증권 발행 (투자설명서)", "424B7": "증권 발행 (투자설명서)",
    "SC 13D": "5% 이상 대량 보유 (경영 참여)", "SC 13G": "5% 이상 대량 보유", "SCHEDULE 13D": "5% 이상 대량 보유 (경영 참여)", "SCHEDULE 13G": "5% 이상 대량 보유",
}
# 8-K 항목 번호의 뜻 (자주 나오는 것만)
ITEMS = {"1.01": "주요 계약 체결", "1.02": "주요 계약 종료", "2.01": "인수·매각 완료", "2.02": "실적 발표", "2.03": "채무 발생",
         "2.05": "구조조정", "3.02": "미등록 증권 판매", "4.02": "재무제표 정정", "5.02": "임원·이사 변동", "5.07": "주주총회 결과",
         "7.01": "공정공시", "8.01": "기타 사건"}
# Form 4 거래 코드
CODES = {"P": "공개시장 매수", "S": "공개시장 매도", "A": "회사로부터 받음", "M": "옵션 행사", "F": "세금 납부용 처분",
         "G": "증여", "C": "전환", "X": "옵션 행사", "D": "회사에 반납", "J": "기타"}


def get(url, **kw):
    time.sleep(PAUSE)
    r = requests.get(url, headers=HEADERS, timeout=40, **kw)
    r.raise_for_status()
    return r


def local(tag):
    return tag.rsplit("}", 1)[-1]


def text(node, path):
    """네임스페이스와 상관없이 path(태그 이름을 / 로 이은 것)의 글자를 찾는다."""
    for part in path.split("/"):
        node = next((c for c in node if local(c.tag) == part), None) if node is not None else None
    return (node.text or "").strip() if node is not None else ""


def children(node, name):
    return [c for c in node.iter() if local(c.tag) == name]


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def recent(cik):
    """회사(또는 운용사)의 최근 공시를 줄 단위로."""
    rec = get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json").json()["filings"]["recent"]
    keys = ("form", "filingDate", "reportDate", "accessionNumber", "primaryDocument", "items")
    return [dict(zip(keys, row)) for row in zip(*(rec.get(k) or [""] * len(rec["form"]) for k in keys))]


def parse_form4(cik, filing):
    """Form 4 한 건에서 보통주 거래를 읽는다."""
    doc = filing["primaryDocument"].split("/")[-1]      # 화면용 변환 경로(xslF345X06/)를 떼면 원본 XML이다
    acc = filing["accessionNumber"].replace("-", "")
    root = ET.fromstring(get(f"{ARCHIVE}/{int(cik)}/{acc}/{doc}").content)
    rel = next(iter(children(root, "reportingOwnerRelationship")), None)
    role = (text(rel, "officerTitle") if rel is not None and text(rel, "isOfficer") in ("1", "true") else "") or \
           ("이사" if rel is not None and text(rel, "isDirector") in ("1", "true") else "") or \
           ("10% 이상 주주" if rel is not None and text(rel, "isTenPercentOwner") in ("1", "true") else "") or "기타"
    owner = text(next(iter(children(root, "reportingOwnerId")), None), "rptOwnerName").title()
    planned = text(root, "aff10b5One") in ("1", "true")
    rows = []
    for t in children(root, "nonDerivativeTransaction"):
        code = text(t, "transactionCoding/transactionCode")
        shares, price = fnum(text(t, "transactionAmounts/transactionShares/value")), fnum(text(t, "transactionAmounts/transactionPricePerShare/value"))
        if not shares or code not in ("P", "S"):     # 공개시장 매수·매도만 남긴다(주식 보상, 옵션 행사, 증여 등은 뺀다)
            continue
        rows.append({"date": text(t, "transactionDate/value"), "filed": filing["filingDate"], "owner": owner, "role": role,
                     "code": code, "kind": CODES.get(code, code), "shares": shares, "price": price,
                     "value": round(shares * price) if price else None,
                     "after": fnum(text(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                     "planned": planned, "acc": filing["accessionNumber"]})
    # 하루에 여러 가격으로 나눠 체결된 거래는 한 건으로 합친다
    merged = {}
    for r in rows:
        m = merged.setdefault((r["date"], r["code"]), {**r, "shares": 0, "value": 0})
        m["shares"] += r["shares"]
        m["value"] += r["value"] or 0
        m["after"] = r["after"]
    for m in merged.values():
        m["price"] = round(m["value"] / m["shares"], 2) if m["value"] else None
        m["value"] = m["value"] or None
    return list(merged.values())


def company(ticker, cik, old, today):
    """한 종목의 최근 공시와 내부자 매매."""
    rows = recent(cik)
    since_filings = (today - dt.timedelta(days=90)).isoformat()
    since_insider = (today - dt.timedelta(days=180)).isoformat()
    filings = []
    for f in rows:
        if f["form"] in FORMS and f["filingDate"] >= since_filings and len(filings) < 10:
            items = [ITEMS[i] for i in (f.get("items") or "").split(",") if i in ITEMS]
            filings.append({"date": f["filingDate"], "form": f["form"], "label": FORMS[f["form"]], "items": items,
                            "acc": f["accessionNumber"],
                            "url": f"{ARCHIVE}/{int(cik)}/{f['accessionNumber'].replace('-', '')}/{f['primaryDocument']}"})
    known = {}
    for r in (old or {}).get("insider", []):
        known.setdefault(r["acc"], []).append(r)
    seen = set((old or {}).get("form4_seen", []))
    insider, form4_seen = [], []
    for f in [x for x in rows if x["form"] == "4" and x["filingDate"] >= since_insider][:60]:
        acc = f["accessionNumber"]
        form4_seen.append(acc)
        if acc in seen:                       # 이미 읽은 문서는 다시 받지 않는다
            insider += known.get(acc, [])
            continue
        try:
            insider += parse_form4(cik, f)
        except Exception as exc:
            print(f"[참고] Form 4 {ticker} {acc}: {exc}", file=sys.stderr)
            form4_seen.pop()
    insider.sort(key=lambda r: (r["date"], r["acc"]), reverse=True)
    window = (today - dt.timedelta(days=90)).isoformat()
    buys = [r for r in insider if r["code"] == "P" and r["date"] >= window]
    sells = [r for r in insider if r["code"] == "S" and r["date"] >= window]
    summary = {"buy_count": len(buys), "buy_value": sum(r["value"] or 0 for r in buys),
               "sell_count": len(sells), "sell_value": sum(r["value"] or 0 for r in sells),
               "sell_planned": sum(1 for r in sells if r["planned"])}
    return {"cik": int(cik), "filings": filings, "insider": insider, "form4_seen": form4_seen, "summary": summary}


def parse_13f(cik, filing):
    """13F 한 건의 보유 종목을 회사별로 합친다(주식만, 옵션 제외)."""
    acc = filing["accessionNumber"].replace("-", "")
    files = get(f"{ARCHIVE}/{int(cik)}/{acc}/index.json").json()["directory"]["item"]
    name = next((f["name"] for f in files if f["name"].lower().endswith(".xml") and "primary_doc" not in f["name"].lower()), None)
    if not name:
        raise ValueError("보유 종목 표를 찾지 못했습니다")
    root = ET.fromstring(get(f"{ARCHIVE}/{int(cik)}/{acc}/{name}").content)
    holdings = {}
    for row in children(root, "infoTable"):
        if text(row, "putCall"):
            continue
        issuer, value, shares = text(row, "nameOfIssuer").upper(), fnum(text(row, "value")) or 0, fnum(text(row, "shrsOrPrnAmt/sshPrnamt")) or 0
        key = text(row, "cusip").upper()[:6] or issuer     # 이름 표기는 분기마다 달라질 수 있어 식별번호로 묶는다
        h = holdings.setdefault(key, {"key": key, "issuer": issuer, "value": 0, "shares": 0})
        h["value"] += value
        h["shares"] += shares
    # 금액은 달러로 적는 것이 규칙이지만 천 달러 단위로 적는 운용사가 있다. 주당 가격이 1달러도 안 되게 나오면 천 달러 단위로 본다
    prices = sorted(h["value"] / h["shares"] for h in holdings.values() if h["shares"])
    if prices and prices[len(prices) // 2] < 1:
        for h in holdings.values():
            h["value"] *= 1000
    return {"acc": filing["accessionNumber"], "period": filing["reportDate"], "filed": filing["filingDate"],
            "total": sum(h["value"] for h in holdings.values()), "holdings": holdings}


def manager(cfg, old, watch_names):
    """운용사의 최신 13F와 직전 분기 대비 변화."""
    filings = [f for f in recent(cfg["cik"]) if f["form"] == "13F-HR"][:2]
    if not filings:
        raise ValueError("13F 공시가 없습니다")
    # 같은 13F를 이미 읽었고 관심 종목 목록도 그대로면 다시 받지 않는다(종목을 추가·삭제하면 다시 맞춰 본다)
    if old and old.get("acc") == filings[0]["accessionNumber"] and old.get("watch_keys") == sorted(watch_names):
        return old
    now = parse_13f(cfg["cik"], filings[0])
    before = parse_13f(cfg["cik"], filings[1])["holdings"] if len(filings) > 1 else {}

    def describe(h):
        prev = before.get(h["key"])
        if not before:
            change = None
        elif prev is None:
            change = "새로 매수"
        elif h["shares"] > prev["shares"] * 1.01:
            grew = (h["shares"] / prev["shares"] - 1) * 100
            change = f"늘림 +{grew:.0f}%" if grew < 1000 else "크게 늘림 (10배 이상)"
        elif h["shares"] < prev["shares"] * 0.99:
            change = f"줄임 −{(1 - h['shares'] / prev['shares']) * 100:.0f}%"
        else:
            change = "그대로"
        return {"issuer": h["issuer"].title(), "value": h["value"], "weight_pct": round(h["value"] / now["total"] * 100, 1) if now["total"] else None,
                "change": change}
    ranked = sorted(now["holdings"].values(), key=lambda h: h["value"], reverse=True)
    watch = []
    same = lambda issuer, key: issuer == key or issuer.startswith(key + " ")
    for ticker, (label, key) in watch_names.items():
        hit = next((h for h in ranked if same(h["issuer"], key)), None)
        gone = hit is None and any(same(h["issuer"], key) for h in before.values())
        if hit:
            watch.append({"ticker": ticker, "name": label, **describe(hit)})
        elif gone:
            watch.append({"ticker": ticker, "name": label, "value": 0, "weight_pct": 0, "change": "전부 매도"})
    sold = [h["issuer"].title() for k, h in sorted(before.items(), key=lambda kv: kv[1]["value"], reverse=True) if k not in now["holdings"]][:5]
    return {"name": cfg["name"], "who": cfg.get("who"), "cik": int(cfg["cik"]), "acc": now["acc"], "period": now["period"], "filed": now["filed"],
            "total": now["total"], "count": len(ranked), "top": [describe(h) for h in ranked[:10]], "watch": watch, "sold": sold,
            "watch_keys": sorted(watch_names),
            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(cfg['cik'])}&type=13F-HR"}


GENERIC = {"CORP", "CORPORATION", "INC", "LTD", "LIMITED", "GROUP", "TECHNOLOGIES", "CO", "PLC", "NV", "HOLDINGS", "COM"}


def match_key(title):
    """13F의 회사 이름과 맞춰 볼 앞부분. 둘째 단어가 흔한 말(Corp, Inc 등)이면 첫 단어만 쓴다."""
    words = "".join(ch for ch in title.upper() if ch.isalnum() or ch == " ").split()
    return " ".join(words[:2]) if len(words) > 1 and words[1] not in GENERIC else words[0]


def build(config, prev, today, warn):
    """하루 한 번 SEC 데이터를 모은다. prev 는 이전 결과의 'sec' 부분."""
    prev = prev or {}
    us = [e["ticker"] for e in config["watchlist"].get("us", [])]
    known = set(prev.get("companies") or {}) | set(prev.get("not_on_sec") or [])
    on_sec = sorted(t for t in us if t not in set(prev.get("not_on_sec") or []))
    managers_ok = all(m.get("watch_keys") == on_sec for m in prev.get("managers", []))   # 13F에서 맞춰 본 종목 목록도 그대로인지
    if prev.get("fetched") == today.isoformat() and all(t in known for t in us) and managers_ok:
        # 오늘 이미 받았고 새로 추가된 종목이 없다. 목록에서 뺀 종목만 지운다
        return {**prev, "companies": {t: c for t, c in (prev.get("companies") or {}).items() if t in us}}
    try:
        listing = get("https://www.sec.gov/files/company_tickers.json").json().values()
        ciks = {row["ticker"]: (row["cik_str"], row["title"]) for row in listing}
    except Exception as exc:
        warn("SEC 종목 목록", exc)
        return prev
    companies, watch_names, not_on_sec = {}, {}, []
    for entry in config["watchlist"].get("us", []):
        ticker = entry["ticker"]
        if ticker not in ciks:
            not_on_sec.append(ticker)
            continue
        cik, title = ciks[ticker]
        watch_names[ticker] = (entry["name"], match_key(title))
        try:
            companies[ticker] = company(ticker, cik, (prev.get("companies") or {}).get(ticker), today)
        except Exception as exc:
            warn(f"SEC 공시 {ticker}", exc)
            if ticker in (prev.get("companies") or {}):
                companies[ticker] = prev["companies"][ticker]
    managers = []
    old_managers = {m["cik"]: m for m in prev.get("managers", [])}
    for cfg in config.get("sec", {}).get("managers", []):
        try:
            managers.append(manager(cfg, old_managers.get(int(cfg["cik"])), watch_names))
        except Exception as exc:
            warn(f"13F {cfg['name']}", exc)
            if int(cfg["cik"]) in old_managers:
                managers.append(old_managers[int(cfg["cik"])])
    return {"fetched": today.isoformat(), "source": "SEC EDGAR", "companies": companies, "managers": managers, "not_on_sec": not_on_sec}
