"""아침 브리핑: 관심 종목마다 '무엇이 바뀌었나'와 '왜 표시됐나'를 정리한다 (AI 없이 규칙으로).

- 🔴 즉시 확인(red): 하루 ±5% 이상, 실적 발표 오늘·내일, 실적 발표 직후
- 🟡 참고(yellow): 일주일 ±10% 이상, 실적 7일 이내, 새 공시, 기술적 신호(RSI·200일선·크로스·52주), 공매도, 내부자 매수
- ⚪ 변화 없음(none): 위에 해당 없음
기준 숫자는 config/dashboard.json 의 briefing 에서 바꾼다. 이유마다 출처와 기준일을 붙인다.
뉴스는 AI가 중요도 1~2로 분류한 기사만 🔴 즉시 확인으로 올린다(news_ai.py). 그 밖에는 제목에 회사 이름이 들어간 최근 기사 하나만 함께 보여 준다.
"""
import datetime as dt

# 알림 종류 중 브리핑 이유로 옮겨 쓸 것 (급등락·실적·공시는 아래에서 직접 만든다)
ALERT_KINDS = {"RSI", "200일선", "골든크로스", "데드크로스", "52주", "공매도"}
SEC_BROWSE = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}"


def signed(x, digits=1, unit="%"):
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x):.{digits}f}{unit}"


