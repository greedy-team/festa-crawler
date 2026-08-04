# 인스타그램 총학 계정 핸들 수집 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 블로그 HTML에서 인스타그램 계정 후보를 수집하고 LLM이 총학 계정만 판별해 `festivals.csv`에 `instagram_handle` 컬럼으로 싣는다 (이슈 #1).

**Architecture:** 하이브리드 — `fetch.py`가 HTML href에서 후보를 정규식 수집(`FetchResult.instagram_candidates`), `extract.py`가 후보 목록을 프롬프트에 넣어 문맥으로 판별(`ExtractionResult.instagram_handle`), `crawl.py`가 CSV로 연결. 마지막에 캐시 초기화 후 전체 재실행으로 기존 21건 백필.

**Tech Stack:** 기존 그대로 (Python 3.11+, pydantic v2, pytest; LLM은 `extract.call_claude`의 `claude -p`).

**Spec:** `2026-08-04-crawler-pipeline-design.md` (2026-08-04 개정판, 같은 디렉토리)

## Global Constraints

- 모든 명령은 `/Users/luca/Documents/GitHub/festa/crawler`에서 실행, 테스트는 `.venv/bin/pytest` (현재 37/37)
- 작업 브랜치: `feat_1_인스타그램_총학_계정_핸들_수집` (이미 생성·푸시됨. develop 분기)
- **커밋 형식(팀 컨벤션): `<타입> : <설명> #1`** — 콜론 양옆 공백, 이슈번호 필수. 예: `feat : fetch에 인스타그램 후보 수집 추가 #1`
- 각 태스크 완료 시 즉시 push (`git push`)
- LLM 호출은 `extract.call_claude()`로만; 단위 테스트는 `call_claude`를 mock — 실제 CLI 호출 금지 (Task 4 백필 제외)
- CSV는 `crawl.write_csv` 경유 (utf-8-sig + 수식 새니타이즈 유지)
- `empty_body` 행은 추출이 돌지 않으므로 핸들 null — 미검증 후보를 CSV에 싣지 않는다
- PR은 develop 대상, 본문에 `관련 이슈: #1` — **`close #1` 금지**

---

### Task 1: fetch.py — 인스타그램 후보 수집

**Files:**
- Modify: `fetch.py` (FetchResult, fetch_body, 새 함수 instagram_candidates)
- Modify: `tests/fixtures/tistory_sample.html` (본문 컨테이너 **바깥**에 링크 2개 추가)
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: 기존 `fetch.parse_html`, `fetch.FetchResult`
- Produces (Task 3이 사용):
  - `fetch.instagram_candidates(html: str) -> list[str]` — href/텍스트의 `instagram.com/<핸들>`에서 핸들만 소문자·중복제거·등장순으로 추출. 경로 세그먼트(`p`, `reel`, `reels`, `explore`, `accounts`, `stories`, `share`)는 제외
  - `fetch.FetchResult.instagram_candidates: list[str]` (기본 `[]`) — `ok`·`empty_body` 모두 채움 (`fetch_failed`는 HTML이 없으므로 빈 리스트)

- [ ] **Step 1: fixture에 링크 추가**

`tests/fixtures/tistory_sample.html`의 `</div>`(본문 컨테이너 닫힘)와 `</body>` 사이에 사이드바 블록을 추가한다 — 본문 텍스트 추출 결과가 변하지 않도록 반드시 컨테이너 **바깥**:

```html
  <div class="sidebar">
    <a href="https://www.instagram.com/hyu_festival/">총학생회 인스타그램</a>
    <a href="https://www.instagram.com/p/CUbHfhpswxt/">게시물 링크</a>
  </div>
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_fetch.py`에 추가:

```python
def test_instagram_candidates_extracts_handles_excludes_paths():
    html = read("tistory_sample.html")
    assert fetch.instagram_candidates(html) == ["hyu_festival"]   # /p/... 경로는 제외


def test_instagram_candidates_dedup_and_lowercase():
    html = (
        '<a href="https://instagram.com/HYU_Festival/">1</a>'
        '<a href="https://www.instagram.com/hyu_festival?igsh=x">2</a>'
        '<a href="https://instagram.com/explore/">3</a>'
    )
    assert fetch.instagram_candidates(html) == ["hyu_festival"]


def test_instagram_candidates_empty_when_none():
    assert fetch.instagram_candidates("<html><body>없음</body></html>") == []
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: FAIL — `AttributeError: module 'fetch' has no attribute 'instagram_candidates'`

- [ ] **Step 4: 구현**

`fetch.py` 상단에 `import re` 추가(없다면), 상수·함수 추가:

```python
_IG_HANDLE = re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})")
_IG_NON_HANDLES = {"p", "reel", "reels", "explore", "accounts", "stories", "share"}


