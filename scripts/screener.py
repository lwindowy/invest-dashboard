"""조건 스크리너용 종목 표: 나스닥 100 + 관심 종목(미국). 하루 한 번 (AI 아님).

- 종목 목록: 위키백과 'List of NASDAQ-100 companies' 표. 7일에 한 번 다시 받고, 실패하면 이전 목록을 쓴다.
- 숫자: Yahoo Finance 종목 요약(info)의 값 그대로(Yahoo 정의). 주가 수익률·52주 고점 대비·200일선은 Yahoo 일봉 1년치로 직접 계산.
- 같은 날 다시 돌면 이미 받은 종목은 그대로 두고 빠진 종목만 받는다. 실패한 종목은 이전 값을 쓰고 표시한다.
"""
import datetime as dt
import io
import re
import sys
import time

import pandas as pd
import requests
import yfinance as yf

VERSION = 1
LIST_URL = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
LIST_DAYS = 7
UA = {"User-Agent": "invest-dashboard (personal use)"}

# (키, Yahoo info 이름, 배율, 소수 자릿수)
INFO = [("market_cap", "marketCap", 1, 0), ("pe", "trailingPE", 1, 1), ("fpe", "forwardPE", 1, 1),
        ("ps", "priceToSalesTrailing12Months", 1, 1), ("peg", "trailingPegRatio", 1, 2), ("ev_ebitda", "enterpriseToEbitda", 1, 1),
        ("rev_growth", "revenueGrowth", 100, 1), ("eps_growth", "earningsGrowth", 100, 1),
        ("gross_margin", "grossMargins", 100, 1), ("op_margin", "operatingMargins", 100, 1), ("net_margin", "profitMargins", 100, 1),
        ("roe", "returnOnEquity", 100, 1), ("debt_equity", "debtToEquity", 1, 0), ("beta", "beta", 1, 2),
        ("short_float", "shortPercentOfFloat", 100, 1), ("rec", "recommendationMean", 1, 1)]


def num(v, d):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f or f in (float("inf"), float("-inf")) else round(f, d)


def universe(prev, today, warn):
    old = (prev or {}).get("universe") or {}
    if old.get("fetched") and (today - dt.date.fromisoformat(old["fetched"])).days < LIST_DAYS and old.get("tickers"):
        return old
    try:
        r = requests.get(LIST_URL, headers=UA, timeout=30)
        r.raise_for_status()
        table = next(t for t in pd.read_html(io.StringIO(r.text), flavor="lxml") if "Ticker" in t.columns)
        tickers = sorted({str(x).strip().replace(".", "-") for x in table["Ticker"] if str(x).strip()})
        if len(tickers) < 90:
            raise ValueError(f"종목이 {len(tickers)}개뿐입니다")
        asof = re.findall(r"[Aa]s of ([A-Z][a-z]+ \d+, 20\d\d)", r.text)
        return {"fetched": today.isoformat(), "tickers": tickers, "asof": asof[0] if asof else None,
                "source": "위키백과 List of NASDAQ-100 companies", "url": LIST_URL}
    except Exception as exc:
        warn("나스닥 100 종목 목록", exc)
        return old or {"tickers": [], "source": "없음"}


def price_stats(tickers):
    out = {}
    try:
        df = yf.download(tickers, period="1y", interval="1d", auto_adjust=False, progress=False, threads=False, group_by="ticker")
    except Exception as exc:
        print(f"[참고] 스크리너 일봉: {exc}", file=sys.stderr)
        return out
    for t in tickers:
        try:
            c = (df[t] if len(tickers) > 1 else df)["Close"].dropna()
        except Exception:
            continue
        if len(c) < 30:
            continue
        last = float(c.iloc[-1])
        ret = lambda n: round((last / float(c.iloc[-1 - n]) - 1) * 100, 1) if len(c) > n else None
        ma200 = float(c.tail(200).mean()) if len(c) >= 200 else None
        out[t] = {"price": round(last, 2), "asof": c.index[-1].date().isoformat(), "r1m": ret(21), "r3m": ret(63), "r1y": ret(len(c) - 1),
                  "from_high": round((last / float(c.max()) - 1) * 100, 1),
                  "vs_ma200": round((last / ma200 - 1) * 100, 1) if ma200 else None}
    return out


def build(config, prev, today, warn):
    prev = prev if (prev or {}).get("v") == VERSION else {}
    uni = universe(prev, today, warn)
    watch = [e["ticker"] for e in config["watchlist"].get("us", [])]
    tickers = sorted(set(uni.get("tickers") or []) | set(watch))
    same_day = prev.get("fetched") == today.isoformat()
    old = {r["ticker"]: r for r in prev.get("rows") or []}
    todo = [t for t in tickers if not same_day or t not in old or old[t].get("stale")]
    if not todo:
        return prev
    stats = price_stats(todo)
    rows, failed = [], 0
    for t in tickers:
        if t not in todo:
            rows.append(old[t])
            continue
        try:
            info = yf.Ticker(t).info or {}
            if not info.get("marketCap"):
                raise ValueError("시가총액 없음")
            row = {"ticker": t, "name": info.get("shortName") or info.get("longName") or t,
                   "sector": info.get("sector"), "industry": info.get("industry")}
            for key, name, mul, d in INFO:
                v = num(info.get(name), 6)
                row[key] = round(v * mul, d) if v is not None else None
            fcf, cap = num(info.get("freeCashflow"), 0), row["market_cap"]
            row["fcf_yield"] = round(fcf / cap * 100, 1) if fcf is not None and cap else None
            rate, px = num(info.get("dividendRate"), 4), num(info.get("currentPrice") or info.get("regularMarketPrice"), 4)
            row["div_yield"] = round(rate / px * 100, 2) if rate and px else 0.0 if rate == 0 or info.get("dividendRate") is None else None
            tp = num(info.get("targetMeanPrice"), 2)
            row.update(stats.get(t) or {})
            row["target_upside"] = round((tp / row["price"] - 1) * 100, 1) if tp and row.get("price") else None
            row["ndx"], row["watch"] = t in (uni.get("tickers") or []), t in watch
            rows.append(row)
        except Exception as exc:
            failed += 1
            print(f"[참고] 스크리너 {t}: {exc}", file=sys.stderr)
            if t in old:
                rows.append({**old[t], "stale": True})
        time.sleep(0.2)
    if failed > len(todo) / 3:
        warn("스크리너", f"{len(todo)}개 중 {failed}개 실패")
    return {"v": VERSION, "fetched": today.isoformat(), "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
            "universe": uni, "rows": rows, "failed": failed, "source": "Yahoo Finance",
            "note": __doc__.split("\n\n", 1)[1].strip()}
