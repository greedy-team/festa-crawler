import csv
import json
from pathlib import Path

import pytest

import crawl
from crawl import (UniversityRow, build_festival_row, build_lineup_rows,
                   process_row, write_csv)
from extract import ExtractError
from fetch import FetchResult
from schema import ExtractionResult, LineupItem


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
        "description": "연세대학교의 대표 축제.",
        "hashtags": ["연세대축제", "아카라카"],
        "external_visitor_policy": "CONDITIONAL",
        "verification_method": "PRE_BOOKING",
        "ticket_type": "PAID", "ticket_open_at": "2026-05-07T14:00:00",
        "admission_raw": "외부인은 예매 후 입장 가능합니다.",
        "instagram_handle": "yonsei_festival",
        "lineup": [
            {"artist_raw": "잔나비", "day": 1},
            {"artist_raw": "십센치", "day": 1},
            {"artist_raw": "시크릿", "day": 2, "is_secret": True},
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
    cached = {"schema_version": 2, "university": "연세대학교", "campus": "신촌캠퍼스",
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
    cached = {"schema_version": 2, "university": "연세대학교", "campus": "옛캠퍼스",
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


def test_csv_headers_match_backend_spec():
    assert crawl.FESTIVAL_FIELDS == [
        "import_key", "host_name", "name", "start_date", "end_date", "venue_name",
        "poster_url", "image_urls", "description", "hashtags",
        "external_visitor_policy", "verification_method", "ticket_type",
        "ticket_open_at", "admission_raw", "source_url", "discovery", "flag",
        "instagram_url",
    ]
    assert crawl.LINEUP_FIELDS == [
        "import_key", "day", "order", "artist_raw", "artist_canonical", "revealed",
    ]


def test_build_rows():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "flag": "ok", "discovery": "manual",
              "poster_image_url": "https://example.com/p.jpg",
              "image_urls": ["https://cdn.example.com/1.jpg", "https://cdn.example.com/2.jpg"],
              "extraction": _extraction().model_dump()}
    frow = build_festival_row(record)
    assert frow["import_key"] == "연세대학교-2026"
    assert frow["host_name"] == "연세대학교"
    assert frow["name"] == "아카라카"
    assert frow["flag"] == "OK"
    assert frow["discovery"] == "MANUAL"
    assert frow["image_urls"] == "https://cdn.example.com/1.jpg|https://cdn.example.com/2.jpg"
    assert frow["hashtags"] == "연세대축제|아카라카"
    assert frow["instagram_url"] == "https://www.instagram.com/yonsei_festival"
    assert frow["start_date"] == "2026-05-21"
    assert frow["end_date"] == "2026-05-23"
    assert frow["venue_name"] == "노천극장"
    assert frow["description"] == "연세대학교의 대표 축제."
    assert frow["external_visitor_policy"] == "CONDITIONAL"
    assert frow["verification_method"] == "PRE_BOOKING"
    assert frow["ticket_type"] == "PAID"
    assert frow["ticket_open_at"] == "2026-05-07T14:00:00"
    assert frow["poster_url"] == "https://example.com/p.jpg"
    assert set(frow) == set(crawl.FESTIVAL_FIELDS)

    lrows = build_lineup_rows(record, {"십센치": "10CM"})
    assert [r["order"] for r in lrows] == [1, 2, 1]      # 일차별로 1부터
    assert lrows[0]["day"] == 1 and lrows[2]["day"] == 2
    assert lrows[1]["artist_canonical"] == "10CM"        # 매핑 적용
    assert lrows[2]["revealed"] == "false"
    assert lrows[2]["artist_raw"] == "" and lrows[2]["artist_canonical"] == ""
    assert set(lrows[0]) == set(crawl.LINEUP_FIELDS)


def test_build_rows_without_extraction():
    record = {"university": "고려대학교", "campus": "안암캠퍼스",
              "region": "서울 성북구", "year": 2026, "url": None, "discovery": "",
              "flag": "no_source", "poster_image_url": None, "extraction": None}
    frow = build_festival_row(record)
    assert frow["flag"] == "NO_SOURCE"
    assert frow["name"] == ""
    assert build_lineup_rows(record, {}) == []


def test_build_lineup_rows_skips_non_ok_festival():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "flag": "mismatch", "discovery": "",
              "poster_image_url": None, "extraction": _extraction().model_dump()}
    assert build_lineup_rows(record, {}) == []


def test_admission_raw_truncated_to_200_chars():
    long_ext = _extraction().model_copy(update={"admission_raw": "가" * 300})
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "flag": "ok", "discovery": "manual",
              "poster_image_url": None, "extraction": long_ext.model_dump()}
    assert len(build_festival_row(record)["admission_raw"]) == 200


