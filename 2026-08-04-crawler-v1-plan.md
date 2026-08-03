# FESTA 크롤러 v1 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 큐레이션된 블로그 URL에서 축제 상세+라인업을 추출해 운영자 검토용 CSV 3종을 만드는 로컬 배치 크롤러.

**Architecture:** `crawl.py`가 `universities.csv`를 순회하며 `fetch.py`(본문 수집) → `extract.py`(claude -p 추출+검증) → raw JSON 캐시 → CSV 출력. 전체 완료 후 `enrich.py`가 아티스트 정규화 및 마스터 생성(LLM 1콜). LLM 접점은 `extract.call_claude()` 단 하나.

**Tech Stack:** Python 3.11+, requests, beautifulsoup4, trafilatura, pydantic v2, pytest. LLM은 로컬 Claude Code CLI(`claude -p`, 구독 인증).

**Spec:** `crawler/2026-08-04-crawler-pipeline-design.md` (같은 디렉토리)

## Global Constraints

- 모든 명령은 `crawler/` 디렉토리에서 실행한다 (레포 루트 아님)
- Python 가상환경: `crawler/.venv` — 명령 예시는 `.venv/bin/python`, `.venv/bin/pytest`
- HTTP: User-Agent `FESTA-crawler/0.1 (festival lineup archive)`, 동일 호스트 요청 간 최소 3초, 타임아웃 10초 + 재시도 1회, robots.txt 차단 경로 접근 금지
- 본문 상한 8,000자 절단, `empty_body` 판정 기준: 본문 100자 미만
- CSV 인코딩은 항상 `utf-8-sig` (Excel 호환)
- LLM 호출은 `extract.call_claude()` 함수를 통해서만: `claude -p <prompt> --output-format json`, 호출 타임아웃 120초, 모델 지정 안 함(세션 기본값)
- 수집한 본문 원문 텍스트는 디스크에 저장하지 않는다 (추출 프롬프트에만 사용)
- `flag` 허용값: `ok | fetch_failed | empty_body | extract_failed | mismatch | no_source`
- 커밋 메시지: `<type>: <설명>` (feat/test/chore/docs)

---

### Task 1: 스캐폴드 + 추출 스키마 (`schema.py`)

**Files:**
- Create: `crawler/requirements.txt`
- Create: `crawler/.gitignore`
- Create: `crawler/conftest.py` (빈 파일 — pytest가 crawler/를 import path에 넣게 함)
- Create: `crawler/schema.py`
- Test: `crawler/tests/test_schema.py`

**Interfaces:**
- Consumes: 없음
- Produces (이후 모든 태스크가 사용):
  - `schema.LineupItem(BaseModel)` — `artist_raw: str`, `day_label: str|None=None`, `date: str|None=None`, `time: str|None=None`, `is_secret: bool=False`
  - `schema.ExtractionResult(BaseModel)` — `found: bool`, `university_name: str`, `year: int`, `festival_name: str|None=None`, `start_date: str|None=None`, `end_date: str|None=None`, `venue_name: str|None=None`, `outsider_admission: str|None=None`, `ticket_info: str|None=None`, `lineup: list[LineupItem]=[]`
  - `schema.ArtistMaster(BaseModel)` — `name_canonical: str`, `name_en: str|None=None`, `real_name: str|None=None`, `category: str|None=None`, `aliases: list[str]=[]`, `needs_review: bool=False`
  - `schema.EnrichResult(BaseModel)` — `mapping: dict[str, str]`, `artists: list[ArtistMaster]`

- [ ] **Step 1: 환경 파일 작성**

`crawler/requirements.txt`:

```
requests>=2.32
beautifulsoup4>=4.12
trafilatura>=1.12
pydantic>=2.7
pytest>=8.0
```

`crawler/.gitignore`:

```
.venv/
output/
__pycache__/
.pytest_cache/
```

`crawler/conftest.py`: 빈 파일 생성.

- [ ] **Step 2: venv 생성 및 의존성 설치**

Run: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
Expected: 에러 없이 설치 완료 (`.venv/bin/pytest --version` 동작 확인)

- [ ] **Step 3: 실패하는 테스트 작성**

`crawler/tests/test_schema.py`:

```python
import pytest
from pydantic import ValidationError

from schema import ArtistMaster, EnrichResult, ExtractionResult, LineupItem


def test_extraction_result_full_parse():
    data = {
        "found": True,
        "university_name": "연세대학교",
        "year": 2026,
        "festival_name": "아카라카",
        "start_date": "2026-05-21",
        "end_date": "2026-05-23",
        "venue_name": "노천극장",
        "outsider_admission": "외부인 입장 가능",
        "ticket_info": "유료, 예매 5.07 오픈",
        "lineup": [
            {"artist_raw": "잔나비", "day_label": "1일차", "date": "2026-05-21"},
            {"artist_raw": "시크릿", "is_secret": True},
        ],
    }
    result = ExtractionResult.model_validate(data)
    assert result.lineup[0].artist_raw == "잔나비"
    assert result.lineup[0].time is None          # 미지정 필드는 None
    assert result.lineup[0].is_secret is False    # 기본값
    assert result.lineup[1].is_secret is True


def test_extraction_result_minimal_not_found():
    # found=False인 글도 스키마는 통과해야 함 (역방향 검증은 별도 단계)
    result = ExtractionResult.model_validate(
        {"found": False, "university_name": "고려대학교", "year": 2026}
    )
    assert result.festival_name is None
    assert result.lineup == []


def test_extraction_result_rejects_missing_required():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({"university_name": "연세대학교", "year": 2026})


def test_enrich_result_parse():
    data = {
        "mapping": {"십센치": "10CM", "10cm": "10CM"},
        "artists": [
            {"name_canonical": "10CM", "name_en": "10CM", "real_name": "권정열",
             "category": "가수", "aliases": ["십센치"], "needs_review": False}
        ],
    }
    result = EnrichResult.model_validate(data)
    assert result.mapping["십센치"] == "10CM"
    assert result.artists[0].name_canonical == "10CM"


def test_artist_master_defaults():
    a = ArtistMaster.model_validate({"name_canonical": "잔나비"})
    assert a.needs_review is False
    assert a.aliases == []
```

- [ ] **Step 4: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'schema'`

- [ ] **Step 5: `schema.py` 구현**

```python
"""추출 결과 및 아티스트 마스터의 pydantic 모델."""
from pydantic import BaseModel, Field


class LineupItem(BaseModel):
    artist_raw: str
    day_label: str | None = None
    date: str | None = None
    time: str | None = None
    is_secret: bool = False


class ExtractionResult(BaseModel):
    found: bool
    university_name: str
    year: int
    festival_name: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    venue_name: str | None = None
    outsider_admission: str | None = None
    ticket_info: str | None = None
    lineup: list[LineupItem] = Field(default_factory=list)


