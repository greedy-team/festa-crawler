#!/usr/bin/env python3
"""ISSUE-HELPER — 이슈 생성/제목수정 시 브랜치명·커밋 메시지 댓글 생성 (내재화 버전).

구 외부 액션(Cassiiopeia/github-issue-helper@deploy)을 대체한다. stdlib 전용.

브랜치 규칙: `{타입}_{이슈번호}_{슬러그}`  (예: feat_112_install_banner)
  타입은 `type:` 라벨 → 이슈 타입 → 제목 [태그] 순으로 추론한다.
  슬러그는 한글·영문소문자·숫자를 밑줄로 잇는다.

  한글 허용 근거: 과거 "한글 브랜치명은 PR 생성 시 422" 보고가 있었으나
  실측 결과 push·REST API PR 생성·Actions 모두 정상이었다. 그 422는 Windows
  PowerShell ConvertTo-Json 인코딩 버그로 보이며 gh/git 경로에는 해당 없다.
  단 한글은 UTF-8 3바이트라 길이는 문자 수가 아니라 바이트로 제한한다.

⚠️ 불변 계약 — 아래 형식을 기계 파싱하는 소비자가 있으므로 절대 깨지 마라:
  1. 이슈 번호가 `_숫자_`(또는 끝)로 구분돼 등장할 것
     - scripts/common/issue_number.py : (?:^|[/_-])(\\d+)(?:[/_-]|$)  ← 커밋/보고서/리뷰 스킬
  2. 댓글 본문의 `### 브랜치` 제목 + 코드블록

설정: version.yml metadata.template.options.issue_helper (없으면 전부 기본값).
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── 기본 설정 (version.yml에 issue_helper 섹션이 없을 때) ─────────────────
DEFAULT_CONFIG = {
    "branch_prefix": "",
    "max_branch_length": 100,
    "timezone": "Asia/Seoul",
    "commit_template": "${issueTitle} : ${commitType} : {변경 사항에 대한 설명} ${issueUrl}",
    "commit_type_map": {},
    "comment_marker": "<!-- ISSUE-HELPER -->",
    "show_guide": True,
}

# GitHub 네이티브 이슈 타입(org 설정) → 타입. 제목 태그보다 우선한다 —
# 드롭다운으로 고르는 구조라 사람이 제목에 태그를 빠뜨려도 정확하다.
# Task는 다른 팀 레포에서 쓰는 org 공용 타입이라 남겨두고 chore로 흡수한다.
ISSUE_TYPE_MAP = {
    "Bug": "fix",
    "Feature": "feat",
    "Refactor": "refactor",
    "Chore": "chore",
    "Docs": "docs",
    "Task": "chore",
}

# 제목 태그 → 타입 (이슈 타입·라벨이 둘 다 없을 때의 폴백). 설정 commit_type_map이 병합됨.
DEFAULT_COMMIT_TYPE_MAP = {
    "버그": "fix",
    "기능요청": "feat",
    "기능추가": "feat",
    "기능개선": "feat",
    "리팩토링": "refactor",
    "설정": "chore",
    "문서": "docs",
}

# 라벨 `type: xxx` → 타입. 이슈 타입(org owner 권한 필요)을 만들 수 없어도
# 레포 admin만으로 굴러가는 경로 — 이 레포의 실질적인 1차 소스다.
LABEL_TYPE_PREFIX = "type: "
BRANCH_TYPES = ("feat", "fix", "refactor", "chore", "docs")

FALLBACK_TYPE = "feat"   # 타입을 어디서도 못 찾았을 때. 경고와 함께 쓴다.

# 느슨한 ref는 `.git/refs/heads/<name>` 파일이라 파일명 한계(255B)를 넘으면 안 된다.
# 한글 3바이트/자 × 100자 = 300바이트라 문자 수 제한만으로는 못 막는다.
MAX_REF_BYTES = 200

_SLUG_SEP = "_"
_TAG = re.compile(r"\[([^\]]*)\]")
_NON_SLUG = re.compile(r"[^가-힣a-z0-9]+")   # 한글/영문소문자/숫자 외 → 구분자


def _strip_emoji(text: str) -> str:
    """이모지(So)·제어문자(C*)·변형선택자 제거 — 구 TS \\p{So}|\\p{C}|\\uFE0F|\\u200D 패리티."""
    out = []
    for ch in text:
        if ch in ("️", "‍"):
            continue
        cat = unicodedata.category(ch)
        if cat == "So" or cat.startswith("C"):
            continue
        out.append(ch)
    return "".join(out)


def extract_issue_title(raw_title: str) -> str:
    """[태그]·이모지 제거. 결과가 비면 원본 trim 반환 (구 동작 보존)."""
    title = _TAG.sub("", raw_title).strip()
    title = _strip_emoji(title).strip()
    return title if title else raw_title.strip()


def slugify(title: str) -> str:
    """한글·영문소문자·숫자를 밑줄로 잇는다.

    영문을 소문자로 통일하는 이유: macOS/Windows는 파일명 대소문자를 구분하지 않아
    `Feat_1_API`와 `feat_1_api`가 같은 ref 파일로 충돌한다.
    """
    return _NON_SLUG.sub(_SLUG_SEP, title.lower()).strip(_SLUG_SEP)


def infer_commit_type(issue: dict, type_map: dict | None = None) -> str | None:
    """이슈 타입 → `type:` 라벨 → 제목 [태그] 순으로 조회. 전부 없으면 None.

    None을 기본값으로 뭉개지 않는 이유: 타입 없는 이슈에 feat을 붙이면 버그 이슈가
    feat_ 브랜치를 받고도 아무도 모른다. 호출부가 FALLBACK_TYPE과 경고를 함께 붙인다.
    """
    issue_type = (issue.get("type") or {}).get("name")
    if issue_type and issue_type in ISSUE_TYPE_MAP:
        return ISSUE_TYPE_MAP[issue_type]

    for label in issue.get("labels") or []:
        name = label.get("name") or ""
        if name.startswith(LABEL_TYPE_PREFIX):
            candidate = name[len(LABEL_TYPE_PREFIX):].strip()
            if candidate in BRANCH_TYPES:
                return candidate

    merged = dict(DEFAULT_COMMIT_TYPE_MAP)
    if type_map:
        merged.update(type_map)
    for tag in _TAG.findall(issue.get("title") or ""):
        commit_type = merged.get(tag.strip())
        if commit_type:
            return commit_type
    return None


def create_branch_name(
    title: str,
    issue_number: int | str,
    commit_type: str,
    branch_prefix: str = "",
    max_branch_length: int = 100,
) -> str:
    """`{타입}_{번호}_{슬러그}`. 슬러그가 비면(기호뿐인 제목) 타입_번호까지만."""
    slug = slugify(title)
    base = f"{commit_type}_{issue_number}"
    if slug:
        base = f"{base}{_SLUG_SEP}{slug}"
    if max_branch_length > 0:
        base = base[:max_branch_length]
    while len(base.encode("utf-8")) > MAX_REF_BYTES:   # 한글 3B/자 — 문자 수로는 못 막는다
        base = base[:-1]
    return f"{branch_prefix}{base.rstrip(_SLUG_SEP)}"


def render_commit_message(template: str, ctx: dict) -> str:
    """${변수} 치환 — 기존 5종 + commitType/labels/assignees. 미지 변수는 그대로 둔다."""
    out = template
    for key in ("issueTitle", "issueUrl", "issueNumber", "branchName",
                "date", "commitType", "labels", "assignees"):
        out = out.replace("${" + key + "}", str(ctx.get(key, "")))
    return out.strip()


# ── 설정 로드 (version.yml — pyyaml 없이 이 섹션만 파싱) ────────────────────
def _strip_inline_comment(raw: str) -> str:
    """따옴표 밖의 ` #...`만 주석으로 제거한다.

    따옴표를 무시하고 자르면 `"... #${issueNumber}"` 같은 값이 통째로 잘린다 —
    커밋 템플릿에 이슈 번호를 `#31` 형태로 넣는 순간 터지는 자리다.
    """
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        if end != -1:
            return raw[:end + 1]
        return raw
    return re.sub(r"\s+#.*$", "", raw)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_config(repo_root: str = ".") -> dict:
    """version.yml의 issue_helper 블록을 파싱해 DEFAULT_CONFIG에 병합한다.

    파일/섹션이 없으면 기본값 그대로 — 기존 통합 레포의 무설정 동작을 보존한다.
    향후 마법사 '설정 중앙관리' 메뉴가 이 섹션을 읽고 쓴다 (플랫 스칼라 + 얕은 맵 1개 유지).
    """
    cfg = dict(DEFAULT_CONFIG)
    cfg["commit_type_map"] = dict(DEFAULT_CONFIG["commit_type_map"])
    path = Path(repo_root) / "version.yml"
    if not path.exists():
        return cfg

    lines = path.read_text(encoding="utf-8").splitlines()
    section_indent = None
    in_type_map = False
    type_map_indent = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())

        if section_indent is None:
            if re.match(r"^issue_helper:\s*(#.*)?$", stripped):
                section_indent = indent
            continue

        if indent <= section_indent:  # 섹션 종료
            break

        m = re.match(r"""^["']?([^"':]+)["']?\s*:\s*(.*?)\s*$""", stripped)
        if not m:
            continue
        key, raw = m.group(1).strip(), _strip_inline_comment(m.group(2))

        if in_type_map and indent > type_map_indent:
            cfg["commit_type_map"][key] = _unquote(raw)
            continue
        in_type_map = False

        if key == "commit_type_map":
            in_type_map = True
            type_map_indent = indent
        elif key == "max_branch_length":
            try:
                cfg[key] = int(_unquote(raw))
            except ValueError:
                pass  # 잘못된 값은 기본값 유지
        elif key == "show_guide":
            cfg[key] = _unquote(raw).lower() != "false"
        elif key in ("branch_prefix", "timezone", "commit_template", "comment_marker"):
            cfg[key] = _unquote(raw)
    return cfg


# ── 동적 가이드 — 레포에 실존하는 워크플로우만 안내 (거짓 안내 원천 차단) ────
# ⚠️ 확장 규칙: 새 워크플로우가 브랜치 규칙(YYYYMMDD_#번호_)에 의존하게 되면 여기 한 줄 추가.
#    파일 실존 기반이므로 마법사 setting에서 타입 변경 시 자동 추종된다.
GUIDE_LINES = [
    ("PROJECT-FLUTTER-PROJECTOPS-APP-BUILD-TRIGGER.yaml",
     "`@projectops app build` 댓글 빌드 — 이 댓글의 브랜치를 자동 인식해서 빌드"),
    ("PROJECT-FLUTTER-ANDROID-TEST-APK.yaml",
     "테스트 APK 빌드 — 브랜치의 `#이슈번호`로 이슈 정보를 빌드 노트에 자동 포함"),
    ("PROJECT-FLUTTER-IOS-TEST-TESTFLIGHT.yaml",
     "테스트 TestFlight 빌드 — 브랜치의 `#이슈번호`로 이슈 정보를 자동 연동"),
]

_GUIDE_ALWAYS = [
    "커밋/보고서/리뷰 스킬 — 브랜치명에서 이슈 번호를 자동 추출해 커밋 메시지·보고서 완성",
]

_BRANCH_STRATEGY = (
    "**브랜치 전략**\n"
    "- `main` — 배포 트리거. 푸시하면 Vercel **Production** 자동 배포\n"
    "- `develop` — 배포 전 통합. 푸시하면 Vercel **Preview** 자동 생성\n"
    "- 작업 브랜치는 `develop`에서 따고 `develop`으로 PR을 올립니다\n"
)


def build_guide(workflows_dir: Path) -> str:
    """접이식(details) 안내 본문. 레포에 의존 기능이 있으면 그 목록을, 없으면 권장 한 줄만."""
    active = [text for fname, text in GUIDE_LINES if (workflows_dir / fname).exists()]
    items = "\n".join(f"- {t}" for t in active + _GUIDE_ALWAYS)
    return (
        "<details>\n"
        "<summary>💡 브랜치 규칙</summary>\n\n"
        f"{_BRANCH_STRATEGY}\n"
        "**이름 규칙** — `타입_이슈번호_슬러그`\n"
        "타입은 **`type:` 라벨**에서 결정됩니다 (템플릿을 고르면 자동으로 붙습니다).\n\n"
        "| 라벨 | 브랜치 | 예시 |\n"
        "| --- | --- | --- |\n"
        "| `type: fix` | `fix` | `fix_118_로그인_500_에러` |\n"
        "| `type: feat` | `feat` | `feat_112_설치_배너` |\n"
        "| `type: refactor` | `refactor` | `refactor_125_api_client` |\n"
        "| `type: chore` | `chore` | `chore_131_ci_setup` |\n"
        "| `type: docs` | `docs` | `docs_132_그라운드_룰` |\n\n"
        "라벨을 바꾸면 이 댓글도 자동으로 갱신됩니다. 라벨이 없으면 사이드바 **Type**(이슈 타입) "
        "→ 제목의 `[버그]` `[기능요청]` `[리팩토링]` `[설정]` `[문서]` 태그 순으로 폴백합니다.\n\n"
        "제목은 **한글로 써도 됩니다.** 한글·영문소문자·숫자만 남기고 나머지는 `_`로 잇습니다 "
        "(영문 대문자는 소문자로 통일 — 대소문자를 구분하지 않는 파일시스템에서의 충돌 방지).\n\n"
        "이 형식을 쓰면 아래가 자동으로 연동됩니다:\n"
        f"{items}\n"
        "</details>"
    )


def build_comment_body(cfg: dict, branch_name: str, commit_message: str,
                       guide: str, notice: str = "") -> str:
    """불변 계약 2: 서명 한 줄 + ### 브랜치 코드블록 구조 유지 (구 파서 하위호환)."""
    marker = cfg["comment_marker"]
    guide_block = f"\n{guide}\n" if (cfg.get("show_guide", True) and guide) else ""
    return (
        f"{marker}\n\n"
        "이슈 브랜치 가이드\n"
        "---\n\n"
        f"{notice}"
        "### 브랜치\n"
        f"```\n{branch_name}\n```\n\n"
        "### 커밋 메시지\n"
        f"```\n{commit_message}\n```\n"
        f"{guide_block}\n"
        f"{marker}"
    )