def test_build_lineup_rows_day_none_gets_own_order():
    ext = _extraction().model_copy(update={"lineup": [
        LineupItem(artist_raw="잔나비", day=None),
        LineupItem(artist_raw="십센치", day=None),
    ]})
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "flag": "ok", "discovery": "manual",
              "poster_image_url": None, "extraction": ext.model_dump()}
    lrows = build_lineup_rows(record, {})
    assert [r["day"] for r in lrows] == ["", ""]         # 불명은 빈 값 (백엔드에서 INVALID)
    assert [r["order"] for r in lrows] == [1, 2]


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


def test_build_festival_row_includes_instagram_url():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "flag": "ok", "discovery": "manual",
              "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    frow = build_festival_row(record)
    assert frow["instagram_url"] == "https://www.instagram.com/yonsei_festival"
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
    assert frow["discovery"] == "SEARCH"
    assert frow["source_url"] == "https://found.example.com/p"
    assert list(frow.keys()) == crawl.FESTIVAL_FIELDS


def test_process_row_cache_keyed_on_seed_url(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    cached = {"schema_version": 2, "university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구",
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


def test_process_row_recollects_versionless_cache(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    old = {"university": "연세대학교", "campus": "신촌캠퍼스",
           "region": "서울 서대문구", "year": 2026,
           "seed_url": "https://example.com/post", "url": "https://example.com/post",
           "discovery": "manual", "flag": "ok", "poster_image_url": None,
           "extraction": _extraction().model_dump()}          # schema_version 없음 = 구 스키마
    (raw_dir / "연세대학교.json").write_text(json.dumps(old), "utf-8")
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(
        status="ok", body="본문" * 100, image_urls=[]))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())
    record = process_row(_row(), tmp_path)
    assert record["schema_version"] == crawl.SCHEMA_VERSION
    cached = json.loads((raw_dir / "연세대학교.json").read_text("utf-8"))
    assert cached["schema_version"] == crawl.SCHEMA_VERSION   # 새 캐시로 갱신됨


def test_process_row_keeps_old_ok_cache_when_recollect_fails(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    old = {"university": "연세대학교", "campus": "신촌캠퍼스",
           "region": "서울 서대문구", "year": 2026,
           "seed_url": "https://example.com/post", "url": "https://example.com/post",
           "discovery": "manual", "flag": "ok", "poster_image_url": None,
           "extraction": _extraction().model_dump()}
    before = json.dumps(old)
    (raw_dir / "연세대학교.json").write_text(before, "utf-8")
    monkeypatch.setattr(crawl, "fetch_body",
                        lambda url: FetchResult(status="fetch_failed", error="410"))
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "ok"                             # 구 데이터 유지
    assert record["extraction"] is not None
    after = (raw_dir / "연세대학교.json").read_text("utf-8")
    assert after == before                                    # 캐시 파일은 그대로 — 다음 실행에서 재시도


def test_process_row_keeps_old_ok_cache_on_transient_discovery_failure(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    old = {"university": "연세대학교", "campus": "신촌캠퍼스",
           "region": "서울 서대문구", "year": 2026,
           "seed_url": "https://example.com/post", "url": "https://example.com/post",
           "discovery": "manual", "flag": "ok", "poster_image_url": None,
           "extraction": _extraction().model_dump()}
    before = json.dumps(old)
    (raw_dir / "연세대학교.json").write_text(before, "utf-8")
    monkeypatch.setattr(crawl, "fetch_body",
                        lambda url: FetchResult(status="fetch_failed", error="410"))
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: None)   # 탐색 자체 실패(조기 반환 경로)
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "ok"                             # 구 데이터 유지
    assert record["extraction"] is not None
    after = (raw_dir / "연세대학교.json").read_text("utf-8")
    assert after == before                                    # 캐시 파일은 그대로 — 다음 실행에서 재시도


def test_process_row_keeps_old_ok_cache_on_mismatch(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    old = {"university": "연세대학교", "campus": "신촌캠퍼스",
           "region": "서울 서대문구", "year": 2026,
           "seed_url": "https://example.com/post", "url": "https://example.com/post",
           "discovery": "manual", "flag": "ok", "poster_image_url": None,
           "extraction": _extraction().model_dump()}
    before = json.dumps(old)
    (raw_dir / "연세대학교.json").write_text(before, "utf-8")
    wrong = _extraction().model_copy(update={"year": 2024})
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: wrong)
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(), tmp_path)
    assert record["flag"] == "ok"                             # mismatch가 구 데이터를 덮지 않는다
    assert record["extraction"] is not None
    after = (raw_dir / "연세대학교.json").read_text("utf-8")
    assert after == before                                    # 캐시 파일은 그대로 — 다음 실행에서 재시도


def test_process_row_no_fallback_when_seed_url_changed(tmp_path, monkeypatch):
    """시드 url이 바뀐 경우는 schema_version 폴백 대상이 아니다 — 재수집 실패가 그대로 남아야 한다."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    old = {"schema_version": 2, "university": "연세대학교", "campus": "신촌캠퍼스",
           "region": "서울 서대문구", "year": 2026,
           "seed_url": "https://old.example.com/post", "url": "https://old.example.com/post",
           "discovery": "manual", "flag": "ok", "poster_image_url": None,
           "extraction": _extraction().model_dump()}
    (raw_dir / "연세대학교.json").write_text(json.dumps(old), "utf-8")
    monkeypatch.setattr(crawl, "fetch_body",
                        lambda url: FetchResult(status="fetch_failed", error="404"))
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    record = process_row(_row(), tmp_path)   # _row()의 url은 캐시의 seed_url과 다르다
    assert record["flag"] == "fetch_failed"   # 폴백 없이 실패 flag 그대로


def test_process_row_new_records_carry_schema_version(tmp_path, monkeypatch):
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(
        status="ok", body="본문" * 100, image_urls=["https://cdn.example.com/1.jpg"]))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())
    record = process_row(_row(), tmp_path)
    assert record["schema_version"] == crawl.SCHEMA_VERSION
    assert record["image_urls"] == ["https://cdn.example.com/1.jpg"]


def test_import_key_format():
    assert crawl.import_key("연세대학교", 2026) == "연세대학교-2026"


def test_import_key_links_festival_and_lineup():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "discovery": "manual",
              "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    frow = build_festival_row(record)
    lrows = build_lineup_rows(record, {})
    assert frow["import_key"] == "연세대학교-2026"
    assert [r["import_key"] for r in lrows] == ["연세대학교-2026"] * 3
    assert list(frow.keys()) == crawl.FESTIVAL_FIELDS
    assert list(lrows[0].keys()) == crawl.LINEUP_FIELDS


def test_lineup_rows_drop_denormalized_columns():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "discovery": "manual",
              "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    lrow = build_lineup_rows(record, {})[0]
    for dropped in ("day_label", "date", "time", "source_url", "is_secret"):
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


def _write_seed(dir_path: Path, year: int, rows: list[dict]) -> Path:
    path = dir_path / f"universities-{year}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f, fieldnames=["university", "campus", "region", "year", "url"])
        w.writeheader()
        w.writerows(rows)
    return path


def _seed_row(year: int = 2026, url: str = "") -> dict:
    return {"university": "연세대학교", "campus": "신촌캠퍼스",
            "region": "서울 서대문구", "year": str(year), "url": url}


def test_run_writes_into_year_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_seed(tmp_path, 2026, [_seed_row()])
    monkeypatch.setattr(crawl, "discover_sitemap", lambda u, y: [])
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    base = tmp_path / "output"

    crawl.run(2026, base)

    assert (base / "2026" / "festivals.csv").exists()
    assert (base / "2026" / "lineup.csv").exists()
    assert not (base / "festivals.csv").exists()


def test_run_rejects_year_mismatch_in_seed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_seed(tmp_path, 2027, [_seed_row(year=2026)])   # 파일명은 2027, 내용은 2026

    with pytest.raises(SystemExit) as e:
        crawl.run(2027, tmp_path / "output")
    assert "2026" in str(e.value)


def test_run_missing_seed_lists_available(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_seed(tmp_path, 2026, [_seed_row()])

    with pytest.raises(SystemExit) as e:
        crawl.run(2027, tmp_path / "output")
    assert "universities-2026.csv" in str(e.value)


def test_run_does_not_touch_other_year(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "output"
    other = base / "2027"
    other.mkdir(parents=True)
    (other / "festivals.csv").write_text("건드리지 마시오", encoding="utf-8")
    _write_seed(tmp_path, 2026, [_seed_row()])
    monkeypatch.setattr(crawl, "discover_sitemap", lambda u, y: [])
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])

    crawl.run(2026, base)

    assert (other / "festivals.csv").read_text(encoding="utf-8") == "건드리지 마시오"


def test_build_lineup_rows_applies_mapping():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "discovery": "manual",
              "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    lrows = build_lineup_rows(record, {"잔나비": "JANNABI"})
    assert lrows[0]["artist_canonical"] == "JANNABI"
    assert lrows[0]["artist_raw"] == "잔나비"     # 원문 표기는 보존


def test_build_lineup_rows_falls_back_to_raw_when_unmapped():
    record = {"university": "연세대학교", "campus": "신촌캠퍼스",
              "region": "서울 서대문구", "year": 2026,
              "url": "https://example.com/post", "discovery": "manual",
              "flag": "ok", "poster_image_url": None,
              "extraction": _extraction().model_dump()}
    lrows = build_lineup_rows(record, {})
    assert lrows[0]["artist_canonical"] == "잔나비"


def test_rerun_keeps_normalized_names(tmp_path, monkeypatch):
    """이슈 #14의 회귀 방어 — crawl을 다시 돌려도 정규화가 유지되어야 한다."""
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "output"
    _write_seed(tmp_path, 2026, [_seed_row(url="https://example.com/post")])
    crawl.save_artist_mapping(base, {"잔나비": "JANNABI"})
    monkeypatch.setattr(crawl, "fetch_body", lambda url: FetchResult(
        status="ok", body="본문" * 100))
    monkeypatch.setattr(crawl, "extract", lambda body, u, y, cands=None: _extraction())

    crawl.run(2026, base)
    crawl.run(2026, base)          # 재실행 — 여기서 지워지면 안 된다

    with open(base / "2026" / "lineup.csv", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["artist_canonical"] == "JANNABI"


def test_load_artist_mapping_missing_is_empty(tmp_path):
    assert crawl.load_artist_mapping(tmp_path) == {}


def test_save_and_load_artist_mapping_roundtrip(tmp_path):
    crawl.save_artist_mapping(tmp_path, {"십센치": "10CM"})
    assert crawl.load_artist_mapping(tmp_path) == {"십센치": "10CM"}


def test_load_artist_mapping_corrupt_aborts(tmp_path):
    """조용히 빈 매핑으로 넘어가면 정규화 결과가 통째로 사라진다 — 반드시 중단해야 한다."""
    (tmp_path / "artist_mapping.json").write_text("{깨진 JSON", encoding="utf-8")
    with pytest.raises(SystemExit):
        crawl.load_artist_mapping(tmp_path)


def test_load_artist_mapping_non_object_aborts(tmp_path):
    (tmp_path / "artist_mapping.json").write_text('["배열은 안 됨"]', encoding="utf-8")
    with pytest.raises(SystemExit):
        crawl.load_artist_mapping(tmp_path)


def test_load_artist_mapping_non_string_value_aborts(tmp_path):
    """손으로 고치는 파일이라 오타가 난다 — 문자열이 아니면 그대로 CSV에 실린다."""
    (tmp_path / "artist_mapping.json").write_text(
        '{"십센치": ["10CM"], "잔나비": 123}', encoding="utf-8")
    with pytest.raises(SystemExit):
        crawl.load_artist_mapping(tmp_path)


def test_run_aborts_on_old_flat_output(tmp_path, monkeypatch):
    """연도 폴더 없는 예전 레이아웃 — 그냥 두면 29곳을 조용히 다시 수집한다."""
    monkeypatch.chdir(tmp_path)
    _write_seed(tmp_path, 2026, [_seed_row()])
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    base = tmp_path / "output"
    (base / "raw").mkdir(parents=True)
    (base / "festivals.csv").write_text("예전 레이아웃", encoding="utf-8")

    with pytest.raises(SystemExit) as e:
        crawl.run(2026, base)
    assert "artist_mapping.json" in str(e.value)   # 마이그레이션 절차가 담겨 있다
    assert not (base / "2026").exists()            # 빈 연도 폴더를 만들지 않는다


def test_run_guard_ignores_fresh_clone_and_year_layout(tmp_path, monkeypatch):
    """가드는 옛 평면 레이아웃에만 걸린다 — output/이 없어도, 이미 옮겼어도 그냥 돈다."""
    monkeypatch.chdir(tmp_path)
    _write_seed(tmp_path, 2026, [_seed_row()])
    monkeypatch.setattr(crawl, "discover_cached", lambda u, y, o: [])
    base = tmp_path / "output"

    crawl.run(2026, base)      # output/ 자체가 없는 새 클론
    crawl.run(2026, base)      # 이제 output/2026/festivals.csv 가 있다

    assert (base / "2026" / "festivals.csv").exists()
