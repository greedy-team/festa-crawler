# 산출물을 백엔드 번들 업로드 명세로 전환 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `output/<연도>/` 산출물 CSV 3종이 백엔드 `POST /admin/imports/bundle` 명세에 그대로 업로드 가능한 번들이 되게 한다.

**Architecture:** 제자리 전환 — 내부 스키마와 업로드 스키마를 한 벌로 유지한다. 추출 스키마(pydantic)와 프롬프트를 신규 필드까지 확장하고, CSV 경계에서 대문자 enum·`|` 조인·반전 변환을 적용한다. 캐시에 `schema_version`을 도입해 구 캐시를 자동 재수집하되, 재수집 실패 시 구 성공 캐시로 폴백한다.

**Tech Stack:** Python 3.13, pydantic, requests/BeautifulSoup/trafilatura, pytest 8, LLM은 로컬 `claude` CLI 헤드리스 (`extract.call_claude`가 유일한 접점).

**설계 문서:** `2026-08-09-bundle-spec-migration-design.md` · **이슈:** #16 · **브랜치:** `feat_16_산출물을_백엔드_업로드_명세로_전환` (이미 생성·푸시됨)

## Global Constraints

- 실행: `.venv/bin/python`, 테스트: `.venv/bin/python -m pytest` (venv 필수)
- 커밋 형식: `feat : <변경 사항 설명> #16` — `Co-Authored-By` 금지
- **push 금지** (빈 브랜치 선행 푸시는 이미 완료). 커밋은 각 Task 끝에서만
- `output/` 커밋 금지. `docs/크롤링 번들 업로드.md`(untracked)는 건드리지 않는다
- CSV는 `utf-8-sig`(BOM) + `write_csv()`(원자적 쓰기 + 수식 새니타이즈) 유지
- festivals 헤더(19열, 명세 순서): `import_key,host_name,name,start_date,end_date,venue_name,poster_url,image_urls,description,hashtags,external_visitor_policy,verification_method,ticket_type,ticket_open_at,admission_raw,source_url,discovery,flag,instagram_url`
- lineup 헤더(6열): `import_key,day,order,artist_raw,artist_canonical,revealed`
- artists 헤더(5열): `name,other_names,genre,image_url,needs_review` — `category`는 두지 않는다 (장르로 일원화, 2026-08-09 결정)
- enum 값: flag `OK FETCH_FAILED EMPTY_BODY EXTRACT_FAILED MISMATCH NO_CANDIDATE NO_SOURCE` / discovery `MANUAL SITEMAP SEARCH` / policy `ALLOWED CONDITIONAL DENIED` / method `NONE STUDENT_ID PRE_BOOKING INVITATION OTHER` / ticket `FREE PAID` / genre `HIPHOP BALLAD_RNB DANCE BAND`
- 다중값 구분자는 `|`. 내부 record·캐시의 flag/discovery는 소문자 유지 — 대문자 변환은 CSV 경계(build 함수)에서만
- 주석·문서는 기존처럼 한국어. 요청받지 않은 리팩터링 금지

---

### Task 1: schema.py 재편

**Files:**
- Modify: `schema.py`, `enrich.py` (`ARTIST_FIELDS`·`_merge_artists`만 — ArtistMaster 개명이 즉시 깨뜨리는 부분의 전방 전환. 하위호환 심 금지)
- Test: `tests/test_schema.py`, `tests/test_enrich.py` (픽스처를 새 필드명으로)

> 2026-08-09 수정: 스키마 개명이 enrich.py를 즉시 깨뜨리는 결합이 확인돼,
> `ARTIST_FIELDS`(새 5열)와 `_merge_artists`의 전환을 이 태스크로 앞당긴다
> (개발 단계 — 구 CSV 호환 유지하지 않음, 사용자 결정). Task 6에는 프롬프트·
> genre 분류·마이그레이션·가드 메시지가 남는다.

**Interfaces:**
- Produces: `ExtractionResult`(신규 필드: `description: str|None`, `hashtags: list[str]`, `external_visitor_policy/verification_method/ticket_type: Literal|None`, `ticket_open_at: str|None`, `admission_raw: str|None`; 제거: `outsider_admission`, `ticket_info`), `LineupItem`(`artist_raw: str`, `day: int|None`, `is_secret: bool`; 제거: `day_label`, `date`, `time`), `ArtistMaster`(`name: str`, `other_names: list[str]`, `genre: Genre|None`, `needs_review: bool`), 타입 별칭 `Genre`
- Consumes: 없음 (기반 태스크)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_schema.py`에서 아래 3개 테스트를 교체·추가. `test_extraction_result_full_parse`와 `test_enrich_result_parse`, `test_artist_master_defaults`를 새 스키마 기준으로 다시 쓰고, enum 거부 테스트를 추가한다:

```python
def test_extraction_result_full_parse():
    data = {
        "found": True,
        "university_name": "연세대학교",
        "year": 2026,
        "festival_name": "아카라카",
        "start_date": "2026-05-21",
        "end_date": "2026-05-23",
        "venue_name": "노천극장",
        "description": "연세대학교의 대표 축제. 3일간 노천극장에서 열린다.",
        "hashtags": ["연세대축제", "아카라카"],
        "external_visitor_policy": "CONDITIONAL",
        "verification_method": "PRE_BOOKING",
        "ticket_type": "PAID",
        "ticket_open_at": "2026-05-07T14:00:00",
        "admission_raw": "재학생 우선 입장이며 외부인은 예매 후 입장 가능합니다.",
        "lineup": [
            {"artist_raw": "잔나비", "day": 1},
            {"artist_raw": "시크릿", "is_secret": True},
        ],
    }
    result = ExtractionResult.model_validate(data)
    assert result.lineup[0].day == 1
    assert result.lineup[1].day is None          # 미지정은 None
    assert result.lineup[1].is_secret is True
    assert result.external_visitor_policy == "CONDITIONAL"


def test_extraction_result_rejects_bad_enum():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(
            {"found": True, "university_name": "연세대학교", "year": 2026,
             "external_visitor_policy": "MAYBE"}
        )


def test_enrich_result_parse():
    data = {
        "mapping": {"십센치": "10CM", "10cm": "10CM"},
        "artists": [
            {"name": "10CM", "other_names": ["십센치", "권정열"],
             "genre": "BAND", "needs_review": False}
        ],
    }
    result = EnrichResult.model_validate(data)
    assert result.artists[0].name == "10CM"
    assert result.artists[0].genre == "BAND"


def test_artist_master_defaults():
    a = ArtistMaster.model_validate({"name": "잔나비"})
    assert a.needs_review is False
    assert a.other_names == []
    assert a.genre is None
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_schema.py -v` / Expected: 위 테스트들이 ValidationError 또는 AttributeError로 FAIL

- [ ] **Step 3: schema.py 수정** — `LineupItem`·`ExtractionResult`·`ArtistMaster`를 아래로 교체 (`EnrichResult`·`Candidate`·`DiscoverResult`는 그대로):

```python
"""추출 결과 및 아티스트 마스터의 pydantic 모델."""
from typing import Literal

