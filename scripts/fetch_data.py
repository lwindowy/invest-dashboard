#!/usr/bin/env python3
"""설정(config/)을 읽어 데이터를 수집하고 site/data/dashboard.json 으로 저장한다.

원칙
- 화면은 이 파일이 만든 JSON만 읽는다.
- 한 종목·지표 수집이 실패해도 나머지는 그대로 만든다.
  실패한 항목은 이전 결과(--prev)가 있으면 그 값을 '이전 값'으로 표시한다.
- 지표 하나 = config/dashboard.json 의 series 한 줄 + 아래 SOURCES 의 수집 함수 하나.
"""
import argparse
import datetime as dt
import io
import json
import math
import re
import sys
import time
from calendar import monthrange
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

import ai_export
import briefing
import earnings
import news_ai
import profiles
import financials
import screener
import sec
import thesis

ROOT = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_PAGE = "https://fred.stlouisfed.org/series/"
COT_API = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"   # CFTC 금융선물 참가자별 포지션(TFF, 선물만)
NDX_PAGE = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
FOMC_PAGE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
SPARK_BY_FREQ = {"D": 63, "W": 104, "M": 36, "Q": 12}  # 추이 그래프에 쓰는 점 개수
SPARK_DAYS = 63   # 약 3개월
NEWS_COUNT = 8    # 종목별로 보여 줄 뉴스 수
MONTH = 21        # 거래일 기준 약 1개월

errors = []


def warn(where, exc):
    errors.append({"where": where, "message": str(exc)[:200]})
    print(f"[실패] {where}: {exc}", file=sys.stderr)