def build(data, config, today, now):
    rules = config["briefing"]
    move = config["alerts"]["move_pct"]
    t_iso, tomorrow = today.isoformat(), (today + dt.timedelta(days=1)).isoformat()
    since_alert = (today - dt.timedelta(days=1)).isoformat()                      # 어제부터 생긴 알림
    since_filing = (today - dt.timedelta(days=rules["filing_days"])).isoformat()  # 공시는 미국 날짜라 하루 더 본다
    news_floor = now - dt.timedelta(hours=rules["news_hours"])
    sec = (data.get("sec") or {}).get("companies") or {}
    on_sec = set(sec) | set((data.get("sec") or {}).get("not_on_sec") or [])
    rows = []
    for market, items in data["watchlist"].items():
        for w in items:
            t = w["ticker"]
            s = data["stocks"].get(t) or {}
            fund = s.get("fund") or {}
            earn = fund.get("earnings") or {}
            reasons = []

            def add(level, text, why, source, url=None, date=None):
                reasons.append({"level": level, "text": text, "why": why, "source": source, "url": url, "date": date})

            if w.get("price") is None:
                rows.append({"ticker": t, "name": w["name"], "market": market, "level": "none", "error": True, "reasons": [],
                             "coverage": {"price": False}})
                continue
            src_price = f"Yahoo Finance · {w.get('asof')} 종가"
            d1, w1 = w.get("change_pct"), w.get("w1_pct")
            if d1 is not None and abs(d1) >= move:
                add("red", f"하루 {signed(d1)}", f"하루 변동이 ±{move}% 이상", src_price, date=w.get("asof"))
            elif w1 is not None and abs(w1) >= rules["week_move_pct"]:
                add("yellow", f"일주일 {signed(w1)}", f"5거래일 변동이 ±{rules['week_move_pct']}% 이상", src_price, date=w.get("asof"))
            nxt = earn.get("next")
            days_left = (dt.date.fromisoformat(nxt) - today).days if nxt else None
            if nxt in (t_iso, tomorrow):
                add("red", f"실적 발표 {'오늘' if nxt == t_iso else '내일'} ({nxt[5:7]}/{nxt[8:10]})", "실적 발표가 오늘·내일", f"Yahoo Finance 실적 일정 · {fund.get('fetched')} 확인",
                    date=nxt)
            elif days_left is not None and 0 <= days_left <= rules["earnings_soon_days"]:
                add("yellow", f"실적 발표 {days_left}일 뒤 ({nxt[5:7]}/{nxt[8:10]})", f"실적 발표가 {rules['earnings_soon_days']}일 이내",
                    f"Yahoo Finance 실적 일정 · {fund.get('fetched')} 확인", date=nxt)
            last = earn.get("last") or {}
            if last.get("date") and last["date"] >= since_alert:
                sur = last.get("surprise_pct")
                add("red", f"실적 발표됨: EPS {last.get('eps_actual')} (예상 {last.get('eps_estimate')}"
                    + (f", {signed(sur)}" if sur is not None else "") + ")", "어제·오늘 실적 발표", "Yahoo Finance", date=last["date"])
            co = sec.get(t)
            if co:
                for f in co.get("filings", []):
                    if f["date"] >= since_filing:
                        what = " · ".join(f["items"]) if f["items"] else f["label"]
                        add("yellow", f"새 공시 {f['form']}: {what}", f"최근 {rules['filing_days']}일 안에 접수된 공시", f"SEC · {f['date']} 접수 (미국 날짜)", f["url"], f["date"])
                for r in co.get("insider", []):
                    if r["code"] == "P" and r["filed"] >= since_filing:
                        add("yellow", f"내부자 매수: {r['owner']} ({r['role']})", "임원·이사의 공개시장 매수",
                            f"SEC Form 4 · {r['filed']} 신고", SEC_BROWSE.format(cik=co["cik"], form="4"), r["filed"])
            for a in data.get("alerts", []):
                if a.get("ticker") == t and a["kind"] in ALERT_KINDS and a["id"][:10] >= since_alert:
                    add("yellow", a["title"], a["detail"], "자체 계산 (Yahoo Finance 주가)", date=a["id"][:10])
            # AI가 중요도 1~2로 분류한 최근 기사는 즉시 확인으로 올린다 (같은 사건 기사는 하나만, 중요한 것부터)
            recent = [n for n in ((s.get("news") or {}).get("items") or [])
                      if not n.get("dup_of") and n.get("at") and dt.datetime.fromisoformat(n["at"]) >= news_floor]
            recent.sort(key=lambda n: (n.get("importance") or 3.5, -dt.datetime.fromisoformat(n["at"]).timestamp()))
            shown = set()
            for n in recent:
                if n.get("importance") in (1, 2):
                    shown.add(n["url"])
                    add("red", f"[중요도 {n['importance']} · {n['type']}] {n['title']}", f"AI가 중요도 1~2로 분류한 {rules['news_hours']}시간 이내 뉴스"
                        + (f" — {n['reason']}" if n.get("reason") else ""), f"{n.get('publisher') or '뉴스'} · AI 분류", n["url"], (n["at"] or "")[:10])
            # 참고로 보여 줄 기사 하나: 제목에 회사 이름이 있고, 위에서 이미 보인 기사가 아니며, 일상 기사(중요도 5)가 아닌 것 중 가장 중요한 것.
            # 아직 분류하지 않은 기사는 중요도 3과 4 사이로 본다
            news = next(({k: n.get(k) for k in ("title", "url", "publisher", "at", "importance", "type")} for n in recent
                         if n.get("named") and n["url"] not in shown and n.get("importance") != 5), None)
            level = "red" if any(r["level"] == "red" for r in reasons) else "yellow" if reasons else "none"
            reasons.sort(key=lambda r: r["level"] != "red")
            rows.append({
                "ticker": t, "name": w["name"], "market": market, "currency": w.get("currency"), "price": w.get("price"),
                "d1": d1, "w1": w1, "m1": w.get("m1_pct"), "spark": w.get("spark"), "asof": w.get("asof"), "stale": w.get("stale"),
                "next_earnings": nxt, "earnings_in_days": days_left, "level": level, "reasons": reasons, "news": news,
                # '데이터 없음'과 '신호 없음'을 나누기 위한 표시: 공시를 볼 수 없는 종목인지
                "coverage": {"sec": t in sec, "sec_reason": None if t in sec else
                             "한국 종목은 SEC 공시가 없음 (DART 미연결)" if market == "kr" else
                             "SEC에 공시하지 않는 종목" if t in on_sec else "SEC 공시를 받지 못함"},
            })
    return {"generated_at": now.isoformat(timespec="minutes"), "rules": {**rules, "move_pct": move}, "rows": rows}
