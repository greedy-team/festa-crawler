import pytest

import extract
from extract import ExtractError, verify
from schema import ExtractionResult

VALID_JSON = """{
  "found": true, "university_name": "연세대학교", "year": 2026,
  "festival_name": "아카라카", "start_date": "2026-05-21", "end_date": "2026-05-23",
  "venue_name": "노천극장", "description": "축제 소개.", "hashtags": ["아카라카"],
  "external_visitor_policy": "CONDITIONAL",
  "admission_raw": "외부인은 예매 후 입장 가능합니다.",
  "lineup": [{"artist_raw": "잔나비", "day": 1, "is_secret": false}]
}"""


def test_extract_success(monkeypatch):
    monkeypatch.setattr(extract, "call_claude", lambda prompt, timeout=120: VALID_JSON)
    result = extract.extract("본문", "연세대학교", 2026)
    assert result.festival_name == "아카라카"
    assert result.lineup[0].artist_raw == "잔나비"


def test_extract_strips_code_fences(monkeypatch):
    fenced = "```json\n" + VALID_JSON + "\n```"
    monkeypatch.setattr(extract, "call_claude", lambda prompt, timeout=120: fenced)
    result = extract.extract("본문", "연세대학교", 2026)
    assert result.found is True


def test_extract_retries_once_then_succeeds(monkeypatch):
    responses = iter(["이건 JSON이 아님", VALID_JSON])
    calls = []

    def fake(prompt, timeout=120):
        calls.append(prompt)
        return next(responses)

    monkeypatch.setattr(extract, "call_claude", fake)
    result = extract.extract("본문", "연세대학교", 2026)
    assert result.found is True
    assert len(calls) == 2
    assert "유효하지 않았습니다" in calls[1]   # 재시도 프롬프트에 오류 피드백 포함


def test_extract_fails_after_two_attempts(monkeypatch):
    monkeypatch.setattr(extract, "call_claude", lambda prompt, timeout=120: "여전히 JSON 아님")
    with pytest.raises(ExtractError):
        extract.extract("본문", "연세대학교", 2026)


def _result(**overrides) -> ExtractionResult:
    base = {"found": True, "university_name": "연세대학교", "year": 2026}
    base.update(overrides)
    return ExtractionResult.model_validate(base)


def test_verify_pass_and_partial_name_match():
    assert verify(_result(), "연세대학교", 2026) is True
    assert verify(_result(university_name="연세대"), "연세대학교", 2026) is True


def test_verify_fails_on_mismatch():
    assert verify(_result(found=False), "연세대학교", 2026) is False
    assert verify(_result(university_name="고려대학교"), "연세대학교", 2026) is False
    assert verify(_result(year=2025), "연세대학교", 2026) is False
    assert verify(_result(university_name=""), "연세대학교", 2026) is False


def test_extract_passes_candidates_into_prompt(monkeypatch):
    captured = {}

    def fake(prompt, timeout=120):
        captured["prompt"] = prompt
        return VALID_JSON

    monkeypatch.setattr(extract, "call_claude", fake)
    extract.extract("본문", "한양대학교", 2026, instagram_candidates=["hyu_festival", "blogowner"])
    assert "hyu_festival" in captured["prompt"]
    assert "blogowner" in captured["prompt"]


def test_extract_without_candidates_prompts_none(monkeypatch):
    captured = {}

    def fake(prompt, timeout=120):
        captured["prompt"] = prompt
        return VALID_JSON

    monkeypatch.setattr(extract, "call_claude", fake)
    extract.extract("본문", "연세대학교", 2026)
    assert "후보 없음" in captured["prompt"]


def test_prompt_includes_new_field_rules(monkeypatch):
    seen = {}

    def fake_call(prompt, timeout=120, tools=""):
        seen["prompt"] = prompt
        return ('{"found": true, "university_name": "연세대학교", "year": 2026,'
                ' "description": "축제 소개.", "hashtags": ["아카라카"],'
                ' "external_visitor_policy": "CONDITIONAL",'
                ' "admission_raw": "외부인은 예매 후 입장 가능합니다.",'
                ' "lineup": [{"artist_raw": "잔나비", "day": 1}]}')

    monkeypatch.setattr(extract, "call_claude", fake_call)
    result = extract.extract("본문", "연세대학교", 2026)
    assert result.description == "축제 소개."
    assert result.lineup[0].day == 1
    for token in ["description", "hashtags", "external_visitor_policy",
                  "verification_method", "ticket_type", "ticket_open_at",
                  "admission_raw", "day", "주최명"]:
        assert token in seen["prompt"]


