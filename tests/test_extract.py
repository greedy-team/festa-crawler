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
