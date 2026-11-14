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
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SPARK_DAYS = 63   # 약 3개월
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


def spark(series):
    return [num(v) for v in series.tail(SPARK_DAYS)]


# ───────────────────────── 원본 데이터 받기 ─────────────────────────

def fetch_yahoo(symbols):
    """심볼별 일봉(High, Close) 2년치. 실패한 심볼은 결과에 없다."""
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
                bars = df[s][["High", "Close"]].dropna(subset=["Close"])
            except KeyError:
                continue
            if len(bars) >= 2:
                out[s] = bars
    for s in symbols:
        if s not in out:
            warn(f"Yahoo {s}", last_err or "데이터 없음")
    return out


def fetch_fred(series_id):
    """FRED 시계열(약 3년치). 키 없이 받는 공개 CSV."""
    start = (dt.date.today() - dt.timedelta(days=1100)).isoformat()
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
            "spark": spark(close), "source": "Yahoo Finance"}
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


def src_fred(cfg, ctx):
    s = ctx["fred"][cfg["id"]]
    last, prev = float(s.iloc[-1]), float(s.iloc[-2])
    return {"value": num(last), "prev": num(prev), "diff": num(last - prev),
            "change_pct": num((last / prev - 1) * 100, 2) if prev else None,
            "asof": day(s.index[-1]), "spark": spark(s), "source": "FRED"}


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
            "source": "자체 계산 (Yahoo Finance·FRED)", "note": note,
            "components": [{"name": k, "score": num(v * 100, 0)} for k, v in latest.items() if pd.notna(v)]}


SOURCES = {"yahoo": src_yahoo, "fred": src_fred, "sentiment": src_sentiment}


# ───────────────────────── 관심 종목 ─────────────────────────

def stock_row(entry, market, ctx):
    bars = ctx["yahoo"][entry["ticker"]]
    close = bars["Close"]
    last, prev = float(close.iloc[-1]), float(close.iloc[-2])
    high52 = float(bars["High"].tail(252).max())
    return {"ticker": entry["ticker"], "name": entry["name"], "market": market,
            "currency": "KRW" if market == "kr" else "USD",
            "price": num(last), "change_pct": num((last / prev - 1) * 100, 2),
            "rsi": num(rsi(close), 1), "from_high_pct": num((last / high52 - 1) * 100, 1),
            "history_days": len(close), "asof": day(close.index[-1]), "spark": spark(close),
            "source": "Yahoo Finance"}


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


def earnings_events(ctx, prev):
    """관심 종목의 다음 실적 발표일. 종목별로 실패하면 이전 결과를 다시 쓴다."""
    events = []
    old = [e for e in (prev or {}).get("events_all", []) if e.get("kind") == "실적"]
    for market, entries in ctx["config"]["watchlist"].items():
        for entry in entries:
            try:
                cal = yf.Ticker(entry["ticker"]).calendar or {}
                dates = cal.get("Earnings Date") or []
                if not isinstance(dates, (list, tuple)):
                    dates = [dates]
                for d in dates[:1]:
                    events.append({"date": day(d), "title": f"{entry['name']} 실적 발표", "kind": "실적",
                                   "ticker": entry["ticker"], "source": "Yahoo Finance"})
            except Exception as exc:
                warn(f"실적일 {entry['ticker']}", exc)
                events += [e for e in old if e.get("ticker") == entry["ticker"]]
    return events


def build_events(ctx, prev, today):
    events = earnings_events(ctx, prev)
    for d in ctx["config"]["calendar"].get("fomc", []):
        events.append({"date": d, "title": "FOMC 금리 결정", "kind": "FOMC", "source": "연준 일정"})
    for offset in range(3):
        m = today.month - 1 + offset
        year, month = today.year + m // 12, m % 12 + 1
        quarterly = month in (3, 6, 9, 12)
        events.append({"date": third_friday(year, month).isoformat(),
                       "title": "선물·옵션 동시 만기일" if quarterly else "옵션 만기일",
                       "kind": "만기", "source": "매월 셋째 금요일"})
    for e in ctx["manual"].get("events", []):
        events.append({"date": e["date"], "title": e["title"], "kind": e.get("kind", "내 이벤트"), "source": "직접 입력"})
    events = sorted((e for e in events if e["date"] >= today.isoformat()), key=lambda e: e["date"])
    week = [e for e in events if e["date"] <= (today + dt.timedelta(days=7)).isoformat()]
    if len(week) < 3:  # 한산한 주에는 30일 안의 다음 일정으로 3건까지 채운다
        later = [e for e in events if e not in week and e["date"] <= (today + dt.timedelta(days=30)).isoformat()]
        week += later[:3 - len(week)]
    return events, week[:5]


