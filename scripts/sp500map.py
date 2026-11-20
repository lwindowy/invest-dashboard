"""S&P 500 지도(산업 탭): 업종별로 묶고 시가총액만큼 크게, 등락률만큼 색을 칠할 값을 만든다 (AI 아님).

- 종목·업종: 위키백과 'List of S&P 500 companies' 표(GICS Sector, GICS Sub-Industry). 7일에 한 번 다시 받는다.
  주식 종류가 여러 개인 회사(알파벳 GOOGL·GOOG 등)는 같은 CIK라 하나만 남긴다(PREFER 순서, 없으면 표의 첫 줄).
- 시가총액 = 발행 주식 수 × 최근 종가. 주식 수는 7일에 한 번 다시 정하고, 출처 순서는
  (1) 스크리너가 받은 Yahoo 시가총액 ÷ 그때 주가(나스닥 100), (2) SEC XBRL frames의 dei:EntityCommonStockSharesOutstanding
  (최근 4개 분기 중 가장 늦은 값), (3) Yahoo 종목 요약의 시가총액 ÷ 주가(한 번에 최대 MAX_INFO개).
- 등락률: Yahoo 일봉 1년치로 1일·1주(5거래일)·1개월(21거래일)·연초 이후를 매번 계산한다.
"""
import datetime as dt
import io
import sys
import time

import pandas as pd
import requests
import yfinance as yf

VERSION = 1
LIST_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_UA = {"User-Agent": "invest-dashboard (personal use)"}
SEC_UA = {"User-Agent": "personal-dashboard-bot/1.0"}
REFRESH_DAYS = 7
MAX_INFO = 80
PREFER = ("GOOGL", "FOXA", "NWSA", "BRK-B")


def _r(x, d=1):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if f != f or f in (float("inf"), float("-inf")) else round(f, d)


def _old_enough(fetched, today):
    return not fetched or (today - dt.date.fromisoformat(fetched)).days >= REFRESH_DAYS


def universe(old, today, warn):
    if old and old.get("rows") and not _old_enough(old.get("fetched"), today):
        return old
    try:
        r = requests.get(LIST_URL, headers=WIKI_UA, timeout=30)
        r.raise_for_status()
        t = next(x for x in pd.read_html(io.StringIO(r.text), flavor="lxml") if "GICS Sector" in x.columns)
        rows, seen = [], {}
        for _, x in t.iterrows():
            sym = str(x["Symbol"]).strip().replace(".", "-")
            cik = int(x["CIK"]) if str(x.get("CIK", "")).strip().isdigit() else None
            row = {"t": sym, "n": str(x["Security"]).strip(), "s": str(x["GICS Sector"]).strip(), "i": str(x["GICS Sub-Industry"]).strip(), "cik": cik}
            if cik and cik in seen:          # 같은 회사의 다른 주식 종류
                if sym in PREFER:
                    rows[seen[cik]] = row
                continue
            if cik:
                seen[cik] = len(rows)
            rows.append(row)
        if len(rows) < 450:
            raise ValueError(f"종목이 {len(rows)}개뿐입니다")
        return {"fetched": today.isoformat(), "rows": rows, "source": "위키백과 List of S&P 500 companies", "url": LIST_URL}
    except Exception as exc:
        warn("S&P 500 종목 목록", exc)
        return old or {"rows": []}


def sec_shares(today):
    """SEC frames: 회사별 발행 주식 수(가장 최근 분기 말 근처 값). {cik: (shares, end)}"""
    out = {}
    y, q = today.year, (today.month - 1) // 3 + 1
    periods = []
    for _ in range(4):
        q -= 1
        if q == 0:
            y, q = y - 1, 4
        periods.append(f"CY{y}Q{q}I")
    for p in reversed(periods):              # 오래된 분기부터 덮어써서 가장 최근 값이 남게
        try:
            r = requests.get(f"https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/{p}.json", headers=SEC_UA, timeout=60)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            for d in r.json().get("data", []):
                if d.get("val"):
                    out[d["cik"]] = (float(d["val"]), d.get("end"))
            time.sleep(0.2)
        except Exception as exc:
            print(f"[참고] SEC frames {p}: {exc}", file=sys.stderr)
    return out