from pydantic import BaseModel, Field

ExternalVisitorPolicy = Literal["ALLOWED", "CONDITIONAL", "DENIED"]
VerificationMethod = Literal["NONE", "STUDENT_ID", "PRE_BOOKING", "INVITATION", "OTHER"]
TicketType = Literal["FREE", "PAID"]
Genre = Literal["HIPHOP", "BALLAD_RNB", "DANCE", "BAND"]


class LineupItem(BaseModel):
    artist_raw: str
    day: int | None = None
    is_secret: bool = False


class ExtractionResult(BaseModel):
    found: bool
    university_name: str
    year: int
    festival_name: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    venue_name: str | None = None
    description: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    external_visitor_policy: ExternalVisitorPolicy | None = None
    verification_method: VerificationMethod | None = None
    ticket_type: TicketType | None = None
    ticket_open_at: str | None = None
    admission_raw: str | None = None
    instagram_handle: str | None = None
    lineup: list[LineupItem] = Field(default_factory=list)


class ArtistMaster(BaseModel):
    name: str
    other_names: list[str] = Field(default_factory=list)
    genre: Genre | None = None
    needs_review: bool = False
```

- [ ] **Step 4: 전체 테스트 통과 확인** — Run: `.venv/bin/python -m pytest` / Expected: 전부 PASS. (구 필드를 담은 기존 픽스처는 pydantic이 extra 키를 무시하므로 통과한다. `test_extract.py`의 응답 픽스처가 구 필드를 쓰면 이 시점엔 무시될 뿐 깨지지 않는다 — 깨지면 해당 픽스처에서 제거된 필드 키만 지운다)

- [ ] **Step 5: Commit** — `git add schema.py tests/test_schema.py && git commit -m "feat : 추출 스키마를 번들 명세 필드로 재편 #16"`

---

### Task 2: fetch.py 본문 이미지 수집

**Files:**
- Modify: `fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Produces: `parse_html(html, base_url="") -> (body|None, og|None, image_urls: list[str])` (3-튜플로 변경), `FetchResult.image_urls: list[str]`
- Consumes: 없음

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_fetch.py`에 추가. 기존 `test_parse_html_*` 3개는 3-튜플 언패킹으로 수정한다 (`body, og = parse_html(html)` → `body, og, images = parse_html(html)`):

```python
def test_parse_html_collects_body_images():
    html = ('<div class="entry-content">' + "본문" * 60
            + '<img src="https://cdn.example.com/a.jpg">'
            + '<img data-src="/relative/b.jpg">'
            + '<img src="https://cdn.example.com/a.jpg">'   # 중복
            + '<img src="">'
            + "</div>")
    body, og, images = fetch.parse_html(html, base_url="https://blog.example.com/post")
    assert images == ["https://cdn.example.com/a.jpg",
                      "https://blog.example.com/relative/b.jpg"]


def test_parse_html_caps_images_at_five():
    imgs = "".join(f'<img src="https://cdn.example.com/{i}.jpg">' for i in range(8))
    html = '<div class="entry-content">' + "본문" * 60 + imgs + "</div>"
    _, _, images = fetch.parse_html(html, base_url="https://blog.example.com/")
    assert len(images) == 5


def test_parse_html_fallback_has_no_images(monkeypatch):
    # 셀렉터가 못 잡아 trafilatura 폴백으로 본문을 얻은 경우 이미지는 빈 리스트
    monkeypatch.setattr(fetch.trafilatura, "extract", lambda html: "본문" * 60)
    html = "<p>" + "본문" * 60 + '<img src="https://cdn.example.com/a.jpg"></p>'
    body, og, images = fetch.parse_html(html)
    assert body is not None
    assert images == []
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_fetch.py -v` / Expected: 새 테스트가 "too many values to unpack" 또는 TypeError로 FAIL

- [ ] **Step 3: fetch.py 수정** — `from urllib.parse import urljoin, urlparse`로 import 확장. `FetchResult`에 `image_urls: list[str] = field(default_factory=list)` 추가. 상수 `MAX_BODY_IMAGES = 5` 추가. `parse_html`을 아래로 교체:

```python
def parse_html(html: str, base_url: str = "") -> tuple[str | None, str | None, list[str]]:
    """(본문 텍스트 or None, og:image URL or None, 본문 이미지 URL 목록).

    이미지는 본문 컨테이너 안의 <img>만 등장순으로 수집한다 (중복 제거, 최대 5장).
    trafilatura 폴백으로 본문을 얻은 경우엔 컨테이너를 모르므로 빈 목록이다.
    """
    soup = BeautifulSoup(html, "html.parser")

    og = None
    meta = soup.find("meta", property="og:image")
    if meta and meta.get("content"):
        og = meta["content"].strip()

    body, images = None, []
    for selector in BODY_SELECTORS:
        node = soup.select_one(selector)
        if node:
            text = node.get_text(separator="\n", strip=True)
            if len(text) >= MIN_BODY_CHARS:
                body = text
                images = _body_images(node, base_url)
                break

    if body is None:
        extracted = trafilatura.extract(html)
        if extracted and len(extracted) >= MIN_BODY_CHARS:
            body = extracted

    if body is not None:
        body = body[:MAX_BODY_CHARS]
    return body, og, images


def _body_images(node, base_url: str) -> list[str]:
    urls: list[str] = []
    for img in node.find_all("img"):
        src = (img.get("src") or img.get("data-src") or "").strip()
        if not src:
            continue
        absolute = urljoin(base_url, src)
        if not absolute.startswith(("http://", "https://")):
            continue
        if absolute not in urls:
            urls.append(absolute)
        if len(urls) == MAX_BODY_IMAGES:
            break
    return urls
```

`fetch_body`의 호출부를 수정 — `body, og = parse_html(html)` 자리(155행 부근)를:

```python
    body, og, images = parse_html(html, base_url=url)
    candidates = instagram_candidates(html)
    if body is None:
        return FetchResult(status="empty_body", poster_image_url=og, instagram_candidates=candidates)
    return FetchResult(status="ok", body=body, poster_image_url=og,
                       image_urls=images, instagram_candidates=candidates)
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_fetch.py -v` 그리고 `.venv/bin/python -m pytest` / Expected: 전부 PASS

- [ ] **Step 5: Commit** — `git add fetch.py tests/test_fetch.py && git commit -m "feat : 본문 이미지 URL 수집 추가 #16"`

---

### Task 3: extract.py 프롬프트 확장

**Files:**
- Modify: `extract.py` (`PROMPT_TEMPLATE`만)
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: Task 1의 `ExtractionResult` 신규 필드명 (프롬프트 스키마 블록과 일치해야 함)
- Produces: 변경 없음 (`extract()` 시그니처 불변)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_extract.py`에 추가. 파일 상단의 성공 응답 픽스처(JSON 문자열)는 신규 필드를 포함하도록 갱신한다 (`outsider_admission`/`ticket_info`/`day_label` 키 제거, `description`·`day` 등 추가):