# ───────────────────────── 조립 ─────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "site/data/dashboard.json"))
    ap.add_argument("--prev", help="이전 결과 JSON. 실패한 항목의 값을 여기서 가져온다.")
    args = ap.parse_args()

    config = json.loads((ROOT / "config/dashboard.json").read_text(encoding="utf-8"))
    manual = json.loads((ROOT / "config/manual.json").read_text(encoding="utf-8"))
    prev = None
    if args.prev and Path(args.prev).is_file():
        try:
            prev = json.loads(Path(args.prev).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"이전 결과를 읽지 못해 무시합니다: {exc}", file=sys.stderr)

    # 필요한 심볼·시계열을 설정에서 모아 한 번에 받는다
    series, regime, senti = config["series"], config["regime"], config["sentiment"]
    symbols = {c["symbol"] for c in series.values() if c["source"] == "yahoo"}
    symbols |= {e["ticker"] for entries in config["watchlist"].values() for e in entries}
    symbols |= {regime["trend"]["symbol"], regime["vol"]["symbol"], regime["commodity"]["oil"], regime["commodity"]["dollar"]}
    symbols |= set(regime["breadth"]["sectors"]) | set(regime["rotation"]["offense"]) | set(regime["rotation"]["defense"])
    symbols |= {senti[k] for k in ("stock", "bond", "equal_weight", "index", "vix")}
    fred_ids = {c["id"] for c in series.values() if c["source"] == "fred"}
    fred_ids |= {regime["rates"]["fred"], regime["credit"]["fred"], senti["fred_hy"]}

    ctx = {"config": config, "manual": manual, "yahoo": fetch_yahoo(sorted(symbols)), "fred": {}}
    for sid in sorted(fred_ids):
        s = fetch_fred(sid)
        if s is not None:
            ctx["fred"][sid] = s

    out_series = {}
    for sid, cfg in series.items():
        meta = {k: v for k, v in cfg.items() if k in ("name", "decimals", "unit", "change", "diff_unit", "diff_decimals")}
        try:
            out_series[sid] = {**meta, **SOURCES[cfg["source"]](cfg, ctx)}
        except Exception as exc:
            if not any(sid_err in str(e["where"]) for e in errors for sid_err in (cfg.get("symbol", "∅"), cfg.get("id", "∅"))):
                warn(f"지표 {cfg['name']}", exc)
            old = (prev or {}).get("series", {}).get(sid)
            out_series[sid] = {**old, **meta, "stale": True} if old and old.get("value") is not None else {**meta, "value": None, "error": True}

    watch = {}
    for market, entries in config["watchlist"].items():
        watch[market] = []
        old_rows = {r["ticker"]: r for r in (prev or {}).get("watchlist", {}).get(market, [])}
        for entry in entries:
            try:
                watch[market].append(stock_row(entry, market, ctx))
            except Exception:
                old = old_rows.get(entry["ticker"])
                if old and old.get("price") is not None:
                    watch[market].append({**old, "name": entry["name"], "stale": True})
                else:
                    watch[market].append({"ticker": entry["ticker"], "name": entry["name"], "market": market,
                                          "currency": "KRW" if market == "kr" else "USD", "price": None, "error": True})

    today = dt.datetime.now(KST).date()
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
        "watchlist": watch,
        "events": events_week,
        "events_all": events_all,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"저장: {out} · 지표 {len(out_series)}개 · 종목 {sum(len(v) for v in watch.values())}개 · 실패 {len(errors)}건")

    got_anything = bool(ctx["yahoo"]) or bool(ctx["fred"])
    if not got_anything and prev is None:
        sys.exit("모든 출처에서 수집에 실패했고 이전 결과도 없습니다.")


if __name__ == "__main__":
    main()
