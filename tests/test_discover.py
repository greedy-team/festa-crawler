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
