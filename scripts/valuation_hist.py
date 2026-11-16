"""밸류에이션 5년 위치: 지금 P/E, EV/EBITDA, P/S, FCF 수익률이 지난 5년 분포에서 몇 %인지 (AI 아님).

- 주가: Yahoo 주간 종가(주식 분할 반영). 이익·현금흐름: SEC 분기 값의 최근 4개 분기 합계.
- 주마다 '그날 이미 공시됐을 분기'까지만 쓴다: 분기가 끝나고 45일 뒤부터 그 분기 숫자를 쓴다(10-Q 제출 기한 근사, 대시보드가 정한 값).
- 시가총액 = 주가 × 그 분기 말 발행주식 수(없으면 희석 주식 수). EV = 시가총액 − 순현금.
- 분모(이익, EBITDA)가 0 이하인 주는 배수를 만들지 않고 건너뛴다.
- 퍼센타일 = 지난 5년의 주간 값 중 지금보다 낮거나 같은 값의 비율.
  P/E·EV/EBITDA·P/S는 높을수록 비싸고, FCF 수익률은 높을수록 싸다.
"""
import bisect
import datetime as dt

LAG_DAYS = 45
YEARS = 5
MIN_POINTS = 100   # 약 2년. 이보다 적으면 분포라고 보기 어려워 퍼센타일을 내지 않는다

METRICS = [
    ("pe", "P/E", "시가총액 ÷ 최근 4분기 순이익", True),
    ("ev_ebitda", "EV/EBITDA", "(시가총액 − 순현금) ÷ 최근 4분기 (영업이익 + 감가상각비)", True),
    ("ps", "P/S", "시가총액 ÷ 최근 4분기 매출", True),
    ("fcf_yield", "FCF 수익률", "최근 4분기 FCF ÷ 시가총액 × 100", False),
]


def ttm_rows(quarterly):
    """분기 표 → 분기 말마다 최근 4개 분기 합계와 그 분기 말 재무상태."""
    out = []
    for i in range(3, len(quarterly)):
        w = quarterly[i - 3:i + 1]
        span = (dt.date.fromisoformat(w[-1]["end"]) - dt.date.fromisoformat(w[0]["start"])).days
        if abs(span - 365) > 20:          # 분기가 빠져 있으면 합계를 만들지 않는다
            continue
        def total(k):
            vals = [q.get(k) for q in w]
            return sum(vals) if all(v is not None for v in vals) else None
        q = w[-1]
        ebitda = total("op_income") + total("dna") if total("op_income") is not None and total("dna") is not None else None
        out.append({"end": q["end"], "net_income": total("net_income"), "revenue": total("revenue"), "fcf": total("fcf"),
                     "ebitda": ebitda, "net_cash": q.get("net_cash"), "shares": q.get("shares_out") or q.get("shares_diluted")})
    # 주식 수가 빈 분기는 앞 분기 값을 이어 쓴다(4분기는 희석 주식 수가 공시되지 않는 경우가 있다)
    last = None
    for r in out:
        r["shares"] = r["shares"] or last
        last = r["shares"]
    return out


def build(fin, price_weekly, today):
    if not fin or not price_weekly:
        return None
    rows = ttm_rows(fin.get("quarterly") or [])
    if not rows:
        return None
    avail = [(dt.date.fromisoformat(r["end"]) + dt.timedelta(days=LAG_DAYS)).isoformat() for r in rows]
    floor = (today - dt.timedelta(days=365 * YEARS + 7)).isoformat()
    series = {k: [] for k, *_ in METRICS}
    for d, price in price_weekly:
        if d < floor:
            continue
        i = bisect.bisect_right(avail, d) - 1
        if i < 0:
            continue
        r = rows[i]
        if not r["shares"]:
            continue
        cap = price * r["shares"]
        vals = {"pe": cap / r["net_income"] if r["net_income"] and r["net_income"] > 0 else None,
                "ev_ebitda": (cap - (r["net_cash"] or 0)) / r["ebitda"] if r["ebitda"] and r["ebitda"] > 0 and r["net_cash"] is not None else None,
                "ps": cap / r["revenue"] if r["revenue"] and r["revenue"] > 0 else None,
                "fcf_yield": r["fcf"] / cap * 100 if r["fcf"] is not None and cap > 0 else None}
        for k, v in vals.items():
            if v is not None:
                series[k].append([d, round(v, 2)])
    out = {"note": __doc__.split("\n\n", 1)[1].strip(), "lag_days": LAG_DAYS, "years": YEARS, "metrics": []}
    for k, name, formula, high_is_expensive in METRICS:
        s = series[k]
        item = {"key": k, "name": name, "formula": formula, "high_is_expensive": high_is_expensive, "series": s, "points": len(s)}
        if len(s) < MIN_POINTS:
            src = {"pe": "net_income", "ev_ebitda": "ebitda", "ps": "revenue", "fcf_yield": "fcf"}[k]
            recent = rows[-1].get(src)
            if recent is None:
                why = {"ebitda": "회사가 분기 감가상각비를 한 항목으로 적지 않아 EBITDA를 만들 수 없습니다(데이터 없음)",
                       "fcf": "분기 영업현금흐름·설비투자 값이 없어 FCF를 만들 수 없습니다(데이터 없음)"}.get(src, "분기 값이 없어 계산할 수 없습니다(데이터 없음)")
            elif recent <= 0 and k != "fcf_yield":
                why = "최근 4개 분기 " + {"net_income": "순이익이", "ebitda": "EBITDA가", "revenue": "매출이"}[src] + " 0 이하(적자)라 배수를 만들지 않습니다"
            else:
                why = "상장 기간이 짧거나 과거에 적자였던 기간이 길어 비교할 값이 2년치가 안 됩니다"
            item.update({"current": s[-1][1] if s else None, "percentile": None, "why_missing": why})
        else:
            vals = sorted(v for _, v in s)
            cur = s[-1][1]
            pct = round(bisect.bisect_right(vals, cur) / len(vals) * 100)
            item.update({"current": cur, "asof": s[-1][0], "percentile": pct, "min": vals[0], "median": vals[len(vals) // 2], "max": vals[-1],
                         "from": s[0][0]})
            cheap = (pct <= 20) if high_is_expensive else (pct >= 80)
            dear = (pct >= 80) if high_is_expensive else (pct <= 20)
            item["reading"] = "5년 중 싼 편" if cheap else "5년 중 비싼 편" if dear else "5년 중 중간"
        out["metrics"].append(item)
    return out
