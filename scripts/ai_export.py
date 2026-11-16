"""Claude 같은 AI가 읽기 좋게 종목별 요약 파일을 만든다 (site/data/ai/).

- 화면용 dashboard.json 은 모든 종목·지표가 한데 섞여 있고 단위 설명이 없어서, 종목 하나당 파일 하나로 다시 정리한다.
- 계산은 여기(코드)에서 끝내고, AI는 해석만 하게 한다. 파일마다 출처, 기준일, 단위, 계산 방법을 함께 적는다.
- 개인 정보(보유 수량 등)는 넣지 않는다. 저장소와 사이트가 공개다.
"""
import json

import datetime as dt

import financials
import quality
import valuation_hist
import re


def site_url(data):
    owner, repo = data["site"]["repo"].split("/")
    return f"https://{owner}.github.io/{repo}/"


def file_name(ticker):
    return re.sub(r"[^A-Za-z0-9.-]", "_", ticker) + ".json"


def ratio(a, b, digits=1):
    return round(a / b, digits) if a is not None and b not in (None, 0) and b > 0 else None


def valuation(fund, fin):
    """Yahoo 시가총액과 SEC 최근 4개 분기 합계(없으면 최근 연간)로 직접 계산하는 배수."""
    cap = (fund or {}).get("market_cap")
    fin = fin or {}
    base, basis = fin.get("ttm"), "최근 4개 분기 합계"
    if not base and fin.get("annual"):
        base, basis = fin["annual"][-1], "최근 회계연도 (분기 자료가 없음)"
    last = ((fin.get("quarterly") or []) or (fin.get("annual") or []) or [{}])[-1]
    if not cap or not base:
        return None
    ev = cap - last["net_cash"] if last.get("net_cash") is not None else None
    return {
        "market_cap": cap, "basis": basis, "basis_end": base.get("end"), "net_cash_end": last.get("end"),
        "ps": ratio(cap, base.get("revenue")), "pe": ratio(cap, base.get("net_income")),
        "p_fcf": ratio(cap, base.get("fcf")), "fcf_yield_pct": ratio((base.get("fcf") or 0) * 100, cap, 2) if base.get("fcf") is not None else None,
        "ev": ev, "ev_sales": ratio(ev, base.get("revenue")), "ev_ebit": ratio(ev, base.get("op_income")),
        "note": "시가총액은 Yahoo(최근 값), 이익·현금흐름은 SEC 값(basis 참고), 순현금은 SEC 최근 분기(또는 연도) 말 값이다. "
                "EV = 시가총액 − 순현금. 이익·FCF가 0 이하이면 배수를 계산하지 않는다(null).",
    }