class ArtistMaster(BaseModel):
    name_canonical: str
    name_en: str | None = None
    real_name: str | None = None
    category: str | None = None
    aliases: list[str] = Field(default_factory=list)
    needs_review: bool = False


class EnrichResult(BaseModel):
    mapping: dict[str, str]
    artists: list[ArtistMaster]
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_schema.py -v`
Expected: 5 passed

- [ ] **Step 7: 커밋**

```bash
git add crawler/requirements.txt crawler/.gitignore crawler/conftest.py crawler/schema.py crawler/tests/test_schema.py
git commit -m "feat: 크롤러 스캐폴드 및 추출 스키마 모델"
```

---

### Task 2: 대학 시드 (`universities.csv`) + 로더

**Files:**
- Create: `crawler/universities.csv`
- Create: `crawler/crawl.py` (로더 부분만 — Task 5에서 확장)
- Test: `crawler/tests/test_load_universities.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `crawl.UniversityRow` (dataclass) — `university: str`, `campus: str`, `region: str`, `year: int`, `url: str | None`
  - `crawl.load_universities(path: Path) -> list[UniversityRow]`

- [ ] **Step 1: 실패하는 테스트 작성**

`crawler/tests/test_load_universities.py`:

```python
from pathlib import Path

from crawl import load_universities

CSV_PATH = Path(__file__).parent.parent / "universities.csv"


def test_loads_29_rows():
    rows = load_universities(CSV_PATH)
    assert len(rows) == 29


def test_url_empty_becomes_none():
    rows = load_universities(CSV_PATH)
    by_name = {r.university: r for r in rows}
    assert by_name["한국외국어대학교"].url is None      # 원본 목록에 '없음'
    assert by_name["연세대학교"].url is not None


def test_fields_populated():
    rows = load_universities(CSV_PATH)
    r = next(x for x in rows if x.university == "연세대학교")
    assert r.campus == "신촌캠퍼스"
    assert r.region == "서울 서대문구"
    assert r.year == 2026
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/test_load_universities.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawl'`

- [ ] **Step 3: `universities.csv` 작성**

원본 `서울 상위 대학 29개.md` 기준. URL이 '없음'/'안올라옴'/메모뿐인 행은 url 빈칸.
캠퍼스·지역 값은 Task 7 스모크에서 사람이 최종 확인한다. 건국대만 2025 링크라 year=2025.

```csv
university,campus,region,year,url
서울대학교,관악캠퍼스,서울 관악구,2026,https://redduck.tistory.com/entry/2026-%EC%84%9C%EC%9A%B8%EB%8C%80%ED%95%99%EA%B5%90-%EC%B6%95%EC%A0%9C-%EC%B4%9D%EC%A0%95%EB%A6%AC%EF%BD%9C%EB%9D%BC%EC%9D%B8%EC%97%85%C2%B7%EC%9D%BC%EC%A0%95%C2%B7%EC%99%B8%EB%B6%80%EC%9D%B8-%EC%9E%85%EC%9E%A5%EA%B9%8C%EC%A7%80-%ED%95%9C%EB%88%88%EC%97%90-%EC%A0%95%EB%A6%AC
연세대학교,신촌캠퍼스,서울 서대문구,2026,https://www.wikifoodie.co.kr/news/articleView.html?idxno=12236
고려대학교,안암캠퍼스,서울 성북구,2026,
한양대학교,서울캠퍼스,서울 성동구,2026,https://memogipost.tistory.com/entry/2026-%ED%95%9C%EC%96%91%EB%8C%80-%EC%84%9C%EC%9A%B8%EC%BA%A0%ED%8D%BC%EC%8A%A4-%EC%B6%95%EC%A0%9C
건국대학교,서울캠퍼스,서울 광진구,2025,https://jcks100.com/entry/2025-%EA%B1%B4%EA%B5%AD%EB%8C%80-%EB%8C%80%ED%95%99%EC%B6%95%EC%A0%9C-%EC%B4%88%EB%8C%80%EA%B0%80%EC%88%98-%EB%9D%BC%EC%9D%B8%EC%97%85-%EB%B0%8F-%EC%8B%B8%EC%9D%B4-%EA%B3%B5%EC%97%B0-%EC%9D%BC%EC%A0%95
중앙대학교,서울캠퍼스,서울 동작구,2026,
홍익대학교,서울캠퍼스,서울 마포구,2026,https://memogipost.tistory.com/entry/2026-%ED%99%8D%EC%9D%B5%EB%8C%80%ED%95%99%EA%B5%90-%EC%84%9C%EC%9A%B8%EC%BA%A0%ED%8D%BC%EC%8A%A4%EC%B6%95%EC%A0%9C
경희대학교,서울캠퍼스,서울 동대문구,2026,https://news.comingmoney.com/entry/2026-%EA%B2%BD%ED%9D%AC%EB%8C%80%ED%95%99%EA%B5%90-%EC%B6%95%EC%A0%9C-%EB%9D%BC%EC%9D%B8%EC%97%85%EA%B3%BC-%EC%9D%BC%EC%A0%95-%EC%B4%9D%EC%A0%95%EB%A6%AC
세종대학교,서울캠퍼스,서울 광진구,2026,https://memogipost.tistory.com/entry/2026-%EC%84%B8%EC%A2%85%EB%8C%80%ED%95%99%EA%B5%90-%EB%8C%80%EB%8F%99%EC%A0%9C
성균관대학교,인문사회과학캠퍼스,서울 종로구,2026,https://memogipost.tistory.com/entry/2026-%EC%84%B1%EA%B7%A0%EA%B4%80%EB%8C%80%ED%95%99%EA%B5%90%EC%B6%95%EC%A0%9C-%EB%AC%B8%ED%96%89%EB%8C%80%EB%8F%99%EC%A0%9C
서강대학교,서울캠퍼스,서울 마포구,2026,https://memogipost.tistory.com/entry/2026-%EC%84%9C%EA%B0%95%EB%8C%80%ED%95%99%EA%B5%90-%EB%8C%80%EB%8F%99%EC%A0%9C
한국외국어대학교,서울캠퍼스,서울 동대문구,2026,
서울시립대학교,서울캠퍼스,서울 동대문구,2026,https://blog.naver.com/travelnote77/224280969490
동국대학교,서울캠퍼스,서울 중구,2026,https://schedule.comingmoney.com/entry/2026-%EB%8F%99%EA%B5%AD%EB%8C%80%ED%95%99%EA%B5%90-%EC%B6%95%EC%A0%9C-DIRVANA-%EC%9D%BC%EC%A0%95%EA%B3%BC-%EB%9D%BC%EC%9D%B8%EC%97%85-%ED%95%B5%EC%8B%AC-%EC%A0%95%EB%A6%AC
숭실대학교,서울캠퍼스,서울 동작구,2026,https://memogipost.tistory.com/entry/2026-%EC%88%AD%EC%8B%A4%EB%8C%80%ED%95%99%EA%B5%90%EC%B6%95%EC%A0%9C-%EB%8C%80%EB%8F%99%EC%A0%9C
국민대학교,서울캠퍼스,서울 성북구,2026,https://memogipost.tistory.com/entry/2026-%EA%B5%AD%EB%AF%BC%EB%8C%80%ED%95%99%EA%B5%90%EC%B6%95%EC%A0%9C-%EB%8C%80%EB%8F%99%EC%A0%9C
광운대학교,서울캠퍼스,서울 노원구,2026,https://memogipost.tistory.com/entry/2026-%EA%B4%91%EC%9A%B4%EB%8C%80%ED%95%99%EA%B5%90-%EB%8C%80%EB%8F%99%EC%A0%9C
서울과학기술대학교,서울캠퍼스,서울 노원구,2026,https://memogipost.tistory.com/entry/2026-%EC%84%9C%EC%9A%B8%EA%B3%BC%ED%95%99%EA%B8%B0%EC%88%A0%EB%8C%80%ED%95%99%EA%B5%90-%ED%9A%83%EB%B6%88%EC%A0%9C
명지대학교,인문캠퍼스,서울 서대문구,2026,https://memogipost.tistory.com/entry/2026-%EB%AA%85%EC%A7%80%EB%8C%80%ED%95%99%EA%B5%90-%EC%9D%B8%EB%AC%B8%EC%BA%A0%ED%8D%BC%EC%8A%A4-%EB%B0%B1%EB%A7%88%EB%8C%80%EB%8F%99%EC%A0%9C
상명대학교,서울캠퍼스,서울 종로구,2026,https://memogipost.tistory.com/entry/2026-%EC%83%81%EB%AA%85%EB%8C%80%ED%95%99%EA%B5%90-%EC%84%9C%EC%9A%B8%EC%BA%A0%ED%8D%BC%EC%8A%A4-%EB%8C%80%EB%8F%99%EC%A0%9C
이화여자대학교,서울캠퍼스,서울 서대문구,2026,https://towbworld.tistory.com/entry/2026-%EC%9D%B4%ED%99%94%EC%97%AC%EB%8C%80-%EC%B6%95%EC%A0%9C-%EB%9D%BC%EC%9D%B8%EC%97%85-%EC%B4%9D%EC%A0%95%EB%A6%AC%EF%BD%9CNCT-WISH%C2%B7%EC%9B%90%EC%9C%84-%EA%B3%B5%EC%97%B0%EC%8B%9C%EA%B0%84-%EC%99%B8%EB%B6%80%EC%9D%B8-%EC%9E%85%EC%9E%A5-%EC%A0%9C%ED%95%9C-%EC%95%88%EB%82%B4
숙명여자대학교,서울캠퍼스,서울 용산구,2026,
성신여자대학교,수정캠퍼스,서울 성북구,2026,
서울여자대학교,서울캠퍼스,서울 노원구,2026,https://memogipost.tistory.com/entry/2026-%EC%84%9C%EC%9A%B8%EC%97%AC%EC%9E%90%EB%8C%80%EC%B6%95%EC%A0%9C-%EB%8C%80%EB%8F%99%EC%A0%9C
동덕여자대학교,서울캠퍼스,서울 성북구,2026,
덕성여자대학교,쌍문캠퍼스,서울 도봉구,2026,https://memogipost.tistory.com/entry/2026-%EB%8D%95%EC%84%B1%EC%97%AC%EC%9E%90%EB%8C%80%ED%95%99%EA%B5%90-%EA%B7%BC%ED%99%94%EC%A0%9C
한성대학교,서울캠퍼스,서울 성북구,2026,https://memogipost.tistory.com/entry/2026-%ED%95%9C%EC%84%B1%EB%8C%80%ED%95%99%EA%B5%90-%EB%8C%80%EB%8F%99%EC%A0%9C
서경대학교,서울캠퍼스,서울 성북구,2026,
삼육대학교,서울캠퍼스,서울 노원구,2026,
```

