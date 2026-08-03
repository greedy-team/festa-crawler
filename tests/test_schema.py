import pytest
from pydantic import ValidationError

from schema import ArtistMaster, EnrichResult, ExtractionResult, LineupItem


def test_extraction_result_full_parse():
    data = {
        "found": True,
        "university_name": "연세대학교",
        "year": 2026,
        "festival_name": "아카라카",
        "start_date": "2026-05-21",
        "end_date": "2026-05-23",
        "venue_name": "노천극장",
        "outsider_admission": "외부인 입장 가능",
        "ticket_info": "유료, 예매 5.07 오픈",
        "lineup": [
            {"artist_raw": "잔나비", "day_label": "1일차", "date": "2026-05-21"},
            {"artist_raw": "시크릿", "is_secret": True},
        ],
    }
    result = ExtractionResult.model_validate(data)
    assert result.lineup[0].artist_raw == "잔나비"
    assert result.lineup[0].time is None          # 미지정 필드는 None
    assert result.lineup[0].is_secret is False    # 기본값
    assert result.lineup[1].is_secret is True


def test_extraction_result_minimal_not_found():
    # found=False인 글도 스키마는 통과해야 함 (역방향 검증은 별도 단계)
    result = ExtractionResult.model_validate(
        {"found": False, "university_name": "고려대학교", "year": 2026}
    )
    assert result.festival_name is None
    assert result.lineup == []


def test_extraction_result_rejects_missing_required():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({"university_name": "연세대학교", "year": 2026})


def test_enrich_result_parse():
    data = {
        "mapping": {"십센치": "10CM", "10cm": "10CM"},
        "artists": [
            {"name_canonical": "10CM", "name_en": "10CM", "real_name": "권정열",
             "category": "가수", "aliases": ["십센치"], "needs_review": False}
        ],
    }
    result = EnrichResult.model_validate(data)
    assert result.mapping["십센치"] == "10CM"
    assert result.artists[0].name_canonical == "10CM"


def test_artist_master_defaults():
    a = ArtistMaster.model_validate({"name_canonical": "잔나비"})
    assert a.needs_review is False
    assert a.aliases == []
