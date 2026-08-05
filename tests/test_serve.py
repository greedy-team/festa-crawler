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
