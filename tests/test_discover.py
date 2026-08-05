import json
from urllib.parse import quote

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


def test_discover_cached_returns_none_on_failure(tmp_path, monkeypatch):
    def boom(prompt, timeout=120, tools=""):
        raise ExtractError("세션 한도")

    monkeypatch.setattr(discover, "call_claude", boom)
    assert discover.discover_cached("한양대학교", 2026, tmp_path) is None
    assert not (tmp_path / "discovered" / "한양대학교.json").exists()   # 실패는 캐시 안 함


def test_discover_blocks_subdomains_and_ports(monkeypatch):
    payload = """{"candidates": [
      {"url": "https://m.search.naver.com/search.naver?query=x"},
      {"url": "https://namu.wiki:443/w/test"},
      {"url": "https://www.google.com/search?q=x"},
      {"url": "https://blog.example.com/ok"}
    ]}"""
    monkeypatch.setattr(discover, "call_claude", lambda p, timeout=120, tools="": payload)
    assert discover.discover("한양대학교", 2026) == ["https://blog.example.com/ok"]


def test_discover_keeps_lookalike_domain(monkeypatch):
    # 접미사 규칙이 과하게 잡지 않는지 — notnamu.wiki는 namu.wiki가 아니다
    payload = '{"candidates": [{"url": "https://notnamu.wiki/article"}]}'
    monkeypatch.setattr(discover, "call_claude", lambda p, timeout=120, tools="": payload)
    assert discover.discover("한양대학교", 2026) == ["https://notnamu.wiki/article"]


def test_discover_blocks_instagram_and_youtube(monkeypatch):
    payload = """{"candidates": [
      {"url": "https://www.instagram.com/hyu_festival/"},
      {"url": "https://instagram.com/p/ABC123/"},
      {"url": "https://m.youtube.com/watch?v=xyz"},
      {"url": "https://youtu.be/xyz"},
      {"url": "https://www.newshyu.com/news/articleView.html?idxno=1"}
    ]}"""
    monkeypatch.setattr(discover, "call_claude", lambda p, timeout=120, tools="": payload)
    assert discover.discover("한양대학교", 2026) == [
        "https://www.newshyu.com/news/articleView.html?idxno=1"
    ]


def test_discover_prompt_tells_llm_to_skip_unreadable_sources(monkeypatch):
    captured = {}

    def fake(prompt, timeout=120, tools=""):
        captured["prompt"] = prompt
        return '{"candidates": []}'

    monkeypatch.setattr(discover, "call_claude", fake)
    discover.discover("한양대학교", 2026)
    assert "인스타그램" in captured["prompt"]
    assert "유튜브" in captured["prompt"]