def instagram_candidates(html: str) -> list[str]:
    """HTML에서 인스타그램 계정 핸들 후보를 등장순·중복제거로 추출한다."""
    found: list[str] = []
    for match in _IG_HANDLE.finditer(html):
        handle = match.group(1).lower().rstrip(".")
        if handle not in _IG_NON_HANDLES and handle not in found:
            found.append(handle)
    return found
```

`FetchResult`에 필드 추가 (`from dataclasses import dataclass, field`로 임포트 확장):

```python
@dataclass
class FetchResult:
    status: str                     # ok | fetch_failed | empty_body
    body: str | None = None
    poster_image_url: str | None = None
    error: str | None = None
    instagram_candidates: list[str] = field(default_factory=list)
```

`fetch_body`에서 `body, og = parse_html(html)` 직후에 `candidates = instagram_candidates(html)`를 계산하고, `empty_body`·`ok` 두 반환 모두에 `instagram_candidates=candidates`를 넘긴다.

- [ ] **Step 5: 통과 확인 + 전체 스위트**

Run: `.venv/bin/pytest tests/test_fetch.py -v` → 새 테스트 3개 포함 전부 PASS
Run: `.venv/bin/pytest` → 40 passed (기존 37 + 3)

- [ ] **Step 6: 이슈 라벨 갱신 + 커밋·푸시**

```bash
gh issue edit 1 --repo greedy-team/festa-crawler --add-label 작업중 --remove-label 작업전
git add fetch.py tests/fixtures/tistory_sample.html tests/test_fetch.py
git commit -m "feat : fetch에 인스타그램 후보 수집 추가 #1"
git push
```

---

### Task 2: schema.py + extract.py — 핸들 판별

**Files:**
- Modify: `schema.py` (ExtractionResult에 필드 1개)
- Modify: `extract.py` (프롬프트, extract 시그니처)
- Test: `tests/test_extract.py`, `tests/test_schema.py`

**Interfaces:**
- Consumes: 없음 (Task 1과 독립 — 후보는 순수 인자로 받음)
- Produces (Task 3이 사용):
  - `schema.ExtractionResult.instagram_handle: str | None = None` (`ticket_info` 다음)
  - `extract.extract(body: str, university: str, year: int, instagram_candidates: list[str] | None = None) -> ExtractionResult`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_schema.py`에 추가:

```python
def test_extraction_result_instagram_handle_optional():
    # 구 캐시(필드 없음)와 신규 응답 모두 파싱돼야 한다
    old = ExtractionResult.model_validate(
        {"found": True, "university_name": "연세대학교", "year": 2026}
    )
    assert old.instagram_handle is None
    new = ExtractionResult.model_validate(
        {"found": True, "university_name": "한양대학교", "year": 2026,
         "instagram_handle": "hyu_festival"}
    )
    assert new.instagram_handle == "hyu_festival"
```

`tests/test_extract.py`에 추가:

```python
def test_extract_passes_candidates_into_prompt(monkeypatch):
    captured = {}

    def fake(prompt, timeout=120):
        captured["prompt"] = prompt
        return VALID_JSON

    monkeypatch.setattr(extract, "call_claude", fake)
    extract.extract("본문", "한양대학교", 2026, instagram_candidates=["hyu_festival", "blogowner"])
    assert "hyu_festival" in captured["prompt"]
    assert "blogowner" in captured["prompt"]


def test_extract_without_candidates_prompts_none(monkeypatch):
    captured = {}

    def fake(prompt, timeout=120):
        captured["prompt"] = prompt
        return VALID_JSON

    monkeypatch.setattr(extract, "call_claude", fake)
    extract.extract("본문", "연세대학교", 2026)
    assert "후보 없음" in captured["prompt"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_schema.py tests/test_extract.py -v`
Expected: 새 테스트만 FAIL (`instagram_handle` 필드 없음 / `TypeError: unexpected keyword argument`)

- [ ] **Step 3: 구현**

`schema.py` — `ExtractionResult`의 `ticket_info` 아래에:

```python
    instagram_handle: str | None = None
```

`extract.py` — `PROMPT_TEMPLATE` 전체를 아래로 교체 (규칙 1줄 + 스키마 1필드 + 후보 블록 추가):