- [ ] **Step 4: `crawl.py` 로더 구현**

```python
"""FESTA 크롤러 엔트리포인트. Task 5에서 오케스트레이션이 추가된다."""
import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class UniversityRow:
    university: str
    campus: str
    region: str
    year: int
    url: str | None


def load_universities(path: Path) -> list[UniversityRow]:
    rows: list[UniversityRow] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            url = (r.get("url") or "").strip()
            rows.append(
                UniversityRow(
                    university=r["university"].strip(),
                    campus=r["campus"].strip(),
                    region=r["region"].strip(),
                    year=int(r["year"]),
                    url=url or None,
                )
            )
    return rows
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_load_universities.py -v`
Expected: 3 passed

- [ ] **Step 6: 커밋**

```bash
git add crawler/universities.csv crawler/crawl.py crawler/tests/test_load_universities.py
git commit -m "feat: 대학 시드 29행 및 CSV 로더"
```

---

### Task 3: 본문 수집 (`fetch.py`)

**Files:**
- Create: `crawler/fetch.py`
- Create: `crawler/tests/fixtures/tistory_sample.html`
- Create: `crawler/tests/fixtures/image_only.html`
- Test: `crawler/tests/test_fetch.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `fetch.FetchResult` (dataclass) — `status: str` (`"ok" | "fetch_failed" | "empty_body"`), `body: str | None = None`, `poster_image_url: str | None = None`, `error: str | None = None`
  - `fetch.fetch_body(url: str) -> FetchResult` — robots 확인·3초 간격·수집·폴백·절단까지 전부 처리
  - (내부, 테스트 대상) `fetch.parse_html(html: str) -> tuple[str | None, str | None]` — (본문 or None, og:image or None)

- [ ] **Step 1: fixture 작성**

`crawler/tests/fixtures/tistory_sample.html`:

```html
<!doctype html>
<html>
<head>
  <meta property="og:image" content="https://example.com/poster.jpg">
  <title>2026 연세대학교 축제 총정리</title>
</head>
<body>
  <div class="tt_article_useless_p_margin">
    <p>2026 연세대학교 아카라카가 5월 21일(수)부터 5월 23일(금)까지 신촌캠퍼스 노천극장에서 열립니다.</p>
    <p>1일차 라인업: 잔나비, 10CM. 2일차 라인업: IVE, 싸이. 3일차는 시크릿 게스트로 공연 당일 공개됩니다.</p>
    <p>외부인은 사전 예매 시 입장 가능하며, 티켓은 유료입니다. 예매는 5월 7일 오픈 예정입니다.</p>
  </div>