def num(x, digits=4):
    """JSON에 넣을 수 있는 숫자로 바꾼다. NaN·무한대는 None."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, digits) if math.isfinite(x) else None


def day(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def spark(series, n=SPARK_DAYS):
    return [num(v) for v in series.tail(n)]


# ───────────────────────── 원본 데이터 받기 ─────────────────────────

def fetch_yahoo(symbols):
    """심볼별 일봉(High, Low, Close) 2년치. 실패한 심볼은 결과에 없다."""
    out, last_err = {}, None
    for attempt in range(3):
        todo = [s for s in symbols if s not in out]
        if not todo:
            break
        if attempt:
            time.sleep(5 * attempt)
        try:
            df = yf.download(todo, period="2y", interval="1d", group_by="ticker",
                             auto_adjust=False, progress=False, threads=False)
        except Exception as exc:  # 네트워크·차단 등
            last_err = exc
            continue
        for s in todo:
            try:
                bars = df[s][["High", "Low", "Close"]].dropna(subset=["Close"])
            except KeyError:
                continue
            if len(bars) >= 2:
                out[s] = bars
    for s in symbols:
        if s not in out:
            warn(f"Yahoo {s}", last_err or "데이터 없음")
    return out


def fetch_fred(series_id):
    """FRED 시계열(약 5년치). 키 없이 받는 공개 CSV."""
    start = (dt.date.today() - dt.timedelta(days=1900)).isoformat()
    last_err = None
    for attempt in range(3):
        if attempt:
            time.sleep(3 * attempt)
        try:
            r = requests.get(FRED_CSV, params={"id": series_id, "cosd": start}, timeout=40)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
            s.index = pd.to_datetime(df.iloc[:, 0])
            s = s.dropna()
            if len(s) >= 2:
                return s
            last_err = "데이터 없음"
        except Exception as exc:
            last_err = exc
    warn(f"FRED {series_id}", last_err)
    return None


# ───────────────────────── 계산 ─────────────────────────

def rsi(close, n=14):
    """RSI(Wilder 방식, 첫 평균은 단순평균). 트레이딩뷰 기본 RSI와 같은 계산."""
    diffs = close.diff().dropna().tolist()
    if len(diffs) < n:
        return None
    gains = [max(d, 0.0) for d in diffs]
    losses = [max(-d, 0.0) for d in diffs]
    avg_gain, avg_loss = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        avg_gain = (avg_gain * (n - 1) + g) / n
        avg_loss = (avg_loss * (n - 1) + l) / n
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def month_change(series):
    """약 1개월(21거래일) 전 대비 (차이, 변화율%)."""
    if len(series) <= MONTH:
        raise ValueError("이력이 1개월 미만")
    now, then = float(series.iloc[-1]), float(series.iloc[-1 - MONTH])
    return now - then, (now / then - 1) * 100


def signed(x, digits=1, unit=""):
    sign = "+" if x > 0 else "−" if x < 0 else ""
    return f"{sign}{abs(x):.{digits}f}{unit}"


# ───────────────────────── 지표(series) 수집 함수 ─────────────────────────

def src_yahoo(cfg, ctx):
    close = ctx["yahoo"][cfg["symbol"]]["Close"]
    last, prev = float(close.iloc[-1]), float(close.iloc[-2])
    item = {"value": num(last), "prev": num(prev), "diff": num(last - prev),
            "change_pct": num((last / prev - 1) * 100, 2), "asof": day(close.index[-1]),
            "spark": spark(close), "source": "Yahoo Finance", "_history": close}
    if cfg.get("note") == "ma200" and len(close) >= 200:
        above = last >= float(close.tail(200).mean())
        item["note"] = "200일선 위" if above else "200일선 아래"
        item["note_level"] = "good" if above else "warn"
    elif cfg.get("note") == "vix":
        for limit, label, level in [(15, "안정 구간 (15 미만)", "good"), (20, "평온 구간 (15~20)", "good"),
                                    (30, "주의 구간 (20~30)", "warn"), (math.inf, "위험 구간 (30 이상)", "bad")]:
            if last < limit:
                item["note"], item["note_level"] = label, level
                break
    return item


def period_label(ts, freq):
    ts = pd.Timestamp(ts)
    if freq == "M":
        return f"{ts.year}년 {ts.month}월"
    if freq == "Q":
        return f"{ts.year}년 {(ts.month - 1) // 3 + 1}분기"
    if freq == "W":
        return f"{ts.month}/{ts.day} 주"
    return None


def next_release(series_id, old, today):
    """FRED 지표 페이지의 'Next Release Date'. 아직 지나지 않은 이전 결과가 있으면 다시 받지 않는다."""
    if old and (old.get("next_release") or "") >= today.isoformat():
        return old["next_release"]
    try:
        r = requests.get(FRED_PAGE + series_id, timeout=30)
        r.raise_for_status()
        m = re.search(r"Next Release Date:\s*(?:<[^>]+>\s*)*([A-Z][a-z]{2} \d{1,2}, \d{4})", r.text)
        return dt.datetime.strptime(m.group(1), "%b %d, %Y").date().isoformat() if m else None
    except Exception as exc:
        print(f"[참고] 다음 발표일 {series_id}: {exc}", file=sys.stderr)
        return None


def src_fred(cfg, ctx):
    """FRED 지표. transform 으로 전년 대비(yoy), 전월 대비 %(mom_pct), 전월 대비 증감(mom_diff)을 계산한다."""
    s = ctx["fred"][cfg["id"]]
    freq, t = cfg.get("freq", "D"), cfg.get("transform")
    raw_date = s.index[-1]
    estimated = False
    if t == "yoy":      # 정확히 1년 전 값과 비교한다. 빠진 달(예: 2025년 10월 CPI)은 앞뒤 달로 추정한다
        estimated = (s.index[-1] - pd.DateOffset(years=1)) not in s.index
        filled = s.asfreq("MS").interpolate()
        ago = filled.reindex(s.index - pd.DateOffset(years=1))
        s = (s / ago.values - 1) * 100
    elif t == "mom_pct":
        s = (s / s.shift(1) - 1) * 100
    elif t == "mom_diff":
        s = s.diff()
    s = (s * cfg.get("scale", 1)).dropna()
    if s.index[-1] != raw_date:
        raise ValueError("최신 값의 비교 대상이 없습니다")
    last, prev = float(s.iloc[-1]), float(s.iloc[-2])
    item = {"value": num(last), "prev": num(prev), "diff": num(last - prev),
            "change_pct": num((last / prev - 1) * 100, 2) if prev else None,
            "asof": day(s.index[-1]), "period": period_label(s.index[-1], freq),
            "spark": spark(s, SPARK_BY_FREQ[freq]), "source": "FRED", "_history": s}
    if estimated:
        item["note"] = "1년 전 값이 발표되지 않아 앞뒤 달로 추정해 계산"
    if freq != "D":
        old =(ctx["prev"] or {}).get("series", {}).get(cfg["_key"])
        item["next_release"] = next_release(cfg["id"], old, ctx["today"])
    return item


def src_manual(cfg, ctx):
    """config/manual.json 에 직접 적는 값. 입력한 날짜를 함께 보여준다."""
    v = ctx["manual"].get("values", {}).get(cfg["key"]) or {}
    if v.get("value") is None:
        return {"value": None, "error": True, "error_note": "값을 아직 입력하지 않았습니다"}
    return {"value": num(v["value"]), "prev": num(v.get("prev")),
            "diff": num(v["value"] - v["prev"]) if v.get("prev") is not None else None,
            "change_pct": None, "asof": v.get("entered"), "spark": [], "source": "직접 입력", "note": v.get("note")}


def build_curve(ctx):
    """수익률 곡선: 현재, 약 1개월 전, 약 1년 전."""
    points = ctx["config"]["curve"]["points"]
    table = pd.DataFrame({label: ctx["fred"][sid] for label, sid in points}).dropna()
    def row(i):
        return {"date": day(table.index[i]), "values": [num(v, 2) for v in table.iloc[i]]}
    return {"labels": [p[0] for p in points], "now": row(-1), "month": row(-1 - MONTH), "year": row(-253),
            "source": "FRED"}


ZQ_CODES = "FGHJKMNQUVXZ"


def fedwatch_chain(avg, meetings):
    """월별 평균 기대 금리(avg[(연, 월)])로 회의마다 회의 전·후 기대 금리를 구한다.

    회의 사이에는 금리가 그대로라고 보고(결정 다음 날부터 새 금리), 각 월물의 한 달 평균이
    그 달에 적용되는 금리들의 날수 가중 평균과 같도록 모든 월물을 한꺼번에 맞춘다(최소제곱).
    CME FedWatch처럼 한 달씩 이어 풀면 월말 회의에서 오차가 몇 배로 커져서 이렇게 한다.
    """
    keys = sorted(avg)
    if not keys or not meetings:
        return []
    starts = [None] + [m + dt.timedelta(days=1) for m in meetings]   # 구간 i 의 금리가 시작되는 날
    rows, rhs = [], []
    for y, mo in keys:
        n = monthrange(y, mo)[1]
        w = [0.0] * len(starts)
        for dd in range(1, n + 1):
            day_ = dt.date(y, mo, dd)
            i = sum(1 for s in starts[1:] if s <= day_)
            w[i] += 1 / n
        rows.append(w)
        rhs.append(avg[(y, mo)])
    A, bvec = np.array(rows), np.array(rhs)
    used = A.sum(axis=0) > 0
    if not used[0]:
        return []
    k = int(np.argmin(used)) if not used.all() else len(starts)   # 데이터가 닿는 구간까지만
    sol = np.linalg.lstsq(A[:, :k], bvec, rcond=None)[0]
    return [{"date": meetings[i].isoformat(), "pre": float(sol[i]), "post": float(sol[i + 1])} for i in range(k - 1)]


def step_probs(change, step):
    """기대 변화 폭을 이웃한 두 결과(step 단위)의 확률로 나눈다. {변화 단계 수: 확률(%)}"""
    k = change / step
    lo = math.floor(k + 1e-9)
    frac = min(max(k - lo, 0.0), 1.0)
    probs = {lo: round((1 - frac) * 100, 1), lo + 1: round(frac * 100, 1)}
    return {s: p for s, p in probs.items() if p >= 0.5}


def build_fedwatch(ctx):
    """연방기금금리 선물(Yahoo, ZQ 월물)로 FOMC 회의별 금리 인하·동결·인상 확률을 계산한다."""
    cfg, today = ctx["config"]["fedwatch"], ctx["today"]
    step = cfg["step"]
    meetings = [dt.date.fromisoformat(m["date"]) for m in ctx["fomc"]["meetings"]]
    horizon = today + dt.timedelta(days=cfg["horizon_days"])
    meetings = [m for m in meetings if today <= m <= horizon]
    if not meetings:
        raise ValueError("앞으로의 FOMC 일정이 없습니다")
    keys, cur = [], (today.year, today.month)
    while cur <= (meetings[-1].year + meetings[-1].month // 12, meetings[-1].month % 12 + 1):
        keys.append(cur)
        cur = (cur[0] + cur[1] // 12, cur[1] % 12 + 1)
    symbols = {f"ZQ{ZQ_CODES[m - 1]}{y % 100:02d}.CBT": (y, m) for y, m in keys}
    df = yf.download(list(symbols), period="3mo", interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=False)
    closes = {}
    for sym, key in symbols.items():
        try:
            c = df[sym]["Close"].dropna()
        except KeyError:
            continue
        if len(c):
            closes[key] = c
    if len(closes) < 2:
        raise ValueError("연방기금금리 선물 가격을 받지 못했습니다")
    asof = max(c.index[-1] for c in closes.values())

    lo_s, hi_s = ctx["fred"].get(cfg["fred_range"][0]), ctx["fred"].get(cfg["fred_range"][1])
    if lo_s is None or hi_s is None:
        raise ValueError("현재 기준금리 범위를 받지 못했습니다")
    rng = [float(lo_s.iloc[-1]), float(hi_s.iloc[-1])]

    def chain_at(when):
        avg = {k: 100 - float(c[c.index <= when].iloc[-1]) for k, c in closes.items() if (c.index <= when).any()}
        return fedwatch_chain(avg, meetings)

    def summary(chain):
        if not chain:
            return None
        base = chain[0]["pre"]
        nxt = step_probs(chain[0]["post"] - chain[0]["pre"], step)
        year_end = [c for c in chain if c["date"][:4] == chain[0]["date"][:4]] or chain[:1]
        last_this_year = year_end[-1]
        return {"next_cut": round(sum(p for s, p in nxt.items() if s < 0), 1),
                "next_hold": round(nxt.get(0, 0.0), 1),
                "next_hike": round(sum(p for s, p in nxt.items() if s > 0), 1),
                "total_bp": round((chain[-1]["post"] - base) * 100, 1),
                "year_end_bp": round((last_this_year["post"] - base) * 100, 1)}

    chain = chain_at(asof)
    if not chain:
        raise ValueError("회의별 기대 금리를 계산하지 못했습니다")
    base = chain[0]["pre"]
    rows = []
    for c in chain:
        cum = step_probs(c["post"] - base, step)
        this = step_probs(c["post"] - c["pre"], step)
        rows.append({
            "date": c["date"],
            "sep": next((m.get("sep", False) for m in ctx["fomc"]["meetings"] if m["date"] == c["date"]), False),
            "implied": round(c["post"], 3),
            "change_bp": round((c["post"] - c["pre"]) * 100, 1),
            "cum_bp": round((c["post"] - base) * 100, 1),
            "cut": round(sum(p for s, p in this.items() if s < 0), 1),
            "hold": round(this.get(0, 0.0), 1),
            "hike": round(sum(p for s, p in this.items() if s > 0), 1),
            "ranges": [{"lo": round(rng[0] + s * step, 2), "hi": round(rng[1] + s * step, 2), "steps": s, "prob": p}
                       for s, p in sorted(cum.items())],
        })
    trading = sorted({d for c in closes.values() for d in c.index if d <= asof})
    compare = {}
    for label, back in (("week", 5), ("month", MONTH)):
        if len(trading) > back:
            when = trading[-1 - back]
            compare[label] = {"date": day(when), **(summary(chain_at(when)) or {})}
    return {"asof": day(asof), "fetched": today.isoformat(), "range": rng, "base": round(base, 3), "step_bp": round(step * 100),
            "meetings": rows, "now": summary(chain), "compare": compare,
            "source": "Yahoo Finance (CBOT 연방기금금리 선물) · FRED (목표 범위) · 자체 계산"}


def src_sentiment(cfg, ctx):
    """CNN Fear & Greed 대신 쓰는 자체 계산 심리 지수(0~100).

    구성 요소마다 '최근 1년 중 오늘이 몇 번째로 높은지(백분위)'를 구해 평균한다.
    CNN은 자동 수집을 차단하므로 공개 가격 데이터로 같은 취지의 값을 만든다.
    """
    c, y = ctx["config"]["sentiment"], ctx["yahoo"]
    idx, vix = y[c["index"]]["Close"], y[c["vix"]]["Close"]
    stock, bond, eq = y[c["stock"]]["Close"], y[c["bond"]]["Close"], y[c["equal_weight"]]["Close"]
    parts = {
        "모멘텀 (S&P 500 ÷ 125일선)": idx / idx.rolling(125).mean(),
        "변동성 (VIX ÷ 50일선, 낮을수록 탐욕)": -(vix / vix.rolling(50).mean()),
        "안전자산 수요 (주식 − 국채 20일 수익률)": stock.pct_change(20) - bond.pct_change(20),
        "시장 폭 (동일가중 − 시총가중 20일 수익률)": eq.pct_change(20) - stock.pct_change(20),
    }
    hy = ctx["fred"].get(c["fred_hy"])
    if hy is not None:
        parts["정크본드 수요 (하이일드 스프레드, 낮을수록 탐욕)"] = -hy.reindex(idx.index, method="ffill")
    ranks = pd.DataFrame({k: v.rolling(252).rank(pct=True) for k, v in parts.items()})
    score = (ranks.mean(axis=1) * 100).dropna()
    last, prev = float(score.iloc[-1]), float(score.iloc[-2])
    for limit, label in [(25, "극단적 공포 (0~25)"), (45, "공포 (25~45)"), (55, "중립 (45~55)"),
                         (75, "탐욕 (55~75)"), (math.inf, "극단적 탐욕 (75~100)")]:
        if last < limit:
            note = label
            break
    latest = ranks.loc[score.index[-1]]
    return {"value": num(last, 0), "prev": num(prev, 0), "diff": num(round(last) - round(prev), 0),
            "change_pct": None, "asof": day(score.index[-1]), "spark": [num(v, 1) for v in score.tail(SPARK_DAYS)],
            "source": "자체 계산 (Yahoo Finance·FRED)", "note": note, "_history": score,
            "components": [{"name": k, "score": num(v * 100, 0)} for k, v in latest.items() if pd.notna(v)]}


def nasdaq100_tickers():
    """위키백과의 나스닥 100 구성 종목 표에서 티커를 읽는다."""
    r = requests.get(NDX_PAGE, timeout=40, headers={"User-Agent": "invest-dashboard/1.0 (personal use)"})
    r.raise_for_status()
    for table in re.findall(r"<table[^>]*wikitable.*?</table>", r.text, re.S):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)
        if not rows or not re.sub(r"<[^>]+>|\s", "", rows[0]).startswith("Ticker"):
            continue
        cells = [re.search(r"<td[^>]*>(.*?)</td>", row, re.S) for row in rows[1:]]
        tickers = [re.sub(r"<[^>]+>", "", c.group(1)).strip() for c in cells if c]
        tickers = [t.replace(".", "-") for t in tickers if re.fullmatch(r"[A-Z.]{1,6}", t)]
        if len(tickers) >= 90:
            return tickers
    raise ValueError("나스닥 100 구성 종목 표를 찾지 못했습니다")


def build_valuation(ctx):
    """종목 묶음의 포워드 PER = 시가총액 합 ÷ 예상 순이익 합. 하루 한 번 계산하고 매일 값을 쌓는다.

    종목별 예상 순이익은 시가총액 ÷ 포워드 PER 로 구한다(적자 예상 종목은 음수로 합산).
    """
    today, old = ctx["today"].isoformat(), (ctx["prev"] or {}).get("valuation") or {}
    if old.get("fetched") == today:
        return old
    history = {k: list(v) for k, v in (old.get("history") or {}).items()}
    try:
        members = {}
        for b in ctx["config"]["valuation"]["baskets"]:
            try:
                members[b["id"]] = nasdaq100_tickers() if b.get("source") == "wikipedia_nasdaq100" else b["tickers"]
            except Exception as exc:
                warn(f"밸류에이션 {b['name']} 구성 종목", exc)
                members[b["id"]] = (old.get("baskets") or {}).get(b["id"], {}).get("tickers") or []
        fx = float(ctx["yahoo"][ctx["config"]["fx_symbol"]]["Close"].iloc[-1])
        infos = {}
        for t in sorted({t for ts in members.values() for t in ts}):
            try:
                info = yf.Ticker(t).info or {}
                cap = info.get("marketCap")
                if cap:
                    infos[t] = (cap / fx if info.get("currency") == "KRW" else cap, info.get("forwardPE"))
            except Exception as exc:
                print(f"[참고] 밸류에이션 {t}: {exc}", file=sys.stderr)
            time.sleep(0.15)
        baskets = {}
        for b in ctx["config"]["valuation"]["baskets"]:
            tickers = members[b["id"]]
            known = [infos[t] for t in tickers if t in infos]
            used = [(cap, pe) for cap, pe in known if pe]
            cap_all, cap_used = sum(c for c, _ in known), sum(c for c, _ in used)
            earnings = sum(c / pe for c, pe in used)
            coverage = cap_used / cap_all if cap_all else 0
            value = cap_used / earnings if earnings > 0 and coverage >= 0.8 else None
            baskets[b["id"]] = {"name": b["name"], "value": num(value, 2), "used": len(used), "total": len(tickers),
                                "coverage_pct": num(coverage * 100, 0), "tickers": tickers}
            if value is not None:
                rows = [h for h in history.get(b["id"], []) if h[0] != today] + [[today, num(value, 2)]]
                history[b["id"]] = rows[-2000:]
            else:
                warn(f"밸류에이션 {b['name']}", f"계산 불가 (반영 {len(used)}/{len(tickers)}개)")
        return {"fetched": today, "baskets": baskets, "history": history, "source": "자체 계산 (Yahoo Finance)"}
    except Exception as exc:
        warn("밸류에이션", exc)
        return old


def src_valuation(cfg, ctx):
    v = ctx["valuation"]
    b = v["baskets"][cfg["basket"]]
    if b.get("value") is None:
        raise ValueError("계산된 값이 없습니다")
    hist = pd.Series({pd.Timestamp(d): x for d, x in v["history"].get(cfg["basket"], [])}, dtype=float)
    prev = float(hist.iloc[-2]) if len(hist) > 1 else None
    notes = [f"{b['total']}개 중 {b['used']}개 반영"]
    base = ctx["manual"].get("values", {}).get(cfg.get("baseline") or "", {})
    if base.get("value"):
        gap = (b["value"] / base["value"] - 1) * 100
        notes.insert(0, f"5년 평균 {base['value']:g}배 대비 {signed(gap, 0, '%')}")
    return {"value": b["value"], "prev": num(prev), "diff": num(b["value"] - prev, 2) if prev is not None else None,
            "change_pct": None, "asof": v["fetched"], "spark": [num(x) for x in hist.tail(SPARK_DAYS)],
            "source": v["source"], "note": " · ".join(notes), "_history": hist}


def src_cot(cfg, ctx):
    """COT: 지수 선물에서 Leveraged Funds(헤지펀드·CTA)의 순포지션 = 롱 − 숏. 매주 금요일 발표, 화요일 기준."""
    r = requests.get(COT_API, timeout=40, params={
        "$select": "report_date_as_yyyy_mm_dd,lev_money_positions_long,lev_money_positions_short,open_interest_all",
        "$where": f"cftc_contract_market_code='{cfg['code']}'", "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 160})
    r.raise_for_status()
    rows = r.json()
    if len(rows) < 10:
        raise ValueError("COT 데이터가 부족합니다")
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["report_date_as_yyyy_mm_dd"])
    df = df.sort_index()
    net = (pd.to_numeric(df["lev_money_positions_long"]) - pd.to_numeric(df["lev_money_positions_short"])) / 1000   # 천 계약
    last, prev = float(net.iloc[-1]), float(net.iloc[-2])
    rank = float((net <= last).mean() * 100)      # 최근 약 3년 중 지금이 아래에서 몇 %인지
    share = last * 1000 / float(df["open_interest_all"].iloc[-1]) * 100
    side = "숏 쏠림이 큰 편" if rank <= 15 else "롱 쪽으로 기운 편" if rank >= 85 else "보통 범위"
    return {"value": num(last, 1), "prev": num(prev, 1), "diff": num(last - prev, 1), "change_pct": None,
            "asof": day(net.index[-1]), "period": f"{net.index[-1].month}/{net.index[-1].day} 화요일 기준",
            "spark": spark(net, 104), "source": "CFTC",
            "note": f"최근 3년 중 {'하위 ' + format(rank, '.0f') if rank <= 50 else '상위 ' + format(100 - rank, '.0f')}% ({side}) · 미결제약정의 {signed(share, 1, '%')}",
            "_history": net}


def src_cta(cfg, ctx):
    """CTA(추세추종 펀드) 포지션 추정치, −100(전부 숏)~+100(전부 롱). 실제 신고 데이터가 아니라 가격으로 계산한 값이다.

    공개된 추세추종 규칙을 단순화: 여러 기간(1·3·6·12개월)의 수익률을 변동성으로 나눠 방향과 강도를 구하고 평균한다.
    """
    close = ctx["yahoo"][cfg["symbol"]]["Close"]
    vol = close.pct_change().rolling(60).std()
    parts = [(close.pct_change(k) / (vol * math.sqrt(k))).clip(-4, 4).apply(math.tanh) for k in (21, 63, 126, 252)]
    score = (pd.concat(parts, axis=1).mean(axis=1, skipna=False) * 100).dropna()
    last, prev = float(score.iloc[-1]), float(score.iloc[-2])
    side = "롱 쪽 추정" if last >= 30 else "숏 쪽 추정" if last <= -30 else "중립 부근 추정"
    return {"value": num(last, 0), "prev": num(prev, 0), "diff": num(round(last) - round(prev), 0), "change_pct": None,
            "asof": day(score.index[-1]), "spark": [num(v, 1) for v in score.tail(SPARK_DAYS)],
            "source": "자체 추정 (Yahoo Finance 선물 가격)", "note": side, "_history": score}


def src_relmom(cfg, ctx):
    """묶음(예: 기술·통신 섹터 ETF)의 기준 지수 대비 초과 수익률(%p). TMT 모멘텀 지수의 대체 지표."""
    y, days = ctx["yahoo"], cfg.get("days", 63)
    basket = pd.concat([y[t]["Close"].pct_change(days) for t in cfg["symbols"]], axis=1).mean(axis=1, skipna=False)
    rel = ((basket - y[cfg["benchmark"]]["Close"].pct_change(days)) * 100).dropna()
    last, prev = float(rel.iloc[-1]), float(rel.iloc[-2])
    return {"value": num(last, 1), "prev": num(prev, 1), "diff": num(last - prev, 1), "change_pct": None,
            "asof": day(rel.index[-1]), "spark": spark(rel), "source": "자체 계산 (Yahoo Finance)",
            "note": "기술주가 시장보다 강함" if last > 0 else "기술주가 시장보다 약함", "_history": rel}


def src_ratio(cfg, ctx):
    """두 종목의 가격 비율(예: QQQ ÷ SPY). 오르면 앞의 것이 상대적으로 강하다."""
    a, b = (ctx["yahoo"][t]["Close"] for t in cfg["symbols"])
    ratio = (a / b).dropna()
    last, prev = float(ratio.iloc[-1]), float(ratio.iloc[-2])
    month = (last / float(ratio.iloc[-1 - MONTH]) - 1) * 100
    return {"value": num(last, 4), "prev": num(prev, 4), "diff": num(last - prev, 4), "change_pct": num((last / prev - 1) * 100, 2),
            "asof": day(ratio.index[-1]), "spark": spark(ratio), "source": "자체 계산 (Yahoo Finance)",
            "note": f"한 달 {signed(month, 1, '%')}", "_history": ratio}


def src_liquidity(cfg, ctx):
    """순유동성 = 연준 총자산 − 역레포 잔고 − 재무부 현금(TGA). 시장에 풀려 있는 돈의 대략적인 크기(조 달러)."""
    f = ctx["fred"]
    assets = f["WALCL"]                                              # 백만 달러, 주간
    rrp = f["RRPONTSYD"].reindex(assets.index, method="ffill") * 1000   # 십억 → 백만 달러
    tga = f["WTREGEN"].reindex(assets.index, method="ffill")
    net = ((assets - rrp - tga) / 1e6).dropna()
    last, prev = float(net.iloc[-1]), float(net.iloc[-2])
    month = last - float(net.iloc[-5])
    return {"value": num(last, 3), "prev": num(prev, 3), "diff": num(last - prev, 3), "change_pct": num((last / prev - 1) * 100, 2),
            "asof": day(net.index[-1]), "period": f"{net.index[-1].month}/{net.index[-1].day} 주",
            "spark": spark(net, 104), "source": "자체 계산 (FRED)", "note": f"4주 전 대비 {signed(month, 2, '조 달러')}", "_history": net}


def compact_history(s):
    """차트용 이력. 최근 1년은 그대로, 그 이전은 주 단위로 줄여 파일 크기를 줄인다."""
    s = s.dropna()
    if len(s) > 400:
        s = pd.concat([s.iloc[:-260].resample("W").last().dropna(), s.iloc[-260:]])
        s = s[~s.index.duplicated(keep="last")].sort_index()
    return {"dates": [day(d) for d in s.index], "values": [num(v) for v in s]}


SOURCES = {"cot": src_cot, "cta": src_cta, "relmom": src_relmom, "ratio": src_ratio, "liquidity": src_liquidity,
           "valuation": src_valuation, "yahoo": src_yahoo, "fred": src_fred, "sentiment": src_sentiment, "manual": src_manual}


# ───────────────────────── 관심 종목 ─────────────────────────

def stock_row(entry, market, ctx):
    bars = ctx["yahoo"][entry["ticker"]]
    close = bars["Close"]
    last, prev = float(close.iloc[-1]), float(close.iloc[-2])
    high52 = float(bars["High"].tail(252).max())
    return {"ticker": entry["ticker"], "name": entry["name"], "market": market,
            "currency": "KRW" if market == "kr" else "USD",
            "price": num(last), "change_pct": num((last / prev - 1) * 100, 2),
            "w1_pct": num((last / float(close.iloc[-6]) - 1) * 100, 2) if len(close) > 6 else None,     # 5거래일 전 대비
            "m1_pct": num((last / float(close.iloc[-22]) - 1) * 100, 2) if len(close) > 22 else None,   # 21거래일 전 대비
            "rsi": num(rsi(close), 1), "from_high_pct": num((last / high52 - 1) * 100, 1),
            "history_days": len(close), "asof": day(close.index[-1]), "spark": spark(close),
            "source": "Yahoo Finance"}


# ───────────────────────── 종목 한 장 요약 ─────────────────────────

MA_DAYS = [5, 20, 60, 120, 200]
CHART_DAYS = 126   # 상대 강도 차트에 쓰는 기간(약 6개월)


def cci(bars, n=20):
    """CCI(20). 대표가격 = (고가+저가+종가)/3, 트레이딩뷰 기본과 같은 계산."""
    tp = ((bars["High"] + bars["Low"] + bars["Close"]) / 3).dropna()
    if len(tp) < n:
        return None
    window = tp.tail(n)
    mean_dev = (window - window.mean()).abs().mean()
    return float((tp.iloc[-1] - window.mean()) / (0.015 * mean_dev)) if mean_dev else 0.0


def crossed(a, b, days):
    """최근 days 거래일 안에 a가 b를 위로(+1) 또는 아래로(-1) 뚫었는지. 없으면 0."""
    above = (a > b)[(a.notna() & b.notna())].tail(days + 1).tolist()
    for prev, cur in reversed(list(zip(above, above[1:]))):
        if prev != cur:
            return 1 if cur else -1
    return 0


def chart_checklist(close, rules):
    """노션 「차트 분석」의 기준을 자동 점검한다. 이력이 모자란 항목은 hit=None(확인 불가)."""
    ma = {n: close.rolling(n).mean() for n in MA_DAYS}
    last = float(close.iloc[-1])
    now = {n: (float(ma[n].iloc[-1]) if pd.notna(ma[n].iloc[-1]) else None) for n in MA_DAYS}
    recent, near, far = rules["recent_days"], rules["near_ma20_pct"], rules["far_ma20_pct"]
    have = lambda *ns: all(now[n] is not None for n in ns)
    gap20 = (last / now[20] - 1) * 100 if have(20) else None
    cross = crossed(ma[20], ma[60], recent) if have(60) else None
    cross200 = crossed(close, ma[200], recent) if have(200) else None

    def item(text, hit, detail):
        return {"text": text, "hit": hit, "detail": detail}
    stack = [f"{n}일선" for n in (5, 20, 60, 120)]
    buy = [
        item("정배열 (5 > 20 > 60 > 120일선)", now[5] > now[20] > now[60] > now[120] if have(5, 20, 60, 120) else None,
             "단기 이평선이 위, 장기 이평선이 아래로 차례대로 놓인 상태"),
        item(f"골든크로스 (최근 {recent}거래일 안에 20일선이 60일선을 상향 돌파)", cross == 1 if cross is not None else None,
             "지금 20일선이 60일선 " + ("위" if now[20] > now[60] else "아래") if have(60) else "이력 부족"),
        item(f"200일선 상향 돌파 (최근 {recent}거래일)", cross200 == 1 if cross200 is not None else None,
             f"주가가 200일선 대비 {signed((last / now[200] - 1) * 100, 1, '%')}" if have(200) else "상장 후 200거래일이 안 됨"),
    ]
    wait = [
        item(f"20일선 근처에서 횡보 (간격 ±{near:g}% 이내)", abs(gap20) <= near if gap20 is not None else None,
             f"20일선 대비 {signed(gap20, 1, '%')}" if gap20 is not None else "이력 부족"),
        item(f"20일선과 간격이 지나치게 벌어짐 (±{far:g}% 초과)", abs(gap20) > far if gap20 is not None else None,
             "지나치게 벌어지면 되돌아올 가능성이 높음"),
        item("단기 이평선만 돌파 (5·20일선 위, 200일선 아래)", last > now[5] and last > now[20] and last < now[200] if have(200) else None,
             "장기 추세를 돌파해야 매수세가 강해짐" if have(200) else "상장 후 200거래일이 안 됨"),
    ]
    sell = [
        item(f"데드크로스 (최근 {recent}거래일 안에 20일선이 60일선을 하향 돌파)", cross == -1 if cross is not None else None,
             "지금 20일선이 60일선 " + ("위" if now[20] > now[60] else "아래") if have(60) else "이력 부족"),
        item("200일선 아래", last < now[200] if have(200) else None,
             (f"최근 {recent}거래일 안에 하향 이탈" if cross200 == -1 else f"200일선 대비 {signed((last / now[200] - 1) * 100, 1, '%')}") if have(200) else "상장 후 200거래일이 안 됨"),
        item("역배열 (5 < 20 < 60 < 120일선)", now[5] < now[20] < now[60] < now[120] if have(5, 20, 60, 120) else None,
             "정배열의 반대. 단기 이평선이 아래에 놓인 상태"),
    ]
    mas = [{"days": n, "value": num(now[n]), "gap_pct": num((last / now[n] - 1) * 100, 1) if now[n] else None} for n in MA_DAYS]
    groups = [{"title": "사야 할 때", "tone": "good", "items": buy},
              {"title": "기다려야 할 때", "tone": "warn", "items": wait},
              {"title": "팔아야 할 때 (최소한 매수는 하지 말자)", "tone": "bad", "items": sell}]
    return mas, groups


def period_returns(close, fx):
    """기간 수익률(%). fx(원/달러)가 있으면 원화 환산 수익률도 함께 계산한다."""
    krw = close * fx.reindex(close.index, method="ffill") if fx is not None else None
    out = []
    for label, days in [("1개월", 21), ("3개월", 63), ("6개월", 126), ("1년", 252)]:
        if len(close) <= days:
            out.append({"label": label, "local": None, "krw": None})
            continue
        row = {"label": label, "local": num((close.iloc[-1] / close.iloc[-1 - days] - 1) * 100, 1), "krw": None}
        if krw is not None and pd.notna(krw.iloc[-1]) and pd.notna(krw.iloc[-1 - days]):
            row["krw"] = num((krw.iloc[-1] / krw.iloc[-1 - days] - 1) * 100, 1)
        out.append(row)
    return out


def fundamentals(ticker, old, today):
    """재무 요약·실적·목표주가·공매도. 하루 한 번만 받는다(같은 날에는 이전 결과를 다시 쓴다)."""
    if old and old.get("fetched") == today.isoformat() and "debt_metrics" in old \
            and (old.get("earnings") or {}).get("v") == earnings.VERSION:
        return old
    tk = yf.Ticker(ticker)
    info = tk.info or {}
    if not info.get("marketCap"):
        raise ValueError("재무 요약을 받지 못했습니다")
    g = lambda k, d=4: num(info.get(k), d)
    cash, debt = g("totalCash", 0), g("totalDebt", 0)
    short_date = info.get("dateShortInterest")
    fund = {
        "fetched": today.isoformat(), "source": "Yahoo Finance",
        "currency": info.get("financialCurrency") or info.get("currency"),
        "long_name": info.get("longName"), "sector": info.get("sector"), "industry": info.get("industry"),
        "website": info.get("website"),
        "market_cap": g("marketCap", 0), "cash": cash, "debt": debt,
        "net_cash": cash - debt if cash is not None and debt is not None else None,
        "per": g("trailingPE", 2), "forward_per": g("forwardPE", 2), "psr": g("priceToSalesTrailing12Months", 2),
        "peg": num(info.get("trailingPegRatio") or info.get("pegRatio"), 2),
        "eps": g("trailingEps", 2), "forward_eps": g("forwardEps", 2),
        "roe_pct": num(info["returnOnEquity"] * 100, 1) if info.get("returnOnEquity") is not None else None,
        "revenue_growth_pct": num(info["revenueGrowth"] * 100, 1) if info.get("revenueGrowth") is not None else None,
        "target": {"mean": g("targetMeanPrice", 2), "high": g("targetHighPrice", 2), "low": g("targetLowPrice", 2),
                   "analysts": info.get("numberOfAnalystOpinions")},
        "short": {"float_pct": num(info["shortPercentOfFloat"] * 100, 1) if info.get("shortPercentOfFloat") is not None else None,
                  "ratio": g("shortRatio", 2), "shares": g("sharesShort", 0),
                  "date": day(pd.Timestamp(short_date, unit="s")) if short_date else None},
        "quarters": [], "earnings": {}, "debt_metrics": {},
    }
    try:  # 부채 지표: 개별 회사채 가격·CDS 대신 재무제표로 보는 신용 위험
        inc, bal = tk.quarterly_income_stmt, tk.quarterly_balance_sheet
        cols = sorted(inc.columns)[-4:]

        def ttm(name):   # 최근 4개 분기 합계. 한 분기라도 비면 계산하지 않는다
            vals = [inc.loc[name, c] for c in cols] if name in inc.index else []
            return float(sum(vals)) if len(vals) == 4 and all(pd.notna(v) for v in vals) else None
        ebit, interest, ebitda = ttm("EBIT"), ttm("Interest Expense"), info.get("ebitda")
        latest = sorted(bal.columns)[-1]
        short_debt = next((float(bal.loc[n, latest]) for n in ("Current Debt And Capital Lease Obligation", "Current Debt")
                           if n in bal.index and pd.notna(bal.loc[n, latest])), None)
        fund["debt_metrics"] = {
            "debt_to_equity_pct": g("debtToEquity", 1), "current_ratio": g("currentRatio", 2),
            "net_debt_to_ebitda": num((debt - cash) / ebitda, 2) if ebitda and ebitda > 0 and debt is not None and cash is not None else None,
            "ebitda": num(ebitda, 0), "ebit_ttm": num(ebit, 0), "interest_ttm": num(interest, 0),
            "interest_coverage": num(ebit / interest, 2) if ebit is not None and interest and interest > 0 else None,
            "short_debt": num(short_debt, 0),
            "cash_to_short_debt": num(cash / short_debt, 2) if cash is not None and short_debt and short_debt > 0 else None,
            "interest_quarters": [{"period": f"{c.year % 100}.{c.month:02d}", "interest": num(inc.loc["Interest Expense", c], 0)}
                                  for c in sorted(inc.columns) if "Interest Expense" in inc.index and pd.notna(inc.loc["Interest Expense", c])],
        }
    except Exception as exc:
        print(f"[참고] 부채 지표 {ticker}: {exc}", file=sys.stderr)
    try:  # 분기 실적 추이 (Yahoo 무료 데이터는 최근 4~5개 분기만 제공)
        inc, cf = tk.quarterly_income_stmt, tk.quarterly_cashflow
        row = lambda df, name, col: num(df.loc[name, col], 4) if name in df.index and col in df.columns else None
        for col in sorted(inc.columns):
            q = {"period": f"{col.year % 100}.{col.month:02d}", "date": day(col),
                 "revenue": row(inc, "Total Revenue", col), "op_income": row(inc, "Operating Income", col),
                 "eps": row(inc, "Diluted EPS", col), "fcf": row(cf, "Free Cash Flow", col),
                 "capex": row(cf, "Capital Expenditure", col)}
            if q["revenue"] is not None:
                fund["quarters"].append(q)
    except Exception as exc:
        print(f"[참고] 분기 실적 {ticker}: {exc}", file=sys.stderr)
    try:  # 다음 실적 발표 일정과 지난 실적 기록(예상 대비 EPS, 발표 후 주가 반응)
        fund["earnings"] = earnings.build(tk, ticker, today, KST)
    except Exception as exc:
        print(f"[참고] 실적 발표일 {ticker}: {exc}", file=sys.stderr)
    return fund


def stock_news(entry, old, long_name=None):
    """종목별 최근 뉴스(Yahoo 검색).
    Yahoo의 '관련 종목' 표시는 지나가듯 언급한 기사에도 붙어서, 제목에 회사 이름이나 티커가 들어간 기사를 먼저 고른다.
    제목에 이름이 들어간 기사가 적으면 관련 종목 표시가 붙은 기사로 채운다.
    한국 종목은 티커로 검색하면 결과가 없어 설정의 news_q(영문 회사명)로 찾는다."""
    tickers = {entry["ticker"], *entry.get("news_match", [])}
    words = {re.sub(r"\.K[SQ]$", "", entry["ticker"]), *entry.get("news_keywords", [])}
    for name in (entry.get("news_q"), long_name):
        if name:
            words.add(re.sub(r"[^\w.-]", "", name.split()[0]))   # "CoreWeave, Inc." → CoreWeave
    words = {w for w in words if len(w) >= 2 and not w.isdigit()}
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I)
    try:
        items = []
        for count in (20, 10):  # Yahoo가 가끔 많은 수를 요청하면 빈 결과를 돌려줘서 줄여 다시 묻는다
            items = yf.Search(entry.get("news_q") or entry["ticker"], news_count=count, max_results=0).news or []
            if items:
                break
    except Exception as exc:
        print(f"[참고] 뉴스 {entry['ticker']}: {exc}", file=sys.stderr)
        return {**old, "stale": True} if old else None
    named, related = [], []
    for n in items:
        if not n.get("title") or not n.get("link") or n.get("type") not in (None, "STORY", "VIDEO"):
            continue
        t = n.get("providerPublishTime")
        row = {"title": n["title"], "publisher": n.get("publisher"), "url": n["link"],
               "at": dt.datetime.fromtimestamp(t, KST).isoformat(timespec="minutes") if t else None}
        if pattern.search(n["title"]):
            named.append({**row, "named": True})   # 제목에 회사 이름·티커가 들어간 기사
        elif tickers & set(n.get("relatedTickers") or []):
            related.append(row)
    picked = (named + related)[:NEWS_COUNT] if len(named) < NEWS_COUNT else named[:NEWS_COUNT]
    picked.sort(key=lambda n: n["at"] or "", reverse=True)
    return {"source": "Yahoo Finance", "fetched": dt.datetime.now(KST).isoformat(timespec="minutes"), "items": picked}


def stock_detail(entry, market, row, ctx, old):
    """종목 한 장 요약에 필요한 값. 가격 계열은 매번, 재무 계열은 하루 한 번 갱신한다."""
    bars = ctx["yahoo"][entry["ticker"]]
    close = bars["Close"]
    year = bars.tail(252)
    mas, groups = chart_checklist(close, ctx["config"]["chart_rules"])
    fx = ctx["yahoo"].get(ctx["config"]["fx_symbol"]) if market != "kr" else None
    detail = {**row, "low52": num(year["Low"].min()), "high52": num(year["High"].max()),
              "cci": num(cci(bars), 0), "mas": mas, "checklist": groups,
              "returns": period_returns(close, fx["Close"] if fx is not None else None),
              "chart": {"dates": [day(d) for d in close.tail(CHART_DAYS).index], "close": [num(v) for v in close.tail(CHART_DAYS)]},
              "links": {k: entry[k] for k in ("ir", "notion") if entry.get(k)},
              "rating": {k: v for k, v in (ctx["manual"].get("ratings", {}).get(entry["ticker"]) or {}).items()} or None}
    detail.pop("spark", None)
    old_fund = (old or {}).get("fund")
    try:
        detail["fund"] = fundamentals(entry["ticker"], old_fund, ctx["today"])
    except Exception as exc:
        warn(f"재무 {entry['ticker']}", exc)
        detail["fund"] = {**old_fund, "stale": True} if old_fund else None
    detail["news"] = stock_news(entry, (old or {}).get("news"), (detail["fund"] or {}).get("long_name"))
    return detail


# ───────────────────────── 시장 국면 판단판 ─────────────────────────

def regime_trend(c, ctx):
    close = ctx["yahoo"][c["symbol"]]["Close"]
    last, ma50, ma200 = float(close.iloc[-1]), float(close.tail(50).mean()), float(close.tail(200).mean())
    gap = signed((last / ma200 - 1) * 100, 1, "%")
    if last >= ma200 and ma50 >= ma200:
        return "양호", f"S&P 500이 200일선 위 ({gap})"
    if last < ma200 and ma50 < ma200:
        return "위험", f"S&P 500이 200일선 아래 ({gap})"
    return "주의", f"S&P 500과 200일선이 엇갈림 ({gap})"


def regime_breadth(c, ctx):
    closes = [ctx["yahoo"][s]["Close"] for s in c["sectors"]]
    above = sum(float(x.iloc[-1]) >= float(x.tail(200).mean()) for x in closes)
    state = "양호" if above >= c["good_min"] else "위험" if above <= c["bad_max"] else "주의"
    return state, f"{len(closes)}개 섹터 중 {above}개가 200일선 위"


def regime_rotation(c, ctx):
    def avg(symbols):
        return sum(month_change(ctx["yahoo"][s]["Close"])[1] for s in symbols) / len(symbols)
    gap = avg(c["offense"]) - avg(c["defense"])
    state = "양호" if gap >= c["good_min"] else "위험" if gap <= c["bad_max"] else "주의"
    lead = "경기민감주가 상대 강세" if gap >= 0 else "방어주가 상대 강세"
    return state, f"{lead} (한 달 {signed(gap, 1, '%p')})"


def regime_rates(c, ctx):
    s = ctx["fred"][c["fred"]]
    diff, _ = month_change(s)
    state = "양호" if diff <= c["good_max"] else "위험" if diff >= c["bad_min"] else "주의"
    return state, f"10년물 {float(s.iloc[-1]):.2f}%, 한 달 {signed(diff, 2, '%p')}"


def regime_credit(c, ctx):
    s = ctx["fred"][c["fred"]]
    level, (diff, _) = float(s.iloc[-1]), month_change(s)
    if level >= c["bad_level"] or diff >= c["bad_change"]:
        state = "위험"
    elif level < c["good_level"] and diff < c["good_change"]:
        state = "양호"
    else:
        state = "주의"
    return state, f"하이일드 스프레드 {level:.2f}%p, 한 달 {signed(diff, 2, '%p')}"


def regime_vol(c, ctx):
    last = float(ctx["yahoo"][c["symbol"]]["Close"].iloc[-1])
    state = "양호" if last < c["good_max"] else "위험" if last >= c["bad_min"] else "주의"
    where = f"{c['good_max']} 아래" if state == "양호" else f"{c['bad_min']} 이상" if state == "위험" else f"{c['good_max']}~{c['bad_min']}"
    return state, f"VIX {last:.1f} ({where})"


def regime_commodity(c, ctx):
    oil = month_change(ctx["yahoo"][c["oil"]]["Close"])[1]
    dollar = month_change(ctx["yahoo"][c["dollar"]]["Close"])[1]
    if oil >= c["bad_oil"] or dollar >= c["bad_dollar"]:
        state = "위험"
    elif oil < c["good_oil"] and dollar < c["good_dollar"]:
        state = "양호"
    else:
        state = "주의"
    return state, f"한 달간 유가 {signed(oil, 1, '%')}, 달러 {signed(dollar, 1, '%')}"


def regime_rules(r):
    return {
        "trend": "양호: S&P 500과 50일선이 모두 200일선 위 · 위험: 모두 아래 · 그 외 주의",
        "breadth": f"11개 섹터 ETF 중 200일선 위 개수. 양호: {r['breadth']['good_min']}개 이상 · 위험: {r['breadth']['bad_max']}개 이하",
        "rotation": f"경기민감 섹터와 방어 섹터의 한 달 수익률 차이. 양호: {r['rotation']['good_min']:g}%p 이상 · 위험: −{abs(r['rotation']['bad_max']):g}%p 이하",
        "rates": f"미국채 10년물 한 달 변화. 양호: +{r['rates']['good_max']:.2f}%p 이하 · 위험: +{r['rates']['bad_min']:.2f}%p 이상",
        "credit": f"하이일드 스프레드. 양호: {r['credit']['good_level']:g}%p 미만이고 한 달 +{r['credit']['good_change']:g}%p 미만 · 위험: {r['credit']['bad_level']:g}%p 이상이거나 한 달 +{r['credit']['bad_change']:g}%p 이상",
        "vol": f"VIX. 양호: {r['vol']['good_max']} 미만 · 위험: {r['vol']['bad_min']} 이상",
        "commodity": f"한 달 변화율. 양호: 유가 +{r['commodity']['good_oil']}% 미만이고 달러 +{r['commodity']['good_dollar']}% 미만 · 위험: 유가 +{r['commodity']['bad_oil']}% 이상이거나 달러 +{r['commodity']['bad_dollar']}% 이상",
    }


REGIME = [("trend", "추세", regime_trend), ("breadth", "시장 폭", regime_breadth),
          ("rotation", "섹터 이동", regime_rotation), ("rates", "금리", regime_rates),
          ("credit", "신용", regime_credit), ("vol", "변동성", regime_vol),
          ("commodity", "원자재·달러", regime_commodity)]


def build_regime(ctx):
    cfg = ctx["config"]["regime"]
    rules, items = regime_rules(cfg), []
    for key, name, fn in REGIME:
        try:
            state, why = fn(cfg[key], ctx)
        except Exception as exc:
            warn(f"국면 판단 {name}", exc)
            state, why = "확인 불가", "데이터를 받지 못했습니다"
        items.append({"id": key, "name": name, "state": state, "why": why, "rule": rules[key]})
    count = lambda s: sum(i["state"] == s for i in items)
    return {"items": items, "total": len(items), "good": count("양호"), "warn": count("주의"),
            "bad": count("위험"), "unknown": count("확인 불가")}


# ───────────────────────── 일정 ─────────────────────────

def third_friday(year, month):
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(4 - first.weekday()) % 7 + 14)


def earnings_events(ctx):
    """관심 종목의 다음 실적 발표일(종목 한 장 요약에서 받은 값)."""
    events = []
    for entries in ctx["config"]["watchlist"].values():
        for entry in entries:
            fund = (ctx["stocks_out"].get(entry["ticker"]) or {}).get("fund") or {}
            earn = fund.get("earnings") or {}
            when, nd = earn.get("next"), earn.get("next_detail") or {}
            if when:
                local = (("한국 " if earn.get("market") == "KR" else "미국 ") + nd["date"][5:].replace("-", "/") +
                         (" " + nd["time"] if nd.get("time") else "")) if nd.get("date") else None
                events.append({"date": when, "title": f"{entry['name']} 실적 발표", "kind": "실적",
                               "ticker": entry["ticker"], "source": "Yahoo Finance",
                               "timing": nd.get("timing"), "local": local})
    return events


def fetch_fomc(ctx):
    """연준 공식 일정 페이지에서 FOMC 결정일(회의 둘째 날)을 읽는다. 하루 한 번만 받는다.

    실패하면 이전 결과, 그것도 없으면 config 의 calendar.fomc 를 쓴다.
    """
    today, old = ctx["today"], (ctx["prev"] or {}).get("fomc") or {}
    if old.get("fetched") == today.isoformat() and old.get("meetings"):
        return old
    try:
        r = requests.get(FOMC_PAGE, timeout=40, headers={"User-Agent": "invest-dashboard (personal use)"})
        r.raise_for_status()
        meetings = []
        panels = re.split(r">(\d{4}) FOMC Meetings<", r.text)
        for year, body in zip(panels[1::2], panels[2::2]):
            rows = re.findall(r"fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<", body, re.S)
            for month, days in rows:
                if "(" in days:        # 임시 회의·서면 표결은 뺀다
                    continue
                last_month = month.split("/")[-1].strip()[:3]
                month_no = next(i + 1 for i, m in enumerate(MONTHS) if m.startswith(last_month))
                day_no = int(re.findall(r"\d+", days)[-1])
                meetings.append({"date": dt.date(int(year), month_no, day_no).isoformat(), "sep": "*" in days})
        meetings = sorted((m for m in meetings if m["date"] >= (today - dt.timedelta(days=45)).isoformat()), key=lambda m: m["date"])
        if not [m for m in meetings if m["date"] >= today.isoformat()]:
            raise ValueError("앞으로의 회의 일정을 찾지 못했습니다")
        return {"fetched": today.isoformat(), "meetings": meetings, "source": "연준 공식 일정"}
    except Exception as exc:
        print(f"[참고] FOMC 일정: {exc}", file=sys.stderr)
        if old.get("meetings"):
            return old
        return {"meetings": [{"date": d, "sep": False} for d in ctx["config"]["calendar"].get("fomc", [])], "source": "설정 파일"}


def build_events(ctx, prev, today):
    events = earnings_events(ctx)
    for m in ctx["fomc"]["meetings"]:
        events.append({"date": m["date"], "title": "FOMC 금리 결정" + (" (경제전망 발표)" if m.get("sep") else ""),
                       "kind": "FOMC", "source": ctx["fomc"]["source"] + " · 미국 날짜"})
    for offset in range(13):
        m = today.month - 1 + offset
        year, month = today.year + m // 12, m % 12 + 1
        quarterly = month in (3, 6, 9, 12)
        events.append({"date": third_friday(year, month).isoformat(),
                       "title": "선물·옵션 동시 만기일" if quarterly else "옵션 만기일",
                       "kind": "만기", "source": "매월 셋째 금요일"})
    seen = set()
    for sid, cfg in ctx["config"]["series"].items():   # 지표에 event 이름이 있으면 다음 발표일을 일정에 넣는다
        when = (ctx.get("series_out", {}).get(sid) or {}).get("next_release")
        label = cfg.get("event") or cfg["name"].split(" (")[0]
        if when and cfg.get("calendar", True) and (label, when) not in seen:
            seen.add((label, when))
            events.append({"date": when, "title": f"{label} 발표", "kind": "경제지표", "source": "FRED 발표 일정 · 미국 날짜",
                           "minor": not cfg.get("event")})
    for e in ctx["manual"].get("events", []):
        events.append({"date": e["date"], "title": e["title"], "kind": e.get("kind", "내 이벤트"), "source": "직접 입력"})
    # 지난 일정은 이전 결과에서 45일치를 이어받아 달력에 남긴다
    floor = (today - dt.timedelta(days=45)).isoformat()
    events = [e for e in events if e["date"] >= today.isoformat()]
    events += [e for e in (prev or {}).get("events_all", []) if floor <= e["date"] < today.isoformat()]
    uniq = {(e["date"], e["title"]): e for e in events}
    past_and_future = sorted(uniq.values(), key=lambda e: (e["date"], e["kind"]))
    events = [e for e in past_and_future if e["date"] >= today.isoformat() and not e.get("minor")]
    week = [e for e in events if e["date"] <= (today + dt.timedelta(days=7)).isoformat()]
    if len(week) < 3:  # 한산한 주에는 30일 안의 다음 일정으로 3건까지 채운다
        later = [e for e in events if e not in week and e["date"] <= (today + dt.timedelta(days=30)).isoformat()]
        week += later[:3 - len(week)]
    return past_and_future, week[:5]


# ───────────────────────── 산업 ─────────────────────────

def build_heatmap(ctx):
    """업종·테마 ETF의 기간별 수익률(%)."""
    year_start = pd.Timestamp(ctx["today"].year, 1, 1)
    groups = []
    for g in ctx["config"]["heatmap"]["groups"]:
        cells = []
        for symbol, name in g["items"]:
            try:
                close = ctx["yahoo"][symbol]["Close"]
                ret = lambda days: num((float(close.iloc[-1]) / float(close.iloc[-1 - days]) - 1) * 100, 1) if len(close) > days else None
                before = close[close.index < year_start]
                cells.append({"symbol": symbol, "name": name, "asof": day(close.index[-1]),
                              "d1": ret(1), "w1": ret(5), "m1": ret(21), "m3": ret(63),
                              "ytd": num((float(close.iloc[-1]) / float(before.iloc[-1]) - 1) * 100, 1) if len(before) else None})
            except Exception as exc:
                warn(f"히트맵 {symbol}", exc)
        groups.append({"name": g["name"], "cells": cells})
    return {"groups": groups, "source": "Yahoo Finance"}


def build_capex(ctx):
    """빅테크 분기 설비투자. 회사마다 회계 분기가 달라 분기 말 달을 3·6·9·12월로 맞춰 합친다. 하루 한 번만 받는다."""
    today, old = ctx["today"].isoformat(), (ctx["prev"] or {}).get("capex") or {}
    if old.get("fetched") == today and old.get("companies"):
        return old
    companies = []
    for ticker, name in ctx["config"]["capex"]["companies"]:
        try:
            cf = yf.Ticker(ticker).quarterly_cashflow
            quarters = {}
            for col in cf.columns:
                v = cf.loc["Capital Expenditure", col] if "Capital Expenditure" in cf.index else None
                if v is not None and pd.notna(v):
                    end = col + pd.offsets.MonthEnd(0) + pd.DateOffset(months=(3 - col.month % 3) % 3)   # 8월 말 → 9월로
                    quarters[f"{end.year % 100}.{end.month:02d}"] = num(abs(float(v)), 0)
            if quarters:
                companies.append({"ticker": ticker, "name": name, "quarters": quarters})
        except Exception as exc:
            warn(f"설비투자 {ticker}", exc)
    if not companies:
        return old
    periods = sorted({p for c in companies for p in c["quarters"]})
    complete = [p for p in periods if all(p in c["quarters"] for c in companies)]
    totals = [{"period": p, "total": sum(c["quarters"][p] for c in companies)} for p in complete]
    for t in totals:   # 1년 전 같은 분기가 있으면 증가율을 붙인다
        yy, mm = t["period"].split(".")
        ago = next((x["total"] for x in totals if x["period"] == f"{int(yy) - 1}.{mm}"), None)
        t["yoy_pct"] = num((t["total"] / ago - 1) * 100, 1) if ago else None
    return {"fetched": today, "companies": companies, "periods": periods, "totals": totals, "source": "Yahoo Finance"}


# ───────────────────────── 알림 ─────────────────────────

def build_alerts(ctx, data, now):
    """알릴 만한 변화를 찾는다. 같은 알림은 하루에 한 번만 만들고, 며칠 동안 쌓아 둔다.

    클로드 예약 작업(아침·오후 브리핑)과 홈 화면이 이 목록을 읽는다.
    """
    rules, prev = ctx["config"]["alerts"], ctx["prev"] or {}
    today, tomorrow = ctx["today"].isoformat(), (ctx["today"] + dt.timedelta(days=1)).isoformat()
    found = []

    def add(key, kind, title, detail, level="info", ticker=None, day_=None):
        # id 앞의 날짜가 같으면 같은 알림으로 본다. 종가 기준 알림은 그 종가의 날짜를 써서 주말에 되풀이되지 않게 한다
        found.append({"id": f"{day_ or today}:{kind}:{key}", "kind": kind, "level": level, "ticker": ticker,
                      "title": title, "detail": detail, "at": now})

    old_stocks = prev.get("stocks", {})
    for t, s in data["stocks"].items():
        if s.get("stale") or s.get("price") is None:
            continue
        o, name = old_stocks.get(t) or {}, s["name"]
        chg = s.get("change_pct")
        if chg is not None and abs(chg) >= rules["move_pct"]:
            add(t, "급등락", f"{name} {signed(chg, 1, '%')}", f"{s['asof']} 종가 기준 하루 변동", "warn", t, s["asof"])
        rsi_now, rsi_old = s.get("rsi"), o.get("rsi")
        if rsi_now is not None and rsi_old is not None:
            if rsi_now >= rules["rsi_high"] > rsi_old:
                add(t, "RSI", f"{name} RSI {rsi_now:.0f} (과매수 진입)", f"RSI가 {rules['rsi_high']} 이상으로 올라섬", "info", t)
            if rsi_now <= rules["rsi_low"] < rsi_old:
                add(t, "RSI", f"{name} RSI {rsi_now:.0f} (과매도 진입)", f"RSI가 {rules['rsi_low']} 이하로 내려옴", "info", t)
        gap = lambda row: next((m["gap_pct"] for m in row.get("mas", []) if m["days"] == 200), None)
        g_now, g_old = gap(s), gap(o)
        if g_now is not None and g_old is not None and (g_now >= 0) != (g_old >= 0):
            up = g_now >= 0
            add(t, "200일선", f"{name} 200일선 {'상향 돌파' if up else '하향 이탈'}", f"200일선 대비 {signed(g_now, 1, '%')}", "good" if up else "warn", t)
        hit = lambda row, gi, ii: (row.get("checklist") or [{}] * 3)[gi].get("items", [{}] * 3)[ii].get("hit") if row.get("checklist") else None
        if hit(s, 0, 1) and hit(o, 0, 1) is False:
            add(t, "골든크로스", f"{name} 골든크로스", "20일선이 60일선을 상향 돌파", "good", t)
        if hit(s, 2, 0) and hit(o, 2, 0) is False:
            add(t, "데드크로스", f"{name} 데드크로스", "20일선이 60일선을 하향 돌파", "warn", t)
        if s.get("history_days", 0) >= 252 and o.get("price") is not None:
            if s["price"] >= s["high52"] * 0.999 and o["price"] < s["high52"] * 0.999:
                add(t, "52주", f"{name} 52주 신고가", f"현재가가 최근 1년 최고가 부근", "good", t)
            if s["price"] <= s["low52"] * 1.001 and o["price"] > s["low52"] * 1.001:
                add(t, "52주", f"{name} 52주 신저가", f"현재가가 최근 1년 최저가 부근", "warn", t)
        earn, old_earn = (s.get("fund") or {}).get("earnings") or {}, (o.get("fund") or {}).get("earnings") or {}
        if earn.get("next") in (today, tomorrow):
            add(f"{t}:{earn['next']}", "실적 예정", f"{name} 실적 발표 {'오늘' if earn['next'] == today else '내일'}", f"{earn['next']} (한국 시간)", "info", t)
        last, old_last = earn.get("last") or {}, old_earn.get("last") or {}
        if last.get("date") and old_last.get("date") and last["date"] != old_last["date"]:
            sur = last.get("surprise_pct")
            add(f"{t}:{last['date']}", "실적 결과", f"{name} 실적 발표: EPS {last.get('eps_actual')} (예상 {last.get('eps_estimate')})",
                f"예상 대비 {signed(sur, 1, '%')}" if sur is not None else "예상 대비 값 없음",
                "good" if (sur or 0) > 0 else "warn" if (sur or 0) < 0 else "info", t)
        sf = ((s.get("fund") or {}).get("short") or {}).get("float_pct")
        sf_old = ((o.get("fund") or {}).get("short") or {}).get("float_pct")
        if sf is not None and sf_old is not None and sf >= rules["short_float"] > sf_old:
            add(t, "공매도", f"{name} Short Float {sf:.1f}%", f"{rules['short_float']}% 이상으로 올라섬", "warn", t)

    # SEC 공시: 최근 이틀 안에 접수된 수시공시·증권 발행·내부자 공개시장 매수만 알린다
    recent_day = (ctx["today"] - dt.timedelta(days=2)).isoformat()
    for t, c in ((data.get("sec") or {}).get("companies") or {}).items():
        name = (data["stocks"].get(t) or {}).get("name", t)
        for f in c.get("filings", []):
            if f["date"] >= recent_day and (f["form"] == "8-K" or f["form"].startswith("424B")):
                what = " · ".join(f["items"]) if f["items"] else f["label"]
                add(f["acc"], "공시", f"{name} {f['form']}: {what}", f"{f['date']} 접수 (미국 날짜)", "info", t, f["date"])
        # 내부자 클러스터: 새로 생겼거나 사람 수가 늘어난 때만(같은 묶음에 거래만 더해진 것은 다시 알리지 않음)
        old_cl = ((((prev.get("sec") or {}).get("companies") or {}).get(t) or {}).get("clusters")) or {}
        for side, word, tone in (("buy", "매수", "good"), ("sell", "매도", "warn")):
            before = {e["key"]: e["people"] for e in old_cl.get(side, [])}
            for e in (c.get("clusters") or {}).get(side, []):
                if e["active"] and e["end"] >= recent_day and e["people"] > before.get(e["key"], 0):
                    add(f"cluster:{t}:{e['key']}:{e['people']}", "내부자 클러스터",
                        f"{name} 내부자 {e['people']}명 {word} 클러스터",
                        f"{e['start']}~{e['end']} · {e['trades']}건 · 약 {e['value']:,.0f}달러" + (" (계획 매도 제외)" if side == "sell" else ""),
                        tone, t, e["end"])
        for r in c.get("insider", []):
            if r["code"] == "P" and r["filed"] >= recent_day:
                add(r["acc"], "내부자 매수", f"{name} 내부자 매수: {r['owner']} ({r['role']})",
                    f"{r['shares']:,.0f}주" + (f" · 약 {r['value']:,.0f}달러" if r.get("value") else ""), "good", t, r["filed"])

    old_regime = {i["id"]: i["state"] for i in (prev.get("regime") or {}).get("items", [])}
    rank = {"양호": 0, "주의": 1, "위험": 2}
    for i in data["regime"]["items"]:
        before = old_regime.get(i["id"])
        if before in rank and i["state"] in rank and before != i["state"]:
            worse = rank[i["state"]] > rank[before]
            add(i["id"], "시장 국면", f"시장 국면 '{i['name']}' {before} → {i['state']}", i["why"], "warn" if worse else "good")
    vix, vix_old = (data["series"].get("vix") or {}).get("value"), ((prev.get("series") or {}).get("vix") or {}).get("value")
    if vix is not None and vix_old is not None and vix >= rules["vix_high"] > vix_old:
        add("vix", "변동성", f"VIX {vix:.1f} (공포 구간 진입)", f"VIX가 {rules['vix_high']} 이상으로 올라섬", "warn")
    for e in data["events_all"]:
        if e["date"] in (today, tomorrow) and (e["kind"] == "FOMC" or (e["kind"] == "경제지표" and not e.get("minor"))):
            add(f"{e['title']}:{e['date']}", "일정", f"{e['title']} {'오늘' if e['date'] == today else '내일'}", f"{e['date']} (미국 날짜)")

    # 이전 알림을 이어받고, 오래된 것은 지운다. 같은 알림이 이미 있으면 처음 만든 시각을 유지한다
    floor = (ctx["today"] - dt.timedelta(days=rules["keep_days"])).isoformat()
    merged = {a["id"]: a for a in prev.get("alerts", []) if a["id"][:10] >= floor}
    for a in found:
        merged.setdefault(a["id"], a)
    return sorted(merged.values(), key=lambda a: a["at"], reverse=True)


def build_brief(data):
    """클로드 브리핑이 읽는 작은 요약 파일. 전체 데이터 대신 이것만 읽어 사용량을 줄인다."""
    pick = lambda sid: {k: data["series"].get(sid, {}).get(k) for k in ("name", "value", "change_pct", "diff", "asof", "note")}
    return {
        "generated_at": data["generated_at"],
        "regime": {"summary": {k: data["regime"][k] for k in ("total", "good", "warn", "bad")},
                   "items": [{k: i[k] for k in ("name", "state", "why")} for i in data["regime"]["items"]]},
        "market": [pick(s) for s in ("sp500", "nasdaq", "sox", "kospi", "vix", "sentiment", "us10y", "hy_spread", "dxy", "usdkrw", "wti", "pe_nasdaq100")],
        "watchlist": [{"ticker": s["ticker"], "name": s["name"], "price": s.get("price"), "change_pct": s.get("change_pct"),
                       "rsi": s.get("rsi"), "from_high_pct": s.get("from_high_pct"), "asof": s.get("asof"),
                       "next_earnings": ((data["stocks"].get(s["ticker"], {}).get("fund") or {}).get("earnings") or {}).get("next"),
                       "news": [{k: n[k] for k in ("title", "publisher", "at")}
                                for n in ((data["stocks"].get(s["ticker"], {}).get("news") or {}).get("items") or [])[:3]]}
                      for rows in data["watchlist"].values() for s in rows],
        "fomc_odds": None if not data.get("fedwatch") else {
            "next_meeting": data["fedwatch"]["meetings"][0]["date"], "target_range": data["fedwatch"]["range"],
            **{k: data["fedwatch"]["meetings"][0][k] for k in ("cut", "hold", "hike")},
            "week_ago": (data["fedwatch"].get("compare") or {}).get("week"), "asof": data["fedwatch"]["asof"]},
        "events_next_7_days": data["events"],
        "alerts": data["alerts"],
        "changes": [{"ticker": r["ticker"], "name": r["name"], "level": r["level"],
                     "reasons": [x["text"] for x in r["reasons"]]} for r in (data.get("briefing") or {}).get("rows", []) if r["level"] != "none"],
        "site": "https://" + data["site"]["repo"].split("/")[0] + ".github.io/" + data["site"]["repo"].split("/")[1] + "/",
    }


# ───────────────────────── 조립 ─────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "site/data/dashboard.json"))
    ap.add_argument("--prev", help="이전 결과 JSON. 실패한 항목의 값을 여기서 가져온다.")
    ap.add_argument("--news-ai", help="AI 뉴스 분류 결과(news_ai.json). 없으면 --prev 와 같은 폴더에서 찾는다.")
    ap.add_argument("--prev-financials", help="이전 장기 재무 JSON. 없으면 --prev 와 같은 폴더의 financials.json 을 찾는다.")
    args = ap.parse_args()

    config = json.loads((ROOT / "config/dashboard.json").read_text(encoding="utf-8"))
    manual = json.loads((ROOT / "config/manual.json").read_text(encoding="utf-8"))
    prev = None
    if args.prev and Path(args.prev).is_file():
        try:
            prev = json.loads(Path(args.prev).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"이전 결과를 읽지 못해 무시합니다: {exc}", file=sys.stderr)
    prev_fin = None
    fin_path = Path(args.prev_financials) if args.prev_financials else Path(args.prev).with_name("financials.json") if args.prev else None
    if fin_path and fin_path.is_file():
        try:
            prev_fin = json.loads(fin_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"이전 장기 재무를 읽지 못해 무시합니다: {exc}", file=sys.stderr)

    prev_scr = None
    scr_path = Path(args.prev).with_name("screener.json") if args.prev else None
    if scr_path and scr_path.is_file():
        try:
            prev_scr = json.loads(scr_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"이전 스크리너 표를 읽지 못해 무시합니다: {exc}", file=sys.stderr)

    # 필요한 심볼·시계열을 설정에서 모아 한 번에 받는다
    series, regime, senti = config["series"], config["regime"], config["sentiment"]
    symbols = {c["symbol"] for c in series.values() if c.get("symbol")}
    symbols |= {t for c in series.values() for t in c.get("symbols", [])} | {c["benchmark"] for c in series.values() if c.get("benchmark")}
    symbols |= {e["ticker"] for entries in config["watchlist"].values() for e in entries}
    symbols |= {regime["trend"]["symbol"], regime["vol"]["symbol"], regime["commodity"]["oil"], regime["commodity"]["dollar"]}
    symbols |= set(regime["breadth"]["sectors"]) | set(regime["rotation"]["offense"]) | set(regime["rotation"]["defense"])
    symbols |= {senti[k] for k in ("stock", "bond", "equal_weight", "index", "vix")}
    symbols |= {config["fx_symbol"], config["benchmark"]["symbol"]}
    symbols |= {symbol for g in config["heatmap"]["groups"] for symbol, _ in g["items"]}
    fred_ids = {c["id"] for c in series.values() if c["source"] == "fred"}
    fred_ids |= {i for c in series.values() for i in c.get("needs", [])}
    fred_ids |= {regime["rates"]["fred"], regime["credit"]["fred"], senti["fred_hy"]}
    fred_ids |= {sid for _, sid in config["curve"]["points"]}
    fred_ids |= set(config["fedwatch"]["fred_range"])

    today = dt.datetime.now(KST).date()
    ctx = {"config": config, "manual": manual, "prev": prev, "today": today,
           "yahoo": fetch_yahoo(sorted(symbols)), "fred": {}}
    for sid in sorted(fred_ids):
        s = fetch_fred(sid)
        if s is not None:
            ctx["fred"][sid] = s

    ctx["valuation"] = build_valuation(ctx)
    out_series, history = {}, {}
    for sid, cfg in series.items():
        meta = {k: v for k, v in cfg.items() if k in ("name", "decimals", "unit", "change", "diff_unit", "diff_decimals", "signed", "prefix", "help")}
        try:
            item = SOURCES[cfg["source"]]({**cfg, "_key": sid}, ctx)
            hist = item.pop("_history", None)
            if hist is not None and len(hist) >= 2:
                history[sid] = compact_history(hist)
            out_series[sid] = {**meta, **item, "chart": sid in history}
        except Exception as exc:
            if not any(sid_err in str(e["where"]) for e in errors for sid_err in (cfg.get("symbol", "∅"), cfg.get("id", "∅"))):
                warn(f"지표 {cfg['name']}", exc)
            old = (prev or {}).get("series", {}).get(sid)
            out_series[sid] = {**old, **meta, "stale": True, "chart": False} if old and old.get("value") is not None else {**meta, "value": None, "error": True}

    watch, stocks = {}, {}
    old_stocks = (prev or {}).get("stocks", {})
    for market, entries in config["watchlist"].items():
        watch[market] = []
        old_rows = {r["ticker"]: r for r in (prev or {}).get("watchlist", {}).get(market, [])}
        for entry in entries:
            try:
                row = stock_row(entry, market, ctx)
                watch[market].append(row)
                stocks[entry["ticker"]] = stock_detail(entry, market, row, ctx, old_stocks.get(entry["ticker"]))
            except Exception as exc:
                if entry["ticker"] in ctx["yahoo"]:
                    warn(f"종목 {entry['ticker']}", exc)
                if entry["ticker"] in old_stocks:
                    stocks[entry["ticker"]] = {**old_stocks[entry["ticker"]], "stale": True}
                old = old_rows.get(entry["ticker"])
                if old and old.get("price") is not None:
                    watch[market].append({**old, "name": entry["name"], "stale": True})
                else:
                    watch[market].append({"ticker": entry["ticker"], "name": entry["name"], "market": market,
                                          "currency": "KRW" if market == "kr" else "USD", "price": None, "error": True})

    ctx["series_out"], ctx["stocks_out"] = out_series, stocks
    bench = None
    try:
        b = ctx["yahoo"][config["benchmark"]["symbol"]]["Close"].tail(CHART_DAYS + 10)
        bench = {"name": config["benchmark"]["name"], "dates": [day(d) for d in b.index], "close": [num(v) for v in b]}
    except Exception as exc:
        warn("비교 지수", exc)
    try:
        curve = build_curve(ctx)
    except Exception as exc:
        warn("수익률 곡선", exc)
        curve = (prev or {}).get("curve")
    ctx["fomc"] = fetch_fomc(ctx)
    try:
        fedwatch = build_fedwatch(ctx)
    except Exception as exc:
        warn("금리 인하 확률", exc)
        fedwatch = {**(prev or {}).get("fedwatch"), "stale": True} if (prev or {}).get("fedwatch") else None
    try:
        events_all, events_week = build_events(ctx, prev, today)
    except Exception as exc:
        warn("일정", exc)
        events_all, events_week = (prev or {}).get("events_all", []), (prev or {}).get("events", [])

    data = {
        "generated_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "site": config["site"],
        "tabs": config["tabs"],
        "regime": build_regime(ctx),
        "series": out_series,
        "curve": curve,
        "watchlist": watch,
        "stocks": stocks,
        "benchmark": bench,
        "events": events_week,
        "events_all": events_all,
        "fomc": ctx["fomc"],
        "fedwatch": fedwatch,
        "valuation": ctx["valuation"],
        "sec": sec.build(config, (prev or {}).get("sec"), today, warn),
        "financials": None,
        "heatmap": build_heatmap(ctx),
        "capex": build_capex(ctx),
        "debt_rules": config["debt_rules"],
        "glossary": json.loads((ROOT / "config/glossary.json").read_text(encoding="utf-8"))["terms"],
        "errors": errors,
    }
    ai_path = Path(args.news_ai) if args.news_ai else Path(args.prev).with_name("news_ai.json") if args.prev else None
    news_result = {}
    if ai_path and ai_path.is_file():
        try:
            news_result = json.loads(ai_path.read_text(encoding="utf-8"))
        except Exception as exc:
            warn("AI 뉴스 분류 파일", exc)
    try:
        dropped = news_ai.apply(data, news_result)
        if dropped:
            print(f"[참고] AI 뉴스 분류 중 검사에 걸려 뺀 항목 {len(dropped)}건: {dropped[:3]}", file=sys.stderr)
    except Exception as exc:
        warn("AI 뉴스 분류 적용", exc)
    prof_path = ai_path.with_name("profiles.json") if ai_path else None
    prof_result = {}
    if prof_path and prof_path.is_file():
        try:
            prof_result = json.loads(prof_path.read_text(encoding="utf-8"))
        except Exception as exc:
            warn("회사 소개 파일", exc)
    try:
        n_bad = profiles.apply(data, prof_result)
        if n_bad:
            print(f"[참고] 회사 소개 검사에서 뺀 항목 {n_bad}건", file=sys.stderr)
    except Exception as exc:
        warn("회사 소개 적용", exc)
    try:
        data["alerts"] = build_alerts(ctx, data, data["generated_at"])
    except Exception as exc:
        warn("알림", exc)
        data["alerts"] = (prev or {}).get("alerts", [])
    try:
        data["briefing"] = briefing.build(data, config, today, dt.datetime.now(KST))
    except Exception as exc:
        warn("아침 브리핑", exc)
        data["briefing"] = (prev or {}).get("briefing")
    fin = financials.build(config, prev_fin, today, warn)
    data["financials"] = {"fetched": fin.get("fetched"), "source": fin.get("source"), "tickers": sorted(fin.get("companies") or {})}
    try:   # 투자 논리 점검판 (config/thesis.json + 시세·재무)
        for t, th in thesis.build(data, fin, warn).items():
            data["stocks"][t]["thesis"] = th
    except Exception as exc:
        warn("투자 논리 점검판", exc)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.parent / "financials.json").write_text(json.dumps(fin, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    try:
        scr = screener.build(config, prev_scr, today, warn)
        (out.parent / "screener.json").write_text(json.dumps(scr, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        data["screener"] = {"fetched": scr.get("fetched"), "count": len(scr.get("rows") or [])}
    except Exception as exc:
        warn("스크리너", exc)
        if prev_scr:
            (out.parent / "screener.json").write_text(json.dumps(prev_scr, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    try:
        n_ai = ai_export.write(data, fin, out.parent / "ai")
    except Exception as exc:
        warn("AI용 요약 파일", exc)
        n_ai = 0
    (out.parent / "profile_queue.json").write_text(json.dumps(profiles.build_queue(data, prof_result, today), ensure_ascii=False, indent=1), encoding="utf-8")
    (out.parent / "news_queue.json").write_text(json.dumps(news_ai.build_queue(data, news_result, dt.datetime.now(KST)), ensure_ascii=False, indent=1), encoding="utf-8")
    (out.parent / "brief.json").write_text(json.dumps(build_brief(data), ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    (out.parent / "history.json").write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"저장: {out} · 지표 {len(out_series)}개 · 종목 {sum(len(v) for v in watch.values())}개 · 장기 재무 {len(fin.get('companies') or {})}개 · AI용 파일 {n_ai}개 · 실패 {len(errors)}건")

    got_anything = bool(ctx["yahoo"]) or bool(ctx["fred"])
    if not got_anything and prev is None:
        sys.exit("모든 출처에서 수집에 실패했고 이전 결과도 없습니다.")


if __name__ == "__main__":
    main()
