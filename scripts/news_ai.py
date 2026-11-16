"""AI 뉴스 분류 결과(news_ai.json)를 다루는 곳: 분류할 기사 목록 만들기, 결과 검사, 화면 데이터에 붙이기.

흐름
1. 30분 갱신(GitHub)이 아직 분류하지 않은 기사를 data/news_queue.json 으로 내보낸다.
2. Claude 예약 작업(미국 장 시간대에 하루 4번)이 그 목록을 읽고 기사마다 중요도·유형·사건 이름을 붙이고,
   종목별 '이번 달 요약'을 써서 news_ai.json 으로 ai-results 브랜치에 저장한다.
   지시문: config/ai_tasks/news_classify.md
3. 다음 30분 갱신이 그 파일을 받아 검사(validate)한 뒤 뉴스에 붙인다. 검사에 걸린 항목은 버린다.

누가 분류하든(예약 작업이든, 나중에 API든) 파일 형식은 같다. AI는 숫자를 만들지 않고 판단과 요약만 한다.

검사·병합 명령(예약 작업이 저장 전에 돌린다):
    python scripts/news_ai.py check  <news_ai.json> --queue <news_queue.json>
    python scripts/news_ai.py merge  <기존 news_ai.json> <새 결과.json> --queue <news_queue.json> -o <저장할 파일>
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

TYPES = ["실적", "가이던스", "M&A", "자사주 매입", "배당", "규제", "소송", "경영진 변동", "구조조정", "기타"]
KEEP_DAYS = 62          # 분류 결과를 남겨 두는 기간 (이번 달 요약에 지난 기사도 쓰려고 두 달 가까이)
QUEUE_DAYS = 7          # 이보다 오래된 기사는 분류하지 않는다
FILE_URL = "https://raw.githubusercontent.com/{repo}/ai-results/news_ai.json"


def news_id(url, ticker):
    """기사 번호. 같은 기사가 여러 종목에 붙으면 종목마다 중요도가 달라서 종목을 함께 넣는다."""
    return hashlib.sha1(f"{ticker}|{url}".encode("utf-8")).hexdigest()[:12]


def norm_title(t):
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()


def build_queue(data, ai, now):
    """분류해야 할 기사: 최근 QUEUE_DAYS 안이고 아직 결과가 없는 것. 종목 이름도 같이 적어 판단을 돕는다."""
    done = set((ai or {}).get("items") or {})
    floor = (now - dt.timedelta(days=QUEUE_DAYS)).isoformat()
    items = []
    for t, s in data["stocks"].items():
        for n in ((s.get("news") or {}).get("items") or []):
            i = news_id(n["url"], t)
            if i in done or (n.get("at") or "") < floor:
                continue
            items.append({"id": i, "ticker": t, "company": s.get("name"), "long_name": (s.get("fund") or {}).get("long_name"),
                          "title": n["title"], "publisher": n.get("publisher"), "at": n.get("at"), "url": n["url"],
                          "title_names_company": bool(n.get("named"))})
    return {"generated_at": now.isoformat(timespec="minutes"), "types": TYPES, "count": len(items), "items": items,
            "instructions": "config/ai_tasks/news_classify.md"}


def validate(ai, known=None):
    """형식과 출처를 검사한다. 통과한 항목만 남긴 새 사전과 버린 이유 목록을 돌려준다.
    known: 출처로 인정할 기사 {id: 기사}. 주지 않으면 결과 파일 안의 기사만 인정한다."""
    problems, items = [], {}
    for i, it in ((ai or {}).get("items") or {}).items():
        why = None
        if not isinstance(it, dict) or not it.get("url") or news_id(it["url"], it.get("ticker")) != i:
            why = "id가 기사 주소와 맞지 않음"
        elif known is not None and i not in known:
            why = "분류 대기 목록에 없는 기사 (지어낸 기사일 수 있음)"
        elif not isinstance(it.get("importance"), int) or not 1 <= it["importance"] <= 5:
            why = "중요도가 1~5 정수가 아님"
        elif it.get("type") not in TYPES:
            why = f"유형이 목록에 없음 ({it.get('type')})"
        elif not it.get("ticker") or not it.get("title"):
            why = "종목·제목 없음"
        if why:
            problems.append(f"{i}: {why}")
            continue
        items[i] = {k: it.get(k) for k in ("ticker", "title", "url", "publisher", "at", "importance", "type", "event", "reason", "classified_at")}
        items[i]["event"] = (items[i]["event"] or "")[:80]
        items[i]["reason"] = (items[i]["reason"] or "")[:200]
    monthly = {}
    for t, m in ((ai or {}).get("monthly") or {}).items():
        lines = []
        for ln in (m or {}).get("lines") or []:
            srcs = [s for s in (ln.get("sources") or []) if s in items and items[s]["ticker"] == t]
            if not ln.get("text") or not srcs:     # 출처 없는 문장은 버린다
                problems.append(f"요약 {t}: 출처 기사가 없는 문장을 뺌")
                continue
            lines.append({"text": ln["text"][:300], "sources": srcs[:5]})
        if lines and re.match(r"^\d{4}-\d{2}$", str(m.get("month", ""))):
            monthly[t] = {"month": m["month"], "lines": lines[:5], "updated_at": m.get("updated_at")}
    return {"version": 1, "updated_at": (ai or {}).get("updated_at"), "by": (ai or {}).get("by"), "items": items, "monthly": monthly}, problems


def merge(old, new, known, now):
    """새 결과를 기존 결과에 더한다. 같은 기사는 새 판단으로 바꾸고, KEEP_DAYS 보다 오래된 기사는 지운다.
    새 기사는 분류 대기 목록(known)에 있는 것만 받는다. 요약 문장의 출처는 지난 기사여도 된다."""
    old_v, _ = validate(old)
    new_items, problems = validate({"items": (new or {}).get("items") or {}}, known)
    stamp = now.isoformat(timespec="minutes")
    items = {**old_v["items"], **{i: {**it, "classified_at": it.get("classified_at") or stamp} for i, it in new_items["items"].items()}}
    floor = (now - dt.timedelta(days=KEEP_DAYS)).isoformat()
    items = {i: it for i, it in items.items() if (it.get("at") or "") >= floor}
    monthly = {**old_v["monthly"], **((new or {}).get("monthly") or {})}
    result, more = validate({"items": items, "monthly": monthly, "updated_at": stamp, "by": (new or {}).get("by") or old_v.get("by")})
    return result, problems + more


def apply(data, ai):
    """검사를 통과한 결과를 화면 데이터에 붙인다: 기사마다 중요도·유형, 같은 사건 묶기, 이번 달 요약."""
    ai, problems = validate(ai)
    got = ai["items"]
    for t, s in data["stocks"].items():
        news = s.get("news") or {}
        groups = {}
        for n in news.get("items") or []:
            i = news_id(n["url"], t)
            n["id"] = i
            n.pop("dup_of", None)
            c = got.get(i)
            if c:
                n.update({"importance": c["importance"], "type": c["type"], "event": c.get("event"), "reason": c.get("reason")})
            # 같은 사건(AI가 붙인 사건 이름) 또는 같은 제목이면 한 묶음으로 본다
            key = (c.get("event") or "").strip().lower() if c and c.get("event") else norm_title(n["title"])
            groups.setdefault(key, []).append(n)
        for g in groups.values():   # 묶음마다 가장 중요한(같으면 가장 최근) 기사 하나만 보이고 나머지는 그 아래로 접는다
            g.sort(key=lambda n: (n.get("importance") or 9, -(dt.datetime.fromisoformat(n["at"]).timestamp() if n.get("at") else 0)))
            for n in g[1:]:
                n["dup_of"] = g[0]["id"]
        if t in ai["monthly"]:
            m = ai["monthly"][t]
            s["news_month"] = {**m, "sources": {i: {k: got[i][k] for k in ("title", "url", "publisher", "at")} for ln in m["lines"] for i in ln["sources"]}}
    data["news_ai"] = {"updated_at": ai.get("updated_at"), "by": ai.get("by"), "classified": len(got), "problems": len(problems)}
    return problems


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("file")
    c.add_argument("--queue")
    m = sub.add_parser("merge")
    m.add_argument("old")
    m.add_argument("new")
    m.add_argument("--queue", required=True)
    m.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8")) if p and Path(p).is_file() else {}
    queue = load(getattr(a, "queue", None))
    known = {it["id"]: it for it in queue.get("items", [])} if queue else None
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    if a.cmd == "check":
        res, problems = validate(load(a.file), known)
    else:
        res, problems = merge(load(a.old), load(a.new), known, now)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for p in problems:
        print("버림:", p)
    print(f"통과: 기사 {len(res['items'])}개, 이번 달 요약 {len(res['monthly'])}종목, 버림 {len(problems)}건")


if __name__ == "__main__":
    main()
