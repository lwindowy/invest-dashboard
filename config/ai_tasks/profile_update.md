# 회사 소개 작업 지시문

뉴스 분류 예약 작업이 뉴스 분류를 마친 뒤 이어서 이 지시를 따른다. 한 번 실행에 **최대 2종목**만 쓴다.
결과는 `ai-results` 브랜치의 `profiles.json` 하나에만 저장한다. `main` 과 다른 브랜치, 코드 파일은 건드리지 않는다.

## 순서

1. 다시 쓸 종목 목록을 받는다.
   ```bash
   curl -fsSL "https://lwindowy.github.io/invest-dashboard/data/profile_queue.json" -o /tmp/pq.json
   ```
   `count` 가 0이면 아무것도 하지 않고 끝낸다. 1 이상이면 앞에서부터 2종목만 고른다.
2. 기존 결과를 받는다(없으면 빈 파일).
   ```bash
   git fetch --depth=1 origin ai-results && git show FETCH_HEAD:profiles.json > /tmp/pold.json || echo '{}' > /tmp/pold.json
   ```
3. 종목마다 자료를 읽는다.
   - 대기 목록의 `reports`(SEC 10-K·10-Q·20-F 원문 주소). 연간 보고서의 사업 설명(Item 1, 20-F는 Item 4)을 먼저 본다. SEC에 요청할 때는 User-Agent 헤더를 붙인다.
   - `https://lwindowy.github.io/invest-dashboard/` + `ai_file`: 이 파일의 `financials.earnings_release`(최근 실적 보도자료 본문)에서 부문별 매출, 전망, 경영진 발언을 찾는다.
   - 경영진 이름·직책은 `https://finance.yahoo.com/quote/<티커>/profile/` 또는 보도자료에서 찾는다.
   - 기존 소개(`/tmp/pold.json`)가 있으면 바뀐 부분만 고친다.
4. 아래 "쓰는 법"과 "형식"대로 `/tmp/pnew.json` 을 쓰고 검사한다. "버림"이 나오면 고쳐서 다시 돌린다.
   ```bash
   python scripts/profiles.py check /tmp/pnew.json
   python scripts/profiles.py merge /tmp/pold.json /tmp/pnew.json -o /tmp/profiles.json
   ```
5. `ai-results` 브랜치에 `profiles.json` 만 올린다(커밋 메시지 "회사 소개 (종목들)"). 올리면 `kick.yml` 이 사이트 갱신을 실행한다.
6. 쓴 종목과 이유(대기 목록의 `why`)를 짧게 남긴다.

## 쓰는 법

- 쉬운 한국어로 짧게 쓴다. 회사 이름·제품 이름은 원어를 그대로 써도 된다.
- **출처에 있는 내용만** 쓴다. 문장마다 `src` 에 출처 번호(1부터, `sources` 순서)를 단다. 출처를 달 수 없으면 쓰지 않는다.
- 숫자는 출처에 있는 값만 쓴다. 비중(%)처럼 계산한 값은 `revenue.note` 에 "계산한 값"이라고 적는다. 비중 합계가 100%를 넘으면 안 된다.
- 회사의 주장(예: "업계 최고")은 "~라고 밝혔다/주장한다"로 쓴다. 전망은 "~로 예상했다"로 쓴다.
- 칸별 개수: business 2~4줄, vision 1~3줄, strengths 1~2줄, risks 1~2줄, management 1~5명. 자료가 없으면 빈 목록으로 둔다(지어내지 않는다).
- 한국 종목은 DART를 아직 연결하지 않아 매출 구성·비전 자료가 부족하다. 있는 자료만 쓴다.

## 형식 (`/tmp/pnew.json`)

```json
{
  "updated_at": "2026-11-17T12:00+09:00",
  "items": {
    "NVDA": {
      "updated": "2026-11-17", "by": "Claude 예약 작업 (구독)",
      "basis": "10-K(2026-01 회계연도), 2027 회계연도 2분기 실적 보도자료",
      "sources": [{"title": "NVIDIA 10-K (2026 회계연도)", "url": "https://www.sec.gov/...", "date": "2026-02-25"}],
      "one_liner": {"text": "한 줄 소개", "src": [1]},
      "business": [{"text": "무엇을 하나", "src": [1]}],
      "revenue": {"period": "2027 회계연도 2분기 (매출 962억 달러)", "note": "비중은 계산한 값",
                  "segments": [{"name": "데이터센터", "share_pct": 92.5, "note": "890억 달러, 전년 대비 +117%", "src": [2]}]},
      "management": [{"name": "젠슨 황 (Jensen Huang)", "role": "창업자 · CEO", "note": "", "src": [2]}],
      "vision": [{"text": "앞으로의 방향", "src": [2]}],
      "strengths": [{"text": "강점", "src": [1]}],
      "risks": [{"text": "위험 요인", "src": [1]}]
    }
  }
}
```
