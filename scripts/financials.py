"""SEC XBRL 재무제표(companyfacts)로 만드는 장기 재무 추이와 실적 보도자료.

- 키가 필요 없는 공개 데이터다. 하루 한 번만 받는다.
- 회사가 공시에 적은 숫자만 쓴다. 비율(마진, ROIC, FCF 등)은 그 숫자로 여기서 계산한다.
- 미국 SEC에 공시하는 회사만 된다. 한국 종목은 없다.
- 상장 전 기간은 자료가 없다. 외국 기업(20-F)은 연간 자료만 있는 경우가 많다.

분기 값 만드는 법
- 손익계산서는 분기(약 3개월) 값이 공시에 그대로 있다.
- 현금흐름표는 10-Q에 '연초부터 누적'(3·6·9개월)으로만 있어서, 누적값의 차이로 분기 값을 만든다.
- 4분기는 따로 공시하지 않아서 '연간 − 9개월 누적'으로 만든다.
"""
import datetime as dt
import html
import re
import sys

import sec
import yfinance as yf

FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json"
RELEASE_CHARS = 60000   # AI용 파일에 넣을 실적 보도자료 본문 길이(글자)
YEARS = 15              # 연간 표에 남길 햇수
QUARTERS = 28           # 분기 표에 남길 분기 수 (밸류에이션 5년 퍼센타일에 최근 4분기 합계가 필요해 7년치)

