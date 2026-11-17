"""투자 논리 점검판: config/thesis.json 에 적은 공개 사실(출처 달린 숫자·일정)과 수집한 시세·재무를 합쳐
종목별 '논리가 숫자로 맞아 가는지' 확인할 값을 만든다. 종목을 가리지 않는 공통 틀이다.

- 사람이 적는 것(config/thesis.json, 종목마다): 질문 한 줄, 숫자 칸 구성(cards), 분기 매출 구성(segments),
  논리와 반대 관점(pillars), 회사가 밝힌 일정(milestones), 목표 변경 기록(guidance), 논리가 바뀐 기록(evolution), 출처.
- 여기서 계산하는 것: 시가총액·현금·EV, 매출 부문 비중, 주식 수 1년 변화(희석), 공매도, 이자비용,
  cards 에서 고른 지표 값, 경쟁사(peers)·시장과 나눠 본 주가 변화, 다음 실적일.

매수·매도 판단은 하지 않는다. 숫자와 출처만 보여 준다.

검사 명령(설정을 고친 뒤 돌린다):
    python scripts/thesis.py check
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
    restricted = _fact(cfg, "restricted_cash") or 0   # facts 에 restricted_cash 를 적으면 현금에 더해 보여 준다
    ev = mcap + (debt or 0) - (cash or 0) - restricted if mcap is not None else None
    m = {
        "currency": f.get("currency") or s.get("currency"),
        "market_cap": mcap, "cash": cash, "restricted_cash": restricted or None, "debt": debt, "ev": ev,
        "mcap_to_cash": _r(mcap / (cash + restricted), 2) if mcap and cash else None,
    }
    # 분기 매출 구성에서 가장 최근 분기의 부문별 비중
    sg = cfg.get("segments") or {}
    rows, keys = sg.get("rows") or [], [x["key"] for x in sg.get("series") or []]
    if rows and keys:
        last = rows[-1]
        tot = sum(last.get(k) or 0 for k in keys)
        m["segment_share"] = {k: _r((last.get(k) or 0) / tot * 100, 1) for k in keys} if tot else {}
        m["segments_period"] = last.get("q")
    # cards 에서 고른 지표(거시경제 탭의 지표 id)의 지금 값
    m["series"] = {}
    for c in cfg.get("cards") or []:
        sid = c.get("series")
        sv = (data.get("series") or {}).get(sid) if sid else None
        if sv and sv.get("value") is not None:
            m["series"][sid] = {"name": sv.get("name"), "value": sv.get("value"), "asof": sv.get("asof"),
                                "prefix": sv.get("prefix"), "decimals": sv.get("decimals")}
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
    e = f.get("earnings") or {}
    m["next_earnings"] = e.get("next")

    # 경쟁사(관심 종목에 있는 것만) 시가총액과 주가 변화
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


STATUS = ("완료", "진행 중", "일정 변경", "대기", "취소")
CALC_CARDS = ("market_cap", "cash", "dilution", "short", "interest", "next_earnings")


def check(cfgs):
    """설정 파일을 검사해 문제 목록을 돌려준다. 출처 번호가 범위를 벗어나거나 출처 없는 문장이 있으면 잡는다."""
    problems = []
    for t, c in cfgs.items():
        n = len(c.get("sources") or [])
        bad = lambda ids: not ids or any(not isinstance(i, int) or not 1 <= i <= n for i in ids)
        for k in ("question", "updated", "sources"):
            if not c.get(k):
                problems.append(f"{t}: {k} 없음")
        for i, x in enumerate(c.get("sources") or []):
            if not str(x.get("url", "")).startswith("https://") or not x.get("title") or not x.get("date"):
                problems.append(f"{t}: 출처 {i + 1} 의 title·url·date 확인")
        for k, x in (c.get("facts") or {}).items():
            if bad(x.get("src")):
                problems.append(f"{t}: facts.{k} 출처 번호")
            if x.get("value") is None and not x.get("text"):
                problems.append(f"{t}: facts.{k} 값 없음")
        keys = [x.get("key") for x in (c.get("segments") or {}).get("series") or []]
        for r in (c.get("segments") or {}).get("rows") or []:
            if bad(r.get("src")) or any(r.get(k) is None for k in keys):
                problems.append(f"{t}: segments {r.get('q')} 값·출처 확인")
        for card in c.get("cards") or []:
            if card.get("calc") and card["calc"] not in CALC_CARDS:
                problems.append(f"{t}: cards calc '{card['calc']}' 모름")
            for fk in (card.get("fact"), card.get("sub_fact")):
                if fk and fk not in (c.get("facts") or {}):
                    problems.append(f"{t}: cards 가 가리키는 facts.{fk} 없음")
            if card.get("segment") and card["segment"] not in keys:
                problems.append(f"{t}: cards segment '{card['segment']}' 가 segments.series 에 없음")
        for g in (c.get("guidance") or []) + (c.get("evolution") or []):
            if bad(g.get("src")) or not g.get("date") or not g.get("text"):
                problems.append(f"{t}: 기록 {g.get('date')} 날짜·문장·출처 확인")
        for ms in c.get("milestones") or []:
            if bad(ms.get("src")) or ms.get("status") not in STATUS:
                problems.append(f"{t}: 일정 '{ms.get('what')}' 상태·출처 확인")
        for p in c.get("pillars") or []:
            for e in (p.get("evidence") or []) + (p.get("counter_evidence") or []):
                if bad(e.get("src")):
                    problems.append(f"{t}: 논리 '{p.get('title')}' 근거 출처 번호 — {e.get('text', '')[:20]}")
            if not p.get("claim") or not p.get("counter"):
                problems.append(f"{t}: 논리 '{p.get('title')}' 에 논리·반대 관점이 모두 있어야 함")
    return problems


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


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["check"]:
        found = check(load())
        print("\n".join(found) if found else f"문제 없음 ({len(load())}종목)")
        sys.exit(1 if found else 0)
    sys.exit("사용법: python scripts/thesis.py check")
