import csv
import json
from pathlib import Path

import crawl
from crawl import (UniversityRow, build_festival_row, build_lineup_rows,
                   process_row, write_csv)
from fetch import FetchResult
from schema import ExtractionResult


def _row(**overrides) -> UniversityRow:
    base = dict(university="연세대학교", campus="신촌캠퍼스",
                region="서울 서대문구", year=2026, url="https://example.com/post")
    base.update(overrides)
    return UniversityRow(**base)


def _extraction() -> ExtractionResult:
    return ExtractionResult.model_validate({
        "found": True, "university_name": "연세대학교", "year": 2026,
        "festival_name": "아카라카", "start_date": "2026-05-21",
        "end_date": "2026-05-23", "venue_name": "노천극장",
        "outsider_admission": "사전 예매 시 가능", "ticket_info": "유료",
        "instagram_handle": "hyu_festival",
        "lineup": [
            {"artist_raw": "잔나비", "day_label": "1일차", "date": "2026-05-21"},
            {"artist_raw": "시크릿", "is_secret": True},
        ],
    })


def test_process_row_no_url(tmp_path):
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "no_source"
    assert record["extraction"] is None


def test_process_row_happy_path_writes_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(
        status="ok", body="본문" * 100, poster_image_url="https://example.com/p.jpg"))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "ok"
    assert record["poster_image_url"] == "https://example.com/p.jpg"
    cached = json.loads((tmp_path / "raw" / "연세대학교.json").read_text("utf-8"))
    assert cached["extraction"]["festival_name"] == "아카라카"


def test_process_row_uses_cache(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    cached = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026, "url": "https://example.com/post",
              "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    (raw_dir / "연세대학교.json").write_text(json.dumps(cached), "utf-8")

    def boom(url):
        raise AssertionError("캐시가 있으면 fetch하면 안 됨")

    monkeypatch.setattr(crawl, "fetch_body", boom)
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "ok"


def test_process_row_mismatch_flag(tmp_path, monkeypatch):
    wrong = _extraction().model_copy(update={"year": 2024})
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: wrong)
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "mismatch"
    assert record["extraction"] is not None   # 결과는 보존, 판단은 사람이


def test_process_row_refetches_when_cached_year_differs(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    stale = {"university": "연세대학교", "campus": "신촌캠퍼스",
             "region": "서울 서대문구", "year": 2025, "url": "https://example.com/post",
             "flag": "ok", "poster_image_url": None, "extraction": _extraction().model_dump()}
    (raw_dir / "연세대학교.json").write_text(json.dumps(stale), "utf-8")
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())
    record = process_row(_row(), tmp_path)   # _row()의 year는 2026
    assert record["year"] == 2026


def test_process_row_cache_hit_refreshes_campus_region(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    cached = {"university": "연세대학교", "campus": "옛캠퍼스",
              "region": "서울 옛구", "year": 2026, "url": "https://example.com/post",
              "flag": "ok", "poster_image_url": None, "extraction": _extraction().model_dump()}
    (raw_dir / "연세대학교.json").write_text(json.dumps(cached), "utf-8")

    def boom(url):
        raise AssertionError("캐시 적중이면 fetch하면 안 됨")

    monkeypatch.setattr(crawl, "fetch_body", boom)
    record = process_row(_row(), tmp_path)
    assert record["campus"] == "신촌캠퍼스"
    assert record["region"] == "서울 서대문구"


def test_build_rows():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "flag": "ok",
              "poster_image_url": "https://example.com/p.jpg",
              "extraction": _extraction().model_dump()}
    frow = build_festival_row(record)
    assert frow["festival_name"] == "아카라카"
    assert frow["flag"] == "ok"
    lrows = build_lineup_rows(record)
    assert len(lrows) == 2
    assert lrows[0]["artist_canonical"] == "잔나비"   # 초기값 = artist_raw
    assert lrows[1]["is_secret"] == "true"


def test_build_rows_without_extraction():
    record = {"university": "고려대학교", "campus": "안암캠퍼스",
              "region": "서울 성북구", "year": 2026, "url": None,
              "flag": "no_source", "poster_image_url": None, "extraction": None}
    frow = build_festival_row(record)
    assert frow["flag"] == "no_source"
    assert frow["festival_name"] == ""
    assert build_lineup_rows(record) == []


def test_write_csv_utf8_bom(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, ["a", "b"], [{"a": "한글", "b": "x"}])
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")   # BOM
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["a"] == "한글"


def test_process_row_no_url_writes_no_cache(tmp_path):
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "no_source"
    assert not (tmp_path / "raw" / "연세대학교.json").exists()


def test_write_csv_sanitizes_formula_prefix(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, ["a", "b"], [{"a": "=SUM(A1)", "b": "@잔나비"}])
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["a"] == "'=SUM(A1)"
    assert rows[0]["b"] == "'@잔나비"


def test_process_row_fetch_failed_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "fetch_body",
                        lambda url: FetchResult(status="fetch_failed", error="timeout"))
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "fetch_failed"
    assert not (tmp_path / "raw" / "연세대학교.json").exists()


def test_process_row_refetches_when_cached_url_differs(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    stale = {"university": "연세대학교", "campus": "신촌캠퍼스",
             "region": "서울 서대문구", "year": 2026, "url": None,
             "flag": "no_source", "poster_image_url": None, "extraction": None}
    (raw_dir / "연세대학교.json").write_text(json.dumps(stale), "utf-8")
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "ok"          # 스테일 캐시 무시하고 재처리


def test_process_row_passes_candidates_to_extract(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(
        status="ok", body="본문" * 100, instagram_candidates=["hyu_festival"]))

    def fake_extract(body, u, y, cands=None):
        captured["cands"] = cands
        return _extraction()

    monkeypatch.setattr(crawl, "extract", fake_extract)
    process_row(_row(), tmp_path)
    assert captured["cands"] == ["hyu_festival"]


def test_build_festival_row_includes_instagram_handle():
    record = {"university": "한양대학교", "campus": "서울캠퍼스",
              "region": "서울 성동구", "year": 2026,
              "url": "https://example.com/post", "flag": "ok",
              "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    frow = build_festival_row(record)
    assert frow["instagram_handle"] == "hyu_festival"
    assert list(frow.keys()) == crawl.FESTIVAL_FIELDS   # 컬럼 순서 일치
