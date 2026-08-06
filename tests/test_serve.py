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
    data = serve.load_data(tmp_path, tmp_path)
    assert data["festivals"][0]["flag"] == "ok"
    assert data["lineup"][0]["artist_raw"] == "잔나비"
    assert data["artists"] == []          # enrich 전이면 빈 목록이 정상


def test_load_data_all_missing_is_empty(tmp_path):
    assert serve.load_data(tmp_path, tmp_path) == {"festivals": [], "lineup": [], "artists": []}


def test_load_data_raises_when_csv_is_mid_write(tmp_path, monkeypatch):
    _write(tmp_path / "festivals.csv", ["festival_id"], [{"festival_id": "x"}])

    def boom(*args, **kwargs):
        raise csv.Error("쓰는 중")

    monkeypatch.setattr(serve.csv, "DictReader", boom)
    with pytest.raises(serve.CsvUnreadable):
        serve.load_data(tmp_path, tmp_path)


def test_load_data_reads_artists_from_base_dir(tmp_path):
    # artists.csv는 연도 공통이라 out_dir(연도 폴더)이 아니라 base_dir(output/)에 있다.
    # base_dir을 out_dir.parent와 다른 경로로 둬서, load_data가 base_dir 인자 대신
    # out_dir.parent를 암묵적으로 계산하는 지름길을 쓰면 반드시 실패하게 만든다.
    out_dir = tmp_path / "output" / "2026"
    base_dir = tmp_path / "common"
    _write(out_dir / "festivals.csv", ["festival_id"], [{"festival_id": "x"}])
    _write(out_dir / "lineup.csv", ["festival_id"], [{"festival_id": "x"}])
    _write(base_dir / "artists.csv", ["artist_canonical"], [{"artist_canonical": "잔나비"}])
    data = serve.load_data(out_dir, base_dir)
    assert data["festivals"] != []
    assert data["lineup"] != []
    assert data["artists"][0]["artist_canonical"] == "잔나비"


def _never(argv):
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
    status, body = serve.handle_run(
        {"job": "rm"}, tmp_path, {"연세대학교"}, start=_never, year=2026)
    assert status == 400
    assert "job" in body["error"]


def test_run_rejects_university_not_in_seed(tmp_path):
    status, body = serve.handle_run(
        {"job": "crawl", "university": "없는대학교"}, tmp_path, {"연세대학교"}, start=_never,
        year=2026)
    assert status == 400


def test_run_rejects_path_traversal_without_touching_files(tmp_path):
    out = tmp_path / "output"
    (out / "raw").mkdir(parents=True)
    victim = out / "victim.json"          # out/raw/../victim.json 이 가리키는 곳
    victim.write_text("{}", encoding="utf-8")
    status, body = serve.handle_run(
        {"job": "crawl", "university": "../victim"}, out, {"연세대학교"}, start=_never,
        year=2026)
    assert status == 400
    assert victim.exists()                # 경로 조립에 도달하지 않았다


def test_run_rejects_university_with_enrich(tmp_path):
    status, body = serve.handle_run(
        {"job": "enrich", "university": "연세대학교"}, tmp_path, {"연세대학교"}, start=_never,
        year=2026)
    assert status == 400


def test_run_clears_raw_cache_only(tmp_path):
    out = tmp_path / "output"
    (out / "raw").mkdir(parents=True)
    (out / "discovered").mkdir(parents=True)
    (out / "raw" / "연세대학교.json").write_text("{}", encoding="utf-8")
    (out / "discovered" / "연세대학교.json").write_text("{}", encoding="utf-8")
    started = []

    def start(argv):
        started.append(argv)
        return True

    status, body = serve.handle_run(
        {"job": "crawl", "university": "연세대학교"}, out, {"연세대학교"},
        start=start, year=2026)
    assert status == 200
    assert started == [["crawl.py", "--year", "2026"]]
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
        {"연세대학교"}, start=lambda argv: True, year=2026)
    assert status == 200
    assert not (out / "raw" / "연세대학교.json").exists()
    assert not (out / "discovered" / "연세대학교.json").exists()


def test_run_missing_cache_files_is_fine(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    status, _ = serve.handle_run(
        {"job": "crawl", "university": "연세대학교", "rediscover": True}, out,
        {"연세대학교"}, start=lambda argv: True, year=2026)
    assert status == 200          # 파일이 없어도 예외 없이 통과


def test_run_conflicts_while_job_running(tmp_path, monkeypatch):
    monkeypatch.setattr(serve.JOB, "running", lambda: True)
    status, body = serve.handle_run(
        {"job": "crawl"}, tmp_path, set(), start=_never, year=2026)
    assert status == 409


def test_run_conflicts_when_start_loses_race(tmp_path):
    # running()은 False를 보고했지만 start()가 실제 시작 시점에 경합에서 졌다고 보고하는 경우.
    # start()의 반환값이 최종 판정이어야 한다.
    status, body = serve.handle_run(
        {"job": "crawl"}, tmp_path, set(), start=lambda argv: False, year=2026)
    assert status == 409


class _FlipFlopProc:
    """poll()을 부를 때마다 다른 값을 반환한다 — snapshot()이 두 번 부르면 모순되는
    (running=True, returncode=0) 같은 결과가 나온다는 걸 증명하는 가짜 프로세스."""

    def __init__(self) -> None:
        self.calls = 0

    def poll(self):
        self.calls += 1
        return None if self.calls == 1 else 0


def test_job_snapshot_polls_once_and_fields_agree():
    job = serve.Job()
    job._lines = ["a", "b"]
    job._proc = _FlipFlopProc()
    snap = job.snapshot(0)
    assert job._proc.calls == 1
    assert snap == {"lines": ["a", "b"], "running": True, "returncode": None}


def test_parse_from_index_absent_is_zero():
    assert serve.parse_from_index("") == 0


def test_parse_from_index_zero():
    assert serve.parse_from_index("from=0") == 0


def test_parse_from_index_positive():
    assert serve.parse_from_index("from=5") == 5


def test_parse_from_index_non_numeric_is_none():
    assert serve.parse_from_index("from=abc") is None


def test_parse_from_index_empty_value_is_zero():
    assert serve.parse_from_index("from=") == 0


def test_run_passes_year_to_crawl(tmp_path):
    started = []

    def start(argv):
        started.append(argv)
        return True

    status, _ = serve.handle_run(
        {"job": "crawl"}, tmp_path, set(), start=start, year=2027)
    assert status == 200
    assert started == [["crawl.py", "--year", "2027"]]


def test_run_enrich_gets_no_year(tmp_path):
    started = []

    def start(argv):
        started.append(argv)
        return True

    status, _ = serve.handle_run(
        {"job": "enrich"}, tmp_path, set(), start=start, year=2027)
    assert status == 200
    assert started == [["enrich.py"]]