</body>
</html>
```

`crawler/tests/fixtures/image_only.html`:

```html
<!doctype html>
<html>
<head><meta property="og:image" content="https://example.com/poster2.jpg"></head>
<body><div class="tt_article_useless_p_margin"><img src="poster.jpg"></div></body>
</html>
```

- [ ] **Step 2: 실패하는 테스트 작성**

`crawler/tests/test_fetch.py`:

```python
import time
from pathlib import Path

import fetch
from fetch import parse_html

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_html_extracts_body_and_og_image():
    body, og = parse_html(read("tistory_sample.html"))
    assert body is not None
    assert "아카라카" in body
    assert "잔나비" in body
    assert og == "https://example.com/poster.jpg"


def test_parse_html_image_only_returns_no_body():
    body, og = parse_html(read("image_only.html"))
    # 본문 100자 미만 → None (empty_body 판정은 호출부)
    assert body is None
    assert og == "https://example.com/poster2.jpg"


def test_parse_html_truncates_to_8000_chars():
    long_html = (
        '<html><body><div class="tt_article_useless_p_margin">'
        + "가나다라마바사아자차" * 2000   # 20,000자
        + "</div></body></html>"
    )
    body, _ = parse_html(long_html)
    assert body is not None
    assert len(body) <= 8000


