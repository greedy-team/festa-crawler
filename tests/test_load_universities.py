import pytest

from pathlib import Path

from crawl import load_universities

CSV_PATH = Path(__file__).parent.parent / "universities-2026.csv"


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


def _seed(tmp_path, rows, header="university,campus,region,year,url,latitude,longitude"):
    path = tmp_path / "universities-2026.csv"
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8-sig")
    return path


def test_coordinates_are_loaded_as_strings(tmp_path):
    path = _seed(tmp_path, ["연세대학교,신촌캠퍼스,서울 서대문구,2026,,37.5665,126.9780"])
    row = load_universities(path)[0]
    assert row.latitude == "37.5665"
    assert row.longitude == "126.9780"


def test_blank_coordinates_pass_through(tmp_path):
    path = _seed(tmp_path, ["연세대학교,신촌캠퍼스,서울 서대문구,2026,,,"])
    row = load_universities(path)[0]
    assert row.latitude == ""
    assert row.longitude == ""


def test_missing_coordinate_columns_stops(tmp_path):
    path = _seed(tmp_path, ["연세대학교,신촌캠퍼스,서울 서대문구,2026,"],
                 header="university,campus,region,year,url")
    with pytest.raises(SystemExit) as e:
        load_universities(path)
    assert "latitude" in str(e.value) and "longitude" in str(e.value)


def test_duplicate_university_stops(tmp_path):
    path = _seed(tmp_path, [
        "성균관대학교,인문사회과학캠퍼스,서울 종로구,2026,,37.5,126.9",
        "성균관대학교,자연과학캠퍼스,경기 수원시,2026,,37.2,126.9",
    ])
    with pytest.raises(SystemExit) as e:
        load_universities(path)
    assert "성균관대학교" in str(e.value)
