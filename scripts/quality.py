"""퀄리티 점수: 재무제표(SEC 연간)로 직접 계산한다. AI를 쓰지 않는다.

- Piotroski F-Score (0~9): 재무가 좋아지고 있나
- Altman Z-Score: 부도 위험 (은행·보험·리츠는 맞지 않아 숨김)
- Beneish M-Score: 이익 부풀리기(분식) 의심
- Sloan 발생액 비율: 이익이 현금으로 들어오나
- Graham Number: 보수적 적정 주가

점수마다 값, 구간(안전·주의·위험), 계산에 쓴 입력값과 기간, 계산식을 함께 돌려준다.
입력값이 하나라도 없으면 값을 만들지 않고 '데이터 부족'으로 둔다(0으로 채우지 않는다).
구간 기준은 널리 쓰이는 원 논문·통상 기준이며, 대시보드가 고른 것이다(아래 각 함수 참고).
"""
import math

FIN_SECTORS = ("Real Estate",)
FIN_WORDS = ("bank", "insurance", "reit", "mortgage")   # Yahoo 'Financial Services' 전체로 거르면 비트코인 채굴·AI 클라우드 회사까지 걸려서 업종 이름으로 고른다


def is_financial(fund):
    """은행·보험·리츠: 부채가 영업의 일부라 Altman Z, 순부채/EBITDA 같은 지표가 맞지 않는다."""
    sector, industry = (fund or {}).get("sector") or "", ((fund or {}).get("industry") or "").lower()
    return sector in FIN_SECTORS or any(w in industry for w in FIN_WORDS)


def need(row, *keys):
    return all(row.get(k) is not None for k in keys)


