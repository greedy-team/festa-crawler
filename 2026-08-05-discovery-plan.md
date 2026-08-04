# 검색 기반 후보 URL 자동 탐색 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수동 URL이 없거나 실패한 대학만 `claude --tools "WebSearch"`로 후보 URL을 찾아 기존 추출·역방향 검증 경로에 태운다 (이슈 #4).

**Architecture:** `discover.py`를 신설해 후보 URL만 모으고(판단 없음), `crawl.process_row`가 수동 URL을 먼저 시도한 뒤 실패하면 후보를 순서대로 태운다. `verify()`가 통과시킨 첫 후보를 채택하고, 지어낸 URL은 `fetch_failed`·엉뚱한 글은 `mismatch`로 기존 장치가 자동 탈락시킨다.

**Tech Stack:** 기존 그대로 (Python 3.13, pydantic v2, pytest; LLM은 `extract.call_claude`의 `claude -p`).

**Spec:** `2026-08-04-crawler-pipeline-design.md` (2026-08-05 개정판, 같은 디렉토리)

## Global Constraints

- 모든 명령은 `/Users/luca/Documents/GitHub/festa/crawler`에서 실행, 테스트는 `.venv/bin/pytest` (현재 **48개 통과**)
- 작업 브랜치: `feat_4_검색_기반_후보_url_자동_탐색` (이미 생성·푸시됨, develop 분기)
- **커밋 형식(팀 컨벤션): `<타입> : <설명> #4`** — 콜론 양옆 공백, 이슈번호 필수. 각 태스크 후 `git push`
- LLM 호출은 `extract.call_claude()`로만. 단위 테스트는 `call_claude`를 monkeypatch — 실제 CLI 호출 금지 (Task 4 실전 검증 제외)
- 추출·정규화 호출은 `tools=""`(도구 전면 차단) 유지. **탐색 호출만 `tools="WebSearch"`**
- 탐색 프롬프트는 최상위 **객체** `{"candidates": [...]}`를 요구한다. 배열 `[...]`은 기존 `_extract_json`(`{`~`}` 구간만 절단)이 파싱하지 못한다
- CSV는 `crawl.write_csv` 경유 (utf-8-sig + 수식 새니타이즈 유지)
- `flag` 허용값: `ok | fetch_failed | empty_body | extract_failed | mismatch | no_source | no_candidate`
- `discovery` 허용값: `manual | search | ""`(빈 문자열)
- PR은 develop 대상, 본문에 `관련 이슈: #4` — **`close #4` 금지**

