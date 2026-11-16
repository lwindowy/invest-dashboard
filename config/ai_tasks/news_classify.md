# AI 뉴스 분류 작업 지시문

Claude 예약 작업이 미국 장 시간대(동부 기준 8:45, 11:30, 14:45, 17:15, 평일)에 이 지시를 따른다.
분류 결과는 `ai-results` 브랜치의 `news_ai.json` 하나에만 저장한다. `main` 과 다른 브랜치, 코드 파일은 건드리지 않는다.

## 순서

1. 분류할 기사 목록을 받는다.
   ```bash
   curl -fsSL "https://lwindowy.github.io/invest-dashboard/data/news_queue.json" -o /tmp/queue.json
   ```
   `count` 가 0이면 아무것도 저장하지 않고 끝낸다.
2. 기존 결과를 받는다(없으면 빈 파일로 시작).
   ```bash
   git fetch --depth=1 origin ai-results && git show FETCH_HEAD:news_ai.json > /tmp/old.json || echo '{}' > /tmp/old.json
   ```
3. 아래 "판단 기준"대로 `/tmp/new.json` 을 쓴다. 형식은 "결과 형식"을 따른다.
4. 검사하고 합친다. "버림"이 나오면 이유를 읽고 고칠 수 있으면 고쳐서 다시 돌린다.
   ```bash
   python scripts/news_ai.py check /tmp/new.json --queue /tmp/queue.json
   python scripts/news_ai.py merge /tmp/old.json /tmp/new.json --queue /tmp/queue.json -o /tmp/news_ai.json
   ```
5. `ai-results` 브랜치에 `news_ai.json` 만 올린다. 브랜치가 없으면 빈 브랜치(orphan)로 만든다. 커밋 메시지는 "뉴스 분류 (시각)".
6. GitHub Actions의 `update.yml` 을 `workflow_dispatch` 로 한 번 실행해, 결과가 바로 화면에 붙게 한다.
7. 분류한 기사 수, 중요도 1~2 기사 목록(종목, 제목)을 짧게 남기고 끝낸다.

## 판단 기준

기사 제목과 매체만 보고 판단한다. 본문을 지어내거나 추측해 숫자를 만들지 않는다.

- **중요도** (정수 1~5, 그 종목 주주 입장에서)
  - 1: 회사의 가치를 크게 바꾸는 사건. 실적 발표 자체, 가이던스 변경, 인수·합병 확정, 대형 소송 판결, CEO 교체, 상장폐지·파산, 대형 규제 조치
  - 2: 중요한 사건. 대형 계약·수주, 자사주 매입·배당 변경 발표, 규제 조사 착수, 주요 임원 변동, 구조조정·감원
  - 3: 알아 둘 만한 소식. 신제품·제휴, 애널리스트 목표가 대폭 변경, 업계 흐름 중 이 회사가 주인공인 기사
  - 4: 해설·전망 기사. "지금 사야 할까", 주가 움직임 설명
  - 5: 일상·홍보·여러 종목 나열 기사, 제목에 이 회사가 주인공이 아닌 기사
  - `title_names_company` 가 false 인 기사(제목에 회사 이름이 없음)는 이 회사가 주인공이 아니면 5로 둔다.
- **유형**: 실적, 가이던스, M&A, 자사주 매입, 배당, 규제, 소송, 경영진 변동, 구조조정, 기타 중 하나. 맞는 것이 없으면 기타.
- **사건 이름**(`event`): 같은 사건을 다룬 기사끼리 같은 짧은 영어 이름을 붙인다. 예: "nvda q3 fy27 earnings", "amd openai deal". 다른 사건이면 다른 이름. 같은 종목 안에서만 묶인다.
- **근거**(`reason`): 왜 그 중요도인지 한국어 한 줄.
- **이번 달 요약**(`monthly`): 이번 실행에서 기사를 분류한 종목만, 이번 달(한국 시간) 기사 가운데 중요도 1~3을 중심으로 3~5줄. 문장마다 근거 기사 id를 `sources` 에 1개 이상 단다. 출처를 달 수 없는 문장은 쓰지 않는다. 기사 제목에 없는 숫자는 쓰지 않는다. 이번 달 기사는 기존 결과(`/tmp/old.json` 의 items)에 있는 것도 쓸 수 있다.

## 결과 형식 (`/tmp/new.json`)

```json
{
  "by": "Claude 예약 작업 (구독)",
  "items": {
    "<대기 목록의 id 그대로>": {
      "ticker": "NVDA", "title": "<대기 목록 그대로>", "url": "<대기 목록 그대로>", "publisher": "...", "at": "<대기 목록 그대로>",
      "importance": 2, "type": "실적", "event": "nvda q3 fy27 earnings", "reason": "실적 발표 일정과 기대치를 다룬 기사"
    }
  },
  "monthly": {
    "NVDA": {"month": "2026-11", "updated_at": "2026-11-17T07:15+09:00",
             "lines": [{"text": "3분기 실적 발표를 앞두고 데이터센터 수요 기대가 이어짐", "sources": ["<id>", "<id>"]}]}
  }
}
```

대기 목록에 없는 기사는 넣지 않는다(검사에서 버려진다). 기사 id, 제목, 주소, 시각은 대기 목록 값을 그대로 옮긴다.