# ── 이벤트 처리 ──────────────────────────────────────────────────────────
def should_process(payload: dict) -> bool:
    """브랜치명을 바꿀 수 있는 이벤트만 처리 — 생성 / 제목 변경 / 타입·타입라벨 변경.

    라벨은 `type:` 접두사가 붙은 것만 본다. 상태 라벨(작업중 등)까지 받으면
    라벨 하나 옮길 때마다 워크플로우가 도는데, 브랜치명은 그대로다.
    """
    action = payload.get("action")
    if action in ("opened", "typed", "untyped"):
        return True
    if action in ("labeled", "unlabeled"):
        return ((payload.get("label") or {}).get("name") or "").startswith(LABEL_TYPE_PREFIX)
    return action == "edited" and bool(payload.get("changes", {}).get("title"))


def today_yyyymmdd(tz_name: str) -> str:
    """설정 타임존 기준 오늘 날짜. 구 액션의 UTC 러너 시각 오차(한국 새벽 -9h)를 개선."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name)).strftime("%Y%m%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y%m%d")


def prepare_comment(payload: dict, cfg: dict, workflows_dir: Path, date_yyyymmdd: str):
    """페이로드 → (브랜치명, 커밋 메시지, 댓글 본문). 네트워크 무의존 — 테스트 가능 단위."""
    issue = payload["issue"]
    raw_title = issue["title"]
    title = extract_issue_title(raw_title)
    issue_number = str(issue["number"])

    commit_type = infer_commit_type(issue, cfg["commit_type_map"])
    notice = ""
    if commit_type is None:
        commit_type = FALLBACK_TYPE
        labels = " · ".join(f"`{LABEL_TYPE_PREFIX}{t}`" for t in BRANCH_TYPES)
        notice = (
            f"> ⚠️ 타입을 찾을 수 없어 `{FALLBACK_TYPE}`으로 추정했습니다.\n"
            f"> {labels} 중 하나를 라벨로 붙이면 타입이 정확해집니다 "
            "(붙이면 이 댓글이 자동 갱신됩니다).\n\n"
        )

    branch = create_branch_name(
        title, issue_number, commit_type,
        branch_prefix=cfg["branch_prefix"], max_branch_length=cfg["max_branch_length"])

    ctx = {
        "issueTitle": title,
        "issueUrl": issue["html_url"],
        "issueNumber": issue_number,
        "branchName": branch,
        "date": date_yyyymmdd,
        "commitType": commit_type,
        "labels": ", ".join(l["name"] for l in issue.get("labels", [])),
        "assignees": ", ".join(a["login"] for a in issue.get("assignees", [])),
    }
    commit_message = render_commit_message(cfg["commit_template"], ctx)
    body = build_comment_body(cfg, branch, commit_message, build_guide(workflows_dir), notice)
    return branch, commit_message, body


# ── GitHub API (urllib — 같은 레포 이슈 댓글이라 redirect 없음) ──────────────
_API = "https://api.github.com"

# 구 액션이 남긴 댓글도 upsert 대상으로 매칭 (중복 댓글 방지 — 하위호환)
LEGACY_MARKER_HINTS = ("github-issue-helper", "<!-- SUH-ISSUE-HELPER -->")


def _request(method: str, url: str, token: str, data: dict | None = None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    payload = None
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, payload) as res:
        return json.loads(res.read().decode("utf-8"))


def find_existing_comment(comments: list, marker: str):
    """신형 마커 우선, 없으면 구 액션 마커 힌트로 매칭."""
    for c in comments:
        if marker in (c.get("body") or ""):
            return c
    for c in comments:
        body = c.get("body") or ""
        if any(hint in body for hint in LEGACY_MARKER_HINTS):
            return c
    return None


def upsert_comment(owner: str, repo: str, issue_number: int, marker: str, body: str, token: str):
    comments = []
    page = 1
    while True:
        batch = _request(
            "GET",
            f"{_API}/repos/{owner}/{repo}/issues/{issue_number}/comments?per_page=100&page={page}",
            token)
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    existing = find_existing_comment(comments, marker)
    if existing:
        _request("PATCH", f"{_API}/repos/{owner}/{repo}/issues/comments/{existing['id']}",
                 token, {"body": body})
        return "updated"
    _request("POST", f"{_API}/repos/{owner}/{repo}/issues/{issue_number}/comments",
             token, {"body": body})
    return "created"


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not event_path or not Path(event_path).exists():
        print("❌ GITHUB_EVENT_PATH가 없습니다 (Actions 환경 전용)", file=sys.stderr)
        return 1
    if not token:
        print("❌ GITHUB_TOKEN이 없습니다", file=sys.stderr)
        return 1

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    if not should_process(payload):
        print("ℹ️ 처리 대상 이벤트가 아님 (opened/제목 edited만) → 종료", file=sys.stderr)
        return 0

    cfg = load_config(".")
    branch, commit_message, body = prepare_comment(
        payload, cfg, Path(".github") / "workflows", today_yyyymmdd(cfg["timezone"]))

    owner = payload["repository"]["owner"]["login"]
    repo = payload["repository"]["name"]
    result = upsert_comment(
        owner, repo, payload["issue"]["number"], cfg["comment_marker"], body, token)
    print(f"✅ 댓글 {result}: {branch}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