**알려진 선행 이슈 (#2, 이 브랜치에서 고치지 않음):** 세션 한도로 `claude` 호출이 죽으면 그 행이 `extract_failed`로 캐시에 굳는다. 탐색은 호출량을 늘려 이 문제를 더 자주 만난다. Task 4에서 중단되면 `output/raw/`의 해당 파일을 지우고 재실행한다.

---

### Task 1: `call_claude` 도구 파라미터 + 탐색 스키마

**Files:**
- Modify: `extract.py` (`call_claude` 시그니처와 argv)
- Modify: `schema.py` (모델 2개 추가)
- Test: `tests/test_extract.py`, `tests/test_schema.py`

**Interfaces:**
- Consumes: 없음
- Produces (Task 2가 사용):
  - `extract.call_claude(prompt: str, timeout: int = CLAUDE_TIMEOUT_SECONDS, tools: str = "") -> str` — `--tools <tools>`로 전달. 기본값 `""`라 기존 호출부는 동작 불변
  - `schema.Candidate(BaseModel)` — `url: str`, `title: str | None = None`
  - `schema.DiscoverResult(BaseModel)` — `candidates: list[Candidate] = []`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_schema.py`에 추가:

```python
def test_discover_result_parse():
    from schema import DiscoverResult

    r = DiscoverResult.model_validate(
        {"candidates": [
            {"url": "https://example.com/a", "title": "한양대 축제"},
            {"url": "https://example.com/b"},
        ]}
    )
    assert r.candidates[0].url == "https://example.com/a"
    assert r.candidates[1].title is None


def test_discover_result_empty_default():
    from schema import DiscoverResult

    assert DiscoverResult.model_validate({}).candidates == []
```

`tests/test_extract.py`에 추가:

```python
def test_call_claude_passes_tools_flag(monkeypatch):
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = '{"result": "OK"}'
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return FakeProc()

    monkeypatch.setattr(extract.subprocess, "run", fake_run)

    extract.call_claude("프롬프트")
    assert captured["argv"][-2:] == ["--tools", ""]      # 기본값은 도구 차단

    extract.call_claude("프롬프트", tools="WebSearch")
    assert captured["argv"][-2:] == ["--tools", "WebSearch"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_schema.py tests/test_extract.py -v`
Expected: 새 테스트 3개 FAIL — `ImportError: cannot import name 'DiscoverResult'` / `TypeError: call_claude() got an unexpected keyword argument 'tools'`

- [ ] **Step 3: 구현**

`schema.py` 맨 아래에 추가:

```python
class Candidate(BaseModel):
    url: str
    title: str | None = None


class DiscoverResult(BaseModel):
    candidates: list[Candidate] = Field(default_factory=list)
```

`extract.py`의 `call_claude` 시그니처와 argv만 바꾼다 (나머지 본문은 그대로):

```python
def call_claude(
    prompt: str, timeout: int = CLAUDE_TIMEOUT_SECONDS, tools: str = ""
) -> str:
    """claude -p 헤드리스 호출. envelope JSON의 result 필드(모델 응답 텍스트)를 반환.

    tools: --tools에 그대로 전달. 기본 ""는 모든 도구 차단(추출·정규화용).
           탐색만 "WebSearch"로 켠다.
    """
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json", "--tools", tools],
            capture_output=True, text=True, timeout=timeout,
        )
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest`
Expected: 51 passed (48 + 3). 실제 숫자를 확인해 보고할 것.

- [ ] **Step 5: 커밋·푸시**

```bash
git add extract.py schema.py tests/test_extract.py tests/test_schema.py
git commit -m "feat : call_claude 도구 파라미터와 탐색 스키마 추가 #4"
git push
```

---

### Task 2: `discover.py` — 후보 URL 탐색

**Files:**
- Create: `discover.py`
- Test: `tests/test_discover.py`

**Interfaces:**
- Consumes: `extract.call_claude`, `extract.ExtractError`, `schema.DiscoverResult`, `extract._extract_json`
- Produces (Task 3이 사용):
  - `discover.MAX_CANDIDATES = 3`
  - `discover.discover(university: str, year: int) -> list[str]` — LLM 1콜, 차단 도메인 제외, URL 문자열 목록 (등장순). 실패 시 `ExtractError`
  - `discover.discover_cached(university: str, year: int, out_dir: Path) -> list[str]` — `output/discovered/<대학>.json` 캐시 래퍼. 캐시는 `year` 일치 시에만 유효. LLM 실패 시 빈 목록 반환(캐시하지 않음)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_discover.py` (신규):

```python
import json

import pytest

import discover
from extract import ExtractError

VALID = """{"candidates": [
  {"url": "https://www.newshyu.com/news/articleView.html?idxno=1", "title": "라치오스 라인업"},
  {"url": "https://namu.wiki/w/%ED%95%9C%EC%96%91%EB%8C%80", "title": "나무위키"},
  {"url": "https://blog.example.com/festival", "title": "축제 정리"}
]}"""


def test_discover_returns_urls_and_drops_blocked(monkeypatch):
    monkeypatch.setattr(discover, "call_claude", lambda p, timeout=120, tools="": VALID)
    urls = discover.discover("한양대학교", 2026)
    assert urls == [
        "https://www.newshyu.com/news/articleView.html?idxno=1",
        "https://blog.example.com/festival",
    ]   # 나무위키는 차단 도메인


def test_discover_uses_websearch_tool_and_long_timeout(monkeypatch):
    captured = {}

    def fake(prompt, timeout=120, tools=""):
        captured["tools"] = tools
        captured["timeout"] = timeout
        captured["prompt"] = prompt
        return VALID

    monkeypatch.setattr(discover, "call_claude", fake)
    discover.discover("한양대학교", 2026)
    assert captured["tools"] == "WebSearch"
    assert captured["timeout"] == discover.DISCOVER_TIMEOUT_SECONDS
    assert "한양대학교" in captured["prompt"] and "2026" in captured["prompt"]


def test_discover_raises_on_unparsable(monkeypatch):
    monkeypatch.setattr(discover, "call_claude", lambda p, timeout=120, tools="": "JSON 아님")
    with pytest.raises(ExtractError):
        discover.discover("한양대학교", 2026)


def test_discover_cached_writes_and_reuses(tmp_path, monkeypatch):
    calls = []

    def fake(prompt, timeout=120, tools=""):
        calls.append(prompt)
        return VALID

    monkeypatch.setattr(discover, "call_claude", fake)

    first = discover.discover_cached("한양대학교", 2026, tmp_path)
    assert len(calls) == 1
    assert (tmp_path / "discovered" / "한양대학교.json").exists()

    second = discover.discover_cached("한양대학교", 2026, tmp_path)
    assert len(calls) == 1          # 캐시 적중 — 재호출 없음
    assert second == first


def test_discover_cached_refetches_on_year_change(tmp_path, monkeypatch):
    cache_dir = tmp_path / "discovered"
    cache_dir.mkdir()
    (cache_dir / "한양대학교.json").write_text(
        json.dumps({"university": "한양대학교", "year": 2025, "candidates": []}), "utf-8"
    )
    calls = []

    def fake(prompt, timeout=120, tools=""):
        calls.append(prompt)
        return VALID

    monkeypatch.setattr(discover, "call_claude", fake)
    urls = discover.discover_cached("한양대학교", 2026, tmp_path)
    assert len(calls) == 1          # 연도가 다르면 캐시 무시
    assert urls


def test_discover_cached_returns_empty_on_failure(tmp_path, monkeypatch):
    def boom(prompt, timeout=120, tools=""):
        raise ExtractError("세션 한도")

    monkeypatch.setattr(discover, "call_claude", boom)
    assert discover.discover_cached("한양대학교", 2026, tmp_path) == []
    assert not (tmp_path / "discovered" / "한양대학교.json").exists()   # 실패는 캐시 안 함
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_discover.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'discover'`

- [ ] **Step 3: `discover.py` 구현**

```python
"""후보 URL 탐색: claude의 WebSearch 도구로 검색해 URL 후보만 모은다.

fetch.py와 같은 원칙 — 후보를 모으기만 하고 "이 글이 맞는 글인가"는 판단하지 않는다.
그 판정은 crawl이 extract → verify로 수행한다.
"""
import json
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from extract import ExtractError, _extract_json, call_claude
from schema import DiscoverResult

DISCOVER_TIMEOUT_SECONDS = 300   # 실측 63초 + 검색 왕복 여유
MAX_CANDIDATES = 3

# robots·라이선스상 쓸 수 없는 곳. 검색 결과에 섞여 나오므로 여기서 뺀다.
BLOCKED_DOMAINS = frozenset({
    "namu.wiki",            # CC BY-NC-SA(비영리) + Cloudflare 봇 방어
    "www.google.com", "google.com", "search.naver.com",   # 검색 결과 페이지 자체
})

PROMPT_TEMPLATE = """'{university}'의 {year}년 대학 축제 라인업을 다룬 웹 문서를 검색해서,
실제로 접근 가능한 URL만 골라 JSON으로 알려주세요.

규칙:
- 웹 검색 결과에 실제로 나온 URL만 씁니다. 절대 URL을 지어내지 마세요.
- '{university}'의 {year}년 축제를 다룬 문서만 고릅니다. 다른 대학이나 다른 연도는 제외합니다.
- 라인업·출연 가수·축제 일정을 다루는 문서를 우선합니다.
- 관련성이 높은 순서로 최대 8개까지.
- 설명이나 마크다운 없이 JSON 객체 하나만 출력하세요.

형식:
{{"candidates": [{{"url": "https://...", "title": "문서 제목"}}]}}"""


def _is_blocked(url: str) -> bool:
    return urlparse(url).netloc.lower() in BLOCKED_DOMAINS


def discover(university: str, year: int) -> list[str]:
    """검색으로 후보 URL을 찾는다. 차단 도메인은 제외하고 등장순으로 반환."""
    prompt = PROMPT_TEMPLATE.format(university=university, year=year)
    raw = call_claude(prompt, timeout=DISCOVER_TIMEOUT_SECONDS, tools="WebSearch")
    try:
        result = DiscoverResult.model_validate_json(_extract_json(raw))
    except (ValueError, ValidationError) as e:
        raise ExtractError(f"탐색 응답 파싱 실패: {e}")
    return [c.url for c in result.candidates if not _is_blocked(c.url)]


def discover_cached(university: str, year: int, out_dir: Path) -> list[str]:
    """탐색 결과 캐시 래퍼. 탐색 1건이 60초 이상 걸려 캐시가 필수다."""
    cache_dir = out_dir / "discovered"
    cache_path = cache_dir / f"{university}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("year") == year:
            return list(cached.get("candidates", []))

    try:
        urls = discover(university, year)
    except ExtractError as e:
        print(f"  탐색 실패: {e}", flush=True)
        return []

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {"university": university, "year": year, "candidates": urls},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return urls
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest`
Expected: 57 passed (51 + 6). 실제 숫자를 확인해 보고할 것.

- [ ] **Step 5: 커밋·푸시**

```bash
git add discover.py tests/test_discover.py
git commit -m "feat : 검색 기반 후보 URL 탐색 모듈 추가 #4"
git push
```

---

### Task 3: `crawl.py` — 탐색 분기 + `discovery` 컬럼

**Files:**
- Modify: `crawl.py` (`FESTIVAL_FIELDS`, `process_row` 분해, `build_festival_row`)
- Test: `tests/test_crawl.py`

**Interfaces:**
- Consumes: `discover.discover_cached`, `discover.MAX_CANDIDATES`, `fetch.fetch_body`, `extract.extract`, `extract.verify`
- Produces:
  - `crawl._attempt_url(url: str, row: UniversityRow) -> dict` — URL 1건 시도. `{"flag":…, "poster_image_url":…, "extraction":…}` 반환
  - raw 레코드에 `seed_url`(캐시 키 = 시드의 URL)과 `discovery`가 추가됨:
    `{"university","campus","region","year","seed_url","url","discovery","flag","poster_image_url","extraction"}`
  - `festivals.csv`에 `discovery` 컬럼 (`source_url`과 `flag` 사이)

**캐시 키가 바뀝니다.** 지금은 `cached["url"] == row.url`로 판정하는데, 탐색이 붙으면 `url`이 시드와 달라질 수 있어 매번 캐시가 빗나갑니다. 그래서 시드 URL을 `seed_url`로 따로 저장하고 그것으로 판정합니다. 기존 캐시 파일에는 `seed_url`이 없으므로 첫 실행에서 전부 재처리됩니다 — Task 4가 어차피 전체 재실행이라 의도된 동작입니다.

**flag 결정 규칙 (모호함 없이):**
- 수동 URL 성공 → `flag=ok`, `discovery=manual`
- 수동 URL 실패 또는 없음 → 탐색 진입
  - 후보 중 하나가 `ok` → `flag=ok`, `discovery=search`, `url`은 그 후보
  - 전부 실패 + 수동 URL이 **있었음** → 수동 시도의 실패 flag 유지, `discovery=""`
  - 전부 실패 + 수동 URL이 **없었음** → `flag=no_candidate`, `discovery=""`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_crawl.py`에 추가 (기존 `_row`/`_extraction` 헬퍼 재사용):

```python
def test_process_row_manual_success_skips_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())

    def boom(university, year, out_dir):
        raise AssertionError("수동 URL이 성공하면 탐색하면 안 됨")

    monkeypatch.setattr(crawl, "discover_cached", boom)
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "ok"
    assert record["discovery"] == "manual"