```python
def test_prompt_includes_new_field_rules(monkeypatch):
    seen = {}

    def fake_call(prompt, timeout=120, tools=""):
        seen["prompt"] = prompt
        return ('{"found": true, "university_name": "연세대학교", "year": 2026,'
                ' "description": "축제 소개.", "hashtags": ["아카라카"],'
                ' "external_visitor_policy": "CONDITIONAL",'
                ' "admission_raw": "외부인은 예매 후 입장 가능합니다.",'
                ' "lineup": [{"artist_raw": "잔나비", "day": 1}]}')

    monkeypatch.setattr(extract_module, "call_claude", fake_call)
    result = extract("본문", "연세대학교", 2026)
    assert result.description == "축제 소개."
    assert result.lineup[0].day == 1
    for token in ["description", "hashtags", "external_visitor_policy",
                  "verification_method", "ticket_type", "ticket_open_at",
                  "admission_raw", "day", "주최명"]:
        assert token in seen["prompt"]
```

(파일의 기존 import 관례에 맞춰 `extract_module`은 `import extract as extract_module` 또는 기존 방식 그대로 — 파일 상단을 보고 동일하게 쓴다.)

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_extract.py -v` / Expected: 새 테스트 FAIL (프롬프트에 신규 토큰 없음)

- [ ] **Step 3: PROMPT_TEMPLATE 교체** — `extract.py`의 `PROMPT_TEMPLATE`을 아래로 교체 (규칙·스키마 블록만 바뀌고 형식 변수 `{university}` `{year}` `{candidates}` `{body}`는 동일):

```python
PROMPT_TEMPLATE = """다음은 '{university}'의 {year}년 축제 관련 블로그 글 본문입니다.
본문에서 축제 정보를 추출해 아래 스키마의 JSON으로만 응답하세요.

규칙:
- 본문에 명시되지 않은 값은 반드시 null로 둡니다. 절대 추측하거나 지어내지 마세요.
- found: 이 글이 실제로 '{university}'의 {year}년 축제 라인업/정보 글이면 true, 아니면 false.
- festival_name: 축제 이름만 씁니다. 대학명(주최명)은 포함하지 않습니다 (예: "아카라카").
- description: 본문에 있는 사실만으로 축제 소개를 2~3문장으로 씁니다. 본문에 없는
  정보나 수식·과장은 넣지 않습니다. 쓸 정보가 부족하면 null.
- hashtags: 본문에 실제로 적힌 해시태그만 '#' 없이 나열합니다. 없으면 빈 배열.
- external_visitor_policy: 외부인 입장에 대한 본문 근거가 있을 때만
  ALLOWED(입장 가능) / CONDITIONAL(조건부 입장) / DENIED(입장 불가) 중 하나. 근거 없으면 null.
- verification_method: 입장 확인 방식의 근거가 있을 때만
  NONE / STUDENT_ID(학생증) / PRE_BOOKING(사전 예매) / INVITATION(초청) / OTHER 중 하나. 근거 없으면 null.
- ticket_type: 유료 근거가 있으면 PAID, 무료 명시가 있으면 FREE. 근거 없으면 null.
- ticket_open_at: 예매 오픈 일시가 명시된 경우만 YYYY-MM-DDTHH:mm:ss 형식. 아니면 null.
- admission_raw: 위 입장·티켓 판단의 근거가 된 본문 문장을 그대로 인용합니다
  (요약·수정 금지). 근거 없으면 null.
- artist_raw: 본문에 적힌 표기 그대로 씁니다 (정규화 금지).
- day: 그 출연자가 서는 일차를 1부터 시작하는 정수로 씁니다. 본문의 일차 표기나
  날짜와 축제 시작일로 판단하고, 판단할 수 없으면 null.
- is_secret: '시크릿', '당일 공개' 등으로 표기된 미공개 출연자면 true.
- instagram_handle: 아래 후보와 본문을 종합해 '{university}'의 축제·총학생회 공식 계정이
  확실한 것만 채웁니다. 블로그 운영자·언론사·무관 계정이면 null. 후보에 없는 계정을 지어내지 마세요.
- 설명이나 마크다운 없이 JSON 객체 하나만 출력하세요.

스키마:
{{"found": bool, "university_name": str, "year": int,
  "festival_name": str|null, "start_date": str|null, "end_date": str|null,
  "venue_name": str|null, "description": str|null, "hashtags": [str],
  "external_visitor_policy": "ALLOWED"|"CONDITIONAL"|"DENIED"|null,
  "verification_method": "NONE"|"STUDENT_ID"|"PRE_BOOKING"|"INVITATION"|"OTHER"|null,
  "ticket_type": "FREE"|"PAID"|null, "ticket_open_at": str|null,
  "admission_raw": str|null, "instagram_handle": str|null,
  "lineup": [{{"artist_raw": str, "day": int|null, "is_secret": bool}}]}}

본문 링크에서 발견된 인스타그램 계정 후보:
{candidates}

본문:
{body}"""
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_extract.py -v` 그리고 `.venv/bin/python -m pytest` / Expected: 전부 PASS

- [ ] **Step 5: Commit** — `git add extract.py tests/test_extract.py && git commit -m "feat : 추출 프롬프트에 번들 명세 신규 필드 반영 #16"`

---

### Task 4: crawl.py 산출 스키마 전환

**Files:**
- Modify: `crawl.py` (`FESTIVAL_FIELDS`, `LINEUP_FIELDS`, `festival_id()`, `_attempt_url()`, `process_row()`의 record 초기값, `build_festival_row()`, `build_lineup_rows()`)
- Test: `tests/test_crawl.py`

**Interfaces:**
- Consumes: Task 1 스키마 필드, Task 2 `FetchResult.image_urls`
- Produces: `import_key(university: str, year: int) -> str` (구 `festival_id()` 개명 — 값 형식 동일), record 키 `image_urls: list[str]`, CSV 행 생성 함수 (컬럼은 Global Constraints의 헤더와 일치)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_crawl.py`의 `_extraction()` 픽스처를 새 스키마로 교체하고, `test_build_rows`/`test_build_rows_without_extraction`/`test_build_festival_row_includes_instagram_handle`/`test_build_festival_row_includes_discovery`를 새 컬럼 기준으로 다시 쓰고, 헤더 계약·order·시크릿·비ok 제외 테스트를 추가한다:

