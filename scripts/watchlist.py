#!/usr/bin/env python3
"""GitHub 요청(이슈) 제목을 읽어 관심 종목을 추가하거나 삭제한다.

제목 형식:  "종목 추가: TSLA"  또는  "종목 삭제: TSLA"
본문(선택): "이름: 테슬라"  — 화면에 보일 한글 이름. 없으면 Yahoo의 회사명을 쓴다.
한국 종목은 숫자 6자리만 적어도 된다(코스피 .KS, 코스닥 .KQ 순서로 찾는다).

결과 안내문은 result.md, 커밋 메시지는 commit.txt 에 쓴다. 바뀐 것이 없으면 commit.txt 를 만들지 않는다.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/dashboard.json"
MAX_STOCKS = 40   # Yahoo 차단을 피하려고 종목 수에 상한을 둔다


def finish(message, commit=None):
    (ROOT / "result.md").write_text(message + "\n", encoding="utf-8")
    if commit:
        (ROOT / "commit.txt").write_text(commit + "\n", encoding="utf-8")
    print(message)
    sys.exit(0)


def lookup(symbol):
    """Yahoo에 있는 종목이면 (티커, 회사명), 없으면 None."""
    import yfinance as yf
    candidates = [symbol + ".KS", symbol + ".KQ"] if re.fullmatch(r"\d{6}", symbol) else [symbol]
    for ticker in candidates:
        try:
            tk = yf.Ticker(ticker)
            if len(tk.history(period="5d")) == 0:
                continue
            info = tk.info or {}
            return ticker, info.get("longName") or info.get("shortName") or ticker
        except Exception as exc:
            print(f"조회 실패 {ticker}: {exc}", file=sys.stderr)
    return None


def main():
    title = os.environ.get("ISSUE_TITLE", "")
    body = os.environ.get("ISSUE_BODY", "") or ""
    m = re.fullmatch(r"\s*종목\s*(추가|삭제)\s*[:：]\s*([A-Za-z0-9.\-]{1,12})\s*", title)
    if not m:
        finish("요청 제목을 이해하지 못했습니다. `종목 추가: TSLA` 또는 `종목 삭제: TSLA` 형식으로 적어 주세요.")
    action, symbol = m.group(1), m.group(2).upper()
    name_match = re.search(r"^\s*이름\s*[:：]\s*(.+?)\s*$", body, re.M)
    name = re.sub(r"[\x00-\x1f<>\"'`\\]", "", name_match.group(1))[:30].strip() if name_match else ""

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    watch = config["watchlist"]
    everything = [(market, e) for market, entries in watch.items() for e in entries]

    def same(entry):
        return entry["ticker"] == symbol or re.sub(r"\.K[SQ]$", "", entry["ticker"]) == symbol

    if action == "삭제":
        found = [(market, e) for market, e in everything if same(e)]
        if not found:
            finish(f"`{symbol}` 은(는) 관심 종목에 없습니다. 바뀐 것은 없습니다.")
        market, entry = found[0]
        watch[market].remove(entry)
        CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        finish(f"**{entry['name']} ({entry['ticker']})** 을(를) 관심 종목에서 뺐습니다. 1~3분 뒤 사이트에 반영됩니다.",
               f"관심 종목 삭제: {entry['ticker']}")

    if any(same(e) for _, e in everything):
        finish(f"`{symbol}` 은(는) 이미 관심 종목에 있습니다. 바뀐 것은 없습니다.")
    if len(everything) >= MAX_STOCKS:
        finish(f"관심 종목이 이미 {MAX_STOCKS}개입니다. 다른 종목을 삭제한 뒤 다시 요청해 주세요.")
    found = lookup(symbol)
    if not found:
        finish(f"`{symbol}` 을(를) Yahoo Finance에서 찾지 못했습니다. 티커를 확인해 주세요. "
               "한국 종목은 숫자 6자리(예: 005930)로 적습니다.")
    ticker, long_name = found
    market = "kr" if re.search(r"\.K[SQ]$", ticker) else "us"
    watch.setdefault(market, []).append({"ticker": ticker, "name": name or long_name})
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finish(f"**{name or long_name} ({ticker})** 을(를) 관심 종목에 넣었습니다. 1~3분 뒤 사이트에 모든 지표가 나옵니다.",
           f"관심 종목 추가: {ticker}")


if __name__ == "__main__":
    main()
