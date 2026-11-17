"""투자 논리 점검판: config/thesis.json 에 적은 공개 사실(출처 달린 숫자·일정)과 수집한 시세·재무를 합쳐
종목별 '논리가 숫자로 맞아 가는지' 확인할 값을 만든다.

- 사람이 적는 것(config/thesis.json): 질문 한 줄, 분기 매출 구성, 회사 목표 변경 기록, 약속과 진행, 논리와 반대 관점, 출처.
- 여기서 계산하는 것: 시가총액 대비 현금·수주 잔고·목표 ARR, 경쟁사와의 시가총액 비교, 주식 수 변화(희석),
  공매도, 비트코인, 이자비용, 주가 변화를 업종·시장 몫으로 나눠 보기, 다음 실적일.

매수·매도 판단은 하지 않는다. 숫자와 출처만 보여 준다.
"""
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    p = ROOT / "config/thesis.json"
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _r(x, d=2):
    return None if x is None else round(x, d)


def _ret_days(close, n):
    """n 거래일 전 대비 수익률(%). 종목 화면 '가격' 칸과 같은 방식(1개월 21일, 3개월 63일)."""
    c = [x for x in (close or []) if x]
    return _r((c[-1] / c[-1 - n] - 1) * 100, 1) if len(c) > n else None


def _ret(s, label):
    return next((r.get("local") for r in s.get("returns") or [] if r.get("label") == label), None)


def _fact(cfg, key):
    return ((cfg.get("facts") or {}).get(key) or {}).get("value")


def build_one(t, cfg, data, fin):
    s = (data.get("stocks") or {}).get(t)
    if not s:
        return None
    f = s.get("fund") or {}
    mcap, cash, debt = f.get("market_cap"), f.get("cash"), f.get("debt")
    restricted = _fact(cfg, "restricted_cash") or 0
    backlog, arr = _fact(cfg, "backlog"), _fact(cfg, "arr_target")
    ev = mcap + (debt or 0) - (cash or 0) - restricted if mcap is not None else None
    m = {
        "market_cap": mcap, "cash": cash, "restricted_cash": restricted or None, "debt": debt, "ev": ev,
        "mcap_to_cash": _r(mcap / (cash + restricted), 2) if mcap and cash else None,
        "mcap_to_backlog": _r(mcap / backlog, 2) if mcap and backlog else None,
        "ev_to_arr": _r(ev / arr, 2) if ev and arr else None,
        "mcap_to_arr": _r(mcap / arr, 2) if mcap and arr else None,
    }
    # 분기 매출 구성에서 가장 최근 AI·채굴 비중
    rows = (cfg.get("segments") or {}).get("rows") or []
    if rows:
        last = rows[-1]
        tot = sum(v for k, v in last.items() if k in ("ai", "btc") and v is not None)
        m["ai_share_pct"] = _r(last["ai"] / tot * 100, 1) if tot else None
        m["btc_share_pct"] = _r(last["btc"] / tot * 100, 1) if tot else None
        m["segments_period"] = last.get("q")
    # 주식 수 변화(희석): SEC 분기 기본 가중평균 주식 수, 1년 전 같은 분기와 비교
    hist = ((fin.get("companies") or {}).get(t) or {}).get("shares_basic_q") or []
    if hist:
        now = hist[-1]
        end = dt.date.fromisoformat(now["end"])
        gap = lambda h: (end - dt.date.fromisoformat(h["end"])).days
        cands = [h for h in hist if 300 <= gap(h) <= 430]   # 1년 전 분기(그 분기 값이 없으면 가장 가까운 분기)
        base = min(cands, key=lambda h: abs(gap(h) - 365)) if cands else None
        m["shares"] = {"q_end": now["end"], "q_shares": now["shares"],
                       "base_end": base["end"] if base else None, "base_shares": base["shares"] if base else None,
                       "yoy_pct": _r((now["shares"] / base["shares"] - 1) * 100, 1) if base else None,
                       "history": hist[-8:]}
    sh = f.get("short") or {}
    m["short_float_pct"], m["short_date"] = sh.get("float_pct"), sh.get("date")
    iq = (f.get("debt_metrics") or {}).get("interest_quarters") or []
    if iq:
        m["interest"] = {"last": iq[-1], "first": iq[0]}
    btc = (data.get("series") or {}).get("btc") or {}
    if btc.get("value") is not None:
        m["btc"] = {"value": btc.get("value"), "asof": btc.get("asof")}
    e = f.get("earnings") or {}
    m["next_earnings"] = e.get("next")

    # 경쟁사 시가총액과 주가 변화(같은 계산식으로 1·3·6개월)
    peers = []
    for p in [t] + (cfg.get("peers") or []):
        ps = (data.get("stocks") or {}).get(p)
        if not ps:
            continue
        peers.append({"ticker": p, "name": ps.get("name"), "market_cap": (ps.get("fund") or {}).get("market_cap"),
                      "r1": _ret(ps, "1개월"), "r3": _ret(ps, "3개월")})
    m["peers"] = peers
    b = data.get("benchmark") or {}
    m["bench"] = {"name": b.get("name"), "r1": _ret_days(b.get("close"), 21), "r3": _ret_days(b.get("close"), 63)}
    for k in ("r1", "r3"):
        others = [x[k] for x in peers[1:] if x[k] is not None]
        m["bench"]["peers_" + k] = _r(sum(others) / len(others), 1) if others else None
    out = {k: v for k, v in cfg.items() if k not in ("facts",)}
    out["facts"] = cfg.get("facts") or {}
    out["calc"] = m
    return out


def build(data, fin, warn):
    result = {}
    for t, cfg in load().items():
        try:
            one = build_one(t, cfg, data, fin or {})
            if one:
                result[t] = one
        except Exception as exc:
            warn(f"투자 논리 점검판 {t}", exc)
    return result