def stock_file(data, fin_all, ticker):
    s = data["stocks"][ticker]
    fund = s.get("fund") or {}
    fin = (fin_all.get("companies") or {}).get(ticker)
    sec_co = ((data.get("sec") or {}).get("companies") or {}).get(ticker)
    cur = fund.get("currency") or s.get("currency")
    out = {
        "about": {
            "what": f"{s['name']}({ticker}) 한 종목의 가격, 밸류에이션, 장기 재무, 실적, 공시, 알림을 모은 분석용 파일이다.",
            "rules_for_ai": [
                "숫자는 이 파일에 있는 값만 인용하고, 값이 null 이면 '데이터 없음'으로 다룬다. 추정해서 채우지 않는다.",
                "금액은 따로 적지 않으면 원 단위 그대로다(예: USD 1234000000 = 12.34억 달러). 비율 이름이 _pct 로 끝나면 % 값이다.",
                "답할 때 어느 기간·기준일의 값인지(end, asof, fetched)를 함께 말한다.",
                "장기 재무(financials)는 회사가 SEC에 낸 숫자이고, 가격·목표주가·공매도는 Yahoo 무료 데이터(약 15분 지연)다.",
                "알림과 체크리스트는 대시보드가 정한 기준으로 자동 점검한 참고용 신호다. 투자 권유가 아니다.",
            ],
            "generated_at": data["generated_at"],
            "site": site_url(data) + "#stocks/" + ticker,
            "currency": cur,
        },
        "ticker": ticker, "name": s["name"], "long_name": fund.get("long_name"), "market": s.get("market"),
        "sector": fund.get("sector"), "industry": fund.get("industry"),
        "price": {k: s.get(k) for k in ("price", "change_pct", "asof", "high52", "low52", "from_high_pct", "rsi", "cci")} |
                 {"returns_pct": s.get("returns"), "moving_averages": s.get("mas"), "source": "Yahoo Finance (약 15분 지연)"},
        "chart_checklist": [{"group": g["title"], "hits": [i["text"] + " — " + i["detail"] for i in g["items"] if i.get("hit")]} for g in s.get("checklist", [])],
        "yahoo_fundamentals": {k: fund.get(k) for k in ("fetched", "market_cap", "cash", "debt", "net_cash", "per", "forward_per", "psr", "peg",
                                                         "eps", "forward_eps", "roe_pct", "revenue_growth_pct", "target", "short", "earnings", "debt_metrics")}
        if fund else None,
        "credit_rating": s.get("rating"),
        "valuation_calc": valuation(fund, fin),
        "quality": quality.build(fin, fund, s.get("price")) if fin else None,
        "valuation_history": valuation_hist.build(fin, (fin or {}).get("price_weekly"), dt.date.fromisoformat(data["generated_at"][:10])) if fin else None,
        "financials": None,
        "earnings_release": None,
        "sec_filings_90d": (sec_co or {}).get("filings"),
        "insider_90d": (sec_co or {}).get("summary"),
        "insider_trades": [{k: r[k] for k in ("date", "owner", "role", "kind", "shares", "price", "value", "planned")} for r in (sec_co or {}).get("insider", [])[:15]],
        "alerts": [a for a in data.get("alerts", []) if a.get("ticker") == ticker],
        "news": [{k: n.get(k) for k in ("title", "publisher", "at", "url", "importance", "type", "event")} for n in ((s.get("news") or {}).get("items") or []) if not n.get("dup_of")],
        "news_note": "importance(1=중대 사건 ~ 5=일상)와 type은 AI가 기사 제목으로 분류한 값이다. 값이 없으면 아직 분류하지 않은 기사다. 같은 사건의 중복 기사는 뺐다.",
        "news_month": s.get("news_month"),
    }
    if fin:
        out["financials"] = {
            "source": fin_all.get("source"), "fetched": fin_all.get("fetched"), "entity": fin.get("entity"), "currency": fin.get("currency"),
            "sec_filings": fin.get("source_url"), "since": fin.get("since"), "since_note": fin.get("since_note"), "stale": fin.get("stale"),
            "splits": fin.get("splits"),
            "fields": fin_all.get("labels"), "method": fin_all.get("method"),
            "ttm": fin.get("ttm"), "annual": fin.get("annual"), "quarterly": (fin.get("quarterly") or [])[-20:],
            "ltm": financials.ltm_rows(fin.get("quarterly") or []), "cagr_pct": financials.cagr(fin.get("annual") or []),
        }
        rel = fin.get("release")
        if rel:
            out["earnings_release"] = {**rel, "note": "가장 최근 실적 발표 8-K(항목 2.02)에 붙은 회사 보도자료(첨부 99.1) 본문이다. "
                                                      "회사가 직접 쓴 글이라 회사 입장의 표현이 섞여 있다. 길면 앞부분만 넣었다(truncated)."}
    elif s.get("market") == "kr":
        out["financials_note"] = "한국 종목은 SEC 자료가 없다. 장기 재무는 DART API 키가 있어야 받을 수 있어 아직 없다. yahoo_fundamentals 의 최근 분기 값만 있다."
        out["yahoo_quarters"] = fund.get("quarters")
    else:
        out["financials_note"] = "SEC 장기 재무를 받지 못했다."
        out["yahoo_quarters"] = fund.get("quarters")
    return out


def index_file(data, files):
    base = site_url(data) + "data/"
    return {
        "about": "개인 투자 대시보드의 AI 분석용 데이터 목록이다. 종목 하나를 분석할 때는 그 종목 파일 하나만 읽으면 된다.",
        "generated_at": data["generated_at"],
        "how_to_use": [
            "종목 분석: stocks 의 url 을 읽는다. 파일 안 about.rules_for_ai 를 따른다.",
            "시장 전체 상황(국면 판단, 주요 지수, 금리, 일정, 알림): market_brief 를 읽는다.",
            "장기 재무는 미국 종목만 있다(SEC). 한국 종목은 Yahoo 최근 분기 값만 있다.",
        ],
        "market_brief": base + "brief.json",
        "stocks": files,
    }


def write(data, fin_all, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    base = site_url(data) + "data/ai/"
    files = []
    for market, rows in data["watchlist"].items():
        for row in rows:
            t = row["ticker"]
            if t not in data["stocks"]:
                continue
            body = stock_file(data, fin_all, t)
            name = file_name(t)
            (out_dir / name).write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
            files.append({"ticker": t, "name": row["name"], "market": market, "url": base + name,
                          "has_sec_financials": body["financials"] is not None})
    names = {file_name(f["ticker"]) for f in files} | {"index.json"}
    for old in out_dir.glob("*.json"):   # 관심 종목에서 뺀 종목의 파일은 지운다
        if old.name not in names:
            old.unlink()
    (out_dir / "index.json").write_text(json.dumps(index_file(data, files), ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    return len(files)
