"""실적 발표 일정과 지난 실적 기록 (AI 아님).

- 출처: Yahoo Finance 실적 발표 일시(earnings_dates)와 예상·실제 EPS, Yahoo 일봉.
- 발표 시점: 거래소 현지 시각으로 장 시작 전이면 '장 전', 장 마감 뒤면 '장 마감 후', 그 사이면 '장중'.
  Yahoo 시각이 0시 정각이면 시각을 모르는 것으로 보고 '시간 미정'. 회사 공지와 다를 수 있다.
- 주가 반응: 발표 뒤 첫 거래일 종가 ÷ 발표 직전 거래일 종가 − 1.
  장 마감 후 발표는 발표일 종가 → 다음 거래일 종가, 그 밖에는 발표 전날 종가 → 발표일 종가.
  같은 구간의 시장 지수(미국 S&P 500, 한국 KOSPI) 변화도 함께 적어 시장 전체 움직임과 구분한다.
- 예상 상회·하회는 EPS만 본다(매출 예상치는 받지 못한다). 차이 ±1% 안이면 '부합'으로 본다(대시보드가 정한 값).
"""
import datetime as dt
import sys

import yfinance as yf

VERSION = 2
KEEP = 12          # 지난 실적 기록을 몇 번까지 보여 줄지
INLINE_PCT = 1.0   # 서프라이즈가 ±1% 안이면 '부합'
SESSIONS = {"US": ("America/New_York", (9, 30), (16, 0), "^GSPC", "S&P 500"),
            "KR": ("Asia/Seoul", (9, 0), (15, 30), "^KS11", "KOSPI")}
_daily = {}


def market_of(ticker):
    return "KR" if ticker.endswith((".KS", ".KQ")) else "US"


def daily(symbol):
    """일봉 종가 4년치(분할 반영). 같은 실행 안에서는 한 번만 받는다."""
    if symbol not in _daily:
        try:
            h = yf.Ticker(symbol).history(period="4y", interval="1d", auto_adjust=False)
            _daily[symbol] = [(d.date(), float(c)) for d, c in h["Close"].dropna().items()]
        except Exception as exc:
            print(f"[참고] 실적 반응용 일봉 {symbol}: {exc}", file=sys.stderr)
            _daily[symbol] = []
    return _daily[symbol]


def timing_in(local, op, cl):
    hm = (local.hour, local.minute)
    if hm == (0, 0):
        return "시간 미정"
    if hm <= op:          # 장 시작 시각에 맞춘 발표도 장 전으로 본다(반응 계산은 같다)
        return "장 전"
    if hm >= cl:
        return "장 마감 후"
    return "장중"


def reaction(bars, date, when):
    """(기준일, 반응일, 변화율%) 또는 None."""
    if not bars:
        return None
    days = [d for d, _ in bars]
    if when == "장 마감 후":
        base = [i for i, d in enumerate(days) if d <= date]
        after = [i for i, d in enumerate(days) if d > date]
    else:
        base = [i for i, d in enumerate(days) if d < date]
        after = [i for i, d in enumerate(days) if d >= date]
    if not base or not after:
        return None
    b, a = base[-1], after[0]
    if (days[a] - date).days > 7:      # 일봉이 비어 있으면 엉뚱한 날과 비교하지 않는다
        return None
    return days[b], days[a], round((bars[a][1] / bars[b][1] - 1) * 100, 1)


def num(v, d=2):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else round(f, d)


def build(tk, ticker, today, kst):
    """Ticker 객체에서 다음 실적 일정과 지난 기록을 만든다. 실패하면 빈 사전."""
    out = {"v": VERSION}
    ed = tk.earnings_dates
    if ed is None or not len(ed):
        return out
    mk = market_of(ticker)
    tz, op, cl, index_sym, index_name = SESSIONS[mk]
    ed = ed.sort_index()
    bars, idx = daily(ticker), daily(index_sym)
    hist = []
    for ts, r in ed.iterrows():
        local = ts.tz_convert(tz)
        when = timing_in(local, op, cl)
        est, act = num(r.get("EPS Estimate")), num(r.get("Reported EPS"))
        row = {"date": local.date().isoformat(), "kst": ts.tz_convert(kst).date().isoformat(),
               "time": local.strftime("%H:%M") if when != "시간 미정" else None, "timing": when}
        if act is None:
            if local.date() >= today - dt.timedelta(days=1) and "next" not in out:
                out["next"] = row["kst"]
                out["next_detail"] = {**row, "eps_estimate": est}
            continue
        sur = num(r.get("Surprise(%)"), 1)
        row.update({"eps_estimate": est, "eps_actual": act, "surprise_pct": sur,
                    "result": None if sur is None or est is None else
                    "부합" if abs(sur) <= INLINE_PCT else "상회" if act > est else "하회"})
        rx = reaction(bars, local.date(), when)
        if rx:
            row.update({"base_day": rx[0].isoformat(), "react_day": rx[1].isoformat(), "move_pct": rx[2]})
            mx = reaction(idx, local.date(), when)
            if mx and mx[1] == rx[1]:
                row.update({"market_pct": mx[2], "excess_pct": round(rx[2] - mx[2], 1)})
        hist.append(row)
    hist = hist[-KEEP:]
    if hist:
        last = hist[-1]
        out["last"] = {"date": last["kst"], "eps_estimate": last["eps_estimate"], "eps_actual": last["eps_actual"],
                       "surprise_pct": last["surprise_pct"]}
    out["history"] = list(reversed(hist))
    out["market"] = mk
    out["index_name"] = index_name
    moves = [h["move_pct"] for h in hist if h.get("move_pct") is not None]
    out["summary"] = {"count": len(hist),
                      "beat": sum(h["result"] == "상회" for h in hist),
                      "miss": sum(h["result"] == "하회" for h in hist),
                      "inline": sum(h["result"] == "부합" for h in hist),
                      "up": sum(m > 0 for m in moves), "down": sum(m < 0 for m in moves), "moves": len(moves),
                      "avg_abs_move": round(sum(abs(m) for m in moves) / len(moves), 1) if moves else None}
    out["note"] = __doc__.split("\n\n", 1)[1].strip()
    return out