def prices(tickers):
    out = {}
    try:
        df = yf.download(tickers, period="1y", interval="1d", auto_adjust=False, progress=False, threads=True, group_by="ticker")
    except Exception as exc:
        print(f"[참고] S&P 500 지도 일봉: {exc}", file=sys.stderr)
        return out
    year_start = pd.Timestamp(dt.date.today().year, 1, 1)
    for t in tickers:
        try:
            c = df[t]["Close"].dropna()
        except Exception:
            continue
        if len(c) < 2:
            continue
        last = float(c.iloc[-1])
        ret = lambda n: _r((last / float(c.iloc[-1 - n]) - 1) * 100) if len(c) > n else None
        before = c[c.index < year_start]
        out[t] = {"price": last, "asof": c.index[-1].date().isoformat(), "d1": ret(1), "w1": ret(5), "m1": ret(21),
                  "ytd": _r((last / float(before.iloc[-1]) - 1) * 100) if len(before) else None}
    return out


def build(prev, scr, today, warn):
    prev = prev if (prev or {}).get("v") == VERSION else {}
    uni = universe(prev.get("universe"), today, warn)
    rows = uni.get("rows") or []
    if not rows:
        return prev or None
    px = prices([r["t"] for r in rows])
    shares = dict(prev.get("shares") or {})        # {티커: {"v": 주식 수, "src": 출처, "fetched": 날짜}}
    need = [r for r in rows if _old_enough((shares.get(r["t"]) or {}).get("fetched"), today)]
    if need:
        scr_rows = {x["ticker"]: x for x in (scr or {}).get("rows") or []}
        sec = sec_shares(today) if any(r["t"] not in scr_rows for r in need) else {}
        info_left = MAX_INFO
        for r in need:
            t, s = r["t"], scr_rows.get(r["t"])
            if s and s.get("market_cap") and s.get("price"):
                shares[t] = {"v": s["market_cap"] / s["price"], "src": "Yahoo 시가총액", "fetched": today.isoformat()}
            elif r.get("cik") in sec:
                shares[t] = {"v": sec[r["cik"]][0], "src": "SEC", "end": sec[r["cik"]][1], "fetched": today.isoformat()}
            elif info_left > 0:
                info_left -= 1
                try:
                    i = yf.Ticker(t).get_info()
                    cap, p = i.get("marketCap"), i.get("regularMarketPrice") or i.get("currentPrice")
                    if cap and p:
                        shares[t] = {"v": cap / p, "src": "Yahoo 시가총액", "fetched": today.isoformat()}
                    time.sleep(0.4)
                except Exception as exc:
                    print(f"[참고] S&P 500 지도 {t} 시가총액: {exc}", file=sys.stderr)
    out, missing = [], []
    for r in rows:
        p, sh = px.get(r["t"]), shares.get(r["t"])
        if not p or not sh:
            missing.append(r["t"])
            continue
        out.append([r["t"], r["n"], r["s"], r["i"], round(sh["v"] * p["price"]), p["d1"], p["w1"], p["m1"], p["ytd"]])
    if missing:
        print(f"[참고] S&P 500 지도에서 빠진 종목 {len(missing)}개: {', '.join(missing[:20])}", file=sys.stderr)
    asof = max((p["asof"] for p in px.values()), default=None)
    src_count = {}
    for t, s in shares.items():
        src_count[s["src"]] = src_count.get(s["src"], 0) + 1
    return {"v": VERSION, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "asof": asof,
            "universe": uni, "shares": shares, "fields": ["t", "n", "s", "i", "cap", "d1", "w1", "m1", "ytd"], "rows": out,
            "missing": missing, "share_sources": src_count,
            "note": "시가총액 = 발행 주식 수 × 최근 종가(주식 수는 7일에 한 번 갱신: Yahoo 시가총액 또는 SEC 공시). 주식 종류가 여러 개인 회사는 하나만."}
