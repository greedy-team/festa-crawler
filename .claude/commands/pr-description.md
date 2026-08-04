# PR Description Mode - PR 본문 생성

당신은 GitHub PR description 작성 전문가입니다. **변경 내용을 기반으로 PR 본문을 생성**하세요. 보고서가 "구현이 끝난 후 무엇을 했나"를 정리한다면, 이 커맨드는 "리뷰어가 봐야 할 PR 본문"을 만듭니다.

## 핵심 원칙

- 입력: `docs/reports/` 보고서, 사용자가 붙여넣은 텍스트, 또는 `git` 상태 — 하나 이상
- 출력: GitHub PR description으로 그대로 붙여넣을 수 있는 **마크다운 텍스트**
- 톤: **사실만 담백하게**. 마케팅·과장·재치 금지
- 브랜치명에서 타입·이슈 번호 자동 추출 → `관련 이슈: #N` 자동 삽입
- 변경 의도(WHY)와 동작 변화(Before/After)를 명확히
- 리뷰어가 5분 내 컨텍스트를 잡을 수 있게

## 절대 금지 사항

- `Claude`, `AI`, `자동 생성`, `Co-Authored-By: Claude` 등 AI 관련 표현 금지
- `Generated with Claude Code` 같은 푸터 금지
- 작성자/작성일/모델명 메타 정보 금지
- 시크릿 노출 금지 (API key, password, token, secret 등 → `{API_KEY}`, `{TOKEN}` 형태로 마스킹)
- 과장·이모지 떡칠 금지 (헤더용 최소 이모지는 허용, 본문 이모지 금지)
- 추측·미확인 사실 금지 (`아마도`, `~일 듯`, `것으로 보입니다` 표현 사용 안 함)
- 구현 노트 같은 잡담 금지 ("처음엔 X로 시도했지만…" 류는 보고서에)

## 처리 절차

### 1단계: 입력 식별 (우선순위 순)

1. **`docs/reports/` 보고서 우선**: 현재 브랜치 이슈 번호 또는 날짜로 매칭되는 보고서가 있으면 그걸 1차 소스로 사용
2. **사용자가 붙여넣은 텍스트**가 있으면 보조 컨텍스트로 활용
3. **`git` 상태 추론** (위 둘 다 없을 때만):
   - `git status`로 변경 파일 목록
   - `git log origin/main..HEAD --oneline`으로 커밋 흐름
   - **이후 추가 git 명령 최소화** (토큰 절약)

### 2단계: 컨텍스트 추출

- **이슈 번호·타입**: 브랜치명에서 함께 추출

  ```bash
  git branch --show-current | grep -oE "^(feat|fix|refactor|chore|docs)_[0-9]+_"
  ```

  - `fix_31_로그인_시_500_에러` → 타입 `fix`, 번호 `31`
  - 매칭 안 되면 `관련 이슈` 줄 생략
- **커밋 타입 분류**: `feat`/`fix`/`refactor`/`chore`/`docs`
  - PR 제목 prefix 결정용
- **변경 파일 그룹핑**: 같은 기능·도메인끼리 묶기

### 3단계: PR 본문 작성

다음 구조로 작성하되, **해당 없는 섹션은 생략**합니다:

```markdown
## Summary

[1-2문장. 무엇을 / 왜]

## Changes

- [변경 사항 1 — 파일·기능 단위, 한 줄]
- [변경 사항 2]
- [변경 사항 3]

## Behavior Change

| 항목 | Before | After |
|---|---|---|
| [동작 1] | [기존] | [변경] |

또는 코드 블록 형태로:

```ts
// Before
if (isExpired(token)) throw new Error("expired");

// After
if (isExpired(token)) {
  return NextResponse.json({ code: "TOKEN_EXPIRED" }, { status: 401 });
}
```

## Test Plan

- [ ] base 브랜치가 `develop`인지 확인 (`main`으로 열면 릴리스 파이프라인이 스킵됩니다)
- [ ] [자동 검증 — lint/test 통과 등]
- [ ] [수동 검증 항목 1]
- [ ] [수동 검증 항목 2]

## Notes

- [추가 컨텍스트, 디자인 문서 위치, 알려진 한계, 후속 작업 등 — 선택]

관련 이슈: #N
```

### 섹션별 작성 규칙

**Summary**
- 2문장 이내
- "이 PR은…" 같은 메타 도입 없이 바로 사실 진술
- 좋은 예: "세션이 만료됐을 때 500 에러가 반환되던 #31 이슈를 수정한다. 만료 체크 분기를 401 응답으로 통일했다."
- 나쁜 예: "이 PR에서는 #31 이슈를 해결하기 위해 다양한 작업을 진행하였습니다."

**Changes**
- 파일·기능 단위로 한 줄씩
- 동사로 시작 ("제거", "단순화", "추가")
- 파일 경로는 백틱으로 감싸기

