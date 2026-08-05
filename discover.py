"""후보 URL 탐색: claude의 WebSearch 도구로 검색해 URL 후보만 모은다.

fetch.py와 같은 원칙 — 후보를 모으기만 하고 "이 글이 맞는 글인가"는 판단하지 않는다.
그 판정은 crawl이 extract → verify로 수행한다.
"""
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from pydantic import ValidationError

from extract import ExtractError, _extract_json, call_claude
from fetch import fetch_text
from schema import DiscoverResult

DISCOVER_TIMEOUT_SECONDS = 300   # 실측 63초 + 검색 왕복 여유
MAX_CANDIDATES = 3

# robots·라이선스상 쓸 수 없거나 본문을 읽을 수 없는 곳. 검색 결과에 섞여 나오므로 여기서 뺀다.
# 서브도메인도 함께 막는다 (m.search.naver.com 등).
BLOCKED_DOMAINS = frozenset({
    "namu.wiki",            # CC BY-NC-SA(비영리) + Cloudflare 봇 방어
    "google.com", "search.naver.com",   # 검색 결과 페이지 자체
    "instagram.com",        # robots 전면 차단 — fetch가 확정 실패한다
    "youtube.com", "youtu.be",   # 영상이라 추출할 본문이 없다
})

# 이미 출처로 쓰고 있는 블로그들의 사이트맵. robots.txt가 /search는 막지만 sitemap.xml은 막지 않는다.
SITEMAP_SOURCES = (
    "https://memogipost.tistory.com/sitemap.xml",
    "https://news.comingmoney.com/sitemap.xml",
    "https://schedule.comingmoney.com/sitemap.xml",
    "https://jcks100.com/sitemap.xml",
    "https://towbworld.tistory.com/sitemap.xml",
)

_LOC = re.compile(r"<loc>(.*?)</loc>", re.DOTALL)
_sitemap_urls: list[str] | None = None      # 프로세스 1회 로드 (디스크 캐시 아님)

PROMPT_TEMPLATE = """'{university}'의 {year}년 대학 축제 라인업을 다룬 웹 문서를 검색해서,
실제로 접근 가능한 URL만 골라 JSON으로 알려주세요.

규칙:
- 웹 검색 결과에 실제로 나온 URL만 씁니다. 절대 URL을 지어내지 마세요.
- '{university}'의 {year}년 축제를 다룬 문서만 고릅니다. 다른 대학이나 다른 연도는 제외합니다.
- 라인업·출연 가수·축제 일정을 다루는 문서를 우선합니다.
- 인스타그램·유튜브는 본문 텍스트를 읽을 수 없으므로 제외하고, 글로 된 문서만 고릅니다.
- 관련성이 높은 순서로 최대 8개까지.
- 설명이나 마크다운 없이 JSON 객체 하나만 출력하세요.

형식:
{{"candidates": [{{"url": "https://...", "title": "문서 제목"}}]}}"""


def _is_blocked(url: str) -> bool:
    host = urlparse(url).netloc.lower().rsplit("@", 1)[-1].split(":")[0]
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)


def _load_sitemap_urls() -> list[str]:
    """대상 사이트맵에서 글 URL을 모은다. 프로세스 안에서 1회만 받는다.

    디스크에 캐시하지 않는다 — 새 글이 계속 올라와 재실행하면 달라지는 상태다.
    소스 하나가 실패하면 그 소스만 건너뛴다.
    """
    global _sitemap_urls
    if _sitemap_urls is not None:
        return _sitemap_urls
    urls: list[str] = []
    for source in SITEMAP_SOURCES:
        xml = fetch_text(source)
        if xml is None:
            print(f"  사이트맵 수집 실패: {source}", flush=True)
            continue
        for raw in _LOC.findall(xml):
            loc = unquote(raw.strip())
            if "/entry/" in loc:
                urls.append(loc)
    _sitemap_urls = urls
    return urls


def discover_sitemap(university: str, year: int) -> list[str]:
    """사이트맵에서 대학 정식 표기와 연도가 모두 든 글 URL을 등장순으로 반환한다.

    엄격 매칭이다 — 어간('고려대')·줄임말('고대')은 쓰지 않는다. 실측에서 '성대'가
    경성대·한성대를, '연대'가 경연대회를 잡았고, 어간은 다른 캠퍼스 글을 끌어왔다.
    관련성 판정은 하지 않는다. '서울대공원' 같은 오탐은 verify가 걸러낸다.
    """
    return [
        url
        for url in _load_sitemap_urls()
        if university in url and str(year) in url and not _is_blocked(url)
    ]


def discover(university: str, year: int) -> list[str]:
    """검색으로 후보 URL을 찾는다. 차단 도메인은 제외하고 등장순으로 반환."""
    prompt = PROMPT_TEMPLATE.format(university=university, year=year)
    raw = call_claude(prompt, timeout=DISCOVER_TIMEOUT_SECONDS, tools="WebSearch")
    try:
        result = DiscoverResult.model_validate_json(_extract_json(raw))
    except (ValueError, ValidationError) as e:
        raise ExtractError(f"탐색 응답 파싱 실패: {e}")
    return [c.url for c in result.candidates if not _is_blocked(c.url)]


def discover_cached(university: str, year: int, out_dir: Path) -> list[str] | None:
    """탐색 결과 캐시 래퍼. 탐색 1건이 60초 이상 걸려 캐시가 필수다.

    반환값: 후보 목록(정당한 0건이면 빈 리스트), 탐색 자체가 실패했으면 None.
    None은 "이 결과를 캐시하지 말고 다음 실행에서 다시 시도하라"는 신호다.
    """
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
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {"university": university, "year": year, "candidates": urls},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return urls