# 항목마다 회사가 쓸 수 있는 XBRL 이름. 앞에 있는 이름을 먼저 쓰고, 그 기간에 값이 없으면 다음 이름으로 채운다.
FLOW = {   # 기간 값 (손익·현금흐름)
    "revenue": ["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:Revenues", "us-gaap:SalesRevenueNet",
                "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax", "us-gaap:SalesRevenueGoodsNet", "ifrs-full:Revenue"],
    "cost_of_revenue": ["us-gaap:CostOfRevenue", "us-gaap:CostOfGoodsAndServicesSold", "us-gaap:CostOfGoodsSold", "ifrs-full:CostOfSales"],
    "gross_profit": ["us-gaap:GrossProfit", "ifrs-full:GrossProfit"],
    "rnd": ["us-gaap:ResearchAndDevelopmentExpense", "us-gaap:ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
            "ifrs-full:ResearchAndDevelopmentExpense"],
    "op_income": ["us-gaap:OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities"],
    "pretax_income": ["us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                      "ifrs-full:ProfitLossBeforeTax"],
    "income_tax": ["us-gaap:IncomeTaxExpenseBenefit", "ifrs-full:IncomeTaxExpenseContinuingOperations"],
    "net_income": ["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss", "ifrs-full:ProfitLossAttributableToOwnersOfParent", "ifrs-full:ProfitLoss"],
    "eps_diluted": ["us-gaap:EarningsPerShareDiluted", "us-gaap:EarningsPerShareBasicAndDiluted", "ifrs-full:DilutedEarningsLossPerShare"],
    "shares_diluted": ["us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding", "ifrs-full:WeightedAverageShares"],
    "ocf": ["us-gaap:NetCashProvidedByUsedInOperatingActivities", "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            "ifrs-full:CashFlowsFromUsedInOperatingActivities"],
    "capex": ["us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", "us-gaap:PaymentsToAcquireProductiveAssets",
              "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "sbc": ["us-gaap:ShareBasedCompensation", "us-gaap:AllocatedShareBasedCompensationExpense"],
    "sga": ["us-gaap:SellingGeneralAndAdministrativeExpense", "ifrs-full:SellingGeneralAndAdministrativeExpense"],
    "selling": ["us-gaap:SellingAndMarketingExpense", "us-gaap:SellingExpense"],          # 판관비를 나눠 적는 회사용
    "admin": ["us-gaap:GeneralAndAdministrativeExpense"],
    "dna": ["us-gaap:DepreciationDepletionAndAmortization", "us-gaap:DepreciationAndAmortization", "us-gaap:DepreciationAmortizationAndAccretionNet",
            "us-gaap:Depreciation", "ifrs-full:DepreciationAndAmortisationExpense"],
    "buyback": ["us-gaap:PaymentsForRepurchaseOfCommonStock"],
    "dividends": ["us-gaap:PaymentsOfDividendsCommonStock", "us-gaap:PaymentsOfDividends"],
}
STOCK = {  # 시점 값 (재무상태표)
    "cash": ["us-gaap:CashAndCashEquivalentsAtCarryingValue", "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
             "ifrs-full:CashAndCashEquivalents"],
    "short_investments": ["us-gaap:ShortTermInvestments", "us-gaap:MarketableSecuritiesCurrent", "us-gaap:AvailableForSaleSecuritiesDebtSecuritiesCurrent",
                          "us-gaap:DebtSecuritiesCurrent", "ifrs-full:CurrentInvestments"],
    "total_assets": ["us-gaap:Assets", "ifrs-full:Assets"],
    "current_assets": ["us-gaap:AssetsCurrent", "ifrs-full:CurrentAssets"],
    "current_liabilities": ["us-gaap:LiabilitiesCurrent", "ifrs-full:CurrentLiabilities"],
    "total_liabilities": ["us-gaap:Liabilities", "ifrs-full:Liabilities"],
    "equity": ["us-gaap:StockholdersEquity", "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
               "ifrs-full:EquityAttributableToOwnersOfParent", "ifrs-full:Equity"],
    "debt_total": ["us-gaap:DebtLongtermAndShorttermCombinedAmount", "us-gaap:LongTermDebt", "ifrs-full:Borrowings",
                   "us-gaap:DebtInstrumentCarryingAmount"],
    "debt_long": ["us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermNotesAndLoans", "us-gaap:LongTermNotesPayable",
                  "us-gaap:ConvertibleNotesPayableNoncurrent", "us-gaap:LongTermDebtAndCapitalLeaseObligations",
                  "ifrs-full:NoncurrentPortionOfNoncurrentBorrowings", "ifrs-full:NoncurrentBorrowings"],
    "debt_current": ["us-gaap:LongTermDebtCurrent", "us-gaap:DebtCurrent", "us-gaap:NotesPayableCurrent", "us-gaap:ShortTermBorrowings",
                     "ifrs-full:CurrentPortionOfNoncurrentBorrowings", "ifrs-full:CurrentBorrowings"],
    "inventory": ["us-gaap:InventoryNet", "ifrs-full:Inventories"],
    "receivables": ["us-gaap:AccountsReceivableNetCurrent", "us-gaap:ReceivablesNetCurrent", "ifrs-full:TradeAndOtherCurrentReceivables"],
    "ppe": ["us-gaap:PropertyPlantAndEquipmentNet", "us-gaap:PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
            "ifrs-full:PropertyPlantAndEquipment"],
    "retained_earnings": ["us-gaap:RetainedEarningsAccumulatedDeficit", "ifrs-full:RetainedEarnings"],
    "liab_and_equity": ["us-gaap:LiabilitiesAndStockholdersEquity", "ifrs-full:EquityAndLiabilities"],   # 총부채를 따로 적지 않는 회사용
    "equity_total": ["us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "us-gaap:StockholdersEquity", "ifrs-full:Equity"],
}
SHARES_OUT = ["us-gaap:CommonStockSharesOutstanding", "ifrs-full:NumberOfSharesOutstanding"]   # 기말 발행주식 수 (시점 값, 주식 수 단위)
# 항목 설명 (AI용 파일의 안내문에 그대로 들어간다)
LABELS = {
    "revenue": "매출", "cost_of_revenue": "매출원가", "gross_profit": "매출총이익", "rnd": "연구개발비", "op_income": "영업이익",
    "pretax_income": "세전이익", "income_tax": "법인세", "net_income": "순이익", "eps_diluted": "희석 EPS (주당 순이익)",
    "shares_diluted": "희석 가중평균 주식 수", "ocf": "영업현금흐름", "capex": "설비투자 (유형자산 취득, 양수로 적음)",
    "fcf": "잉여현금흐름 = 영업현금흐름 − 설비투자", "sbc": "주식보상비용", "sga": "판매관리비", "dna": "감가상각비 (상각 포함)",
    "receivables": "매출채권", "selling": "판매비", "admin": "관리비", "liab_and_equity": "부채와 자본 합계", "equity_total": "자본 합계 (비지배지분 포함)", "ppe": "유형자산 (순액)", "retained_earnings": "이익잉여금 (결손금이면 음수)", "shares_out": "기말 발행주식 수", "buyback": "자사주 매입", "dividends": "배당 지급",
    "cash": "현금성 자산", "short_investments": "단기 투자자산", "total_assets": "총자산", "current_assets": "유동자산",
    "current_liabilities": "유동부채", "total_liabilities": "총부채", "equity": "자기자본", "debt_long": "장기 차입금",
    "debt_current": "1년 내 만기 차입금", "debt_total": "차입금 합계 (회사가 적은 값)",
    "debt": "차입금 합계. 회사가 합계를 적었으면 그 값, 아니면 장기 + 1년 내 만기. 장기 차입금 값이 없으면 비워 둔다", "inventory": "재고자산",
    "net_cash": "순현금 = 현금성 자산 + 단기 투자자산 − 차입금 합계 (음수면 순부채)",
    "gross_margin_pct": "매출총이익률 %", "op_margin_pct": "영업이익률 %", "net_margin_pct": "순이익률 %", "fcf_margin_pct": "FCF 마진 %",
    "rnd_pct": "매출 대비 연구개발비 %", "sbc_pct": "매출 대비 주식보상비용 %", "capex_pct": "매출 대비 설비투자 %",
    "revenue_growth_pct": "매출 성장률 % (연간: 전년 대비, 분기: 전년 같은 분기 대비)", "op_income_growth_pct": "영업이익 성장률 %",
    "eps_growth_pct": "EPS 성장률 %", "fcf_growth_pct": "FCF 성장률 %",
    "roe_pct": "ROE % = 순이익 ÷ 평균 자기자본", "roic_pct": "ROIC % = 세후 영업이익 ÷ 평균 투하자본 (아래 계산 방법 참고)",
    "tax_rate_pct": "실효 법인세율 % = 법인세 ÷ 세전이익", "share_change_pct": "희석 주식 수 증감 % (전년 대비, +면 희석)",
}
METHOD = [
    "모든 원본 숫자는 회사가 SEC에 낸 10-K·10-Q·20-F의 XBRL 값이다. 같은 기간을 나중에 고쳐 낸 값이 있으면 가장 나중에 낸 값을 쓴다.",
    "현금흐름표 분기 값은 누적값(3·6·9개월)의 차이로, 4분기 값은 '연간 − 9개월 누적'으로 만든다.",
    "ROIC: 세후 영업이익 = 영업이익 × (1 − 실효 법인세율). 실효 세율이 0~50% 밖이거나 없으면 21%(미국 법인세율)를 쓴다. "
    "투하자본 = 자기자본 + 차입금 합계 − 현금성 자산 − 단기 투자자산. 기초와 기말의 평균을 쓰고, 0 이하이거나 총자산의 10% 미만이면(현금이 많아 값이 수백 %로 튀는 경우) 계산하지 않는다(null). 대시보드가 정한 방식이다.",
    "분기 ROE·ROIC는 최근 4개 분기 합계로 계산한다. 차입금에는 리스 부채가 들어가지 않는다. 차입금 값이 없으면 ROIC 계산에서 0으로 본다.",
    "주식 분할: 옛 공시의 EPS와 주식 수는 그 공시를 낸 뒤에 있었던 분할(Yahoo 분할 이력)만큼 나누거나 곱해 지금 주식 기준으로 맞춘다. splits 가 null 이면 보정하지 못한 것이다.",
    "EPS와 주식 수는 더할 수 없는 값이라 4분기 값을 만들지 않는다(4분기 EPS는 비어 있다).",
    "총부채를 따로 적지 않은 회사는 '부채와 자본 합계 − 자본 합계(비지배지분 포함)'로, 판관비를 나눠 적은 회사는 '판매비 + 관리비'로 채운다.",
    "회사가 쓰는 XBRL 항목 이름이 기간마다 달라 일부 칸이 비어 있을 수 있다. 빈 칸은 계산하지 않는다(0으로 보지 않는다).",
]


def days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def pick_unit(units, money):
    """한 항목의 단위 중 쓸 것을 고른다. 돈은 가장 최근 값의 통화를 따른다."""
    if not money:
        keys = [k for k in units if k in ("shares", "USD/shares") or "/shares" in k]
    else:
        keys = [k for k in units if "/" not in k and k != "shares" and k != "pure"]
    if not keys:
        return None, []
    key = max(keys, key=lambda k: max(x["end"] for x in units[k]))
    return key, units[key]


def latest_by_period(facts, instant, splits=None, per_share=False):
    """같은 기간(시작·끝)을 여러 번 낸 경우 가장 나중에 낸 값만 남긴다.
    splits(주식 분할 [(날짜, 비율)])가 있으면 EPS(per_share)·주식 수를 지금 주식 기준으로 맞춘다.
    공시를 낸 날 뒤에 있었던 분할만 반영한다(그 전 분할은 회사가 이미 반영해 적는다)."""
    out = {}
    for x in facts:
        if x.get("form") not in ("10-K", "10-Q", "20-F", "40-F", "10-K/A", "10-Q/A", "20-F/A", "10-KT", "6-K"):
            continue
        key = x["end"] if instant else (x.get("start"), x["end"])
        if not instant and not x.get("start"):
            continue
        if key not in out or x["filed"] >= out[key]["filed"]:
            out[key] = x
    result = {}
    for k, v in out.items():
        factor = 1.0
        for when, ratio_ in splits or []:
            if when > v["filed"]:
                factor *= ratio_
        result[k] = v["val"] / factor if per_share else v["val"] * factor
    return result


def merged(gaap, names, money, instant, currency, splits=None):
    """이름 목록을 우선순위대로 합쳐 기간 → 값 사전을 만든다. splits 는 EPS·주식 수에만 준다."""
    result, unit_seen = {}, None
    for full in names:
        ns, name = full.split(":")
        item = gaap.get(ns, {}).get(name)
        if not item:
            continue
        unit, facts = pick_unit(item["units"], money)
        if not facts or (money and currency and unit != currency):
            continue
        unit_seen = unit_seen or unit
        for k, v in latest_by_period(facts, instant, splits, per_share=unit is not None and "/shares" in unit).items():
            result.setdefault(k, v)
    return result, unit_seen


def split_periods(values):
    """기간 값 → (연간 {(시작,끝): 값}, 분기 {(시작,끝): 값})."""
    annual = {k: v for k, v in values.items() if 350 <= days(*k) <= 380}
    quarter = {k: v for k, v in values.items() if 80 <= days(*k) <= 100}
    by_start = {}
    for (s, e), v in values.items():
        if days(s, e) <= 380:
            by_start.setdefault(s, []).append((e, v))
    for s, chain in by_start.items():   # 연초부터 누적값끼리 빼서 분기 값을 만든다 (현금흐름표, 4분기)
        chain.sort()
        for (e1, v1), (e2, v2) in zip(chain, chain[1:]):
            q_start = (dt.date.fromisoformat(e1) + dt.timedelta(days=1)).isoformat()
            if 80 <= days(q_start, e2) <= 100 and (q_start, e2) not in quarter:
                quarter[(q_start, e2)] = v2 - v1
    return annual, quarter


def pct(a, b):
    return round(a / b * 100, 1) if a is not None and b not in (None, 0) else None


def growth(now, before):
    if now is None or before is None or before == 0:
        return None
    return round((now - before) / abs(before) * 100, 1)


def r(x):
    if x is None:
        return None
    return round(x, 4) if abs(x) < 10 else round(x, 2) if abs(x) < 1000 else round(x)


def build_rows(periods, flows, stocks, quarterly):
    """기간 목록마다 원본 값과 계산 값을 한 줄로 만든다."""
    rows = []
    for s, e in periods:
        row = {"start": s, "end": e}
        for k, vals in flows.items():
            row[k] = vals.get((s, e))
        for k, vals in stocks.items():
            row[k] = vals.get(e)
        rows.append(row)
    for row in rows:
        # 회사가 합계를 적지 않은 항목은 나눠 적은 값으로 만든다
        if row.get("total_liabilities") is None and row.get("liab_and_equity") is not None and row.get("equity_total") is not None:
            row["total_liabilities"] = row["liab_and_equity"] - row["equity_total"]
        if row.get("sga") is None and row.get("selling") is not None and row.get("admin") is not None:
            row["sga"] = row["selling"] + row["admin"]
        if row["gross_profit"] is None and row["revenue"] is not None and row["cost_of_revenue"] is not None:
            row["gross_profit"] = row["revenue"] - row["cost_of_revenue"]
        row["fcf"] = row["ocf"] - row["capex"] if row["ocf"] is not None and row["capex"] is not None else None
        row["debt"] = row["debt_total"] if row["debt_total"] is not None else \
            row["debt_long"] + (row["debt_current"] or 0) if row["debt_long"] is not None else None
        if row["cash"] is not None:
            row["net_cash"] = row["cash"] + (row["short_investments"] or 0) - (row["debt"] or 0)
        else:
            row["net_cash"] = None
        rev = row["revenue"]
        for k, src in (("gross_margin_pct", "gross_profit"), ("op_margin_pct", "op_income"), ("net_margin_pct", "net_income"), ("fcf_margin_pct", "fcf"),
                       ("rnd_pct", "rnd"), ("sbc_pct", "sbc"), ("capex_pct", "capex")):
            row[k] = pct(row[src], rev) if rev and rev > 0 else None
        t = row["income_tax"] / row["pretax_income"] if row["income_tax"] is not None and row["pretax_income"] and row["pretax_income"] > 0 else None
        row["tax_rate_pct"] = round(t * 100, 1) if t is not None else None
    # 성장률: 연간은 바로 앞 해, 분기는 4개 분기 전(전년 같은 분기)과 비교한다
    lag = 4 if quarterly else 1
    for i, row in enumerate(rows):
        prev = rows[i - lag] if i >= lag and abs(days(rows[i - lag]["end"], row["end"]) - 365 * (1 if quarterly else lag)) <= 20 else None
        for k, src in (("revenue_growth_pct", "revenue"), ("op_income_growth_pct", "op_income"), ("eps_growth_pct", "eps_diluted"), ("fcf_growth_pct", "fcf")):
            row[k] = growth(row[src], prev[src]) if prev else None
        row["share_change_pct"] = growth(row["shares_diluted"], prev["shares_diluted"]) if prev else None
    # ROE·ROIC: 기초·기말 평균 자본으로. 분기는 최근 4개 분기 합계 이익을 쓴다
    for i, row in enumerate(rows):
        before = rows[i - lag] if i >= lag else None
        if quarterly:
            window = rows[i - 3:i + 1] if i >= 3 else []
            if len(window) != 4 or abs(days(window[0]["start"], row["end"]) - 365) > 20:
                window = []
            ni = sum(w["net_income"] for w in window) if window and all(w["net_income"] is not None for w in window) else None
            oi = sum(w["op_income"] for w in window) if window and all(w["op_income"] is not None for w in window) else None
            taxes = [w["income_tax"] for w in window if w["income_tax"] is not None]
            pre = [w["pretax_income"] for w in window if w["pretax_income"] is not None]
            t = sum(taxes) / sum(pre) if len(taxes) == 4 and len(pre) == 4 and sum(pre) > 0 else None
        else:
            ni, oi = row["net_income"], row["op_income"]
            t = row["tax_rate_pct"] / 100 if row["tax_rate_pct"] is not None else None
        if t is None or not 0 <= t <= 0.5:
            t = 0.21

        def avg(key_fn):
            a, b = key_fn(row), key_fn(before) if before else None
            return (a + b) / 2 if a is not None and b is not None else a
        eq = avg(lambda x: x["equity"])
        row["roe_pct"] = pct(ni, eq) if eq and eq > 0 else None
        ic_of = lambda x: x["equity"] + (x["debt"] or 0) - (x["cash"] or 0) - (x["short_investments"] or 0) if x["equity"] is not None else None
        ic = avg(ic_of)
        assets = avg(lambda x: x["total_assets"])
        # 현금이 많아 투하자본이 아주 작으면 ROIC가 수백 %로 튀어 의미가 없다. 총자산의 10% 미만이면 비워 둔다
        tiny = ic is not None and assets and ic < assets * 0.1
        row["roic_pct"] = pct(oi * (1 - t), ic) if oi is not None and ic and ic > 0 and not tiny else None
    return [{k: r(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v for k, v in row.items()} for row in rows]


def statements(cik, since=None, splits=None):
    """한 회사의 연간·분기 재무 표. since(날짜)가 있으면 그 뒤에 끝난 기간만 남긴다.
    splits 는 주식 분할 목록 [(날짜, 비율)]이다. 옛 공시의 EPS·주식 수를 지금 주식 기준으로 맞추는 데 쓴다."""
    data = sec.get(FACTS.format(int(cik))).json()
    gaap = data.get("facts", {})
    rev_raw, currency = merged(gaap, FLOW["revenue"], True, False, None)
    if not rev_raw:
        raise ValueError("매출 항목을 찾지 못했습니다")
    flows, stocks = {}, {}
    for k, names in FLOW.items():
        money = k not in ("eps_diluted", "shares_diluted")
        flows[k], _ = merged(gaap, names, money, False, currency if money else None, None if money else splits)
    for k, names in STOCK.items():
        stocks[k], _ = merged(gaap, names, True, True, currency)
    stocks["shares_out"], _ = merged(gaap, SHARES_OUT, False, True, None, splits)
    split = {k: split_periods(v) for k, v in flows.items()}
    # EPS와 주식 수는 누적값의 차이로 분기를 만들 수 없다(합산이 안 되는 값). 분기 값이 직접 있는 것만 쓴다
    for k in ("eps_diluted", "shares_diluted"):
        a, _ = split[k]
        split[k] = (a, {p: v for p, v in flows[k].items() if 80 <= days(*p) <= 100})
    annual_flows = {k: v[0] for k, v in split.items()}
    quarter_flows = {k: v[1] for k, v in split.items()}
    annual_periods = sorted(annual_flows["revenue"], key=lambda p: p[1])
    quarter_periods = sorted(quarter_flows["revenue"], key=lambda p: p[1])
    # 같은 끝 날짜에 시작일이 조금 다른 기간이 겹치면(52·53주 회계연도) 하나만 남긴다
    dedupe = lambda ps: list({e: (s, e) for s, e in ps}.values())
    annual_periods, quarter_periods = dedupe(annual_periods), dedupe(quarter_periods)
    if since:
        annual_periods = [p for p in annual_periods if p[1] >= since]
        quarter_periods = [p for p in quarter_periods if p[1] >= since]

    def align(vals, periods):   # 시작일이 하루이틀 다른 기간도 끝 날짜로 맞춘다
        by_end = {}
        for (s, e), v in vals.items():
            by_end.setdefault(e, v)
        return {p: vals.get(p, by_end.get(p[1])) for p in periods}
    annual_flows = {k: align(v, annual_periods) for k, v in annual_flows.items()}
    quarter_flows = {k: align(v, quarter_periods) for k, v in quarter_flows.items()}
    annual = build_rows(annual_periods, annual_flows, stocks, False)
    quarterly = build_rows(quarter_periods, quarter_flows, stocks, True)
    ttm = None
    if len(quarterly) >= 4 and abs(days(quarterly[-4]["start"], quarterly[-1]["end"]) - 365) <= 20:
        last4 = quarterly[-4:]
        ttm = {"end": quarterly[-1]["end"]}
        for k in ("revenue", "gross_profit", "op_income", "net_income", "ocf", "capex", "fcf", "sbc", "rnd"):
            vals = [q[k] for q in last4]
            ttm[k] = r(sum(vals)) if all(v is not None for v in vals) else None
        for k, src in (("gross_margin_pct", "gross_profit"), ("op_margin_pct", "op_income"), ("net_margin_pct", "net_income"), ("fcf_margin_pct", "fcf")):
            ttm[k] = pct(ttm[src], ttm["revenue"]) if ttm["revenue"] and ttm["revenue"] > 0 else None
        ttm["roe_pct"], ttm["roic_pct"] = quarterly[-1]["roe_pct"], quarterly[-1]["roic_pct"]
    # 분기 기본 가중평균 주식 수. 희석(주식 수 증가) 추이를 보는 데 쓴다. 같은 분기에 값이 여럿이면 가장 늦게 낸 공시를 쓴다
    basic = {}
    for row in sorted(gaap.get("us-gaap", {}).get("WeightedAverageNumberOfSharesOutstandingBasic", {}).get("units", {}).get("shares") or [],
                      key=lambda x: x.get("filed") or ""):
        if row.get("start") and row.get("end") and row.get("val") and 80 <= days(row["start"], row["end"]) <= 100:
            basic[row["end"]] = row["val"]
    shares_q = [{"end": d, "shares": basic[d]} for d in sorted(basic)][-12:]
    return {"entity": data.get("entityName"), "currency": currency, "annual": annual[-YEARS:], "quarterly": quarterly[-QUARTERS:], "ttm": ttm,
            "shares_basic_q": shares_q}


def strip_html(raw):
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", raw)
    raw = re.sub(r"(?i)</t[dh]>", " | ", raw)
    raw = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    raw = re.sub(r"[ \t\xa0]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n", raw).strip()


def earnings_release(cik, old):
    """가장 최근 실적 발표 8-K(항목 2.02)의 보도자료(첨부 99.1). 외국 기업은 6-K라 찾지 않는다."""
    rows = sec.recent(cik)
    f = next((x for x in rows if x["form"] == "8-K" and "2.02" in (x.get("items") or "").split(",")), None)
    if not f:
        return None
    if old and old.get("acc") == f["accessionNumber"]:
        return old
    acc = f["accessionNumber"].replace("-", "")
    base = f"{sec.ARCHIVE}/{int(cik)}/{acc}"
    # 공시 목록 페이지에서 첨부의 종류(EX-99.1 보도자료, EX-99.2 CFO 설명·발표 자료)를 읽는다
    page = sec.get(f"{base}/{f['accessionNumber']}-index.html").text
    docs = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", page):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)]
        if len(cells) >= 4 and re.match(r"EX-99\.[12]$", cells[3]) and cells[2].lower().endswith((".htm", ".html")):
            docs.append((cells[3], cells[2]))
    docs = [n for _, n in sorted(docs)]
    if not docs:
        raise ValueError("보도자료 첨부(EX-99)를 찾지 못했습니다")
    parts = []
    for n in docs[:2]:   # 보도자료와 CFO 설명 자료처럼 두 개가 붙는 회사가 있다
        parts.append(f"=== {n} ===\n" + strip_html(sec.get(f"{base}/{n}").text))
    text = "\n\n".join(parts)
    return {"date": f["filingDate"], "period": f.get("reportDate"), "acc": f["accessionNumber"],
            "url": f"{base}/{docs[0]}", "files": [f"{base}/{n}" for n in docs[:2]],
            "chars": len(text), "text": text[:RELEASE_CHARS], "truncated": len(text) > RELEASE_CHARS}


def weekly_prices(tickers):
    """밸류에이션 5년 위치 계산용 주간 종가 6년치 (Yahoo, 주식 분할 반영). 실패하면 빈 사전."""
    if not tickers:
        return {}
    try:
        df = yf.download(tickers, period="6y", interval="1wk", auto_adjust=False, progress=False, threads=False, group_by="ticker")
    except Exception as exc:
        print(f"[참고] 주간 주가: {exc}", file=sys.stderr)
        return {}
    out = {}
    for t in tickers:
        try:
            close = (df[t] if len(tickers) > 1 else df)["Close"].dropna()
            out[t] = [[d.date().isoformat(), round(float(v), 4)] for d, v in close.items()]
        except Exception:
            continue
    return out


VERSION = 3   # 저장 형식이 바뀌면 올린다. 다르면 같은 날이라도 전부 다시 받는다


def build(config, prev, today, warn):
    """하루 한 번 관심 종목(미국)의 장기 재무와 실적 보도자료를 모은다. prev 는 이전 결과(financials.json).
    같은 날 다시 돌면 이미 받은 종목은 그대로 두고, 새로 추가된 종목만 받는다."""
    prev = prev or {}
    old = prev.get("companies") or {}
    entries = config["watchlist"].get("us", [])
    same_day = prev.get("fetched") == today.isoformat() and prev.get("v") == VERSION
    not_on_sec = set(prev.get("not_on_sec") or []) if same_day else set()
    todo = [e for e in entries if not same_day or (e["ticker"] not in old and e["ticker"] not in not_on_sec)]
    keep = {e["ticker"] for e in entries}
    companies = {t: c for t, c in old.items() if same_day and t in keep}   # 오늘 이미 받은 종목 (목록에서 뺀 종목은 버린다)
    result = {"v": VERSION, "fetched": today.isoformat() if same_day or todo else prev.get("fetched"), "source": "SEC EDGAR XBRL (companyfacts)",
              "labels": LABELS, "method": METHOD, "companies": companies, "not_on_sec": sorted(not_on_sec & keep)}
    if not todo:
        return result
    try:
        listing = sec.get("https://www.sec.gov/files/company_tickers.json").json().values()
        ciks = {row["ticker"]: row["cik_str"] for row in listing}
    except Exception as exc:
        warn("SEC 종목 목록 (재무)", exc)
        return {**prev, "companies": {t: c for t, c in old.items() if t in keep}} if not same_day else result
    weekly = weekly_prices([e["ticker"] for e in todo if e["ticker"] in ciks])
    for entry in todo:
        t = entry["ticker"]
        if t not in ciks:
            not_on_sec.add(t)
            continue
        cik = ciks[t]
        try:
            try:   # 주식 분할 이력 (Yahoo). 못 받으면 보정 없이 만들고 표시한다
                sp = yf.Ticker(t).splits
                splits = [(d.date().isoformat(), float(v)) for d, v in sp.items() if v and v > 0]
            except Exception as exc:
                print(f"[참고] 주식 분할 이력 {t}: {exc}", file=sys.stderr)
                splits = None
            st = statements(cik, entry.get("sec_since"), splits)
            st["splits"] = [{"date": d, "ratio": v} for d, v in splits] if splits is not None else None
            st["price_weekly"] = weekly.get(t)
            companies[t] = {"cik": int(cik), "name": entry["name"], **st, "since": entry.get("sec_since"), "since_note": entry.get("sec_since_note"),
                            "source_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(cik)}&type=10-"}
        except Exception as exc:
            warn(f"SEC 재무 {t}", exc)
            if t in old:
                companies[t] = {**old[t], "stale": True}
            continue
        try:
            companies[t]["release"] = earnings_release(cik, (old.get(t) or {}).get("release"))
        except Exception as exc:
            print(f"[참고] 실적 보도자료 {t}: {exc}", file=sys.stderr)
            companies[t]["release"] = (old.get(t) or {}).get("release")
    result["fetched"] = today.isoformat()
    result["not_on_sec"] = sorted(not_on_sec & keep)
    return result


def ltm_rows(quarterly, keep=16):
    """분기 표 → 분기 말마다 최근 12개월(4개 분기 합계) 표. 분기가 빠지면 그 칸은 만들지 않는다.
    손익·현금흐름은 4개 분기 합계, 재무상태(순현금 등)와 ROE·ROIC는 그 분기 값을 쓴다."""
    flows = ("revenue", "gross_profit", "op_income", "net_income", "ocf", "capex", "fcf", "sbc", "rnd", "eps_diluted")
    out = []
    for i in range(3, len(quarterly)):
        w = quarterly[i - 3:i + 1]
        if abs(days(w[0]["start"], w[-1]["end"]) - 365) > 20:
            continue
        q = w[-1]
        row = {"start": w[0]["start"], "end": q["end"]}
        for k in flows:
            vals = [x.get(k) for x in w]
            row[k] = r(sum(vals)) if all(v is not None for v in vals) else None
        for k in ("net_cash", "roe_pct", "roic_pct", "shares_diluted", "cash", "debt"):
            row[k] = q.get(k)
        if row["eps_diluted"] is None and row["net_income"] is not None:   # 4분기 EPS가 없으면 순이익 ÷ 최근 희석 주식 수로 근사
            sh = next((x.get("shares_diluted") for x in reversed(w) if x.get("shares_diluted")), None)
            if sh:
                row["eps_diluted"], row["eps_approx"] = r(row["net_income"] / sh), True
        rev = row["revenue"]
        for k, src in (("gross_margin_pct", "gross_profit"), ("op_margin_pct", "op_income"), ("net_margin_pct", "net_income"), ("fcf_margin_pct", "fcf"),
                       ("rnd_pct", "rnd"), ("sbc_pct", "sbc"), ("capex_pct", "capex")):
            row[k] = pct(row[src], rev) if rev and rev > 0 else None
        out.append(row)
    by_end = {x["end"]: x for x in out}
    for x in out:   # 성장률: 1년 전 LTM과 비교
        prev = next((by_end[e] for e in by_end if abs(days(e, x["end"]) - 365) <= 20), None)
        for k, src in (("revenue_growth_pct", "revenue"), ("op_income_growth_pct", "op_income"), ("eps_growth_pct", "eps_diluted"), ("fcf_growth_pct", "fcf")):
            x[k] = growth(x[src], prev[src]) if prev else None
        x["share_change_pct"] = growth(x["shares_diluted"], prev["shares_diluted"]) if prev else None
    return out[-keep:]


def cagr(annual):
    """연평균 성장률(CAGR) 3·5·10년: 시작과 끝 값이 모두 양수일 때만 계산한다."""
    out = {}
    for k in ("revenue", "op_income", "net_income", "eps_diluted", "fcf"):
        out[k] = {}
        for n in (3, 5, 10):
            if len(annual) > n:
                a, b = annual[-1 - n].get(k), annual[-1].get(k)
                out[k][str(n)] = round(((b / a) ** (1 / n) - 1) * 100, 1) if a and b and a > 0 and b > 0 else None
            else:
                out[k][str(n)] = None
    return out