**Behavior Change**
- 사용자/리뷰어가 체감하는 동작 변화가 있을 때만 작성
- 표 또는 Before/After 코드 블록 둘 중 하나 선택
- 순수 리팩토링이라 동작 변화가 없으면 "동작 변화 없음" 한 줄로 명시

**Test Plan**
- 체크박스 형식 (리뷰어가 PR 페이지에서 클릭 가능)
- 자동(analyze/test) + 수동(시나리오) 분리
- 수동 검증이 불가능한 경우 그 이유를 명시

**Notes**
- 디자인 문서 경로 (`docs/reports/...md`), 후속 정리 항목, trade-off, 디자이너 검토 필요 여부 등
- 없으면 섹션 자체 생략

**관련 이슈**

- 마지막에 한 줄 — `관련 이슈: #31` 형식
- **`Closes #N`을 쓰지 않습니다.** 이 워크플로우에서는 동작하지 않습니다:
  작업 PR은 `develop`으로 머지되는데 GitHub의 closing keyword는 기본 브랜치(`main`)
  머지에서만 동작하고, 릴리스 PR 본문은 RELEASE-CHANGELOG가 CHANGELOG로 덮어씁니다
- 이슈는 **PR 머지 시 자동으로 닫힙니다** — CLOSE-ISSUE-ON-MERGE 워크플로우가 브랜치명에서 이슈 번호를 뽑아 `작업완료` 라벨로 바꾸고 종료합니다

## 출력 형식

1. **PR 제목 제안 (한 줄)**: `<type> : <한글 설명> #N`
2. **PR 본문 마크다운** (체크박스·표·코드 블록 포함)
3. **사용 안내 한 줄**: 클립보드 복사 또는 `gh pr create --body "$(cat ...)"` 안내

```markdown
PR 제목 제안:
fix : 세션 만료 시 401 반환하도록 수정 #31

---

## Summary
...

## Changes
...

(이하 본문)
```

## 파일 저장 (선택)

- 기본은 **출력만** — 사용자가 PR 작성 화면에 붙여넣음
- 사용자가 명시적으로 저장을 원할 때만 `docs/pr/` 디렉토리에 저장
  - 경로: `docs/pr/{YYYYMMDD}_{이슈번호}_{설명}.md`
  - `docs/pr/`는 **추적 대상**이다 — gitignore에 넣지 않는다

## 작성 예시

### 입력
- 브랜치: `fix_31_로그인_시_500_에러`
- 보고서: `docs/reports/20260803_31_로그인_시_500_에러.md` 존재
- 커밋: `fix : 세션 만료 시 401 반환하도록 수정 #31`

### 출력

```markdown
PR 제목 제안:
fix : 세션 만료 시 401 반환하도록 수정 #31

---

## Summary

세션이 만료됐을 때 500 에러가 반환되던 #31 이슈를 수정한다. 만료 체크 이후 예외를 던지던 경로를 제거하고, 만료 시 `TOKEN_EXPIRED` 코드와 함께 401을 반환하도록 통일했다.

## Changes

- `SessionController`: 만료 분기에서 500 예외 대신 401 응답 반환
- `TokenValidator`: `isExpired` 판정에 만료 임계값 상수 분리

## Behavior Change

```ts
// Before
if (isExpired(token)) throw new Error("expired");

// After
if (isExpired(token)) {
  return NextResponse.json({ code: "TOKEN_EXPIRED" }, { status: 401 });
}
```

| 항목 | Before | After |
|---|---|---|
| 세션 만료 응답 | 500 Internal Server Error | 401 + `TOKEN_EXPIRED` |
| 클라이언트 처리 | 에러 바운더리로 흡수, 재로그인 유도 실패 | 401 감지 후 로그인 페이지로 리다이렉트 |

## Test Plan

- [ ] base 브랜치가 `develop`인지 확인 (`main`으로 열면 릴리스 파이프라인이 스킵됩니다)
- [ ] `.venv/bin/python -m pytest` 통과
- [ ] 만료된 토큰으로 요청 시 401 + `TOKEN_EXPIRED` 응답 확인
- [ ] 클라이언트에서 401 수신 시 로그인 페이지로 정상 리다이렉트

## Notes

- 상세 결정 근거: `docs/reports/20260803_31_로그인_시_500_에러.md`

관련 이슈: #31
```

위 마크다운을 GitHub PR 본문에 붙여넣으세요. 또는:

```bash
gh pr create --title "fix : 세션 만료 시 401 반환하도록 수정 #31" --body "$(cat <<'EOF'
... (위 본문)
EOF
)"
```

## 분석 효율성 원칙

- `git status` 1회 → 보고서 파일 우선 → 추가 git 명령 최소화
- `docs/reports/` 보고서가 있으면 그걸 핵심 소스로 사용 (이미 정제된 컨텍스트)
- 변경 파일 전체 diff를 읽지 말고 보고서·커밋 메시지 기반으로 추론
- 의문 사항은 PR 본문에 `Notes` 섹션으로 명시 (추측 금지)

## 출력 후

PR 본문 출력 후 한 줄 안내로 종료 — 추가 질문하지 않음.
