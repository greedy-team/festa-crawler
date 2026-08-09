import time
from pathlib import Path

import fetch
from fetch import parse_html

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_html_extracts_body_and_og_image():
    body, og, images = parse_html(read("tistory_sample.html"))
    assert body is not None
    assert "아카라카" in body
    assert "잔나비" in body
    assert og == "https://example.com/poster.jpg"


def test_parse_html_image_only_returns_no_body():
    body, og, images = parse_html(read("image_only.html"))
    # 본문 100자 미만 → None (empty_body 판정은 호출부)
    assert body is None
    assert og == "https://example.com/poster2.jpg"


def test_parse_html_truncates_to_8000_chars():
    long_html = (
        '<html><body><div class="tt_article_useless_p_margin">'
        + "가나다라마바사아자차" * 2000   # 20,000자
        + "</div></body></html>"
    )
    body, _, _ = parse_html(long_html)
    assert body is not None
    assert len(body) <= 8000


def test_parse_html_collects_body_images():
    html = ('<div class="entry-content">' + "본문" * 60
            + '<img src="https://cdn.example.com/a.jpg">'
            + '<img data-src="/relative/b.jpg">'
            + '<img src="https://cdn.example.com/a.jpg">'   # 중복
            + '<img src="">'
            + "</div>")
    body, og, images = parse_html(html, base_url="https://blog.example.com/post")
    assert images == ["https://cdn.example.com/a.jpg",
                      "https://blog.example.com/relative/b.jpg"]


def test_parse_html_caps_images_at_five():
    imgs = "".join(f'<img src="https://cdn.example.com/{i}.jpg">' for i in range(8))
    html = '<div class="entry-content">' + "본문" * 60 + imgs + "</div>"
    _, _, images = parse_html(html, base_url="https://blog.example.com/")
    assert len(images) == 5


def test_parse_html_fallback_has_no_images(monkeypatch):
    # 셀렉터가 못 잡아 trafilatura 폴백으로 본문을 얻은 경우 이미지는 빈 리스트
    monkeypatch.setattr(fetch.trafilatura, "extract", lambda html: "본문" * 60)
    html = "<p>" + "본문" * 60 + '<img src="https://cdn.example.com/a.jpg"></p>'
    body, og, images = parse_html(html)
    assert body is not None
    assert images == []


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


def test_instagram_candidates_excludes_embed_script():
    html = (
        '<script async src="//www.instagram.com/embed.js"></script>'
        '<a href="https://www.instagram.com/hyu_festival/">계정</a>'
    )
    assert fetch.instagram_candidates(html) == ["hyu_festival"]


def test_instagram_candidates_rejects_lookalike_domain():
    assert fetch.instagram_candidates('<a href="https://notinstagram.com/evil">x</a>') == []


def test_instagram_candidates_keeps_dotted_handles():
    html = '<a href="https://www.instagram.com/smu.festival/">상명대</a>'
    assert fetch.instagram_candidates(html) == ["smu.festival"]


def test_fetch_text_returns_body(monkeypatch):
    monkeypatch.setattr(fetch, "_robots_allowed", lambda url: True)
    monkeypatch.setattr(fetch, "_respect_rate_limit", lambda host: None)

    class Resp:
        text = "<urlset><loc>https://blog.example.com/entry/x</loc></urlset>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fetch.requests, "get", lambda url, **kw: Resp())
    assert "urlset" in fetch.fetch_text("https://blog.example.com/sitemap.xml")


def test_fetch_text_returns_none_when_robots_disallows(monkeypatch):
    monkeypatch.setattr(fetch, "_robots_allowed", lambda url: False)

    def boom(url, **kw):
        raise AssertionError("robots가 막으면 요청하면 안 됨")

    monkeypatch.setattr(fetch.requests, "get", boom)
    assert fetch.fetch_text("https://blog.example.com/sitemap.xml") is None


def test_fetch_text_returns_none_on_request_error(monkeypatch):
    monkeypatch.setattr(fetch, "_robots_allowed", lambda url: True)
    monkeypatch.setattr(fetch, "_respect_rate_limit", lambda host: None)

    def boom(url, **kw):
        raise fetch.requests.RequestException("timeout")

    monkeypatch.setattr(fetch.requests, "get", boom)
    assert fetch.fetch_text("https://blog.example.com/sitemap.xml") is None


def test_fetch_text_respects_rate_limit(monkeypatch):
    hosts = []
    monkeypatch.setattr(fetch, "_robots_allowed", lambda url: True)
    monkeypatch.setattr(fetch, "_respect_rate_limit", hosts.append)

    class Resp:
        text = "ok"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fetch.requests, "get", lambda url, **kw: Resp())
    fetch.fetch_text("https://blog.example.com/sitemap.xml")
    assert hosts == ["blog.example.com"]
