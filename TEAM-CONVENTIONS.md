# festa 협업 규칙

세 레포 **공통 규칙**이 앞이고, 레포별로 다른 건 마지막 섹션에만 있습니다.

> 이 문서는 `festa-frontend`·`festa-backend`·`festa-crawler` **세 레포에 같은 내용으로
> 존재**합니다. 한 곳만 고치면 어긋나므로, 수정할 때 반드시 세 곳을 함께 고치세요.

이슈 → 브랜치 → 커밋 → PR → 릴리스가 자동으로 이어집니다. **이슈부터 만드세요.**

| 레포 | 스택 | 배포 |
| --- | --- | --- |
| `festa-frontend` | Next.js 16 · pnpm | Vercel (자동) |
| `festa-backend` | Spring Boot 4.1 · Java 21 · Gradle | 미설정 (백엔드팀 구성 예정) |
| `festa-crawler` | Python 3.13 · venv | 없음 (로컬 배치 크롤러) |

---

# 공통 규칙

## 1. 브랜치 전략

| 브랜치 | 역할 |
| --- | --- |
| `main` | 릴리스. 버전 태그·CHANGELOG가 여기서 확정 |
| `develop` | 배포 전 통합. **작업 브랜치는 여기서 분기** |
| 작업 브랜치 | 이슈 하나 = 브랜치 하나 |

```
 ① 이슈 생성 ──▶ 봇이 브랜치명·커밋 메시지 댓글
                        │
                        ▼
 작업브랜치     ●──●──●──┐   fix_31_로그인_시_500_에러
                ▲        │ ② PR → develop  (CI 통과해야 머지)
                │        ▼
 develop  ──●───┴────────●────────●──┐
            ③ 여기서 분기              │ ④ 릴리스 PR (develop → main)
                                     │    제목 자동변경 → CHANGELOG → 자동머지
                                     ▼
 main     ──────────────────────────●────  릴리스
                                      └─▶ 버전 태그 + README 갱신
```

**`main`에 직접 푸시 금지.** 브랜치 보호가 걸려 있진 않지만, 프론트는 그 순간 Production이 나갑니다.

## 2. 이슈 생성

**New issue → 템플릿 5종 중 선택.** 템플릿을 고르면 제목 태그와 타입 라벨이 자동으로 붙습니다.

| 템플릿 | 자동 라벨 | 브랜치 타입 |
| --- | --- | --- |
| ❗ 버그 이슈 | `type: fix` | `fix` |
| 🚀 기능 요청 \| 추가 \| 개선 | `type: feat` | `feat` |
| ♻️ 리팩토링 | `type: refactor` | `refactor` |
| 🔧 설정 · 빌드 | `type: chore` | `chore` |
| 📄 문서 | `type: docs` | `docs` |

**제목**

- **한글로 써도 됩니다.** 브랜치명에 그대로 들어갑니다
- 자동으로 붙는 `[버그]` 같은 태그는 지우지 마세요
- 예: `❗ [버그] 로그인 시 500 에러`

**상태 라벨** — 작업 진행에 따라 바꿔주세요 (Projects 보드는 안 씁니다)

`작업전` → `작업중` → `담당자확인` → `작업완료`
(그 외: `피드백` `보류` `취소` `긴급`)

## 3. 브랜치명

이슈를 만들면 **봇이 댓글로 브랜치명과 커밋 메시지를 알려줍니다.** 복사해서 쓰세요.

```
타입_이슈번호_제목슬러그
```

**브랜치명에 한글을 씁니다.** 억지로 영어로 옮기지 마세요 — 이슈 제목을 그대로 쓰면 됩니다.

| 이슈 | 브랜치 |
| --- | --- |
| `#31 ❗ [버그] 로그인 시 500 에러` | `fix_31_로그인_시_500_에러` |
| `#32 🚀 [기능요청] 축제 목록 API` | `feat_32_축제_목록_api` |
| `#33 ♻️ [리팩토링] Entity 분리` | `refactor_33_entity_분리` |

