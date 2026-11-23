"""회사 소개(AI가 공시·회사 자료를 읽고 한국어로 정리) 파일 profiles.json 을 다루는 곳.

흐름
1. 30분 갱신(GitHub)이 소개를 새로 써야 할 종목을 data/profile_queue.json 으로 내보낸다.
   - 소개 없음(mode "new"): 새로 쓴다. 종목을 추가하면 갱신이 끝난 뒤 바로 Claude 예약 작업을 불러 쓴다(update.yml).
   - 새 정기 보고서(mode "review"): 소개를 쓰거나 확인한 뒤 10-K·10-Q·20-F가 새로 나온 종목.
     기존 소개와 비교해 달라진 부분만 고치고, 달라진 것이 없으면 확인한 날(checked)만 적는다.
2. Claude 예약 작업(뉴스 분류와 같은 작업, 한 번에 2종목까지)이 공시와 회사 자료를 읽고 소개를 써서
   ai-results 브랜치의 profiles.json 에 저장한다. 지시문: config/ai_tasks/profile_update.md
3. 다음 30분 갱신이 그 파일을 받아 검사(validate)한 뒤 종목 데이터에 붙인다. 검사에 걸린 항목은 버린다.

AI는 출처에 있는 내용만 옮긴다. 문장마다 출처 번호를 달고, 출처 없는 문장과 숫자는 버린다.

검사 명령(예약 작업이 저장 전에 돌린다):
    python scripts/profiles.py check <profiles.json> [--tickers NVDA,AMD]
    python scripts/profiles.py merge <기존 profiles.json> <새 결과.json> -o <저장할 파일>
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPORTS = ("10-K", "10-Q", "20-F", "40-F")
TEXT_LIST_KEYS = ("business", "vision", "strengths", "risks")


def _src_ok(ids, n):
    return [i for i in (ids or []) if isinstance(i, int) and 1 <= i <= n][:4]


def validate_one(t, p):
    """한 종목 소개를 검사한다. (정리된 소개 또는 None, 문제 목록)."""
    problems = []
    if not isinstance(p, dict):
        return None, [f"{t}: 형식이 사전이 아님"]
    sources = []
    for s in p.get("sources") or []:
        url = (s or {}).get("url") or ""
        if not re.match(r"^https?://", url) or not s.get("title"):
            problems.append(f"{t}: 출처 형식이 틀림 ({url[:60]})")
            sources.append(None)
            continue
        sources.append({"title": str(s["title"])[:160], "url": url[:400], "date": str(s.get("date") or "")[:10]})
    n = len(sources)
    if not n or all(s is None for s in sources):
        return None, problems + [f"{t}: 출처가 없음"]

    def lines(key, limit):
        out = []
        for ln in p.get(key) or []:
            src = [i for i in _src_ok((ln or {}).get("src"), n) if sources[i - 1]]
            if not (ln or {}).get("text") or not src:
                problems.append(f"{t}: {key} 문장에 출처가 없어 뺌")
                continue
            out.append({"text": str(ln["text"])[:260], "src": src})
        return out[:limit]

    out = {"ticker": t, "updated": str(p.get("updated") or "")[:10], "by": str(p.get("by") or "")[:60],
           "basis": str(p.get("basis") or "")[:160], "sources": sources}
    checked = str(p.get("checked") or "")[:10]  # 새 보고서와 비교해 확인한 날(내용을 안 고쳤어도 적는다)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", checked):
        out["checked"] = checked
    one = p.get("one_liner") or {}
    src = [i for i in _src_ok(one.get("src"), n) if sources[i - 1]]
    if not one.get("text") or not src:
        return None, problems + [f"{t}: 한 줄 소개가 없거나 출처가 없음"]
    out["one_liner"] = {"text": str(one["text"])[:200], "src": src}
    for key in TEXT_LIST_KEYS:
        out[key] = lines(key, 6)
    rev = p.get("revenue") or {}
    segs = []
    for sg in rev.get("segments") or []:
        src = [i for i in _src_ok((sg or {}).get("src"), n) if sources[i - 1]]
        sh = (sg or {}).get("share_pct")
        if not sg.get("name") or not src or (sh is not None and not (isinstance(sh, (int, float)) and 0 <= sh <= 100)):
            problems.append(f"{t}: 매출 구성 항목을 뺌 ({(sg or {}).get('name')})")
            continue
        segs.append({"name": str(sg["name"])[:60], "share_pct": round(float(sh), 1) if sh is not None else None,
                     "note": str(sg.get("note") or "")[:160], "src": src})
    total = sum(s["share_pct"] or 0 for s in segs)
    if total > 101:
        problems.append(f"{t}: 매출 비중 합계가 {total:.0f}%라 비중을 지움")
        for s in segs:
            s["share_pct"] = None
    out["revenue"] = {"period": str(rev.get("period") or "")[:40], "segments": segs[:8], "note": str(rev.get("note") or "")[:200]}
    mg = []
    for m in p.get("management") or []:
        src = [i for i in _src_ok((m or {}).get("src"), n) if sources[i - 1]]
        if not (m or {}).get("name") or not m.get("role") or not src:
            problems.append(f"{t}: 경영진 항목을 뺌 ({(m or {}).get('name')})")
            continue
        mg.append({"name": str(m["name"])[:60], "role": str(m["role"])[:80], "note": str(m.get("note") or "")[:160], "src": src})
    out["management"] = mg[:6]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", out["updated"]):
        return None, problems + [f"{t}: 작성일(updated)이 YYYY-MM-DD가 아님"]
    return out, problems


def validate(doc, tickers=None):
    items, problems = {}, []
    for t, p in ((doc or {}).get("items") or {}).items():
        if tickers is not None and t not in tickers:
            problems.append(f"{t}: 관심 종목이 아님")
            continue
        v, pr = validate_one(t, p)
        problems += pr
        if v:
            items[t] = v
    return {"version": 1, "updated_at": (doc or {}).get("updated_at"), "items": items}, problems


def merge(old, new):
    o, _ = validate(old)
    n, problems = validate(new)
    o["items"].update(n["items"])
    o["updated_at"] = (new or {}).get("updated_at") or o.get("updated_at")
    return o, problems


def build_queue(data, prof, today):
    """소개를 새로 써야 할 종목과 참고할 자료 주소."""
    items = (prof or {}).get("items") or {}
    out = []
    for t, s in data["stocks"].items():
        p = items.get(t)
        filings = (((data.get("sec") or {}).get("companies") or {}).get(t) or {}).get("filings") or []
        reports = [f for f in filings if f.get("form") in REPORTS]
        why = mode = None
        if not p:
            why, mode = "소개 없음", "new"
        elif reports and reports[0]["date"] > max(p.get("updated", ""), p.get("checked", "")):
            why, mode = f"새 정기 보고서 {reports[0]['form']} ({reports[0]['date']})", "review"
        if why:
            fund = s.get("fund") or {}
            out.append({"ticker": t, "name": s.get("name"), "long_name": fund.get("long_name"), "why": why, "mode": mode,
                        "website": fund.get("website"), "reports": [{k: f.get(k) for k in ("form", "date", "url")} for f in reports[:3]],
                        "ai_file": f"data/ai/{t}.json"})
    return {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "count": len(out), "items": out,
            "instructions": "config/ai_tasks/profile_update.md"}


def apply(data, prof):
    """검사를 통과한 소개를 종목 데이터에 붙인다. 버린 항목 수를 돌려준다."""
    v, problems = validate(prof, set(data["stocks"]))
    for t, p in v["items"].items():
        data["stocks"][t]["profile"] = p
    return len(problems)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("file")
    c.add_argument("--tickers")
    m = sub.add_parser("merge")
    m.add_argument("old")
    m.add_argument("new")
    m.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).is_file() else {}
    if a.cmd == "check":
        v, problems = validate(load(a.file), set(a.tickers.split(",")) if a.tickers else None)
        print(f"통과 {len(v['items'])}종목: {', '.join(v['items'])}")
        for p in problems:
            print("버림:", p)
        sys.exit(1 if not v["items"] else 0)
    v, problems = merge(load(a.old), load(a.new))
    for p in problems:
        print("버림:", p)
    Path(a.out).write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {a.out} · {len(v['items'])}종목")


if __name__ == "__main__":
    main()
