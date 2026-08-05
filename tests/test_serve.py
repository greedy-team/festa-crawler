import csv

import pytest

import serve


def _write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def test_read_csv_missing_file_is_empty(tmp_path):
    assert serve.read_csv(tmp_path / "nope.csv") == []


def test_load_data_reads_three_files(tmp_path):
    _write(tmp_path / "festivals.csv", ["festival_id", "flag"],
           [{"festival_id": "연세대학교-2026", "flag": "ok"}])
    _write(tmp_path / "lineup.csv", ["festival_id", "artist_raw"],
           [{"festival_id": "연세대학교-2026", "artist_raw": "잔나비"}])
    data = serve.load_data(tmp_path)
    assert data["festivals"][0]["flag"] == "ok"
    assert data["lineup"][0]["artist_raw"] == "잔나비"
    assert data["artists"] == []          # enrich 전이면 빈 목록이 정상


def test_load_data_all_missing_is_empty(tmp_path):
    assert serve.load_data(tmp_path) == {"festivals": [], "lineup": [], "artists": []}


def test_load_data_raises_when_csv_is_mid_write(tmp_path, monkeypatch):
    _write(tmp_path / "festivals.csv", ["festival_id"], [{"festival_id": "x"}])

    def boom(*args, **kwargs):
        raise csv.Error("쓰는 중")

    monkeypatch.setattr(serve.csv, "DictReader", boom)
    with pytest.raises(serve.CsvUnreadable):
        serve.load_data(tmp_path)


def _never(script):
    raise AssertionError("검증에 실패한 요청은 잡을 시작하면 안 됨")


def _seed(tmp_path):
    path = tmp_path / "universities.csv"
    _write(path, ["university", "campus", "region", "year", "url"],
           [{"university": "연세대학교", "campus": "신촌캠퍼스",
             "region": "서울 서대문구", "year": "2026", "url": ""}])
    return path


def test_allowed_universities_from_seed(tmp_path):
    assert serve.load_allowed_universities(_seed(tmp_path)) == {"연세대학교"}


def test_run_rejects_unknown_job(tmp_path):
    status, body = serve.handle_run({"job": "rm"}, tmp_path, {"연세대학교"}, start=_never)
    assert status == 400
    assert "job" in body["error"]


def test_run_rejects_university_not_in_seed(tmp_path):
    status, body = serve.handle_run(
        {"job": "crawl", "university": "없는대학교"}, tmp_path, {"연세대학교"}, start=_never)
    assert status == 400


def test_run_rejects_path_traversal_without_touching_files(tmp_path):
    out = tmp_path / "output"
    (out / "raw").mkdir(parents=True)
    victim = out / "victim.json"          # out/raw/../victim.json 이 가리키는 곳
    victim.write_text("{}", encoding="utf-8")
    status, body = serve.handle_run(
        {"job": "crawl", "university": "../victim"}, out, {"연세대학교"}, start=_never)
    assert status == 400
    assert victim.exists()                # 경로 조립에 도달하지 않았다


def test_run_rejects_university_with_enrich(tmp_path):
    status, body = serve.handle_run(
        {"job": "enrich", "university": "연세대학교"}, tmp_path, {"연세대학교"}, start=_never)
    assert status == 400


def test_run_clears_raw_cache_only(tmp_path):
    out = tmp_path / "output"
    (out / "raw").mkdir(parents=True)
    (out / "discovered").mkdir(parents=True)
    (out / "raw" / "연세대학교.json").write_text("{}", encoding="utf-8")
    (out / "discovered" / "연세대학교.json").write_text("{}", encoding="utf-8")
    started = []
    status, body = serve.handle_run(
        {"job": "crawl", "university": "연세대학교"}, out, {"연세대학교"},
        start=started.append)
    assert status == 200
    assert started == ["crawl.py"]
    assert not (out / "raw" / "연세대학교.json").exists()
    assert (out / "discovered" / "연세대학교.json").exists()   # 탐색 캐시는 유지


def test_run_rediscover_clears_both_caches(tmp_path):
    out = tmp_path / "output"
    (out / "raw").mkdir(parents=True)
    (out / "discovered").mkdir(parents=True)
    (out / "raw" / "연세대학교.json").write_text("{}", encoding="utf-8")
    (out / "discovered" / "연세대학교.json").write_text("{}", encoding="utf-8")
    status, _ = serve.handle_run(
        {"job": "crawl", "university": "연세대학교", "rediscover": True}, out,
        {"연세대학교"}, start=lambda script: None)
    assert status == 200
    assert not (out / "raw" / "연세대학교.json").exists()
    assert not (out / "discovered" / "연세대학교.json").exists()


def test_run_missing_cache_files_is_fine(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    status, _ = serve.handle_run(
        {"job": "crawl", "university": "연세대학교", "rediscover": True}, out,
        {"연세대학교"}, start=lambda script: None)
    assert status == 200          # 파일이 없어도 예외 없이 통과


def test_run_conflicts_while_job_running(tmp_path, monkeypatch):
    monkeypatch.setattr(serve.JOB, "running", lambda: True)
    status, body = serve.handle_run({"job": "crawl"}, tmp_path, set(), start=_never)
    assert status == 409