한글 브랜치명은 `git push`·PR 생성·GitHub Actions·`gh` CLI 모두 정상 동작합니다.
프론트·백엔드 양쪽에서 실측으로 확인했습니다.

```bash
git switch develop && git pull
git switch -c fix_31_로그인_시_500_에러
git push -u origin HEAD          # 커밋 전에 빈 브랜치를 먼저 올립니다
```

> 빈 브랜치를 먼저 올리는 이유: GitHub은 브랜치를 **새로 만드는** 푸시에서 커밋 메시지를 스캔하지 않습니다. 먼저 올려두어야 이후 커밋이 이슈 타임라인에 잡힙니다.

- 한글·영문소문자·숫자만 남고 나머지는 `_`로 이어집니다 (영문 대문자는 소문자로)
- 타입 라벨을 바꾸면 **봇 댓글이 자동으로 갱신**됩니다
- 이 형식을 지켜야 브랜치명에서 이슈 번호가 자동 추출됩니다

## 4. 커밋 메시지

봇 댓글의 커밋 메시지를 복사해 `{...}` 부분만 채웁니다.

```
<타입> : <변경 사항 설명> #<이슈번호>
```

```
fix : 세션 만료 시 401 반환하도록 수정 #31
```

타입: `feat` `fix` `refactor` `chore` `docs`

## 5. PR

### 일반 PR (작업 브랜치 → `develop`)

- 제목: 커밋 메시지와 같은 형식으로 짧게
- 본문: PR 템플릿의 **변경 사항** / **테스트** 채우기
- 본문 마지막에 `관련 이슈: #31` 로 이슈를 연결합니다
- ⚠️ `close #31` 은 쓰지 마세요 — 작업 PR은 `develop`으로 머지되는데 GitHub의 자동 종료는 기본 브랜치(`main`) 머지에서만 동작합니다
- **머지하면 이슈는 자동으로 닫힙니다.** 브랜치명(`타입_이슈번호_슬러그`)에서 번호를 뽑아 `작업완료` 라벨로 바꾸고 종료합니다 — 브랜치 규칙을 지키는 것이 곧 이슈 연동입니다

### 릴리스 PR (`develop` → `main`)

열기만 하면 나머지는 자동입니다.

1. 제목이 `🚀 Deploy YYYYMMDD-vX.Y.Z` 로 자동 변경
2. `CHANGELOG.md` / `CHANGELOG.json` 자동 생성
3. **자동 머지**
4. 버전 태그 + README 버전 갱신 (+ 프론트는 Production 배포)

> ⚠️ **`main`으로 가는 PR은 `develop`에서만 여세요.** 작업 브랜치에서 바로 `main`으로 열면 릴리스 파이프라인이 통째로 건너뜁니다. 이건 관례가 아니라 워크플로우에 걸린 유일한 강제 조건입니다.

릴리스 후 `main`에 생기는 README 버전 커밋은 **자동으로 `develop`에 역병합**되므로 따로 할 일은 없습니다.

## 6. 에이전트 커맨드

위 흐름을 대신 실행해 주는 커맨드가 있습니다. Claude Code와 Codex 양쪽에서 같은 것을 씁니다.

| 커맨드 | 하는 일 |
| --- | --- |
| `/issue` | 템플릿에 맞춰 이슈 제목·본문 작성 |
| `/issue-branch` | `/issue` + GitHub 등록 + 브랜치 생성·선행 푸시 |
| `/commit` | 변경사항을 기능별로 나눠 커밋 (push 안 함) |
| `/report` | 구현 보고서 + 결정 기록(ADR) |
| `/pr-description` | PR 본문 생성 |
| `/rp` | `/report` + `/pr-description` 동시 실행 |
| `/cr` | `/commit` + `/report` 동시 실행 |

**규칙 원본은 `.claude/commands/*.md` 한 곳뿐입니다.** Codex는 `.agents/skills/`에서
같은 파일을 읽습니다. 커맨드를 고치면 양쪽에 동시에 반영됩니다 — 내용을 복사해 두면
반드시 어긋납니다.

산출물은 레포에 커밋합니다 (숨김 폴더 아님):

