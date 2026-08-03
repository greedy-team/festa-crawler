from pathlib import Path

from crawl import load_universities

CSV_PATH = Path(__file__).parent.parent / "universities.csv"


def test_loads_29_rows():
    rows = load_universities(CSV_PATH)
    assert len(rows) == 29


def test_url_empty_becomes_none():
    rows = load_universities(CSV_PATH)
    by_name = {r.university: r for r in rows}
    assert by_name["한국외국어대학교"].url is None      # 원본 목록에 '없음'
    assert by_name["연세대학교"].url is not None


def test_fields_populated():
    rows = load_universities(CSV_PATH)
    r = next(x for x in rows if x.university == "연세대학교")
    assert r.campus == "신촌캠퍼스"
    assert r.region == "서울 서대문구"
    assert r.year == 2026
