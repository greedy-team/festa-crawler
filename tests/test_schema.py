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
        "description": "연세대학교의 대표 축제. 3일간 노천극장에서 열린다.",
        "hashtags": ["연세대축제", "아카라카"],
        "external_visitor_policy": "CONDITIONAL",
        "verification_method": "PRE_BOOKING",
        "ticket_type": "PAID",
        "ticket_open_at": "2026-05-07T14:00:00",
        "admission_raw": "재학생 우선 입장이며 외부인은 예매 후 입장 가능합니다.",
        "lineup": [
            {"artist_raw": "잔나비", "day": 1},
            {"artist_raw": "시크릿", "is_secret": True},
        ],
    }
    result = ExtractionResult.model_validate(data)
    assert result.lineup[0].day == 1
    assert result.lineup[1].day is None          # 미지정은 None
    assert result.lineup[1].is_secret is True
    assert result.external_visitor_policy == "CONDITIONAL"


def test_extraction_result_rejects_bad_enum():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(
            {"found": True, "university_name": "연세대학교", "year": 2026,
             "external_visitor_policy": "MAYBE"}
        )


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
            {"name": "10CM", "other_names": ["십센치", "권정열"],
             "genre": "BAND", "category": "가수", "needs_review": False}
        ],
    }
    result = EnrichResult.model_validate(data)
    assert result.artists[0].name == "10CM"
    assert result.artists[0].genre == "BAND"


def test_artist_master_defaults():
    a = ArtistMaster.model_validate({"name": "잔나비"})
    assert a.needs_review is False
    assert a.other_names == []
    assert a.genre is None


def test_extraction_result_instagram_handle_optional():
    # 구 캐시(필드 없음)와 신규 응답 모두 파싱돼야 한다
    old = ExtractionResult.model_validate(
        {"found": True, "university_name": "연세대학교", "year": 2026}
    )
    assert old.instagram_handle is None
    new = ExtractionResult.model_validate(
        {"found": True, "university_name": "한양대학교", "year": 2026,
         "instagram_handle": "hyu_festival"}
    )
    assert new.instagram_handle == "hyu_festival"


def test_discover_result_parse():
    from schema import DiscoverResult

    r = DiscoverResult.model_validate(
        {"candidates": [
            {"url": "https://example.com/a", "title": "한양대 축제"},
            {"url": "https://example.com/b"},
        ]}
    )
    assert r.candidates[0].url == "https://example.com/a"
    assert r.candidates[1].title is None


def test_discover_result_empty_default():
    from schema import DiscoverResult

    assert DiscoverResult.model_validate({}).candidates == []