```
docs/issues/    이슈 초안
docs/reports/   구현 보고서
docs/pr/        PR 본문 초안
```

---

# 레포별 차이

## CI/CD

| 언제 | `festa-frontend` | `festa-backend` | `festa-crawler` |
| --- | --- | --- | --- |
| PR → `main`/`develop` | 빌드 검증 (`pnpm build`) | — *(백엔드팀 구성 예정)* | — *(필요해지면 추가)* |
| push `develop` | Vercel **Preview** 배포 | — | — |
| push `main` | Vercel **Production** 배포 | — | — |
| push `main` | 버전 태그 + README 갱신 | 버전 태그 + README 갱신 | 버전 태그 + README 갱신 |
| `develop` → `main` PR | CHANGELOG + 자동 머지 | CHANGELOG + 자동 머지 | CHANGELOG + 자동 머지 |
| 이슈 생성 / 제목·라벨 변경 | 브랜치명 댓글 | 브랜치명 댓글 | 브랜치명 댓글 |
| PR → `develop` 머지 | 이슈 자동 종료 | 이슈 자동 종료 | 이슈 자동 종료 |
| 에이전트 커맨드 | Claude · Codex 7종 | Claude · Codex 7종 | Claude · Codex 7종 |

이슈·브랜치·커밋·릴리스·커맨드는 **세 레포가 완전히 동일**합니다. 다른 건 배포와 스택뿐입니다.

## festa-frontend

**패키지 매니저는 pnpm.** `npm` 쓰지 마세요 — `package-lock.json`이 생기면 CI가 깨집니다.

```bash
pnpm install
pnpm dev
```

**환경변수는 Vercel에 등록합니다.** 빌드가 Vercel에서 돌기 때문에 GitHub Secrets에 넣어도 앱에 안 들어갑니다.

- Vercel → Settings → Environment Variables (Production / Preview 각각)
- 로컬: `vercel env pull .env.local`

## festa-backend

```bash
./gradlew build
./gradlew bootRun
```

- Java 21 / Gradle 9.6 (Kotlin DSL)
- **배포는 아직 없습니다.** 백엔드팀이 구성하며, `main` push에 워크플로우를 붙이면 프론트와 같은 흐름이 됩니다
- `version.yml`의 `options.deploy`는 `none`입니다. `docker-ssh`로 되돌리면 `npx projectops` 업데이트 때 Docker 워크플로우가 재설치되니 주의하세요
- `/commit`의 포맷 단계는 비어 있습니다. 포맷터(spotless 등)가 정해진 뒤에 채웁니다

## festa-crawler

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python crawl.py --year 2026    # 수집·추출 → output/<연도>/
.venv/bin/python -m pytest
```

- Python 3.13 / venv + `requirements.txt` (pyproject.toml 없음)
- **배포가 없습니다.** 서버가 아니라 손으로 돌리는 로컬 배치 크롤러입니다
- **테스트 CI도 아직 없습니다.** 필요해지면 `on: pull_request` 워크플로우를 추가합니다
- **수집 결과(`output/`)는 커밋하지 않습니다.** 재생성 가능하고 매 실행마다 바뀝니다
- `version.yml`의 `options.deploy`는 `none`입니다. 되돌리면 `npx projectops` 업데이트 때 배포 워크플로우가 설치됩니다
- `/commit`의 포맷 단계는 비어 있습니다. 포맷터(ruff 등) 도입 후 채웁니다
- 커맨드 산출물 외에 설계·계획 문서를 `docs/plans/` `docs/specs/`에 함께 둡니다

---

# 요약 — 작업 흐름

```
1. 이슈 생성 (템플릿 선택, 제목 한글 OK)
2. 봇 댓글에서 브랜치명 복사 → develop에서 분기 → 빈 채로 먼저 push
3. 작업 후 봇 댓글의 커밋 메시지 형식으로 커밋 → push
4. develop으로 PR → 머지 (이슈 자동 종료)
5. 배포할 때 develop → main PR → 자동 머지
```

`/issue-branch` 하나로 1~2번이 끝납니다.
