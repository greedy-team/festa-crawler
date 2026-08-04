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