def test_prompt_includes_single_day_rules(monkeypatch):
    """하루짜리 축제에서 확정되는 값을 추론하도록 프롬프트가 지시하는지 확인한다.

    원문이 "5월 22일 개최"처럼 날짜 하나만 적으면 end_date와 각 출연자의 day가
    비어 나왔다. 정보가 없는 게 아니라 하루라는 사실에서 확정되는 값이다.
    프롬프트의 실제 효과는 재크롤 실측으로 확인하며, 이 테스트는 지시가
    프롬프트에서 사라지지 않게 잡아둔다.
    """
    seen = {}

    def fake_call(prompt, timeout=120, tools=""):
        seen["prompt"] = prompt
        return ('{"found": true, "university_name": "이화여자대학교", "year": 2026,'
                ' "start_date": "2026-05-22", "end_date": "2026-05-22",'
                ' "lineup": [{"artist_raw": "NCT WISH", "day": 1}]}')

    monkeypatch.setattr(extract, "call_claude", fake_call)
    result = extract.extract("본문", "이화여자대학교", 2026)
    assert result.start_date == result.end_date == "2026-05-22"
    assert result.lineup[0].day == 1
    assert "하루" in seen["prompt"]
    assert "end_date를" in seen["prompt"]


def test_call_claude_passes_tools_flag(monkeypatch):
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = '{"result": "OK"}'
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return FakeProc()

    monkeypatch.setattr(extract.subprocess, "run", fake_run)

    extract.call_claude("프롬프트")
    assert captured["argv"][-2:] == ["--tools", ""]      # 기본값은 도구 차단

    extract.call_claude("프롬프트", tools="WebSearch")
    assert captured["argv"][-2:] == ["--tools", "WebSearch"]


def test_extraction_result_accepts_missing_year():
    # 본문에 연도가 없으면 LLM이 비운다. 스키마가 그것을 받아야 verify가 판단할 수 있다.
    result = ExtractionResult.model_validate_json(
        '{"found": true, "university_name": "연세대학교"}'
    )
    assert result.year is None


def test_verify_passes_when_year_unknown():
    # 연도를 적지 않는 글이 흔하다. 조이면 사람이 채울 원재료까지 사라진다 (DEC-0138)
    assert verify(_result(year=None), "연세대학교", 2026) is True


def test_date_warning_flags_year_gap():
    past = extract.date_warning("2023-05-11T20:30:25+09:00", 2025)
    future = extract.date_warning("2026-09-01T10:29:20+09:00", 2025)
    assert past is not None and "2023" in past
    assert future is not None and "2026" in future


def test_date_warning_silent_when_year_matches():
    assert extract.date_warning("2026-05-10T20:28:00+09:00", 2026) is None
    assert extract.date_warning("2026. 5. 10. 20:28", 2026) is None      # 네이버 표기


def test_date_warning_silent_when_year_unknown():
    assert extract.date_warning(None, 2026) is None
    assert extract.date_warning("등록일 없음", 2026) is None


def _prompt(**overrides) -> str:
    args = {"university": "연세대학교", "year": 2026,
            "body": "본문", "candidates": "(후보 없음)"}
    args.update(overrides)
    return extract.PROMPT_TEMPLATE.format(**args)


def test_prompt_has_rules_for_year_and_university_name():
    # 규칙이 없으면 모델이 프롬프트에 적힌 값을 그대로 되돌려주고 verify가 그것을 확인한다
    prompt = _prompt()
    assert "- year:" in prompt
    assert "- university_name:" in prompt


def test_prompt_tells_model_to_leave_year_null_when_absent():
    year_rule = _prompt().split("- year:")[1].split("\n- ")[0]
    assert "null" in year_rule


def test_prompt_excludes_student_stages_and_hosts_from_lineup():
    prompt = _prompt()
    assert "학생 무대" in prompt
    assert "MC" in prompt