def test_process_row_discovers_when_no_url(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_cached",
                        lambda u, y, o: ["https://found.example.com/post"])
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "ok"
    assert record["discovery"] == "search"
    assert record["url"] == "https://found.example.com/post"


def test_process_row_falls_through_to_second_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_cached",
                        lambda u, y, o: ["https://bad.example.com/x", "https://good.example.com/y"])
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))

    def fake_extract(body, u, y, cands=None):
        return _extraction()

    monkeypatch.setattr(crawl, "extract", fake_extract)
    # 첫 후보는 verify 실패(다른 대학), 두 번째는 통과
    seen = []

    def fake_verify(result, university, year):
        seen.append(university)
        return len(seen) > 1

    monkeypatch.setattr(crawl, "verify", fake_verify)
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "ok"
    assert record["url"] == "https://good.example.com/y"


def test_process_row_no_candidate_when_discovery_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "no_candidate"
    assert record["discovery"] == ""


def test_process_row_keeps_manual_failure_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "fetch_body",
                        lambda url: FetchResult(status="empty_body", poster_image_url=None))
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "empty_body"     # no_candidate로 덮어쓰지 않는다
    assert record["discovery"] == ""


def test_build_festival_row_includes_discovery():
    record = {"university": "한양대학교", "campus": "서울캠퍼스", "region": "서울 성동구",
              "year": 2026, "seed_url": None, "url": "https://found.example.com/p",
              "discovery": "search", "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    frow = build_festival_row(record)
    assert frow["discovery"] == "search"
    assert frow["source_url"] == "https://found.example.com/p"
    assert list(frow.keys()) == crawl.FESTIVAL_FIELDS


def test_process_row_cache_keyed_on_seed_url(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    cached = {"university": "연세대학교", "campus": "신촌캠퍼스", "region": "서울 서대문구",
              "year": 2026, "seed_url": None, "url": "https://found.example.com/p",
              "discovery": "search", "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    (raw_dir / "연세대학교.json").write_text(json.dumps(cached), "utf-8")

    def boom(university, year, out_dir):
        raise AssertionError("캐시 적중이면 탐색하면 안 됨")

    monkeypatch.setattr(crawl, "discover_cached", boom)
    record = process_row(_row(url=None), tmp_path)   # 시드 url=None, 캐시의 seed_url도 None
    assert record["flag"] == "ok"
    assert record["url"] == "https://found.example.com/p"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_crawl.py -v`
Expected: 새 테스트 FAIL — `AttributeError: module 'crawl' has no attribute 'discover_cached'` 등

- [ ] **Step 3: `crawl.py` 구현**

임포트에 추가:

```python
from discover import MAX_CANDIDATES, discover_cached
```

`FESTIVAL_FIELDS`의 `"source_url"` 다음에 `"discovery"` 삽입:

```python
FESTIVAL_FIELDS = [
    "university", "campus", "region", "year", "festival_name",
    "start_date", "end_date", "venue_name", "outsider_admission",
    "ticket_info", "instagram_handle", "poster_image_url", "source_url",
    "discovery", "flag",
]
```

`process_row`를 아래로 교체하고 `_attempt_url`을 그 위에 추가한다:

```python
def _attempt_url(url: str, row: UniversityRow) -> dict:
    """URL 1건을 수집·추출·검증한다. flag/poster_image_url/extraction만 담아 돌려준다."""
    fr = fetch_body(url)
    attempt = {"flag": fr.status, "poster_image_url": fr.poster_image_url, "extraction": None}
    if fr.status != "ok":
        return attempt
    try:
        result = extract(fr.body, row.university, row.year, fr.instagram_candidates)
    except ExtractError:
        attempt["flag"] = "extract_failed"
        return attempt
    attempt["extraction"] = result.model_dump()
    attempt["flag"] = "ok" if verify(result, row.university, row.year) else "mismatch"
    return attempt


def process_row(row: UniversityRow, out_dir: Path) -> dict:
    """대학 1곳 처리. 수동 URL 우선, 실패하면 검색 후보로 폴백."""
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache_path = raw_dir / f"{row.university}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("seed_url") == row.url and cached.get("year") == row.year:
            # 시드 전용 필드는 현재 행 기준으로 갱신 (추출 결과에는 영향 없음)
            cached["campus"] = row.campus
            cached["region"] = row.region
            return cached
        # 시드 URL 또는 연도가 바뀌었으면 캐시 무시하고 다시 처리 (아래에서 덮어씀)

    record = {
        "university": row.university, "campus": row.campus,
        "region": row.region, "year": row.year,
        "seed_url": row.url, "url": row.url, "discovery": "",
        "flag": "no_source", "poster_image_url": None, "extraction": None,
    }

    if row.url is not None:
        record.update(_attempt_url(row.url, row))
        record["discovery"] = "manual" if record["flag"] == "ok" else ""

    if record["flag"] != "ok":
        for candidate in discover_cached(row.university, row.year, out_dir)[:MAX_CANDIDATES]:
            attempt = _attempt_url(candidate, row)
            if attempt["flag"] == "ok":
                record.update(attempt)
                record["url"] = candidate
                record["discovery"] = "search"
                break
        else:
            if row.url is None:
                record["flag"] = "no_candidate"

    if record["flag"] not in ("fetch_failed", "extract_failed"):
        cache_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record
```

`build_festival_row`의 `"source_url"` 항목 다음에 한 줄 추가:

```python
        "discovery": record.get("discovery", ""),
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest`
Expected: 64 passed (57 + 7). 실제 숫자를 확인해 보고할 것. 기존 crawl 테스트 중 `record["url"]`/캐시를 다루는 것들이 `seed_url` 도입으로 깨질 수 있다 — 깨지면 **테스트 기대값이 아니라 캐시 규칙에 맞게** 고친다.

- [ ] **Step 5: 커밋·푸시**

```bash
git add crawl.py tests/test_crawl.py
git commit -m "feat : 수동 URL 실패 시 검색 후보로 폴백 #4"
git push
```

---

### Task 4: 실전 검증 — 빈 곳 8개 탐색

자동 테스트가 아니라 **실제 실행 + 사람 확인**이다. 실제 HTTP와 `claude` CLI 호출(검색 포함)이 발생한다. **`.py` 파일을 수정하지 않는다** — 발견 사항은 보고만.

- [ ] **Step 1: 캐시 초기화 후 전체 실행**

```bash
rm -rf output/raw output/discovered
.venv/bin/python crawl.py
```

수동 URL 21곳 + 탐색 대상 8곳. 탐색 1건이 60초 이상이라 30~50분 예상. Bash timeout 600000ms로 실행하고, 타임아웃되면 같은 명령을 재실행한다(캐시로 이어짐). 완료 줄이 나올 때까지 반복.

세션 한도에 걸리면: 몇 건까지 처리됐는지 기록하고 STATUS=BLOCKED로 보고한다. **`output/raw/`에서 `extract_failed` 행을 지우고 재개**해야 한다 (이슈 #2 미수정 상태).

- [ ] **Step 2: 정규화 실행**

```bash
.venv/bin/python enrich.py
```

- [ ] **Step 3: 검증 집계 (보고용)**

`output/festivals.csv`에서 확인한다:

- flag 집계 — baseline(`ok 20 / empty_body 1 / no_source 8`) 대비. **`no_source`가 줄고 `ok`가 늘었는지**가 이 작업의 성패다
- `discovery` 값별 건수 (`manual` / `search` / 빈칸)
- **탐색으로 채워진 대학 목록과 그 `source_url`** — 도메인이 어디인지 (학보사·언론·블로그 등)
- 탐색으로 채워진 것 중 2곳을 골라 원본을 열어 **정말 그 대학 그 연도 축제 글인지** 확인
- 기존 수동 URL 21곳의 결과가 이전 실행과 같은지 (회귀 확인)
- `output/discovered/`의 후보 목록을 훑어 차단 도메인이 새어 들어오지 않았는지

- [ ] **Step 4: 보고**

리포트에 위 집계와 함께 다음을 적는다: 총 소요 시간, 재실행 횟수, 세션 한도 중단 여부, 탐색 적중률(탐색 시도 8곳 중 몇 곳 성공), 발견한 문제. **PR은 만들지 않는다** — 컨트롤러가 최종 리뷰 후 처리한다.

---

## Self-Review 결과

- **스펙 커버리지**: §3 탐색 수단·적용 범위·후보 채택 → Task 1·2·3, §4 `discover.py`·`discovered/` 캐시 → Task 2, §5.0 탐색 분기 5단계 → Task 3, §6 `discovery` 컬럼·`no_candidate` → Task 3, §7 `tools` 인자·객체 응답 요구 → Task 1·2, §8 검색 스크래핑 금지 → Task 2의 `BLOCKED_DOMAINS`, §9 탐색 실패 격리 → Task 2의 `discover_cached` 예외 처리, §10 탐색 단위·실전 테스트 → Task 2·4. 누락 없음.
- **플레이스홀더**: 없음 — 코드·테스트·명령 전부 실제 내용.
- **타입 일관성**: `discover_cached(university, year, out_dir)` 인자 순서가 Task 2 정의와 Task 3 테스트·구현에서 일치. `_attempt_url`이 반환하는 키 3종(`flag`/`poster_image_url`/`extraction`)이 `record` 키와 일치. `DISCOVER_TIMEOUT_SECONDS`·`MAX_CANDIDATES` 이름이 Task 2 정의와 Task 3 임포트에서 일치.
- **알려진 상호작용**: Task 3의 `seed_url` 도입으로 기존 캐시가 전부 무효화된다. Task 4가 어차피 `rm -rf output/raw`로 시작하므로 실사용 영향은 없다.