def div(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def r(x, d=2):
    return round(x, d) if x is not None else None


def result(name, value, zone, inputs, formula, period, note=None, digits=2):
    return {"name": name, "value": r(value, digits) if isinstance(value, float) else value, "zone": zone,
            "inputs": inputs, "formula": formula, "period": period, "note": note}


def missing(name, formula, why):
    return {"name": name, "value": None, "zone": "데이터 부족", "inputs": {}, "formula": formula, "period": None, "note": why}


def piotroski(cur, prev):
    """9개 항목마다 1점. 8~9 안전, 4~7 주의, 0~3 위험(통상 기준: 8~9 강함, 0~2 약함)."""
    f = "수익성 4개(ROA>0, 영업현금흐름>0, ROA 개선, 영업현금흐름>순이익) + 재무 3개(장기부채비율 감소, 유동비율 개선, 주식 수 안 늘어남) + 효율 2개(매출총이익률 개선, 자산회전율 개선)"
    keys = ("net_income", "ocf", "total_assets", "current_assets", "current_liabilities", "revenue")
    if not prev or not need(cur, *keys) or not need(prev, *keys):
        return missing("Piotroski F-Score", f, "두 해의 순이익·영업현금흐름·자산·유동자산·유동부채·매출이 모두 있어야 계산합니다")
    roa, roa0 = div(cur["net_income"], prev["total_assets"]), div(prev["net_income"], prev["total_assets"])
    lev = lambda x: div(x.get("debt_long") or 0, x["total_assets"])
    cr, cr0 = div(cur["current_assets"], cur["current_liabilities"]), div(prev["current_assets"], prev["current_liabilities"])
    gp = lambda x: div(x.get("gross_profit"), x["revenue"])
    at, at0 = div(cur["revenue"], prev["total_assets"]), div(prev["revenue"], prev["total_assets"])
    sh, sh0 = cur.get("shares_diluted"), prev.get("shares_diluted")
    checks = [
        ("ROA > 0", roa is not None and roa > 0),
        ("영업현금흐름 > 0", cur["ocf"] > 0),
        ("ROA 개선", roa is not None and roa0 is not None and roa > roa0),
        ("영업현금흐름 > 순이익", cur["ocf"] > cur["net_income"]),
        ("장기부채 비율 감소", lev(cur) <= lev(prev)),
        ("유동비율 개선", cr is not None and cr0 is not None and cr > cr0),
        ("주식 수 안 늘어남", sh is not None and sh0 is not None and sh <= sh0 * 1.005),
        ("매출총이익률 개선", gp(cur) is not None and gp(prev) is not None and gp(cur) > gp(prev)),
        ("자산회전율 개선", at is not None and at0 is not None and at > at0),
    ]
    score = sum(1 for _, ok in checks if ok)
    zone = "안전" if score >= 8 else "주의" if score >= 4 else "위험"
    return result("Piotroski F-Score", score, zone, {k: ("통과" if ok else "미통과") for k, ok in checks}, f,
                  f"FY{cur['end'][2:4]} vs FY{prev['end'][2:4]}", "주식 수·매출총이익을 회사가 적지 않은 항목은 미통과로 셉니다." if sh is None or gp(cur) is None else None)


def altman(cur, market_cap, fund):
    """Z = 1.2×운전자본/자산 + 1.4×이익잉여금/자산 + 3.3×EBIT/자산 + 0.6×시가총액/부채 + 1.0×매출/자산.
    2.99 초과 안전, 1.81~2.99 주의(회색 지대), 1.81 미만 위험(Altman 1968 원식, 제조업 기준)."""
    f = "1.2×(유동자산−유동부채)/총자산 + 1.4×이익잉여금/총자산 + 3.3×영업이익/총자산 + 0.6×시가총액/총부채 + 1.0×매출/총자산"
    if is_financial(fund):
        return {**missing("Altman Z-Score", f, "은행·보험·리츠는 부채가 영업의 일부라 이 지표가 맞지 않아 표시하지 않습니다"), "zone": "해당 없음"}
    keys = ("current_assets", "current_liabilities", "retained_earnings", "op_income", "total_assets", "total_liabilities", "revenue")
    if not need(cur, *keys) or not market_cap:
        return missing("Altman Z-Score", f, "유동자산·유동부채·이익잉여금·영업이익·총자산·총부채·매출·시가총액이 모두 있어야 계산합니다")
    ta = cur["total_assets"]
    parts = {"운전자본/총자산": (cur["current_assets"] - cur["current_liabilities"]) / ta, "이익잉여금/총자산": cur["retained_earnings"] / ta,
             "영업이익/총자산": cur["op_income"] / ta, "시가총액/총부채": market_cap / cur["total_liabilities"], "매출/총자산": cur["revenue"] / ta}
    z = 1.2 * parts["운전자본/총자산"] + 1.4 * parts["이익잉여금/총자산"] + 3.3 * parts["영업이익/총자산"] + 0.6 * parts["시가총액/총부채"] + 1.0 * parts["매출/총자산"]
    zone = "안전" if z > 2.99 else "주의" if z >= 1.81 else "위험"
    return result("Altman Z-Score", z, zone, {k: r(v, 3) for k, v in parts.items()}, f, f"FY{cur['end'][2:4]} 재무 + 현재 시가총액",
                  "제조업 기준 원식입니다. 시가총액이 아주 큰 회사는 값이 크게 나옵니다.")


def beneish(cur, prev):
    """M = −4.84 + 0.92 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI − 0.172 SGAI + 4.679 TATA − 0.327 LVGI.
    −1.78 초과 위험(분식 가능성 높음), −2.22~−1.78 주의, −2.22 이하 안전(Beneish 1999, 통상 쓰는 두 기준선)."""
    f = "−4.84 + 0.92×매출채권지수 + 0.528×매출총이익률지수 + 0.404×자산품질지수 + 0.892×매출성장지수 + 0.115×감가상각지수 − 0.172×판관비지수 + 4.679×발생액/자산 − 0.327×레버리지지수"
    keys = ("receivables", "revenue", "gross_profit", "current_assets", "ppe", "total_assets", "dna", "sga", "net_income", "ocf", "total_liabilities")
    if not prev or not need(cur, *keys) or not need(prev, *keys):
        lack = [k for k in keys if cur.get(k) is None or (prev or {}).get(k) is None]
        return missing("Beneish M-Score", f, "두 해 모두 필요한 항목 중 회사가 적지 않은 것이 있습니다: " + ", ".join(lack))
    try:
        dsri = (cur["receivables"] / cur["revenue"]) / (prev["receivables"] / prev["revenue"])
        gmi = (prev["gross_profit"] / prev["revenue"]) / (cur["gross_profit"] / cur["revenue"])
        aq = lambda x: 1 - (x["current_assets"] + x["ppe"]) / x["total_assets"]
        aqi = aq(cur) / aq(prev)
        sgi = cur["revenue"] / prev["revenue"]
        dep = lambda x: x["dna"] / (x["dna"] + x["ppe"])
        depi = dep(prev) / dep(cur)
        sgai = (cur["sga"] / cur["revenue"]) / (prev["sga"] / prev["revenue"])
        tata = (cur["net_income"] - cur["ocf"]) / cur["total_assets"]
        lvgi = (cur["total_liabilities"] / cur["total_assets"]) / (prev["total_liabilities"] / prev["total_assets"])
    except ZeroDivisionError:
        return missing("Beneish M-Score", f, "분모가 0인 항목이 있어 계산할 수 없습니다")
    m = -4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi
    zone = "위험" if m > -1.78 else "주의" if m > -2.22 else "안전"
    note = "매출이 아주 빠르게 느는 회사는 매출성장지수 때문에 값이 높게 나오기 쉽습니다. 의심 신호일 뿐 분식의 증거가 아닙니다."
    if zone == "위험" and sgi > 1.5:   # 대시보드가 정한 보정: 매출 1.5배 이상 급성장한 해는 오경보가 잦아 한 단계 낮춘다
        zone = "주의"
        note = f"매출이 {sgi:.2f}배로 급성장해 이 모델의 오경보가 잦은 구간이라 '위험' 대신 '주의'로 낮춰 표시합니다(대시보드가 정한 보정). 원래 기준으로는 −1.78 초과라 위험입니다."
    inputs = {"매출채권지수(DSRI)": dsri, "매출총이익률지수(GMI)": gmi, "자산품질지수(AQI)": aqi, "매출성장지수(SGI)": sgi,
              "감가상각지수(DEPI)": depi, "판관비지수(SGAI)": sgai, "발생액/자산(TATA)": tata, "레버리지지수(LVGI)": lvgi}
    return result("Beneish M-Score", m, zone, {k: r(v, 3) for k, v in inputs.items()}, f, f"FY{cur['end'][2:4]} vs FY{prev['end'][2:4]}", note)


def sloan(cur, prev):
    """발생액 비율 = (순이익 − 영업현금흐름) ÷ 평균 총자산. 5% 이하 안전, 5~10% 주의, 10% 초과 위험
    (Sloan 1996: 발생액 상위 구간 회사의 이후 수익률이 낮음. 구간 숫자는 대시보드가 정한 값)."""
    f = "(순이익 − 영업현금흐름) ÷ 평균 총자산"
    if not need(cur, "net_income", "ocf", "total_assets"):
        return missing("Sloan 발생액 비율", f, "순이익·영업현금흐름·총자산이 있어야 계산합니다")
    avg = (cur["total_assets"] + prev["total_assets"]) / 2 if prev and prev.get("total_assets") else cur["total_assets"]
    v = (cur["net_income"] - cur["ocf"]) / avg * 100
    zone = "안전" if v <= 5 else "주의" if v <= 10 else "위험"
    return result("Sloan 발생액 비율", v, zone, {"순이익": cur["net_income"], "영업현금흐름": cur["ocf"], "평균 총자산": avg}, f + " (%)",
                  f"FY{cur['end'][2:4]}", "음수면 이익보다 현금이 더 많이 들어온 것이라 좋은 신호입니다.", 1)


def graham(ttm_net_income, cur_q, price, shares):
    """Graham Number = √(22.5 × EPS × 주당순자산). 주가가 이보다 낮으면 안전, 1.5배 이하 주의, 그 위는 위험(비싼 편).
    EPS는 최근 4개 분기 순이익 ÷ 주식 수, 주당순자산은 최근 분기 자기자본 ÷ 주식 수."""
    f = "√(22.5 × EPS × 주당순자산). 22.5 = PER 15배 × PBR 1.5배 (그레이엄의 보수적 기준)"
    if not ttm_net_income or not cur_q or cur_q.get("equity") is None or not shares or not price:
        return missing("Graham Number", f, "최근 4개 분기 순이익, 자기자본, 주식 수, 주가가 있어야 계산합니다")
    eps, bvps = ttm_net_income / shares, cur_q["equity"] / shares
    if eps <= 0 or bvps <= 0:
        return {**missing("Graham Number", f, "적자이거나 자본잠식이라 계산하지 않습니다"), "zone": "해당 없음",
                "inputs": {"EPS (최근 4분기)": r(eps), "주당순자산": r(bvps)}}
    g = math.sqrt(22.5 * eps * bvps)
    ratio = price / g
    zone = "안전" if ratio <= 1 else "주의" if ratio <= 1.5 else "위험"
    return result("Graham Number", g, zone, {"EPS (최근 4분기)": r(eps), "주당순자산": r(bvps), "현재가": price, "현재가 ÷ Graham Number": r(ratio)}, f,
                  f"최근 분기 {cur_q['end']}", "성장주는 거의 항상 '위험(비싼 편)'으로 나옵니다. 가치주 기준의 참고값입니다.")


def build(fin, fund, price):
    """종목 하나의 퀄리티 점수 묶음. 경고(위험)를 맨 앞에 모아 둔다."""
    annual = (fin or {}).get("annual") or []
    if len(annual) < 1:
        return None
    cur, prev = annual[-1], annual[-2] if len(annual) >= 2 else None
    quarterly = (fin or {}).get("quarterly") or []
    cur_q = quarterly[-1] if quarterly else cur
    ttm_ni = ((fin or {}).get("ttm") or {}).get("net_income") or (cur.get("net_income") if not quarterly else None)
    shares = cur_q.get("shares_out") or cur.get("shares_out") or cur.get("shares_diluted")
    scores = [piotroski(cur, prev), altman(cur, (fund or {}).get("market_cap"), fund), beneish(cur, prev), sloan(cur, prev),
              graham(ttm_ni, cur_q, price, shares)]
    warnings = []
    for s in scores:
        if s["zone"] == "위험" and s["name"] in ("Altman Z-Score", "Beneish M-Score", "Sloan 발생액 비율"):
            warnings.append({"Altman Z-Score": "부도 위험 신호", "Beneish M-Score": "이익 부풀리기(분식) 의심 신호",
                             "Sloan 발생액 비율": "이익에 비해 현금이 적게 들어옴"}[s["name"]] + f" ({s['name']} {s['value']})")
    return {"financial_sector": is_financial(fund), "warnings": warnings, "scores": scores,
            "note": "재무제표로 직접 계산한 값이며 AI를 쓰지 않았습니다. 구간 기준은 원 논문·통상 기준을 대시보드가 고른 것입니다."}