```python
def _extraction() -> ExtractionResult:
    return ExtractionResult.model_validate({
        "found": True, "university_name": "연세대학교", "year": 2026,
        "festival_name": "아카라카", "start_date": "2026-05-21",
        "end_date": "2026-05-23", "venue_name": "노천극장",
        "description": "연세대학교의 대표 축제.",
        "hashtags": ["연세대축제", "아카라카"],
        "external_visitor_policy": "CONDITIONAL",
        "verification_method": "PRE_BOOKING",
        "ticket_type": "PAID", "ticket_open_at": "2026-05-07T14:00:00",
        "admission_raw": "외부인은 예매 후 입장 가능합니다.",
        "instagram_handle": "yonsei_festival",
        "lineup": [
            {"artist_raw": "잔나비", "day": 1},
            {"artist_raw": "십센치", "day": 1},
            {"artist_raw": "시크릿", "day": 2, "is_secret": True},
        ],
    })


def test_csv_headers_match_backend_spec():
    assert crawl.FESTIVAL_FIELDS == [
        "import_key", "host_name", "name", "start_date", "end_date", "venue_name",
        "poster_url", "image_urls", "description", "hashtags",
        "external_visitor_policy", "verification_method", "ticket_type",
        "ticket_open_at", "admission_raw", "source_url", "discovery", "flag",
        "instagram_url",
    ]
    assert crawl.LINEUP_FIELDS == [
        "import_key", "day", "order", "artist_raw", "artist_canonical", "revealed",
    ]


def test_build_rows():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "flag": "ok", "discovery": "manual",
              "poster_image_url": "https://example.com/p.jpg",
              "image_urls": ["https://cdn.example.com/1.jpg", "https://cdn.example.com/2.jpg"],
              "extraction": _extraction().model_dump()}
    frow = build_festival_row(record)
    assert frow["import_key"] == "연세대학교-2026"
    assert frow["host_name"] == "연세대학교"
    assert frow["name"] == "아카라카"
    assert frow["flag"] == "OK"
    assert frow["discovery"] == "MANUAL"
    assert frow["image_urls"] == "https://cdn.example.com/1.jpg|https://cdn.example.com/2.jpg"
    assert frow["hashtags"] == "연세대축제|아카라카"
    assert frow["instagram_url"] == "https://www.instagram.com/yonsei_festival"
    assert set(frow) == set(crawl.FESTIVAL_FIELDS)

    lrows = build_lineup_rows(record, {"십센치": "10CM"})
    assert [r["order"] for r in lrows] == [1, 2, 1]      # 일차별로 1부터
    assert lrows[0]["day"] == 1 and lrows[2]["day"] == 2
    assert lrows[1]["artist_canonical"] == "10CM"        # 매핑 적용
    assert lrows[2]["revealed"] == "false"
    assert lrows[2]["artist_raw"] == "" and lrows[2]["artist_canonical"] == ""
    assert set(lrows[0]) == set(crawl.LINEUP_FIELDS)


def test_build_rows_without_extraction():
    record = {"university": "고려대학교", "campus": "안암캠퍼스",
              "region": "서울 성북구", "year": 2026, "url": None, "discovery": "",
              "flag": "no_source", "poster_image_url": None, "extraction": None}
    frow = build_festival_row(record)
    assert frow["flag"] == "NO_SOURCE"
    assert frow["name"] == ""
    assert build_lineup_rows(record, {}) == []


def test_build_lineup_rows_skips_non_ok_festival():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "flag": "mismatch", "discovery": "",
              "poster_image_url": None, "extraction": _extraction().model_dump()}
    assert build_lineup_rows(record, {}) == []


def test_admission_raw_truncated_to_200_chars():
    long_ext = _extraction().model_copy(update={"admission_raw": "가" * 300})
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "flag": "ok", "discovery": "manual",
              "poster_image_url": None, "extraction": long_ext.model_dump()}
    assert len(build_festival_row(record)["admission_raw"]) == 200
```

같은 파일에서 `festival_id` 참조가 있으면 `import_key`로 바꾼다. `day`가 None인 항목의 order 검증도 추가한다:

```python
def test_build_lineup_rows_day_none_gets_own_order():
    ext = _extraction().model_copy(update={"lineup": [
        {"artist_raw": "잔나비", "day": None},
        {"artist_raw": "십센치", "day": None},
    ]})
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "flag": "ok", "discovery": "manual",
              "poster_image_url": None, "extraction": ext.model_dump()}
    lrows = build_lineup_rows(record, {})
    assert [r["day"] for r in lrows] == ["", ""]         # 불명은 빈 값 (백엔드에서 INVALID)
    assert [r["order"] for r in lrows] == [1, 2]
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_crawl.py -v` / Expected: 새·수정 테스트 FAIL (KeyError 등)

- [ ] **Step 3: crawl.py 수정** — 상수·함수를 다음으로 교체:

```python
FESTIVAL_FIELDS = [
    "import_key", "host_name", "name", "start_date", "end_date", "venue_name",
    "poster_url", "image_urls", "description", "hashtags",
    "external_visitor_policy", "verification_method", "ticket_type",
    "ticket_open_at", "admission_raw", "source_url", "discovery", "flag",
    "instagram_url",
]
LINEUP_FIELDS = ["import_key", "day", "order", "artist_raw", "artist_canonical", "revealed"]

ADMISSION_RAW_MAX_CHARS = 200


def import_key(university: str, year: int) -> str:
    """축제 1건의 안정적인 식별자(주최명-연도). 백엔드 명세의 import_key.

    시드에서 university+year 조합이 유일함을 전제한다.
    """
    return f"{university}-{year}"
```

(`festival_id()`는 삭제하고 호출처를 전부 `import_key()`로 바꾼다.)

`_attempt_url()`의 attempt 딕셔너리에 이미지 추가:

```python
    attempt = {"flag": fr.status, "poster_image_url": fr.poster_image_url,
               "image_urls": fr.image_urls, "extraction": None}
```

`process_row()`의 record 초기값에 `"image_urls": []` 추가 (`"poster_image_url": None` 옆).

`build_festival_row()` / `build_lineup_rows()` 교체:

```python
def build_festival_row(record: dict) -> dict:
    ext = record["extraction"] or {}
    handle = ext.get("instagram_handle") or ""
    return {
        "import_key": import_key(record["university"], record["year"]),
        "host_name": record["university"],
        "name": ext.get("festival_name") or "",
        "start_date": ext.get("start_date") or "",
        "end_date": ext.get("end_date") or "",
        "venue_name": ext.get("venue_name") or "",
        "poster_url": record["poster_image_url"] or "",
        "image_urls": "|".join(record.get("image_urls") or []),
        "description": ext.get("description") or "",
        "hashtags": "|".join(ext.get("hashtags") or []),
        "external_visitor_policy": ext.get("external_visitor_policy") or "",
        "verification_method": ext.get("verification_method") or "",
        "ticket_type": ext.get("ticket_type") or "",
        "ticket_open_at": ext.get("ticket_open_at") or "",
        "admission_raw": (ext.get("admission_raw") or "")[:ADMISSION_RAW_MAX_CHARS],
        "source_url": record["url"] or "",
        "discovery": (record.get("discovery") or "").upper(),
        "flag": record["flag"].upper(),
        "instagram_url": f"https://www.instagram.com/{handle}" if handle else "",
    }


def build_lineup_rows(record: dict, mapping: dict[str, str]) -> list[dict]:
    """라인업 행을 만든다. artist_canonical은 매핑에서 채운다 — 매핑에 없으면 원문 그대로.

    flag가 ok인 축제만 출력한다 — 그 외 행은 백엔드에서 고아 INVALID만 만든다.
    시크릿 게스트는 revealed=false + 이름 빈 값 (명세 검증 규칙).
    """
    ext = record["extraction"]
    if not ext or record["flag"] != "ok":
        return []
    key = import_key(record["university"], record["year"])
    order_by_day: dict = {}
    rows = []
    for item in ext["lineup"]:
        day = item.get("day")
        order_by_day[day] = order_by_day.get(day, 0) + 1
        secret = bool(item.get("is_secret"))
        raw = "" if secret else item["artist_raw"]
        rows.append({
            "import_key": key,
            "day": "" if day is None else day,
            "order": order_by_day[day],
            "artist_raw": raw,
            "artist_canonical": "" if secret else mapping.get(raw, raw),
            "revealed": "false" if secret else "true",
        })
    return rows
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest` / Expected: 전부 PASS. (`test_enrich.py`의 lineup 헤더 픽스처가 구 `LINEUP_FIELDS`를 import해서 쓰고 있으면 자동으로 새 헤더를 따라간다 — 개별 실패가 나오면 그 픽스처의 컬럼 키만 새 이름으로 맞춘다)

