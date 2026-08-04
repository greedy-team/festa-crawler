# festa-crawler

대학 축제 정보(축제 상세 + 라인업)를 큐레이션된 블로그 URL에서 수집·추출해 사람이 검토할
CSV로 만드는 **로컬 배치 크롤러**입니다. 서버가 아니라 손으로 돌리는 파이프라인이며,
배포 대상이 없습니다.

## 빠른 시작

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python crawl.py [--limit N]   # 수집·추출 → output/festivals.csv, output/lineup.csv
.venv/bin/python enrich.py              # 아티스트 표기 정규화 → output/artists.csv
.venv/bin/python -m pytest              # 테스트
```

LLM 추출은 로컬 Claude Code CLI(`claude`)를 헤드리스로 호출합니다 — 실행 전 `claude`
로그인이 되어 있어야 합니다.

## 작업 원칙

**코드를 만지기 전에 [`.claude/rules/coding-principles.md`](./.claude/rules/coding-principles.md)를 읽으세요.**

가정을 말하고 시작하기 / 최소한으로 만들기 / 외과적으로 바꾸기 / 검증 기준 먼저 세우기 /
같은 규칙을 두 곳에 적지 않기 — 다섯 가지이며, 각각 이 프로젝트에서 실제로 터진 사례가
근거로 붙어 있습니다.

## 지침 파일 지도

**내용은 전부 `.claude/` 아래에 둡니다. 다른 도구는 그것을 읽습니다.**
같은 규칙을 두 벌로 관리하면 반드시 어긋나기 때문입니다.

| 파일 | 담는 것 | Claude Code | Codex |
| --- | --- | --- | --- |
| `AGENTS.md` | 프로젝트 사실·제약 (이 파일) | `CLAUDE.md`가 import | 세션 시작 시 자동 |
| `.claude/rules/coding-principles.md` | 작업 원칙 | `CLAUDE.md`가 import | **이 파일의 링크를 따라 읽으세요** |
| `TEAM-CONVENTIONS.md` | 이슈·브랜치·커밋·PR 규칙 | 필요 시 | 필요 시 |
| `.claude/commands/*.md` | 커맨드 워크플로우 | 슬래시 커맨드 | `.agents/skills/`가 가리킴 |

Codex는 `AGENTS.md`와 `.agents/skills/`만 자동으로 읽습니다. `.claude/` 아래 파일은
자동으로 열리지 않으니, 위 표의 경로를 직접 읽으세요.

## 하드 제약

깨면 안 되는 것들입니다. 어긴 채 진행하지 마세요.

- **`main`에 직접 푸시 금지.** `main`은 릴리스 브랜치입니다
- **`version.yml`의 `options.deploy`는 `none`으로 유지.** 다른 값으로 되돌리면
  `npx projectops` 업데이트 때 배포 워크플로우가 설치됩니다
- **수집 결과(`output/`)는 커밋하지 않습니다.** 크롤링 산출물이라 재생성 가능하고, 매 실행마다 바뀝니다
- **robots.txt와 요청 간격을 우회하지 않습니다.** 남의 서버를 긁는 코드입니다
- **커밋 메시지에 `Co-Authored-By` 금지**
- **커밋·푸시는 사용자가 요청할 때만.** 알아서 하지 않습니다

## 기술 스택

- Python 3.13 · venv + `requirements.txt` (pyproject.toml 없음)
- requests · beautifulsoup4 · trafilatura (본문 추출 폴백) · pydantic (스키마)
- pytest 8
- LLM 추출: 로컬 `claude` CLI 헤드리스 호출 (API 키 아님 — 구독 세션을 씁니다)

## 구조

| 파일 | 하는 일 |
| --- | --- |
| `crawl.py` | 오케스트레이션 — 시드 순회, 캐시 판정, flag 부여, CSV 출력 |
| `fetch.py` | 본문 수집 (셀렉터 + trafilatura 폴백, robots.txt·요청 간격 준수) |
| `extract.py` | `claude -p` 추출 (검증 + 재시도 + 역방향 검증) |
| `enrich.py` | 아티스트 표기 정규화, 아티스트 마스터 생성 (LLM 1콜 후처리) |
| `schema.py` | pydantic 스키마 |
| `universities.csv` | 대학 29곳 시드 (URL 포함) |

동작 세부(flag 의미, 캐시 규칙, 운영 팁)는 [`README.md`](./README.md)에,
설계 근거는 [`2026-08-04-crawler-pipeline-design.md`](./2026-08-04-crawler-pipeline-design.md)에 있습니다.

## 코드 스타일

- 기존 파일의 스타일을 따릅니다. 주변 코드와 다른 방식을 새로 들이지 않습니다
- 포맷터는 아직 도입 전입니다. 도입되면 이 문단과 `/commit`의 포맷 단계를 함께 채웁니다
- 요청하지 않은 리팩터링·추상화를 끼워 넣지 않습니다

## 작업 흐름

이슈 → 브랜치 → 커밋 → PR → 릴리스가 GitHub Actions로 이어집니다.
**규칙 원본은 [`TEAM-CONVENTIONS.md`](./TEAM-CONVENTIONS.md)입니다.** 여기서 반복하지 않습니다.

요약하면:

- 작업은 **이슈부터** 만듭니다. 봇이 브랜치명과 커밋 메시지를 댓글로 알려줍니다
- 브랜치는 `develop`에서 분기하고, **커밋 전에 빈 채로 먼저 푸시**합니다
- 브랜치명은 `타입_이슈번호_슬러그` (한글 그대로 씁니다)
- 커밋은 `<타입> : <변경 사항 설명> #<이슈번호>`
- PR은 `develop`으로. 머지하면 이슈가 자동으로 닫힙니다

`main`으로 가는 PR은 `develop`에서만 엽니다. 이것만 워크플로우로 강제됩니다.

이슈·브랜치·커밋·릴리스 규칙은 `festa-frontend`·`festa-backend`와 **완전히 동일**합니다.
다른 것은 배포뿐입니다.

## 커맨드

위 흐름을 대신 실행하는 커맨드가 있습니다.

| | |
| --- | --- |
| Claude Code | `.claude/commands/*.md` — `/issue` `/issue-branch` `/commit` `/report` `/pr-description` `/rp` `/cr` |
| Codex | `.agents/skills/*/SKILL.md` — 같은 파일을 읽습니다 |

**규칙 원본은 `.claude/commands/` 한 곳뿐입니다.** Codex 스킬은 내용을 복사하지 않고 그 파일을 가리킵니다.

산출물은 레포에 커밋합니다 (숨김 폴더 아님):

```
docs/issues/    이슈 초안
docs/reports/   구현 보고서
docs/pr/        PR 본문 초안
```

`/commit`의 포맷 단계는 비어 있습니다 — 포맷터(ruff 등) 도입 후 채웁니다.

## CI/CD

| 언제 | 무엇이 |
| --- | --- |
| 이슈 생성·라벨 변경 | 브랜치명·커밋 메시지 댓글 |
| PR → `develop` 머지 | 이슈 자동 종료 |
| `develop` → `main` PR | CHANGELOG 생성 후 자동 머지 |
| push `main` | 버전 태그 + README 갱신 |
| **테스트 CI** | **미설정** — 필요해지면 `on: pull_request` 워크플로우를 추가합니다 |
| **배포** | **없음** — 로컬 배치 크롤러입니다 |

워크플로우가 **어느 브랜치에서 읽히는지**가 중요합니다. `issues`·`issue_comment`·
`pull_request_target`은 기본 브랜치(`main`)에서 읽습니다. 봇 설정을 `develop`에만 두면
이슈 이벤트에는 반영되지 않습니다.

버전은 `version.yml` 하나가 소스입니다 (`project_types: ["basic"]`).
`pyproject.toml`을 도입하면 `"python"`으로 바꾸세요.

## 주의할 점

- 릴리스 워크플로우는 `git add -A`로 커밋합니다. 워킹 트리에 남긴 임시 파일이 릴리스 커밋에 쓸려 들어갑니다
- `.github/scripts/`와 워크플로우는 `npx projectops` 업데이트 시 덮어써집니다. 설정은 코드 기본값이 아니라 `version.yml`에 둡니다
- `version.yml`의 `deploy:` 블록은 런타임에 아무도 읽지 않습니다. `npx projectops` 재실행 때만 쓰이는 메모입니다
- Claude 구독 세션 한도에 걸리면 크롤러가 중단됩니다. 리셋 후 같은 명령으로 재실행하면 캐시로 이어서 처리합니다
