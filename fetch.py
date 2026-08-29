"""본문 수집: robots 확인 → 요청 간격 → 티스토리 셀렉터 → trafilatura 폴백."""
import re
import time
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

USER_AGENT = "FESTA-crawler/0.1 (festival lineup archive)"
MIN_INTERVAL_SECONDS = 3.0
TIMEOUT_SECONDS = 10
MIN_BODY_CHARS = 100
MAX_BODY_CHARS = 8000
MAX_BODY_IMAGES = 5

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
    image_urls: list[str] = field(default_factory=list)


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


def _decode(resp: "requests.Response") -> str:
    """응답 본문을 문서가 실제로 쓴 인코딩으로 읽는다.

    Content-Type에 charset이 없으면 requests는 RFC 2616대로 ISO-8859-1을 쓰고
    HTML·XML이 선언한 인코딩은 보지 않는다. 한국어 본문이 통째로 깨진 채 다음
    단계로 넘어가며, 오류가 아니라 값이 비는 형태로만 드러난다.
    서버가 charset을 밝힌 경우에는 그 선언을 존중한다.
    """
    if "charset" not in resp.headers.get("Content-Type", "").lower():
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def fetch_text(url: str) -> str | None:
    """robots·요청 간격을 지켜 응답 본문을 문자열로 가져온다. 실패하면 None.

    HTML 파싱을 하지 않는다 — sitemap.xml처럼 구조화 문서를 그대로 받을 때 쓴다.
    재시도하지 않는다: 호출자가 실패를 폴백 신호로 쓴다.
    """
    if not _robots_allowed(url):
        return None
    _respect_rate_limit(urlparse(url).netloc)
    try:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        return _decode(resp)
    except requests.RequestException:
        return None


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
            html = _decode(resp)
            break
        except requests.RequestException as e:
            last_error = str(e)

    if html is None:
        return FetchResult(status="fetch_failed", error=last_error)

    body, og, images = parse_html(html, base_url=url)
    candidates = instagram_candidates(html)
    if body is None:
        return FetchResult(status="empty_body", poster_image_url=og, instagram_candidates=candidates)
    return FetchResult(status="ok", body=body, poster_image_url=og,
                       image_urls=images, instagram_candidates=candidates)