def _sitemap(*slugs: str) -> str:
    """실제 사이트맵처럼 퍼센트 인코딩된 <loc> 목록을 만든다."""
    locs = "".join(
        f"<loc>https://blog.example.com/entry/{quote(s)}</loc>" for s in slugs
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset>{locs}</urlset>'


def test_discover_sitemap_strict_match_only(monkeypatch):
    xml = _sitemap(
        "2026-고려대학교-대동제",
        "2026-고려대-과학기술대학-대동제",     # 어간 — 다른 캠퍼스
        "2026-서울대공원-장미원축제",           # 유사 명칭
    )
    monkeypatch.setattr(discover, "_sitemap_urls", None)
    monkeypatch.setattr(discover, "SITEMAP_SOURCES", ("https://blog.example.com/sitemap.xml",))
    monkeypatch.setattr(discover, "fetch_text", lambda url: xml)
    urls = discover.discover_sitemap("고려대학교", 2026)
    assert len(urls) == 1
    assert "고려대학교-대동제" in urls[0]


def test_discover_sitemap_filters_year(monkeypatch):
    xml = _sitemap("2025-고려대학교-대동제", "2026-고려대학교-대동제")
    monkeypatch.setattr(discover, "_sitemap_urls", None)
    monkeypatch.setattr(discover, "SITEMAP_SOURCES", ("https://blog.example.com/sitemap.xml",))
    monkeypatch.setattr(discover, "fetch_text", lambda url: xml)
    urls = discover.discover_sitemap("고려대학교", 2026)
    assert len(urls) == 1
    assert "2026" in urls[0]


def test_discover_sitemap_skips_non_entry_urls(monkeypatch):
    xml = ('<?xml version="1.0"?><urlset>'
           '<loc>https://blog.example.com/category/2026-고려대학교</loc>'
           '<loc>https://blog.example.com/entry/2026-고려대학교-대동제</loc>'
           '</urlset>')
    monkeypatch.setattr(discover, "_sitemap_urls", None)
    monkeypatch.setattr(discover, "SITEMAP_SOURCES", ("https://blog.example.com/sitemap.xml",))
    monkeypatch.setattr(discover, "fetch_text", lambda url: xml)
    urls = discover.discover_sitemap("고려대학교", 2026)
    assert urls == ["https://blog.example.com/entry/2026-고려대학교-대동제"]


def test_discover_sitemap_applies_blocked_domains(monkeypatch):
    xml = ('<?xml version="1.0"?><urlset>'
           '<loc>https://namu.wiki/entry/2026-고려대학교-대동제</loc>'
           '<loc>https://blog.example.com/entry/2026-고려대학교-대동제</loc>'
           '</urlset>')
    monkeypatch.setattr(discover, "_sitemap_urls", None)
    monkeypatch.setattr(discover, "SITEMAP_SOURCES", ("https://blog.example.com/sitemap.xml",))
    monkeypatch.setattr(discover, "fetch_text", lambda url: xml)
    urls = discover.discover_sitemap("고려대학교", 2026)
    assert urls == ["https://blog.example.com/entry/2026-고려대학교-대동제"]


def test_discover_sitemap_fetches_once_per_process(monkeypatch):
    calls = []
    xml = _sitemap("2026-고려대학교-대동제", "2026-연세대학교-무악대동제")
    monkeypatch.setattr(discover, "_sitemap_urls", None)
    monkeypatch.setattr(discover, "SITEMAP_SOURCES", ("https://blog.example.com/sitemap.xml",))

    def fake(url):
        calls.append(url)
        return xml

    monkeypatch.setattr(discover, "fetch_text", fake)
    assert discover.discover_sitemap("고려대학교", 2026)
    assert discover.discover_sitemap("연세대학교", 2026)
    assert len(calls) == 1          # 두 번째 조회는 메모리 캐시


def test_discover_sitemap_skips_failed_source(monkeypatch):
    xml = _sitemap("2026-고려대학교-대동제")
    monkeypatch.setattr(discover, "_sitemap_urls", None)
    monkeypatch.setattr(discover, "SITEMAP_SOURCES", ("https://dead.example.com/sitemap.xml",
                                                     "https://blog.example.com/sitemap.xml"))
    monkeypatch.setattr(
        discover, "fetch_text", lambda url: None if "dead" in url else xml
    )
    urls = discover.discover_sitemap("고려대학교", 2026)
    assert len(urls) == 1           # 죽은 소스는 건너뛰고 나머지로 진행


def test_discover_sitemap_all_sources_fail_returns_empty(monkeypatch):
    monkeypatch.setattr(discover, "_sitemap_urls", None)
    monkeypatch.setattr(discover, "SITEMAP_SOURCES", ("https://dead.example.com/sitemap.xml",))
    monkeypatch.setattr(discover, "fetch_text", lambda url: None)
    assert discover.discover_sitemap("고려대학교", 2026) == []


def test_discover_sitemap_malformed_xml_does_not_raise(monkeypatch):
    monkeypatch.setattr(discover, "_sitemap_urls", None)
    monkeypatch.setattr(discover, "SITEMAP_SOURCES", ("https://blog.example.com/sitemap.xml",))
    monkeypatch.setattr(discover, "fetch_text", lambda url: "<urlset><loc>잘린")
    assert discover.discover_sitemap("고려대학교", 2026) == []
