import csv
import json
from pathlib import Path

import pytest

import crawl
from crawl import (UniversityRow, build_festival_row, build_lineup_rows,
                   process_row, write_csv)
from extract import ExtractError
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


def test_process_row_no_url(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "no_candidate"
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
              "region": "서울 서대문구", "year": 2026,
              "seed_url": "https://example.com/post", "url": "https://example.com/post",
              "discovery": "manual", "flag": "ok", "poster_image_url": None,
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
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])   # 수동 URL 실패 후 탐색 폴백, 후보 없음
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "mismatch"       # 수동 시도의 실패 flag 유지
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
              "region": "서울 옛구", "year": 2026,
              "seed_url": "https://example.com/post", "url": "https://example.com/post",
              "discovery": "manual", "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
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


def test_process_row_no_candidate_is_cached(tmp_path, monkeypatch):
    # 정당한 0건(탐색은 됐지만 후보가 없음)은 캐시해도 된다 — 재검색은 discovered/ 캐시가 막는다
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "no_candidate"
    assert (tmp_path / "raw" / "연세대학교.json").exists()


def test_process_row_transient_discovery_failure_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: None)
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "no_source"      # 탐색을 못 했으므로 no_candidate가 아니다
    assert not (tmp_path / "raw" / "연세대학교.json").exists()   # 캐시 안 함 → 다음 실행에서 재시도


def test_write_csv_sanitizes_formula_prefix(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, ["a", "b"], [{"a": "=SUM(A1)", "b": "@잔나비"}])
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["a"] == "'=SUM(A1)"
    assert rows[0]["b"] == "'@잔나비"


def test_write_csv_keeps_old_file_when_replace_fails(tmp_path, monkeypatch):
    """os.replace() 실패 시 기존 파일이 보존되고 임시 파일도 정리된다."""
    path = tmp_path / "out.csv"
    write_csv(path, ["a"], [{"a": "이전"}])

    def boom(src, dst):
        raise OSError("swap 실패")

    monkeypatch.setattr(crawl.os, "replace", boom)
    with pytest.raises(OSError):
        write_csv(path, ["a"], [{"a": "새것"}])

    # 기존 내용이 보존되어 있다
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["a"] == "이전"
    # 임시 파일도 정리되었다
    assert list(tmp_path.glob("*.tmp*")) == []


def test_process_row_fetch_failed_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "fetch_body",
                        lambda url: FetchResult(status="fetch_failed", error="timeout"))
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])   # 수동 URL 실패 후 탐색 폴백, 후보 없음
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "fetch_failed"   # 수동 시도의 실패 flag 유지
    assert not (tmp_path / "raw" / "연세대학교.json").exists()


def test_process_row_extract_failed_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))

    def boom(body, u, y, cands=None):
        raise ExtractError("세션 한도")

    monkeypatch.setattr(crawl, "extract", boom)
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "extract_failed"
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


def test_process_row_manual_success_skips_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())

    def boom(university, year, out_dir):
        raise AssertionError("수동 URL이 성공하면 탐색하면 안 됨")

    monkeypatch.setattr(crawl, "discover_cached", boom)
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "ok"
    assert record["discovery"] == "manual"


def test_process_row_discovers_when_no_url(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_cached",
                        lambda u, y, o: ["https://found.example.com/post"])
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "ok"
    assert record["discovery"] == "search"
    assert record["url"] == "https://found.example.com/post"


def test_process_row_falls_through_to_second_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_cached",
                        lambda u, y, o: ["https://bad.example.com/x", "https://good.example.com/y"])
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))

    def fake_extract(body, u, y, cands=None):
        return _extraction()

    monkeypatch.setattr(crawl, "extract", fake_extract)
    # 첫 후보는 verify 실패(다른 대학), 두 번째는 통과
    seen = []

    def fake_verify(result, university, year):
        seen.append(university)
        return len(seen) > 1

    monkeypatch.setattr(crawl, "verify", fake_verify)
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "ok"
    assert record["url"] == "https://good.example.com/y"


def test_process_row_no_candidate_when_discovery_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "no_candidate"
    assert record["discovery"] == ""


