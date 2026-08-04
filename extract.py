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
- instagram_handle: 아래 후보와 본문을 종합해 '{university}'의 축제·총학생회 공식 계정이
  확실한 것만 채웁니다. 블로그 운영자·언론사·무관 계정이면 null. 후보에 없는 계정을 지어내지 마세요.
- 설명이나 마크다운 없이 JSON 객체 하나만 출력하세요.

스키마:
{{"found": bool, "university_name": str, "year": int,
  "festival_name": str|null, "start_date": str|null, "end_date": str|null,
  "venue_name": str|null, "outsider_admission": str|null, "ticket_info": str|null,
  "instagram_handle": str|null,
  "lineup": [{{"artist_raw": str, "day_label": str|null, "date": str|null,
              "time": str|null, "is_secret": bool}}]}}

본문 링크에서 발견된 인스타그램 계정 후보:
{candidates}

본문:
{body}"""


class ExtractError(Exception):
    pass


def call_claude(
    prompt: str, timeout: int = CLAUDE_TIMEOUT_SECONDS, tools: str = ""
) -> str:
    """claude -p 헤드리스 호출. envelope JSON의 result 필드(모델 응답 텍스트)를 반환.

    tools: --tools에 그대로 전달. 기본 ""는 모든 도구 차단(추출·정규화용).
           탐색만 "WebSearch"로 켠다.
    """
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json", "--tools", tools],
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


def extract(
    body: str,
    university: str,
    year: int,
    instagram_candidates: list[str] | None = None,
) -> ExtractionResult:
    candidates = (
        "\n".join(f"- {c}" for c in instagram_candidates)
        if instagram_candidates
        else "(후보 없음)"
    )
    prompt = PROMPT_TEMPLATE.format(
        university=university, year=year, body=body, candidates=candidates
    )
    last_error = None
    for _ in range(2):
        raw = call_claude(prompt)
        try:
            return ExtractionResult.model_validate_json(_extract_json(raw))
        except (ValueError, ValidationError) as e:
            last_error = e
            prompt = (
                PROMPT_TEMPLATE.format(
                    university=university, year=year, body=body, candidates=candidates
                )
                + f"\n\n[재시도] 이전 응답이 유효하지 않았습니다: {e}\n"
                  "스키마에 정확히 맞는 JSON 객체 하나만 다시 출력하세요."
            )
    raise ExtractError(f"추출 검증 2회 실패: {last_error}")


def verify(result: ExtractionResult, university: str, year: int) -> bool:
    """역방향 검증: 추출 결과가 요청한 대학·연도의 글이 맞는지 사후 판정."""
    if not result.found:
        return False
    if not result.university_name:
        return False
    name_match = (
        result.university_name in university or university in result.university_name
    )
    return name_match and result.year == year