```python
PROMPT_TEMPLATE = """다음은 '{university}'의 {year}년 축제 관련 블로그 글 본문입니다.
본문에서 축제 정보를 추출해 아래 스키마의 JSON으로만 응답하세요.

규칙:
- 본문에 명시되지 않은 값은 반드시 null로 둡니다. 절대 추측하거나 지어내지 마세요.
- found: 이 글이 실제로 '{university}'의 {year}년 축제 라인업/정보 글이면 true, 아니면 false.
- artist_raw: 본문에 적힌 표기 그대로 씁니다 (정규화 금지).
- is_secret: '시크릿', '당일 공개' 등으로 표기된 미공개 출연자면 true.
- date는 YYYY-MM-DD로 정규화 가능할 때만 채웁니다.
- instagram_handle: 아래 후보와 본문을 종합해 '{university}'의 축제·총학생회 공식 계정이
  확실한 것만 채웁니다. 블로그 운영자·언론사·무관 계정이면 null. 후보에 없는 계정을 지어내지 마세요.
- 설명이나 마크다운 없이 JSON 객체 하나만 출력하세요.

스키마:
{{"found": bool, "university_name": str, "year": int,
  "festival_name": str|null, "start_date": str|null, "end_date": str|null,
  "venue_name": str|null, "outsider_admission": str|null, "ticket_info": str|null,
  "instagram_handle": str|null,
  "lineup": [{{"artist_raw": str, "day_label": str|null, "date": str|null,
              "time": str|null, "is_secret": bool}}]}}

본문 링크에서 발견된 인스타그램 계정 후보:
{candidates}

본문:
{body}"""
```

`extract()` 시그니처와 포맷 호출 변경 (재시도 프롬프트 재구성 포함, 두 군데 모두):

```python
def extract(
    body: str,
    university: str,
    year: int,
    instagram_candidates: list[str] | None = None,
) -> ExtractionResult:
    candidates = (
        "\n".join(f"- {c}" for c in instagram_candidates)
        if instagram_candidates
        else "(후보 없음)"
    )
    prompt = PROMPT_TEMPLATE.format(
        university=university, year=year, body=body, candidates=candidates
    )
    last_error = None
    for _ in range(2):
        raw = call_claude(prompt)
        try:
            return ExtractionResult.model_validate_json(_extract_json(raw))
        except (ValueError, ValidationError) as e:
            last_error = e
            prompt = (
                PROMPT_TEMPLATE.format(
                    university=university, year=year, body=body, candidates=candidates
                )
                + f"\n\n[재시도] 이전 응답이 유효하지 않았습니다: {e}\n"
                  "스키마에 정확히 맞는 JSON 객체 하나만 다시 출력하세요."
            )
    raise ExtractError(f"추출 검증 2회 실패: {last_error}")
```

- [ ] **Step 4: 통과 확인 + 전체 스위트**

Run: `.venv/bin/pytest` → 43 passed (40 + 3). 기존 extract 테스트는 시그니처가 기본값 인자라 그대로 통과해야 한다.

- [ ] **Step 5: 커밋·푸시**

```bash
git add schema.py extract.py tests/test_schema.py tests/test_extract.py
git commit -m "feat : 추출 스키마·프롬프트에 인스타그램 핸들 판별 추가 #1"
git push
```

---

### Task 3: crawl.py — 파이프라인 연결 + CSV 컬럼

**Files:**
- Modify: `crawl.py` (process_row의 extract 호출, FESTIVAL_FIELDS, build_festival_row)
- Test: `tests/test_crawl.py`

**Interfaces:**
- Consumes: `fetch.FetchResult.instagram_candidates` (Task 1), `extract.extract(..., instagram_candidates=)` (Task 2), `schema.ExtractionResult.instagram_handle`
- Produces: `festivals.csv`에 `instagram_handle` 컬럼 (`ticket_info`와 `poster_image_url` 사이)

**주의:** `tests/test_crawl.py`의 기존 monkeypatch 람다들은 `lambda body, u, y: ...` 시그니처다. `process_row`가 4번째 인자를 넘기게 되면 전부 깨지므로 **`lambda body, u, y, cands=None: ...`로 일괄 수정**해야 한다 (파일 내 `monkeypatch.setattr(crawl, "extract", ...)` 전부).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_crawl.py` — `_extraction()` helper의 dict에 `"instagram_handle": "hyu_festival"`을 추가하고, 다음 테스트를 추가:

```python
def test_process_row_passes_candidates_to_extract(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(
        status="ok", body="본문" * 100, instagram_candidates=["hyu_festival"]))

    def fake_extract(body, u, y, cands=None):
        captured["cands"] = cands
        return _extraction()

    monkeypatch.setattr(crawl, "extract", fake_extract)
    process_row(_row(), tmp_path)
    assert captured["cands"] == ["hyu_festival"]