- [ ] **Step 5: Commit** — `git add crawl.py tests/test_crawl.py && git commit -m "feat : 산출 CSV를 번들 명세 컬럼으로 전환 #16"`

---

### Task 5: 캐시 스키마 버전 + 재수집 실패 폴백

**Files:**
- Modify: `crawl.py` (`process_row()`)
- Test: `tests/test_crawl.py`

**Interfaces:**
- Consumes: Task 4의 record 구조
- Produces: 모듈 상수 `SCHEMA_VERSION = 2`, 캐시 record 키 `schema_version: int`

- [ ] **Step 1: 실패하는 테스트 작성** — 기존 캐시 픽스처를 쓰는 테스트(`test_process_row_uses_cache`, `test_process_row_cache_hit_refreshes_campus_region`, `test_process_row_cache_keyed_on_seed_url` 등)의 캐시 딕셔너리에 `"schema_version": 2`를 추가해 "캐시 적중" 의미를 유지하고, 아래를 추가한다:

```python
def test_process_row_recollects_versionless_cache(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    old = {"university": "연세대학교", "campus": "신촌캠퍼스",
           "region": "서울 서대문구", "year": 2026,
           "seed_url": "https://example.com/post", "url": "https://example.com/post",
           "discovery": "manual", "flag": "ok", "poster_image_url": None,
           "extraction": _extraction().model_dump()}          # schema_version 없음 = 구 스키마
    (raw_dir / "연세대학교.json").write_text(json.dumps(old), "utf-8")
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(
        status="ok", body="본문" * 100, image_urls=[]))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())
    record = process_row(_row(), tmp_path)
    assert record["schema_version"] == crawl.SCHEMA_VERSION
    cached = json.loads((raw_dir / "연세대학교.json").read_text("utf-8"))
    assert cached["schema_version"] == crawl.SCHEMA_VERSION   # 새 캐시로 갱신됨


def test_process_row_keeps_old_ok_cache_when_recollect_fails(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    old = {"university": "연세대학교", "campus": "신촌캠퍼스",
           "region": "서울 서대문구", "year": 2026,
           "seed_url": "https://example.com/post", "url": "https://example.com/post",
           "discovery": "manual", "flag": "ok", "poster_image_url": None,
           "extraction": _extraction().model_dump()}
    before = json.dumps(old)
    (raw_dir / "연세대학교.json").write_text(before, "utf-8")
    monkeypatch.setattr(crawl, "fetch_body",
                        lambda url: FetchResult(status="fetch_failed", error="410"))
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "ok"                             # 구 데이터 유지
    assert record["extraction"] is not None
    after = (raw_dir / "연세대학교.json").read_text("utf-8")
    assert after == before                                    # 캐시 파일은 그대로 — 다음 실행에서 재시도


def test_process_row_new_records_carry_schema_version(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(
        status="ok", body="본문" * 100, image_urls=["https://cdn.example.com/1.jpg"]))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())
    record = process_row(_row(), tmp_path)
    assert record["schema_version"] == crawl.SCHEMA_VERSION
    assert record["image_urls"] == ["https://cdn.example.com/1.jpg"]
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_crawl.py -v` / Expected: 새 테스트 FAIL (SCHEMA_VERSION 없음)

- [ ] **Step 3: process_row 수정** — `SCHEMA_VERSION = 2` 상수를 `FESTIVAL_FIELDS` 위에 추가. `process_row`를 다음 구조로 수정:

```python
def process_row(row: UniversityRow, out_dir: Path) -> dict:
    """대학 1곳 처리. 수동 URL → 사이트맵 후보 → 검색 후보 순으로 시도한다."""
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache_path = raw_dir / f"{row.university}.json"
    stale_ok = None
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (cached.get("schema_version") == SCHEMA_VERSION
                and cached.get("seed_url") == row.url
                and cached.get("year") == row.year):
            # 시드 전용 필드는 현재 행 기준으로 갱신 (추출 결과에는 영향 없음)
            cached["campus"] = row.campus
            cached["region"] = row.region
            return cached
        if cached.get("flag") == "ok":
            # 구 스키마(또는 시드 변경)의 성공 캐시 — 재수집 실패 시 폴백으로 쓴다.
            # 재실행은 복원이지 파괴가 아니다 (DEC-0028 원칙).
            stale_ok = cached

    record = {
        "schema_version": SCHEMA_VERSION,
        "university": row.university, "campus": row.campus,
        "region": row.region, "year": row.year,
        "seed_url": row.url, "url": row.url, "discovery": "",
        "flag": "no_source", "poster_image_url": None, "image_urls": [],
        "extraction": None,
    }

    if row.url is not None:
        record.update(_attempt_url(row.url, row))
        record["discovery"] = "manual" if record["flag"] == "ok" else ""

    if record["flag"] != "ok":
        # 사이트맵 우선 — 통과하면 WebSearch(1건 60초 + 세션 한도)를 아예 부르지 않는다
        if not _try_candidates(
            discover_sitemap(row.university, row.year), row, record, "sitemap"
        ):
            candidates = discover_cached(row.university, row.year, out_dir)
            if candidates is None:
                # 탐색 자체가 실패(세션 한도 등) — 일시적이므로 캐시하지 않고 다음 실행에서 재시도
                return _keep_stale_on_failure(record, stale_ok, row)
            if not _try_candidates(candidates, row, record, "search"):
                # 어느 후보도 verify를 통과하지 못함
                if row.url is None:
                    record["flag"] = "no_candidate"

    result = _keep_stale_on_failure(record, stale_ok, row)
    if result is stale_ok:
        return result       # 구 캐시 파일은 그대로 둔다 — 다음 실행에서 다시 시도
    if record["flag"] not in ("fetch_failed", "extract_failed"):
        cache_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def _keep_stale_on_failure(record: dict, stale_ok: dict | None, row: UniversityRow) -> dict:
    """재수집이 실패했고 구 성공 캐시가 있으면 구 데이터를 지키는 쪽을 택한다."""
    if record["flag"] == "ok" or stale_ok is None:
        return record
    stale_ok["campus"] = row.campus
    stale_ok["region"] = row.region
    print("  -> 재수집 실패, 이전 결과 유지", flush=True)
    return stale_ok
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest` / Expected: 전부 PASS. (`test_process_row_happy_path_writes_cache` 등 신규 캐시를 검증하는 테스트가 `schema_version` 추가로 깨지면 단언에 키만 반영)

