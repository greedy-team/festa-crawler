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