def test_build_festival_row_includes_instagram_handle():
    record = {"university": "한양대학교", "campus": "서울캠퍼스",
              "region": "서울 성동구", "year": 2026,
              "url": "https://example.com/post", "flag": "ok",
              "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    frow = build_festival_row(record)
    assert frow["instagram_handle"] == "hyu_festival"
    assert list(frow.keys()) == crawl.FESTIVAL_FIELDS   # 컬럼 순서 일치
```

- [ ] **Step 2: 기존 람다 시그니처 일괄 수정**

파일 내 모든 `monkeypatch.setattr(crawl, "extract", lambda body, u, y: ...)`를
`lambda body, u, y, cands=None: ...`로 바꾼다.

- [ ] **Step 3: 실패 확인**

Run: `.venv/bin/pytest tests/test_crawl.py -v`
Expected: 새 테스트 2개 FAIL (`captured["cands"] is None` / `KeyError: 'instagram_handle'`)

- [ ] **Step 4: 구현**

`crawl.py`:

- `FESTIVAL_FIELDS`의 `"ticket_info"` 다음에 `"instagram_handle"` 삽입
- `process_row`의 추출 호출을
  `result = extract(fr.body, row.university, row.year, fr.instagram_candidates)`로 변경
- `build_festival_row`에 `"instagram_handle": ext.get("instagram_handle") or "",` 추가
  (`ticket_info` 항목 다음 줄)

- [ ] **Step 5: 통과 확인 + 전체 스위트**

Run: `.venv/bin/pytest` → 45 passed (43 + 2)

- [ ] **Step 6: 커밋·푸시**

```bash
git add crawl.py tests/test_crawl.py
git commit -m "feat : 파이프라인에 인스타그램 핸들 연결 및 CSV 컬럼 추가 #1"
git push
```

---

### Task 4: 백필 재실행 + 검증 + PR

자동 테스트가 아니라 **실제 실행 + 사람 확인 + PR 생성**이다. 실제 HTTP와 `claude` CLI 호출이 발생한다 (구독 로그인 필요). 코드 수정 금지 — 발견 사항은 보고만.

- [ ] **Step 1: 캐시 초기화 후 전체 재실행**

```bash
rm -rf output/raw
.venv/bin/python crawl.py        # ~20-30분 (21 URL × 3초 간격 + LLM 추출)
.venv/bin/python enrich.py       # 1콜, 수 분
```

세션 한도에 걸리면 리셋 후 같은 명령 재실행 (캐시로 이어짐).

- [ ] **Step 2: 검증 집계**

`output/festivals.csv`에서 확인해 보고:
- flag 집계가 이전 실행(ok 20 / empty_body 1 / no_source 8)과 동일한가
- `instagram_handle` 채워진 행 수 (기대: HTML에 후보 있는 15곳 중 상당수)
- **한양대 = `hyu_festival`** (href에만 있는 케이스 — 하이브리드의 존재 이유)
- **연세대 = 빈칸** (wikifoodie 오탐이 걸러졌는가 — LLM 판별의 존재 이유)
- 라인업·축제 필드가 이전 실행과 크게 다르지 않은가 (스팟 2건)

- [ ] **Step 3: PR 생성**

```bash
git switch feat_1_인스타그램_총학_계정_핸들_수집   # 확인용
gh pr create --repo greedy-team/festa-crawler --base develop \
  --title "feat : 인스타그램 총학 계정 핸들 수집" \
  --body "$(cat <<'EOF'
## 변경 사항
- fetch.py: HTML에서 인스타그램 계정 후보 수집 (FetchResult.instagram_candidates)
- extract.py/schema.py: 후보+본문 문맥으로 총학 계정 판별 (instagram_handle, 확신 없으면 null)
- crawl.py: festivals.csv에 instagram_handle 컬럼 추가
- 스펙 개정: 하이브리드 채택 근거, oEmbed 확인 결과 기록

## 테스트
- 단위 45개 통과 (신규 8: 후보 추출 3, 스키마/프롬프트 3, 파이프라인 2)
- 캐시 초기화 후 21 URL 전체 재실행 백필 — flag 집계 회귀 없음, 한양대 hyu_festival 검출, 연세대 오탐 차단 확인

관련 이슈: #1
EOF
)"
gh issue edit 1 --repo greedy-team/festa-crawler --add-label 담당자확인 --remove-label 작업중
```

(PR 본문 수치는 Step 2 실측값으로 갱신해서 넣는다. `close #1`은 쓰지 않는다 — develop 머지 시 봇이 이슈를 닫는다.)

---

## Self-Review 결과

- **스펙 커버리지**: 개정 스펙의 후보 수집(§5-4)→Task 1, 판별 규칙·스키마(§5-6, §6)→Task 2, CSV 컬럼(§6)→Task 3, 백필(§2)→Task 4. empty_body 핸들 null 규칙은 구조상 자동 충족(추출 미실행) — Task 3 주의사항에 반영. 누락 없음.
- **플레이스홀더**: 없음 — 코드·테스트·명령 전부 실제 내용.
- **타입 일관성**: `instagram_candidates`(fetch→crawl→extract 인자명), `instagram_handle`(schema→CSV 컬럼) 전 태스크 일치 확인. 기존 테스트 람다 시그니처 충돌은 Task 3 주의사항으로 명시.
