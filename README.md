# invest-dashboard

흩어진 투자 정보를 한 화면에 모아 보는 개인용 대시보드입니다. 실제 시장 데이터를 30분마다 자동으로 받아 GitHub Pages에 올립니다. 혼자 쓰는 용도이고, 모든 신호는 참고용 점검 알림입니다.

- 설계서: https://claude.ai/artifact/TfGt61CeD4imQgoTPs3qs5
- 홈 화면 시안: https://claude.ai/artifact/WetkXZkh1DDMevfHGjF6pK
- 변경 기록: [CHANGELOG.md](CHANGELOG.md)

## 구조

```
config/dashboard.json   종목, 지표, 탭 배치, 국면 판단 기준값 (여기만 고치면 됩니다)
config/manual.json      직접 입력하는 값과 일정
scripts/fetch_data.py   설정을 읽어 데이터를 받고 site/data/dashboard.json 으로 저장
site/                   화면 (index.html, style.css, app.js). 저장된 JSON만 읽습니다
.github/workflows/update.yml   30분마다 수집 → GitHub Pages 배포
```

흐름: 설정 파일 → 수집 스크립트 → `site/data/dashboard.json` → 화면. 수집 결과는 저장소에 올리지 않고 배포할 때마다 새로 만듭니다.

## 지금 들어 있는 기능

| 탭 | 상태 | 내용 |
| --- | --- | --- |
| 홈 | 완료 | 시장 국면 판단판 7칸, 주요 지수 4개, VIX, 심리 지수, 관심 종목(현재가·등락률·RSI·52주 고점 대비·3개월 추이), 이번 주 일정, 금리와 환율 |
| 거시경제 | 완료 | 금리 6개와 수익률 곡선, 신용, 물가, 고용, 경기, 통화·환율, 원자재, 한국. 지표마다 최신값·직전 대비 변화·추이·다음 발표일 |
| 종목, 캘린더 | 1차 예정 | 자리만 있음 |
| 큰손·유동성, 산업 | 2차 예정 | 자리만 있음 |
| 내 기록 | 3차 예정 | 자리만 있음 |

공통: 밝은·어두운 화면 전환, 상승·하락 색 한국식·미국식 전환(브라우저에 저장), 데이터마다 출처와 기준일 표시, 좁은 화면에서 한 줄로 쌓이는 반응형.

## 자주 하는 수정

- **종목 추가·삭제**: `config/dashboard.json` 의 `watchlist` 에 한 줄을 넣거나 지웁니다. 한국 종목은 `005930.KS` 처럼 `.KS` 를 붙입니다.
- **지표 추가**: `series` 에 한 줄을 넣고(`"source": "yahoo"` 는 `symbol`, `"source": "fred"` 는 `id`), 보여줄 탭의 `sections[].items` 에 그 이름을 넣습니다. FRED 지표는 `freq`(M·Q·W)와 `transform`(`yoy` 전년 대비, `mom_pct` 전월 대비 %, `mom_diff` 전월 대비 증감)을 쓸 수 있고, `event` 를 적으면 다음 발표일이 일정에 들어갑니다.
- **직접 입력 값**: `config/manual.json` 의 `values` 에 값과 입력한 날짜(`entered`)를 적습니다.
- **국면 판단 기준 변경**: `regime` 의 숫자를 고칩니다. 화면의 "판단 기준 보기"에 그대로 반영됩니다.
- **직접 적는 일정**: `config/manual.json` 의 `events` 에 `{ "date": "2026-12-01", "title": "…", "kind": "내 이벤트" }` 를 넣습니다.
- **FOMC 날짜**: `calendar.fomc` 에 결정일을 적습니다.

## 데이터 출처

| 데이터 | 출처 | 비고 |
| --- | --- | --- |
| 주가, 지수, 환율, 실적일 | Yahoo Finance (`yfinance`) | 15분가량 지연 |
| 금리, 하이일드 스프레드 | FRED 공개 CSV | 키 없이 받음. 하루 한 번 갱신, 1~2일 늦음 |
| RSI, 이동평균, 국면 판단, 심리 지수 | 주가로 직접 계산 | RSI는 Wilder 방식(트레이딩뷰 기본과 같은 계산) |

설계서와 다르게 처리한 것:

- **Fear & Greed**: CNN이 자동 수집을 차단해서 받지 않습니다. 대신 같은 취지의 "심리 지수 (자체 계산)"를 씁니다. 모멘텀, 변동성, 안전자산 수요, 시장 폭, 정크본드 수요 다섯 가지가 최근 1년 중 어느 위치인지(백분위)를 평균한 0~100 값이며, CNN 값과 숫자가 같지 않습니다.
- **시장 폭**: 개별 종목 500개를 30분마다 받는 대신 11개 섹터 ETF 중 200일선 위에 있는 개수로 봅니다.
- **경제지표 발표일**: FRED 지표 페이지의 "Next Release Date"를 읽습니다. 키가 필요 없고, 날짜가 지났을 때만 다시 받습니다.
- **CPI 전년 대비**: 2025년 10월 CPI는 발표되지 않아, 2026년 10월 값은 앞뒤 달로 추정한 1년 전 값과 비교합니다. 화면에 추정이라고 표시합니다.
- **한국은행 기준금리**: 무료 자동 수집 경로가 없어 `config/manual.json` 에 직접 적습니다. 한국은행 ECOS API 키(무료)를 받으면 자동화할 수 있습니다.
- **한국 수출액**: FRED의 OECD 집계를 쓰며 2~3개월 늦습니다.

## 원칙

- 기능은 하나씩 붙이고, 붙일 때마다 화면을 확인하고 변경 기록을 남깁니다.
- 한 종목·지표 수집이 실패해도 나머지는 정상 표시합니다. 실패한 항목은 직전 배포의 값을 "이전 값"으로 표시합니다.
- 비밀값은 코드에 쓰지 않고 GitHub Secrets에 넣습니다. 실제 계좌 정보는 넣지 않습니다.
- 보유 수량 같은 개인 기록은 저장소가 아니라 브라우저에만 저장합니다.

## 내 컴퓨터에서 돌려 보기

```bash
pip install -r scripts/requirements.txt
```

```bash
python scripts/fetch_data.py
```

```bash
python -m http.server 8000 --directory site
```

## 배포

`main` 브랜치에서 `.github/workflows/update.yml` 이 매시 7분과 37분에 실행됩니다. 저장소 Settings → Pages → Source 가 "GitHub Actions" 여야 합니다. GitHub 예약 실행은 몇 분에서 수십 분 늦을 수 있고, 공개 저장소는 60일 동안 변경이 없으면 예약 실행이 꺼지므로 그때는 Actions 탭에서 다시 켭니다.
