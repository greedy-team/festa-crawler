import pytest

import extract
from extract import ExtractError, verify
from schema import ExtractionResult

VALID_JSON = """{
  "found": true, "university_name": "연세대학교", "year": 2026,
  "festival_name": "아카라카", "start_date": "2026-05-21", "end_date": "2026-05-23",
  "venue_name": "노천극장", "outsider_admission": "사전 예매 시 가능",
  "ticket_info": "유료",
  "lineup": [{"artist_raw": "잔나비", "day_label": "1일차",
              "date": "2026-05-21", "time": null, "is_secret": false}]
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