- [ ] **Step 5: Commit** — `git add crawl.py tests/test_crawl.py && git commit -m "feat : 캐시 스키마 버전 도입, 재수집 실패 시 구 캐시 유지 #16"`

---

### Task 6: enrich.py 전환 + artists.csv 마이그레이션

**Files:**
- Modify: `enrich.py`, `schema.py` (`GenreResult` 추가)
- Test: `tests/test_enrich.py`

> 참고: `ARTIST_FIELDS`(새 5열)와 `_merge_artists` 전환은 Task 1에서 이미 반영됨.
> 이 태스크의 몫은 프롬프트(genre·other_names 규칙), `classify_genres`,
> `_migrate_artists_csv`, lineup 가드 메시지, `GenreResult`다. Step 3~4의 코드 중
> 이미 반영된 부분은 검증만 하고 넘어간다.

**Interfaces:**
- Consumes: Task 1의 `ArtistMaster`(`name`/`other_names`/`genre`), `Genre`; Task 4의 `LINEUP_FIELDS`
- Produces: `ARTIST_FIELDS = ["name", "other_names", "genre", "image_url", "needs_review"]`, `classify_genres(names: list[str]) -> dict[str, str | None]`, `_migrate_artists_csv(base_dir: Path) -> None`, `schema.GenreResult`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_enrich.py`에서 LLM 응답 픽스처의 artists를 새 형태(`{"name": ..., "other_names": [...], "genre": ...}`)로 갱신하고, `test_enrich_accumulates_artists_csv`를 새 컬럼 기준으로 수정하고, 아래를 추가한다:

```python
def test_migrate_artists_csv_converts_old_schema(tmp_path, monkeypatch):
    old_header = "name_canonical,name_en,real_name,category,aliases,needs_review\n"
    (tmp_path / "artists.csv").write_text(
        old_header + "10CM,10CM,권정열,가수,십센치;십cm,false\n", encoding="utf-8-sig")
    monkeypatch.setattr(enrich, "classify_genres", lambda names: {"10CM": "BAND"})
    enrich._migrate_artists_csv(tmp_path)
    with open(tmp_path / "artists.csv", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == enrich.ARTIST_FIELDS
    # name과 같은 표기(10CM)는 별칭에서 제외, 나머지는 | 로 병합
    assert rows[0]["name"] == "10CM"
    assert rows[0]["other_names"] == "권정열|십센치|십cm"
    assert rows[0]["genre"] == "BAND"
    assert rows[0]["image_url"] == ""
    assert rows[0]["needs_review"] == "false"
    assert "category" not in rows[0]          # 장르로 일원화 — category는 버린다


def test_migrate_artists_csv_noop_on_new_schema(tmp_path, monkeypatch):
    new_header = ",".join(enrich.ARTIST_FIELDS) + "\n"
    content = new_header + "10CM,십센치,BAND,,false\n"
    (tmp_path / "artists.csv").write_text(content, encoding="utf-8-sig")

    def boom(names):
        raise AssertionError("새 스키마면 LLM을 부르면 안 됨")

    monkeypatch.setattr(enrich, "classify_genres", boom)
    enrich._migrate_artists_csv(tmp_path)
    assert (tmp_path / "artists.csv").read_text(encoding="utf-8-sig") == content


def test_classify_genres_parses_llm_response(monkeypatch):
    monkeypatch.setattr(enrich, "call_claude",
                        lambda prompt, timeout=900: '{"genres": {"10CM": "BAND", "낯선가수": null}}')
    assert enrich.classify_genres(["10CM", "낯선가수"]) == {"10CM": "BAND", "낯선가수": None}


def test_merge_artists_writes_new_columns(tmp_path):
    enrich._merge_artists(tmp_path, [ArtistMaster(
        name="10CM", other_names=["십센치"], genre="BAND")])
    with open(tmp_path / "artists.csv", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["name"] == "10CM"
    assert rows[0]["other_names"] == "십센치"
    assert rows[0]["genre"] == "BAND"
```

(파일 상단 import에 `from schema import ArtistMaster`가 이미 있는지 확인하고 없으면 추가.)

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_enrich.py -v` / Expected: FAIL (`_migrate_artists_csv`, `classify_genres` 없음)

- [ ] **Step 3: schema.py에 GenreResult 추가** — `EnrichResult` 아래에:

```python
class GenreResult(BaseModel):
    genres: dict[str, Genre | None]
```

- [ ] **Step 4: enrich.py 수정** —

`ARTIST_FIELDS`·구 헤더 상수·프롬프트 교체:

```python
ARTIST_FIELDS = ["name", "other_names", "genre", "image_url", "needs_review"]
OLD_ARTIST_FIELDS = ["name_canonical", "name_en", "real_name", "category",
                     "aliases", "needs_review"]
```

`PROMPT_TEMPLATE`의 규칙에 두 줄 추가 (기존 규칙 뒤):

```
- other_names에는 별칭·영문 표기·본명 등 그 아티스트를 가리키는 다른 표기를
  모두 넣습니다 (name과 같은 표기는 제외).
- genre는 HIPHOP / BALLAD_RNB / DANCE / BAND 중 확실한 것만 채우고,
  모르거나 넷에 안 맞으면 null로 둡니다.
```

스키마 블록을 교체:

```
{{"mapping": {{"원문표기": "정식표기"}},
  "artists": [{{"name": str, "other_names": [str],
               "genre": "HIPHOP"|"BALLAD_RNB"|"DANCE"|"BAND"|null,
               "needs_review": bool}}]}}
```

`_merge_artists`를 새 컬럼으로 교체:

```python
def _merge_artists(base_dir: Path, artists: list[ArtistMaster]) -> None:
    """기존 artists.csv를 유지하고 새 아티스트만 덧붙인다 — 연도 사이에 누적된다."""
    path = base_dir / "artists.csv"
    rows: list[dict] = []
    if path.exists():
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    known = {r["name"] for r in rows}
    for a in artists:
        if a.name in known:
            continue
        rows.append({
            "name": a.name,
            "other_names": "|".join(a.other_names),
            "genre": a.genre or "",
            "image_url": "",
            "needs_review": "true" if a.needs_review else "false",
        })
        known.add(a.name)
    write_csv(path, ARTIST_FIELDS, rows)
```

genre 분류와 1회성 마이그레이션 추가 (import에 `from schema import ArtistMaster, EnrichResult, GenreResult` 반영):

```python
GENRE_PROMPT = """다음 아티스트들의 장르를 분류하세요.

규칙:
- HIPHOP / BALLAD_RNB / DANCE / BAND 중 확실한 것만 채우고, 모르거나 넷에 안 맞으면 null.
- 절대 추측으로 채우지 마세요.
- 설명 없이 JSON 객체 하나만 출력하세요: {{"genres": {{"아티스트명": "HIPHOP"|null}}}}

아티스트 목록:
{names}"""


def classify_genres(names: list[str]) -> dict[str, str | None]:
    """아티스트 name 목록의 장르를 LLM 1콜로 분류한다. 실패하면 예외가 전파돼 중단된다."""
    if not names:
        return {}
    raw = call_claude(GENRE_PROMPT.format(names="\n".join(f"- {n}" for n in names)),
                      timeout=ENRICH_TIMEOUT_SECONDS)
    return GenreResult.model_validate_json(_extract_json(raw)).genres


def _migrate_artists_csv(base_dir: Path) -> None:
    """구 스키마 artists.csv를 새 컬럼으로 1회 변환한다 (genre는 LLM 1콜로 분류).

    변환 실패 시 파일은 건드리지 않으므로 다음 실행에서 다시 시도된다.
    """
    path = base_dir / "artists.csv"
    if not path.exists():
        return
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != OLD_ARTIST_FIELDS:
            return
        old_rows = list(reader)
    genres = classify_genres([r["name_canonical"] for r in old_rows])
    rows = []
    for r in old_rows:
        name = r["name_canonical"]
        others = [x for x in [r["name_en"], r["real_name"]] + r["aliases"].split(";")
                  if x and x != name]
        rows.append({
            "name": name,
            "other_names": "|".join(dict.fromkeys(others)),   # 순서 유지 중복 제거
            "genre": genres.get(name) or "",
            "image_url": "",
            "needs_review": r["needs_review"],
        })    # 구 category는 버린다 — 장르로 일원화
    write_csv(path, ARTIST_FIELDS, rows)
    print(f"artists.csv 마이그레이션 완료: {len(rows)}명, "
          f"genre 분류 {sum(1 for r in rows if r['genre'])}건")
```

`enrich()` 첫 줄에 `_migrate_artists_csv(base_dir)` 호출 추가. 구 lineup 스키마 안내 메시지(137행 부근)의 "(festival_id 없음)"을 "(import_key 없음)"으로 수정.

- [ ] **Step 5: 통과 확인** — Run: `.venv/bin/python -m pytest` / Expected: 전부 PASS

- [ ] **Step 6: Commit** — `git add enrich.py schema.py tests/test_enrich.py && git commit -m "feat : 아티스트 마스터를 명세 컬럼으로 전환, 구 파일 마이그레이션 #16"`

---

### Task 7: review.html 검수 화면 갱신

**Files:**
- Modify: `review.html` (serve.py는 변경 없음 — 시드·캐시 파일명 기준이라 무관)

**Interfaces:**
- Consumes: Task 4·6의 CSV 컬럼명 (검수 화면은 `/api/data`로 CSV를 그대로 받는다)

- [ ] **Step 1: 컬럼 참조 교체** — `review.html`의 `<script>`에서:

`visible()` (80~82행):

```js
function visible() {
  if (filter === "search") return data.festivals.filter((r) => r.discovery === "SITEMAP" || r.discovery === "SEARCH");
  if (filter === "all") return data.festivals;
  return data.festivals.filter((r) => r.flag !== "OK");
}
```

`render()`의 리스트 항목 (90~91행): `r.flag === "OK" ? "" : "bad"` / `${esc(r.flag)}</span>${esc(r.host_name)}`

`renderDetail()` (96~127행)을 다음으로 교체:

```js
function renderDetail(f) {
  if (!f) { $("detail").innerHTML = "<p>표시할 축제가 없습니다.</p>"; return; }
  // import_key가 없는 행(구 스키마 잔존)까지 undefined === undefined로 걸리지 않도록 truthy를 먼저 본다.
  const lineup = data.lineup.filter((l) => l.import_key && l.import_key === f.import_key);
  const url = safeUrl(f.source_url);
  const tags = (f.hashtags || "").split("|").filter(Boolean).map((h) => "#" + h).join(" ");
  const fields = [
    ["축제명", f.name], ["기간", `${f.start_date} ~ ${f.end_date}`],
    ["장소", f.venue_name], ["소개", f.description], ["해시태그", tags],
    ["외부인", f.external_visitor_policy], ["확인 방식", f.verification_method],
    ["티켓", f.ticket_type], ["예매 오픈", f.ticket_open_at],
    ["판단 근거", f.admission_raw], ["인스타", f.instagram_url],
    ["포스터", f.poster_url], ["이미지", f.image_urls],
    ["출처", f.discovery], ["flag", f.flag],
  ];
  $("detail").innerHTML = `
    <h2>${esc(f.import_key)}</h2>
    <p>
      <button class="rerun" data-uni="${esc(f.host_name)}" data-rediscover="0">다시 돌리기</button>
      <button class="rerun" data-uni="${esc(f.host_name)}" data-rediscover="1">탐색부터</button>
    </p>
    <table>${fields.map(([k, v]) =>
      `<tr><th>${esc(k)}</th><td>${esc(v) || "—"}</td></tr>`).join("")}</table>
    <h3>라인업 ${lineup.length}건</h3>
    <table>${lineup.map((l) => `
      <tr><th>${l.day ? esc(l.day) + "일차" : "?"} · ${esc(l.order)}번</th>
          <td>${esc(l.artist_canonical)}
              ${l.artist_canonical !== l.artist_raw
                ? `<span class="raw">← ${esc(l.artist_raw)}</span>` : ""}
              ${l.revealed === "false" ? "🔒" : ""}</td></tr>`).join("")}</table>
    <h3>원본 ${url
      ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">새 탭 ↗</a>` : ""}</h3>
    ${url
      ? `<iframe src="${esc(url)}" sandbox="allow-scripts"
                 referrerpolicy="no-referrer"></iframe>`
      : "<p>출처 URL이 없습니다.</p>"}`;
}
```

`renderArtists()` (130~141행)를 교체:

```js
function renderArtists() {
  const rows = [...data.artists].sort(
    (a, b) => (b.needs_review === "true") - (a.needs_review === "true"));
  $("list").innerHTML = "";
  $("detail").innerHTML = `
    <h2>아티스트 ${rows.length}</h2>
    <table><tr><th>대표명</th><td>장르 / 다른 표기</td></tr>
    ${rows.map((a) => `
      <tr><th>${a.needs_review === "true" ? "⚠️ " : ""}${esc(a.name)}</th>
          <td>${esc(a.genre)} / ${esc(a.other_names)}</td></tr>`).join("")}</table>`;
}
```

- [ ] **Step 2: 잔존 참조 검사** — Run: `grep -nE "festival_id|festival_name|university|outsider|ticket_info|instagram_handle|poster_image_url|day_label|is_secret|name_canonical|aliases|name_en|real_name" review.html` / Expected: 0건

- [ ] **Step 3: 스모크 (수동)** — 산출물이 아직 구 스키마이므로 이 시점엔 화면이 비거나 빈 값이 보이는 게 정상. Task 9의 재크롤 후 육안 확인이 최종 검증이다. 여기서는 `.venv/bin/python serve.py`가 에러 없이 뜨고 `/api/data`가 200을 주는 것만 확인.

- [ ] **Step 4: Commit** — `git add review.html && git commit -m "feat : 검수 화면을 번들 명세 컬럼으로 갱신 #16"`

---

### Task 8: README 갱신 + 백엔드 전달 코멘트

**Files:**
- Modify: `README.md`
- Create: 이슈 #16 코멘트 (파일 아님 — gh CLI)

**Interfaces:**
- Consumes: 확정된 헤더·enum (Global Constraints)

- [ ] **Step 1: README 수정** — 다음 부분만 외과적으로 갱신:
  - ER 다이어그램(73~104행 부근): 컬럼명을 새 스키마로 교체 (`import_key`, `host_name`, `name`, 신규 필드, lineup `day`/`order`/`revealed`, artists `name`/`other_names`/`genre`)
  - flag 표(256행 부근): 값을 대문자로 (`ok` → `OK` 등 7종), 본문 중 `flag != ok` 문구를 `flag != OK`로
  - "스키마 변경 시 재생성" 문단(184행 부근): schema_version 불일치 캐시는 자동 재수집되고, 재수집 실패 시 이전 성공 결과가 유지된다는 설명으로 교체
  - 다중값 구분자·시크릿 게스트 표기 등 산출물 설명이 있으면 `|` 구분·`revealed` 기준으로 수정
- [ ] **Step 2: 검증** — README를 처음부터 끝까지 다시 읽어 구 컬럼명 잔존을 확인 (일괄 치환 후 예시·표·코드블록 안을 특히 본다): `grep -nE "festival_id|outsider_admission|ticket_info|day_label|is_secret|name_canonical|poster_image_url" README.md` / Expected: 0건
- [ ] **Step 3: Commit** — `git add README.md && git commit -m "feat : README 산출물 스키마 설명 갱신 #16"`
- [ ] **Step 4: 백엔드 전달 코멘트 (사용자 승인 후)** — 아래 본문을 사용자에게 보여주고 승인받은 뒤 `gh issue comment 16 --body "..."`로 등록:

```markdown
백엔드 확인·전달 사항 (명세: 크롤링 번들 업로드)

전달
1. flag 나머지 5종 (명세 🚧 자리): FETCH_FAILED / EMPTY_BODY / EXTRACT_FAILED / MISMATCH / NO_SOURCE
   (기존 OK / NO_CANDIDATE 포함 총 7종, 모두 UPPER_SNAKE_CASE)
2. 명세 오탈자: festivals 헤더 코드블록에 instagram_url 누락(표에는 있음),
   artists 헤더 코드블록 끝의 ", ", 파이프 구분자 설명이 마크다운 표를 깨뜨림

확인 요청
3. 인코딩: 크롤러 산출물은 BOM 붙은 UTF-8(utf-8-sig)입니다 (검수자 Excel 호환).
   업로드 파서가 BOM을 허용하는지 확인하고 명세에 명시 부탁합니다.
4. artists.csv에 needs_review 컬럼(true/false) 추가 제안: 크롤러가 정규화 확신이
   없는 아티스트에 이미 이 신호를 만들고 있어, 받아주면 미리보기 needsReview에
   그대로 쓸 수 있습니다. 어려우면 크롤러 쪽에서 컬럼을 제거하겠습니다.
5. flag != OK 행은 discovery가 빈 값입니다 (수집 실패라 발견 경로가 없음).
   필수 컬럼이지만 어차피 SKIP 처리되는 행이라 빈 값 허용을 확인 부탁합니다.
6. instagram_url 컬럼 위치는 헤더 맨 끝으로 두었습니다. 다른 위치가 필요하면 알려주세요.
7. artists.csv에서 category 컬럼 제거를 제안합니다 — 크롤러는 장르(genre)만
   분류하고 자유텍스트 분류는 채우지 않습니다. 명세의 category 예시("가수 ·
   싱어송라이터")가 필요하면 알려주세요.
```

---

### Task 9: 재크롤 실행 + 최종 검증

**Files:** 코드 변경 없음 (실행·검증만)

**Interfaces:**
- Consumes: Task 1~8 전부

- [ ] **Step 1: 전체 테스트** — Run: `.venv/bin/python -m pytest` / Expected: 전부 PASS
- [ ] **Step 2: 스모크 (LLM 1건)** — **사용자에게 실행 시점 확인 후** (claude 세션 한도 소모): `.venv/bin/python crawl.py --year 2026 --limit 1` / Expected: 1곳 재수집 로그, `output/2026/festivals.csv` 헤더가 명세와 일치. 확인: `head -1 output/2026/festivals.csv`
- [ ] **Step 3: 전체 재크롤** — **사용자 승인 후** (~30–50분): `.venv/bin/python crawl.py --year 2026` / Expected: 구 스키마 캐시 29곳 재수집. 완료 후 확인: festivals 29행, `OK` 26곳 내외 (재수집 실패 → 이전 결과 유지 로그가 있으면 그 수만큼 신규 필드가 빈 값). 확인 명령: `.venv/bin/python -c "import csv; rows=list(csv.DictReader(open('output/2026/festivals.csv', encoding='utf-8-sig'))); print(len(rows), sum(1 for r in rows if r['flag']=='OK'))"`
- [ ] **Step 4: enrich 실행** — `.venv/bin/python enrich.py` / Expected: artists.csv 마이그레이션 로그(84명 내외, genre 분류 건수) + 정규화 보존 확인: `grep -c "10CM" output/2026/lineup.csv` ≥ 1 (십센치 → 10CM 매핑 유지)
- [ ] **Step 5: 검수 화면 육안 확인** — `./admin.sh` (serve.py) 실행 후 브라우저에서: 문제만 필터에 `flag != OK` 행만, 상세에 소개·해시태그·입장 분류·판단 근거 표시, 라인업 `N일차 · M번`, 아티스트 탭 장르 표시 확인
- [ ] **Step 6: 이슈 #16에 결과 보고** — `/report` 커맨드 관례대로 `docs/reports/20260809_16_산출물_번들_명세_전환.md` 작성 후 커밋: `git add docs/reports/ && git commit -m "feat : 구현 보고서 작성 #16"` (보고서 양식은 `.claude/commands/report.md`를 따른다)

---

## Self-Review 결과

- 스펙 커버리지: 설계 문서의 모든 항목이 태스크에 대응 — 스키마(1), 이미지(2), 프롬프트(3), CSV 전환(4), 캐시·폴백(5), enrich·마이그레이션(6), 검수 화면(7), README·백엔드 체크리스트(8), 재크롤·검증(9)
- 타입 일관성: `import_key()` 명명은 Task 4에서 정의하고 5·7이 동일 명칭 사용. `ARTIST_FIELDS`·`LINEUP_FIELDS`는 Global Constraints의 헤더와 문자열 일치
- 남긴 결정: 없음 — 미결 항목은 전부 "백엔드 확인 요청"으로 Task 8에 위임
