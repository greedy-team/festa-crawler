"""본문 수집: robots 확인 → 요청 간격 → 티스토리 셀렉터 → trafilatura 폴백."""
import re
import time
from dataclasses import dataclass, field
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

_IG_HANDLE = re.compile(r"(?:^|[/.\"'\s])(?:www\.)?instagram\.com/([A-Za-z0-9_.]{2,30})")
_IG_NON_HANDLES = {"p", "reel", "reels", "explore", "accounts", "stories", "share"}
_IG_FILE_SUFFIXES = ("js", "css", "json", "png", "jpg", "jpeg", "gif", "svg", "ico", "html")

_LAST_REQUEST: dict[str, float] = {}          # host -> monotonic ts
_ROBOTS: dict[str, robotparser.RobotFileParser] = {}   # host -> parser


@dataclass
class FetchResult:
    status: str                     # ok | fetch_failed | empty_body
    body: str | None = None
    poster_image_url: str | None = None
    error: str | None = None
    instagram_candidates: list[str] = field(default_factory=list)


def _respect_rate_limit(host: str) -> None:
    last = _LAST_REQUEST.get(host)
    now = time.monotonic()
    if last is not None and now - last < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - (now - last))
    _LAST_REQUEST[host] = time.monotonic()


def _robots_allowed(url: str) -> bool:
    host = urlparse(url).netloc
    if host not in _ROBOTS:
        try:
            resp = requests.get(
                f"https://{host}/robots.txt",
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT_SECONDS,
            )
            if resp.status_code >= 400:
                _ROBOTS[host] = None          # robots.txt 없음/접근불가 → 명시 차단 없음으로 간주
            else:
                rp = robotparser.RobotFileParser()
                rp.parse(resp.text.splitlines())
                _ROBOTS[host] = rp
        except requests.RequestException:
            _ROBOTS[host] = None
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


def instagram_candidates(html: str) -> list[str]:
    """HTML에서 인스타그램 계정 핸들 후보를 등장순·중복제거로 추출한다."""
    found: list[str] = []
    for match in _IG_HANDLE.finditer(html):
        handle = match.group(1).lower().rstrip(".")
        if handle.rsplit(".", 1)[-1] in _IG_FILE_SUFFIXES:
            continue          # embed.js, static.css 등 파일명은 핸들이 아니다
        if handle in _IG_NON_HANDLES or handle in found:
            continue
        found.append(handle)
    return found


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
    candidates = instagram_candidates(html)
    if body is None:
        return FetchResult(status="empty_body", poster_image_url=og, instagram_candidates=candidates)
    return FetchResult(status="ok", body=body, poster_image_url=og, instagram_candidates=candidates)
