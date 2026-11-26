# invest-dashboard — 작업 안내 (Codex 등 AI 코딩 도구용)

개인용 투자 대시보드입니다. 2026-11-20까지 Claude Code로 만들었고, 그 뒤로 ChatGPT Codex로 이어서 작업합니다. Claude용 안내(`CLAUDE.md`)와 내용이 같습니다. 둘을 고칠 때는 함께 고칩니다.

**2026-11-26부터 사용자가 Claude 구독을 한 달쯤 쉽니다. 먼저 `HANDOFF.md`(Codex 인수인계)를 읽습니다.** 그다음 `README.md` 의 **"새 대화에서 이어가기"**와 **"나중에 할 일"**을 먼저 읽습니다. 지금 상태, 사용자와 정한 일하는 방식, 저장소 밖에 있는 것, 확인이 남은 것이 거기에 있습니다. 바뀐 내용의 기록은 `CHANGELOG.md` 에 있습니다.

## 꼭 지킬 것

- 사용자에게는 한국어 존댓말로, 쉬운 말로 간결하게 답합니다. 못 하는 일은 이유와 필요한 조치를 함께 설명합니다. 정보를 조사할 때는 가장 최근 정보로 답합니다.
- 기능은 하나씩 붙이고, 붙일 때마다 실제 데이터로 수집을 돌리고 화면(PC 1280px, 휴대폰 390px)을 확인해 스크린샷을 보여 줍니다. 작업 환경에서 인터넷이나 브라우저를 쓸 수 없으면 확인하지 못했다고 분명히 말합니다.
- `main` 에 직접 올리지 않습니다. 작업 브랜치에 올린 뒤 사용자가 요청하면 PR을 만들고, 병합되면 실제 사이트(https://lwindowy.github.io/invest-dashboard/)에서 배포를 확인합니다. PR 병합은 사용자가 직접 합니다.
- 저장소가 공개입니다. 노션의 글(유료 구독 콘텐츠 정리, 개인 메모), 보유 수량 같은 개인 정보, 비밀값(토큰·API 키)은 넣지 않습니다. 비밀값은 GitHub Secrets에 사용자가 직접 넣습니다.
- 직접 정한 기준값과 확인하지 못한 부분은 숨기지 않고 알립니다. 값을 지어내지 않습니다. 투자 논리 점검판(`config/thesis.json`)의 사실은 SEC 공시·회사 보도자료로 확인한 것만 적고 문장마다 출처 번호를 답니다.
- 봇 차단을 우회하지 않습니다.
- 작업을 끝내면 `README.md`(기능 표, "새 대화에서 이어가기", "나중에 할 일")와 `CHANGELOG.md` 를 함께 고칩니다.

## 빠른 확인

```bash
pip install -r scripts/requirements.txt
python scripts/fetch_data.py --prev site/data/dashboard.json
python -m http.server 8765 --directory site
```

- 첫 수집은 포워드 PER과 SEC 때문에 3~4분 걸리고, 같은 날 다시 돌리면 빠릅니다.
- 수집에는 인터넷이 필요합니다(Yahoo Finance, FRED, 연준, 위키백과, CFTC, SEC, GitHub Pages). Codex 클라우드 환경은 기본으로 인터넷이 꺼져 있을 수 있어 환경 설정에서 켜야 합니다. 이전 수집 결과는 실제 사이트의 `data/dashboard.json` 을 받아 `site/data/` 에 두고 `--prev` 로 넘기면 됩니다(`site/data/` 는 저장소에 올리지 않음).
- 설정을 고친 뒤 검사: `python scripts/thesis.py check` (투자 논리 점검판), `node --check site/app.js` (화면 코드 문법).

## Claude 쪽에 남아 있는 것 (Codex에서는 관리할 수 없음)

- Claude 예약 작업 두 개(아침·오후 브리핑, 뉴스 분류·회사 소개)는 사용자의 Claude 구독으로 돕니다. **2026-11-26부터 구독을 쉬는 동안에는 멈춰 있습니다(고장 아님, `HANDOFF.md` 참고).** 뉴스 분류 작업은 `config/ai_tasks/` 의 안내를 따라 `ai-results` 브랜치에 결과를 올리고, 그러면 사이트가 갱신됩니다. 이 파일들과 `ai-results` 브랜치의 형식을 바꾸면 그 작업이 깨질 수 있으니 바꾸기 전에 사용자에게 확인합니다. 그 작업을 멈추거나 바꾸려면 사용자가 Claude 앱에서 해야 합니다.