def test_rate_limit_sleeps_between_same_host(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    fetch._LAST_REQUEST.clear()
    fetch._respect_rate_limit("example.com")   # 첫 요청: 대기 없음
    fetch._respect_rate_limit("example.com")   # 두 번째: 3초 미만 경과 → sleep
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= fetch.MIN_INTERVAL_SECONDS


def test_robots_disallowed_returns_fetch_failed(monkeypatch):
    class DenyAll:
        def can_fetch(self, ua, url):
            return False

    monkeypatch.setitem(fetch._ROBOTS, "blocked.example.com", DenyAll())
    result = fetch.fetch_body("https://blocked.example.com/entry/festival")
    assert result.status == "fetch_failed"
    assert result.error == "robots_disallowed"
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fetch'`

- [ ] **Step 4: `fetch.py` 구현**

```python
"""본문 수집: robots 확인 → 요청 간격 → 티스토리 셀렉터 → trafilatura 폴백."""
import time
from dataclasses import dataclass
from urllib import robotparser
from urllib.parse import urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

USER_AGENT = "FESTA-crawler/0.1 (festival lineup archive)"
MIN_INTERVAL_SECONDS = 3.0
TIMEOUT_SECONDS = 10
MIN_BODY_CHARS = 100
MAX_BODY_CHARS = 8000

# 티스토리 스킨별 본문 컨테이너 후보 (순차 시도)
BODY_SELECTORS = [
    ".tt_article_useless_p_margin",
    ".entry-content",
    ".article_view",
    ".contents_style",
    "article",
]

_LAST_REQUEST: dict[str, float] = {}          # host -> monotonic ts
_ROBOTS: dict[str, robotparser.RobotFileParser] = {}   # host -> parser


@dataclass
class FetchResult:
    status: str                     # ok | fetch_failed | empty_body
    body: str | None = None
    poster_image_url: str | None = None
    error: str | None = None


def _respect_rate_limit(host: str) -> None:
    last = _LAST_REQUEST.get(host)
    now = time.monotonic()
    if last is not None and now - last < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - (now - last))
    _LAST_REQUEST[host] = time.monotonic()


def _robots_allowed(url: str) -> bool:
    host = urlparse(url).netloc
    if host not in _ROBOTS:
        rp = robotparser.RobotFileParser()
        rp.set_url(f"https://{host}/robots.txt")
        try:
            rp.read()
        except OSError:
            # robots.txt 접근 불가 → 보수적으로 허용 (차단 명시가 없는 것)
            _ROBOTS[host] = None
        else:
            _ROBOTS[host] = rp
    rp = _ROBOTS[host]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def parse_html(html: str) -> tuple[str | None, str | None]:
    """(본문 텍스트 or None, og:image URL or None). 본문 100자 미만이면 None."""
    soup = BeautifulSoup(html, "html.parser")

    og = None
    meta = soup.find("meta", property="og:image")
    if meta and meta.get("content"):
        og = meta["content"].strip()

    body = None
    for selector in BODY_SELECTORS:
        node = soup.select_one(selector)
        if node:
            text = node.get_text(separator="\n", strip=True)
            if len(text) >= MIN_BODY_CHARS:
                body = text
                break

    if body is None:
        extracted = trafilatura.extract(html)
        if extracted and len(extracted) >= MIN_BODY_CHARS:
            body = extracted

    if body is not None:
        body = body[:MAX_BODY_CHARS]
    return body, og


def fetch_body(url: str) -> FetchResult:
    if not _robots_allowed(url):
        return FetchResult(status="fetch_failed", error="robots_disallowed")

    host = urlparse(url).netloc
    html = None
    last_error = None
    for _ in range(2):  # 최초 1회 + 재시도 1회
        _respect_rate_limit(host)
        try:
            resp = requests.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS
            )
            resp.raise_for_status()
            html = resp.text
            break
        except requests.RequestException as e:
            last_error = str(e)

    if html is None:
        return FetchResult(status="fetch_failed", error=last_error)

    body, og = parse_html(html)
    if body is None:
        return FetchResult(status="empty_body", poster_image_url=og)
    return FetchResult(status="ok", body=body, poster_image_url=og)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: 5 passed

- [ ] **Step 6: 커밋**

```bash
git add crawler/fetch.py crawler/tests/fixtures/ crawler/tests/test_fetch.py
git commit -m "feat: 본문 수집 모듈 (셀렉터+trafilatura 폴백, robots/간격 준수)"
```

---

### Task 4: LLM 추출 (`extract.py`)

**Files:**
- Create: `crawler/extract.py`
- Test: `crawler/tests/test_extract.py`

**Interfaces:**
- Consumes: `schema.ExtractionResult`
- Produces:
  - `extract.ExtractError(Exception)`
  - `extract.call_claude(prompt: str, timeout: int = 120) -> str` — **프로젝트 유일의 LLM 접점.** `claude -p <prompt> --output-format json` 실행, 응답 envelope의 `result` 문자열 반환. 실패 시 `ExtractError`
  - `extract.extract(body: str, university: str, year: int) -> ExtractionResult` — 검증 실패 시 1회 재시도, 최종 실패 시 `ExtractError`
  - `extract.verify(result: ExtractionResult, university: str, year: int) -> bool` — 역방향 검증 (found & 대학명 부분일치 & 연도 일치)

- [ ] **Step 1: 실패하는 테스트 작성**

`crawler/tests/test_extract.py`:

```python
import pytest

import extract
from extract import ExtractError, verify
from schema import ExtractionResult

VALID_JSON = """{
  "found": true, "university_name": "연세대학교", "year": 2026,
  "festival_name": "아카라카", "start_date": "2026-05-21", "end_date": "2026-05-23",
  "venue_name": "노천극장", "outsider_admission": "사전 예매 시 가능",
  "ticket_info": "유료",
  "lineup": [{"artist_raw": "잔나비", "day_label": "1일차",
              "date": "2026-05-21", "time": null, "is_secret": false}]
}"""


def test_extract_success(monkeypatch):
    monkeypatch.setattr(extract, "call_claude", lambda prompt, timeout=120: VALID_JSON)
    result = extract.extract("본문", "연세대학교", 2026)
    assert result.festival_name == "아카라카"
    assert result.lineup[0].artist_raw == "잔나비"


def test_extract_strips_code_fences(monkeypatch):
    fenced = "```json\n" + VALID_JSON + "\n```"
    monkeypatch.setattr(extract, "call_claude", lambda prompt, timeout=120: fenced)
    result = extract.extract("본문", "연세대학교", 2026)
    assert result.found is True


def test_extract_retries_once_then_succeeds(monkeypatch):
    responses = iter(["이건 JSON이 아님", VALID_JSON])
    calls = []

    def fake(prompt, timeout=120):
        calls.append(prompt)
        return next(responses)

    monkeypatch.setattr(extract, "call_claude", fake)
    result = extract.extract("본문", "연세대학교", 2026)
    assert result.found is True
    assert len(calls) == 2
    assert "유효하지 않았습니다" in calls[1]   # 재시도 프롬프트에 오류 피드백 포함


def test_extract_fails_after_two_attempts(monkeypatch):
    monkeypatch.setattr(extract, "call_claude", lambda prompt, timeout=120: "여전히 JSON 아님")
    with pytest.raises(ExtractError):
        extract.extract("본문", "연세대학교", 2026)


def _result(**overrides) -> ExtractionResult:
    base = {"found": True, "university_name": "연세대학교", "year": 2026}
    base.update(overrides)
    return ExtractionResult.model_validate(base)


def test_verify_pass_and_partial_name_match():
    assert verify(_result(), "연세대학교", 2026) is True
    assert verify(_result(university_name="연세대"), "연세대학교", 2026) is True


def test_verify_fails_on_mismatch():
    assert verify(_result(found=False), "연세대학교", 2026) is False
    assert verify(_result(university_name="고려대학교"), "연세대학교", 2026) is False
    assert verify(_result(year=2025), "연세대학교", 2026) is False
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/test_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'extract'`

- [ ] **Step 3: `extract.py` 구현**

```python
"""LLM 추출. call_claude()가 프로젝트 유일의 LLM 접점이다.

API 전환 시 call_claude() 내부만 Anthropic SDK 호출로 교체한다 (시그니처 불변).
"""
import json
import subprocess

from pydantic import ValidationError

from schema import ExtractionResult

CLAUDE_TIMEOUT_SECONDS = 120

PROMPT_TEMPLATE = """다음은 '{university}'의 {year}년 축제 관련 블로그 글 본문입니다.
본문에서 축제 정보를 추출해 아래 스키마의 JSON으로만 응답하세요.

규칙:
- 본문에 명시되지 않은 값은 반드시 null로 둡니다. 절대 추측하거나 지어내지 마세요.
- found: 이 글이 실제로 '{university}'의 {year}년 축제 라인업/정보 글이면 true, 아니면 false.
- artist_raw: 본문에 적힌 표기 그대로 씁니다 (정규화 금지).
- is_secret: '시크릿', '당일 공개' 등으로 표기된 미공개 출연자면 true.
- date는 YYYY-MM-DD로 정규화 가능할 때만 채웁니다.
- 설명이나 마크다운 없이 JSON 객체 하나만 출력하세요.

스키마:
{{"found": bool, "university_name": str, "year": int,
  "festival_name": str|null, "start_date": str|null, "end_date": str|null,
  "venue_name": str|null, "outsider_admission": str|null, "ticket_info": str|null,
  "lineup": [{{"artist_raw": str, "day_label": str|null, "date": str|null,
              "time": str|null, "is_secret": bool}}]}}

본문:
{body}"""


class ExtractError(Exception):
    pass


def call_claude(prompt: str, timeout: int = CLAUDE_TIMEOUT_SECONDS) -> str:
    """claude -p 헤드리스 호출. envelope JSON의 result 필드(모델 응답 텍스트)를 반환."""
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise ExtractError("claude CLI를 찾을 수 없습니다. Claude Code 설치/로그인 필요")
    except subprocess.TimeoutExpired:
        raise ExtractError(f"claude 호출 {timeout}초 타임아웃")
    if proc.returncode != 0:
        raise ExtractError(f"claude 비정상 종료: {proc.stderr[:500]}")
    try:
        envelope = json.loads(proc.stdout)
        return envelope["result"]
    except (json.JSONDecodeError, KeyError) as e:
        raise ExtractError(f"claude 응답 envelope 파싱 실패: {e}")


def _extract_json(text: str) -> str:
    """응답 텍스트에서 첫 '{'부터 마지막 '}'까지를 JSON 후보로 잘라낸다 (코드펜스 무시)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("응답에 JSON 객체가 없음")
    return text[start : end + 1]


def extract(body: str, university: str, year: int) -> ExtractionResult:
    prompt = PROMPT_TEMPLATE.format(university=university, year=year, body=body)
    last_error = None
    for attempt in range(2):  # 최초 1회 + 재시도 1회
        raw = call_claude(prompt)
        try:
            return ExtractionResult.model_validate_json(_extract_json(raw))
        except (ValueError, ValidationError) as e:
            last_error = e
            prompt = (
                PROMPT_TEMPLATE.format(university=university, year=year, body=body)
                + f"\n\n[재시도] 이전 응답이 유효하지 않았습니다: {e}\n"
                  "스키마에 정확히 맞는 JSON 객체 하나만 다시 출력하세요."
            )
    raise ExtractError(f"추출 검증 2회 실패: {last_error}")


def verify(result: ExtractionResult, university: str, year: int) -> bool:
    """역방향 검증: 추출 결과가 요청한 대학·연도의 글이 맞는지 사후 판정."""
    if not result.found:
        return False
    name_match = (
        result.university_name in university or university in result.university_name
    )
    return name_match and result.year == year
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_extract.py -v`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add crawler/extract.py crawler/tests/test_extract.py
git commit -m "feat: claude -p 추출 모듈 (검증+재시도+역방향 검증)"
```

---

### Task 5: 오케스트레이션 + 캐시 + CSV 출력 (`crawl.py` 확장)

**Files:**
- Modify: `crawler/crawl.py` (Task 2에서 만든 파일에 추가)
- Test: `crawler/tests/test_crawl.py`

**Interfaces:**
- Consumes: `fetch.fetch_body`, `fetch.FetchResult`, `extract.extract`, `extract.verify`, `extract.ExtractError`, `schema.ExtractionResult`, `crawl.UniversityRow`, `crawl.load_universities`
- Produces:
  - `crawl.process_row(row: UniversityRow, out_dir: Path) -> dict` — raw 레코드 1건 생성·캐시 (아래 형식)
  - `crawl.build_festival_row(record: dict) -> dict` — festivals.csv 1행
  - `crawl.build_lineup_rows(record: dict) -> list[dict]` — lineup.csv 0~N행 (`artist_canonical`은 일단 `artist_raw` 복사, Task 6이 갱신)
  - `crawl.write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None` — utf-8-sig
  - `crawl.run(input_csv: Path, out_dir: Path, limit: int | None = None) -> None`
  - **raw 레코드 형식** (`output/raw/<대학명>.json`, Task 6이 읽음):
    `{"university": str, "campus": str, "region": str, "year": int, "url": str|null, "flag": str, "poster_image_url": str|null, "extraction": {ExtractionResult dump}|null}`

- [ ] **Step 1: 실패하는 테스트 작성**

`crawler/tests/test_crawl.py`:

```python
import csv
import json
from pathlib import Path

import crawl
from crawl import (UniversityRow, build_festival_row, build_lineup_rows,
                   process_row, write_csv)
from fetch import FetchResult
from schema import ExtractionResult


def _row(**overrides) -> UniversityRow:
    base = dict(university="연세대학교", campus="신촌캠퍼스",
                region="서울 서대문구", year=2026, url="https://example.com/post")
    base.update(overrides)
    return UniversityRow(**base)


def _extraction() -> ExtractionResult:
    return ExtractionResult.model_validate({
        "found": True, "university_name": "연세대학교", "year": 2026,
        "festival_name": "아카라카", "start_date": "2026-05-21",
        "end_date": "2026-05-23", "venue_name": "노천극장",
        "outsider_admission": "사전 예매 시 가능", "ticket_info": "유료",
        "lineup": [
            {"artist_raw": "잔나비", "day_label": "1일차", "date": "2026-05-21"},
            {"artist_raw": "시크릿", "is_secret": True},
        ],
    })


def test_process_row_no_url(tmp_path):
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "no_source"
    assert record["extraction"] is None


def test_process_row_happy_path_writes_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(
        status="ok", body="본문" * 100, poster_image_url="https://example.com/p.jpg"))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y: _extraction())
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "ok"
    assert record["poster_image_url"] == "https://example.com/p.jpg"
    cached = json.loads((tmp_path / "raw" / "연세대학교.json").read_text("utf-8"))
    assert cached["extraction"]["festival_name"] == "아카라카"


def test_process_row_uses_cache(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    cached = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026, "url": "https://example.com/post",
              "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    (raw_dir / "연세대학교.json").write_text(json.dumps(cached), "utf-8")

    def boom(url):
        raise AssertionError("캐시가 있으면 fetch하면 안 됨")

    monkeypatch.setattr(crawl, "fetch_body", boom)
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "ok"


def test_process_row_mismatch_flag(tmp_path, monkeypatch):
    wrong = _extraction().model_copy(update={"year": 2024})
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y: wrong)
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "mismatch"
    assert record["extraction"] is not None   # 결과는 보존, 판단은 사람이


def test_build_rows():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "flag": "ok",
              "poster_image_url": "https://example.com/p.jpg",
              "extraction": _extraction().model_dump()}
    frow = build_festival_row(record)
    assert frow["festival_name"] == "아카라카"
    assert frow["flag"] == "ok"
    lrows = build_lineup_rows(record)
    assert len(lrows) == 2
    assert lrows[0]["artist_canonical"] == "잔나비"   # 초기값 = artist_raw
    assert lrows[1]["is_secret"] == "true"


def test_build_rows_without_extraction():
    record = {"university": "고려대학교", "campus": "안암캠퍼스",
              "region": "서울 성북구", "year": 2026, "url": None,
              "flag": "no_source", "poster_image_url": None, "extraction": None}
    frow = build_festival_row(record)
    assert frow["flag"] == "no_source"
    assert frow["festival_name"] == ""
    assert build_lineup_rows(record) == []


def test_write_csv_utf8_bom(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, ["a", "b"], [{"a": "한글", "b": "x"}])
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")   # BOM
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["a"] == "한글"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/test_crawl.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_festival_row' from 'crawl'`

- [ ] **Step 3: `crawl.py`에 오케스트레이션 추가**

Task 2의 로더 아래에 다음을 추가한다:

```python
import argparse
import json

from extract import ExtractError, extract, verify
from fetch import fetch_body

FESTIVAL_FIELDS = [
    "university", "campus", "region", "year", "festival_name",
    "start_date", "end_date", "venue_name", "outsider_admission",
    "ticket_info", "poster_image_url", "source_url", "flag",
]
LINEUP_FIELDS = [
    "university", "year", "festival_name", "day_label", "date", "time",
    "artist_canonical", "artist_raw", "is_secret", "source_url",
]


def process_row(row: UniversityRow, out_dir: Path) -> dict:
    """URL 1건 처리. output/raw/<대학명>.json 캐시가 있으면 그대로 반환."""
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache_path = raw_dir / f"{row.university}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    record = {
        "university": row.university, "campus": row.campus,
        "region": row.region, "year": row.year, "url": row.url,
        "flag": "no_source", "poster_image_url": None, "extraction": None,
    }
    if row.url is not None:
        fr = fetch_body(row.url)
        record["poster_image_url"] = fr.poster_image_url
        if fr.status != "ok":
            record["flag"] = fr.status
        else:
            try:
                result = extract(fr.body, row.university, row.year)
            except ExtractError:
                record["flag"] = "extract_failed"
            else:
                record["extraction"] = result.model_dump()
                record["flag"] = "ok" if verify(result, row.university, row.year) else "mismatch"

    cache_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def build_festival_row(record: dict) -> dict:
    ext = record["extraction"] or {}
    return {
        "university": record["university"], "campus": record["campus"],
        "region": record["region"], "year": record["year"],
        "festival_name": ext.get("festival_name") or "",
        "start_date": ext.get("start_date") or "",
        "end_date": ext.get("end_date") or "",
        "venue_name": ext.get("venue_name") or "",
        "outsider_admission": ext.get("outsider_admission") or "",
        "ticket_info": ext.get("ticket_info") or "",
        "poster_image_url": record["poster_image_url"] or "",
        "source_url": record["url"] or "",
        "flag": record["flag"],
    }


def build_lineup_rows(record: dict) -> list[dict]:
    ext = record["extraction"]
    if not ext:
        return []
    rows = []
    for item in ext["lineup"]:
        rows.append({
            "university": record["university"], "year": record["year"],
            "festival_name": ext.get("festival_name") or "",
            "day_label": item.get("day_label") or "",
            "date": item.get("date") or "",
            "time": item.get("time") or "",
            "artist_canonical": item["artist_raw"],   # Task 6(enrich)이 갱신
            "artist_raw": item["artist_raw"],
            "is_secret": "true" if item.get("is_secret") else "false",
            "source_url": record["url"] or "",
        })
    return rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(input_csv: Path, out_dir: Path, limit: int | None = None) -> None:
    rows = load_universities(input_csv)
    if limit:
        rows = rows[:limit]
    festival_rows, lineup_rows = [], []
    for i, row in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {row.university} ...", flush=True)
        record = process_row(row, out_dir)
        print(f"  -> {record['flag']}", flush=True)
        festival_rows.append(build_festival_row(record))
        lineup_rows.extend(build_lineup_rows(record))
    write_csv(out_dir / "festivals.csv", FESTIVAL_FIELDS, festival_rows)
    write_csv(out_dir / "lineup.csv", LINEUP_FIELDS, lineup_rows)
    print(f"완료: festivals {len(festival_rows)}행, lineup {len(lineup_rows)}행")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FESTA 크롤러 v1")
    parser.add_argument("--input", type=Path, default=Path("universities.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--limit", type=int, default=None, help="앞에서 N행만 처리 (스모크용)")
    args = parser.parse_args()
    run(args.input, args.output_dir, args.limit)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_crawl.py -v`
Expected: 7 passed. 전체도 확인: `.venv/bin/pytest -v` → 이전 태스크 포함 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add crawler/crawl.py crawler/tests/test_crawl.py
git commit -m "feat: 크롤러 오케스트레이션 (캐시, 플래그, CSV 3열 중 2종 출력)"
```

---

### Task 6: 아티스트 정규화 + 마스터 (`enrich.py`)

**Files:**
- Create: `crawler/enrich.py`
- Test: `crawler/tests/test_enrich.py`

**Interfaces:**
- Consumes: `extract.call_claude`, `extract.ExtractError`, `schema.EnrichResult`, `schema.ArtistMaster`, `crawl.write_csv`, `crawl.LINEUP_FIELDS`, raw 레코드 형식(Task 5), `output/lineup.csv`
- Produces:
  - `enrich.collect_raw_names(out_dir: Path) -> list[str]` — raw/*.json에서 `is_secret=False`인 `artist_raw` 유니크·정렬 목록
  - `enrich.normalize(names: list[str]) -> EnrichResult` — LLM 1콜 (call_claude 재사용, 검증 실패 시 1회 재시도)
  - `enrich.enrich(out_dir: Path) -> None` — lineup.csv의 `artist_canonical` 갱신 + artists.csv 생성
  - **artists.csv 컬럼**: `name_canonical, name_en, real_name, category, aliases, needs_review` (aliases는 `;` 연결)

- [ ] **Step 1: 실패하는 테스트 작성**

`crawler/tests/test_enrich.py`:

```python
import csv
import json
from pathlib import Path

import enrich
from crawl import LINEUP_FIELDS, write_csv
from schema import EnrichResult

ENRICH_JSON = """{
  "mapping": {"십센치": "10CM", "잔나비": "잔나비"},
  "artists": [
    {"name_canonical": "10CM", "name_en": "10CM", "real_name": "권정열",
     "category": "가수", "aliases": ["십센치"], "needs_review": false},
    {"name_canonical": "잔나비", "name_en": "JANNABI", "real_name": null,
     "category": "밴드", "aliases": [], "needs_review": false}
  ]
}"""


def _seed_output(out_dir: Path) -> None:
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "연세대학교.json").write_text(json.dumps({
        "university": "연세대학교", "campus": "신촌캠퍼스", "region": "서울 서대문구",
        "year": 2026, "url": "https://example.com/post", "flag": "ok",
        "poster_image_url": None,
        "extraction": {
            "found": True, "university_name": "연세대학교", "year": 2026,
            "festival_name": "아카라카", "start_date": None, "end_date": None,
            "venue_name": None, "outsider_admission": None, "ticket_info": None,
            "lineup": [
                {"artist_raw": "십센치", "day_label": "1일차", "date": None,
                 "time": None, "is_secret": False},
                {"artist_raw": "잔나비", "day_label": "1일차", "date": None,
                 "time": None, "is_secret": False},
                {"artist_raw": "시크릿", "day_label": "2일차", "date": None,
                 "time": None, "is_secret": True},
            ],
        },
    }, ensure_ascii=False), "utf-8")
    write_csv(out_dir / "lineup.csv", LINEUP_FIELDS, [
        {"university": "연세대학교", "year": 2026, "festival_name": "아카라카",
         "day_label": "1일차", "date": "", "time": "",
         "artist_canonical": "십센치", "artist_raw": "십센치",
         "is_secret": "false", "source_url": "https://example.com/post"},
    ])


def test_collect_raw_names_dedup_and_skip_secret(tmp_path):
    _seed_output(tmp_path)
    names = enrich.collect_raw_names(tmp_path)
    assert names == ["십센치", "잔나비"]   # 정렬됨, '시크릿'(is_secret) 제외


def test_normalize_parses_llm_response(monkeypatch):
    monkeypatch.setattr(enrich, "call_claude", lambda prompt, timeout=120: ENRICH_JSON)
    result = enrich.normalize(["십센치", "잔나비"])
    assert isinstance(result, EnrichResult)
    assert result.mapping["십센치"] == "10CM"


def test_enrich_updates_lineup_and_writes_artists(tmp_path, monkeypatch):
    _seed_output(tmp_path)
    monkeypatch.setattr(enrich, "call_claude", lambda prompt, timeout=120: ENRICH_JSON)
    enrich.enrich(tmp_path)

    with open(tmp_path / "lineup.csv", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["artist_canonical"] == "10CM"
    assert rows[0]["artist_raw"] == "십센치"     # 원문 표기는 보존

    with open(tmp_path / "artists.csv", newline="", encoding="utf-8-sig") as f:
        artists = {r["name_canonical"]: r for r in csv.DictReader(f)}
    assert artists["10CM"]["real_name"] == "권정열"
    assert artists["10CM"]["aliases"] == "십센치"
    assert artists["잔나비"]["needs_review"] == "false"


def test_enrich_no_names_is_noop(tmp_path, monkeypatch):
    (tmp_path / "raw").mkdir(parents=True)

    def boom(prompt, timeout=120):
        raise AssertionError("아티스트가 없으면 LLM을 호출하면 안 됨")

    monkeypatch.setattr(enrich, "call_claude", boom)
    enrich.enrich(tmp_path)   # 예외 없이 종료
    assert not (tmp_path / "artists.csv").exists()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/test_enrich.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'enrich'`

- [ ] **Step 3: `enrich.py` 구현**

```python
"""후처리: 아티스트 표기 정규화 + 마스터 생성 (LLM 1콜)."""
import argparse
import csv
import json
from pathlib import Path

from pydantic import ValidationError

from crawl import LINEUP_FIELDS, write_csv
from extract import ExtractError, call_claude
from schema import EnrichResult

ARTIST_FIELDS = ["name_canonical", "name_en", "real_name", "category",
                 "aliases", "needs_review"]

PROMPT_TEMPLATE = """다음은 대학 축제 라인업에서 추출한 아티스트 표기 목록입니다.
당신이 아는 지식으로 각 표기를 정식 활동명으로 정규화하고, 아티스트 마스터 정보를 만드세요.

규칙:
- 같은 아티스트의 다른 표기는 하나의 name_canonical로 묶습니다 (예: "십센치" → "10CM").
- 모르는 이름이거나 확실하지 않으면 name_canonical에 원문 표기를 그대로 쓰고
  needs_review를 true로 표시하세요. 절대 추측으로 채우지 마세요.
- mapping에는 입력 목록의 모든 표기가 키로 들어가야 합니다.
- 설명 없이 JSON 객체 하나만 출력하세요.

스키마:
{{"mapping": {{"원문표기": "정식표기"}},
  "artists": [{{"name_canonical": str, "name_en": str|null, "real_name": str|null,
               "category": str|null, "aliases": [str], "needs_review": bool}}]}}

아티스트 표기 목록:
{names}"""


def collect_raw_names(out_dir: Path) -> list[str]:
    names: set[str] = set()
    for path in sorted((out_dir / "raw").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        ext = record.get("extraction")
        if not ext:
            continue
        for item in ext["lineup"]:
            if not item.get("is_secret"):
                names.add(item["artist_raw"])
    return sorted(names)


def normalize(names: list[str]) -> EnrichResult:
    prompt = PROMPT_TEMPLATE.format(names="\n".join(f"- {n}" for n in names))
    last_error = None
    for attempt in range(2):
        raw = call_claude(prompt)
        start, end = raw.find("{"), raw.rfind("}")
        try:
            return EnrichResult.model_validate_json(raw[start : end + 1])
        except (ValidationError, ValueError) as e:
            last_error = e
            prompt += f"\n\n[재시도] 이전 응답이 유효하지 않았습니다: {e}\nJSON만 다시 출력하세요."
    raise ExtractError(f"정규화 검증 2회 실패: {last_error}")


def enrich(out_dir: Path) -> None:
    names = collect_raw_names(out_dir)
    if not names:
        print("정규화할 아티스트 없음 — 건너뜀")
        return
    result = normalize(names)

    # lineup.csv의 artist_canonical 갱신 (매핑에 없는 표기는 원문 유지)
    lineup_path = out_dir / "lineup.csv"
    if lineup_path.exists():
        with open(lineup_path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            row["artist_canonical"] = result.mapping.get(
                row["artist_raw"], row["artist_raw"]
            )
        write_csv(lineup_path, LINEUP_FIELDS, rows)

    artist_rows = [{
        "name_canonical": a.name_canonical,
        "name_en": a.name_en or "",
        "real_name": a.real_name or "",
        "category": a.category or "",
        "aliases": ";".join(a.aliases),
        "needs_review": "true" if a.needs_review else "false",
    } for a in result.artists]
    write_csv(out_dir / "artists.csv", ARTIST_FIELDS, artist_rows)
    print(f"완료: artists {len(artist_rows)}행, needs_review "
          f"{sum(1 for a in result.artists if a.needs_review)}건")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="아티스트 정규화/마스터 생성")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    args = parser.parse_args()
    enrich(args.output_dir)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_enrich.py -v`
Expected: 4 passed. 전체: `.venv/bin/pytest` → 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add crawler/enrich.py crawler/tests/test_enrich.py
git commit -m "feat: 아티스트 정규화 및 마스터 생성 (LLM 1콜 후처리)"
```

---

### Task 7: 실전 스모크 — 로드맵 1주차 검증

**Files:**
- Modify: `crawler/universities.csv` (스모크 중 캠퍼스·지역 오류 발견 시)

**Interfaces:**
- Consumes: 전체 파이프라인
- Produces: `output/festivals.csv`, `output/lineup.csv`, `output/artists.csv` + 검증 결과 보고

이 태스크는 자동 테스트가 아니라 **실제 실행 + 사람 확인**이다. LLM 호출과 실제 HTTP가 발생하므로 Claude Code 로그인 상태와 네트워크가 필요하다.

- [ ] **Step 1: 3건 스모크**

Run: `.venv/bin/python crawl.py --limit 3`
Expected: 3행 처리 로그, `output/raw/`에 JSON 3개, `output/festivals.csv`·`output/lineup.csv` 생성.
고려대학교(URL 없음)는 `no_source`로 기록되는지 확인.

- [ ] **Step 2: 전체 29건 실행**

Run: `.venv/bin/python crawl.py`
Expected: 캐시 덕에 앞 3건은 즉시 스킵. 오류로 중단되지 않고 29행 완주.

- [ ] **Step 3: 정규화 실행**

Run: `.venv/bin/python enrich.py`
Expected: `output/artists.csv` 생성, needs_review 건수 출력.

- [ ] **Step 4: 사람 검증 (기록 남기기)**

`output/festivals.csv`를 열어 다음을 집계해 사용자에게 보고:
- flag별 건수 (ok / fetch_failed / empty_body / extract_failed / mismatch / no_source)
- `ok` 중 2~3건을 골라 원본 블로그와 대조 — 라인업 누락·환각 여부
- `universities.csv`의 캠퍼스·지역 값 오류 발견 시 수정
- 이 수치가 파이프라인 문서 로드맵 1주차의 "본문 추출 성공률·LLM 정확도 확정"이다

- [ ] **Step 5: 커밋 (수정분이 있을 때만)**

```bash
git add crawler/universities.csv
git commit -m "chore: 스모크 검증 반영 (대학 시드 수정)"
```

---

## Self-Review 결과 (계획 작성 후 점검)

- **스펙 커버리지**: 스펙 4장(파일 구성)→Task 1~6, 5장(데이터 흐름 1~10단계)→Task 3(1~5단계 중 수집)·Task 4(6~7)·Task 5(1,8,10)·Task 6(9), 6장(스키마 3종)→Task 1·5·6, 7장(LLM 규약)→Task 4, 8장(준수사항)→Task 3, 9장(에러 처리)→Task 3~5, 10장(테스트)→각 태스크+Task 7. 누락 없음.
- **플레이스홀더**: 없음 — 모든 코드·테스트·fixture 실제 내용 포함.
- **타입 일관성**: `ExtractionResult`/`FetchResult`/`UniversityRow`/raw 레코드 형식이 Task 간 Interfaces 블록과 일치함을 확인.