def test_process_row_keeps_manual_failure_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "fetch_body",
                        lambda url: FetchResult(status="empty_body", poster_image_url=None))
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "empty_body"     # no_candidate로 덮어쓰지 않는다
    assert record["discovery"] == ""


def test_build_festival_row_includes_discovery():
    record = {"university": "한양대학교", "campus": "서울캠퍼스", "region": "서울 성동구",
              "year": 2026, "seed_url": None, "url": "https://found.example.com/p",
              "discovery": "search", "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    frow = build_festival_row(record)
    assert frow["discovery"] == "search"
    assert frow["source_url"] == "https://found.example.com/p"
    assert list(frow.keys()) == crawl.FESTIVAL_FIELDS


def test_process_row_cache_keyed_on_seed_url(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    cached = {"university": "연세대학교", "campus": "신촌캠퍼스", "region": "서울 서대문구",
              "year": 2026, "seed_url": None, "url": "https://found.example.com/p",
              "discovery": "search", "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    (raw_dir / "연세대학교.json").write_text(json.dumps(cached), "utf-8")

    def boom(university, year, out_dir):
        raise AssertionError("캐시 적중이면 탐색하면 안 됨")

    monkeypatch.setattr(crawl, "discover_cached", boom)
    record = process_row(_row(url=None), tmp_path)   # 시드 url=None, 캐시의 seed_url도 None
    assert record["flag"] == "ok"
    assert record["url"] == "https://found.example.com/p"


def test_festival_id_format():
    assert crawl.festival_id("연세대학교", 2026) == "연세대학교-2026"


def test_festival_id_links_festival_and_lineup():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "discovery": "manual",
              "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    frow = build_festival_row(record)
    lrows = build_lineup_rows(record)
    assert frow["festival_id"] == "연세대학교-2026"
    assert [r["festival_id"] for r in lrows] == ["연세대학교-2026"] * 2
    assert list(frow.keys()) == crawl.FESTIVAL_FIELDS
    assert list(lrows[0].keys()) == crawl.LINEUP_FIELDS


def test_lineup_rows_drop_denormalized_columns():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "discovery": "manual",
              "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    lrow = build_lineup_rows(record)[0]
    for dropped in ("university", "year", "festival_name"):
        assert dropped not in lrow


def test_process_row_prefers_sitemap_and_skips_websearch(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_sitemap",
                        lambda u, y: ["https://blog.example.com/entry/2026-연세대학교-축제"])
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())

    def boom(university, year, out_dir):
        raise AssertionError("사이트맵이 성공하면 WebSearch를 부르면 안 됨")

    monkeypatch.setattr(crawl, "discover_cached", boom)
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "ok"
    assert record["discovery"] == "sitemap"
    assert record["url"] == "https://blog.example.com/entry/2026-연세대학교-축제"


def test_process_row_falls_back_to_websearch_when_sitemap_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_sitemap", lambda u, y: [])
    monkeypatch.setattr(crawl, "discover_cached",
                        lambda u, y, o: ["https://found.example.com/post"])
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "ok"
    assert record["discovery"] == "search"


def test_process_row_falls_back_when_sitemap_candidates_all_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_sitemap", lambda u, y: ["https://bad.example.com/x"])
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: ["https://good.example.com/y"])
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())

    seen = []

    def fake_verify(result, university, year):
        seen.append(university)
        return len(seen) > 1          # 첫 후보(사이트맵)는 탈락, 두 번째(검색)는 통과

    monkeypatch.setattr(crawl, "verify", fake_verify)
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "ok"
    assert record["discovery"] == "search"
    assert record["url"] == "https://good.example.com/y"


def test_process_row_no_candidate_when_both_sources_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_sitemap", lambda u, y: [])
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "no_candidate"
    assert record["discovery"] == ""


def test_process_row_transient_discovery_failure_after_sitemap_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "discover_sitemap", lambda u, y: [])
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: None)
    record = process_row(_row(url=None), tmp_path)
    assert record["flag"] == "no_source"
    assert not (tmp_path / "raw" / "연세대학교.json").exists()
