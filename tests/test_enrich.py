import csv
import json
from pathlib import Path

import enrich
from crawl import LINEUP_FIELDS, write_csv
from schema import EnrichResult

ENRICH_JSON = """{
  "mapping": {"십센치": "10CM", "잔나비": "잔나비"},
  "artists": [
    {"name_canonical": "10CM", "name_en": "10CM", "real_name": "권정열",
     "category": "가수", "aliases": ["십센치"], "needs_review": false},
    {"name_canonical": "잔나비", "name_en": "JANNABI", "real_name": null,
     "category": "밴드", "aliases": [], "needs_review": false}
  ]
}"""


def _seed_output(out_dir: Path) -> None:
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "연세대학교.json").write_text(json.dumps({
        "university": "연세대학교", "campus": "신촌캠퍼스", "region": "서울 서대문구",
        "year": 2026, "url": "https://example.com/post", "flag": "ok",
        "poster_image_url": None,
        "extraction": {
            "found": True, "university_name": "연세대학교", "year": 2026,
            "festival_name": "아카라카", "start_date": None, "end_date": None,
            "venue_name": None, "outsider_admission": None, "ticket_info": None,
            "lineup": [
                {"artist_raw": "십센치", "day_label": "1일차", "date": None,
                 "time": None, "is_secret": False},
                {"artist_raw": "잔나비", "day_label": "1일차", "date": None,
                 "time": None, "is_secret": False},
                {"artist_raw": "시크릿", "day_label": "2일차", "date": None,
                 "time": None, "is_secret": True},
            ],
        },
    }, ensure_ascii=False), "utf-8")
    write_csv(out_dir / "lineup.csv", LINEUP_FIELDS, [
        {"festival_id": "연세대학교-2026",
         "day_label": "1일차", "date": "", "time": "",
         "artist_canonical": "십센치", "artist_raw": "십센치",
         "is_secret": "false", "source_url": "https://example.com/post"},
    ])


def test_collect_raw_names_dedup_and_skip_secret(tmp_path):
    _seed_output(tmp_path)
    names = enrich.collect_raw_names(tmp_path)
    assert names == ["십센치", "잔나비"]   # 정렬됨, '시크릿'(is_secret) 제외


def test_normalize_parses_llm_response(monkeypatch):
    monkeypatch.setattr(enrich, "call_claude", lambda prompt, timeout=120: ENRICH_JSON)
    result = enrich.normalize(["십센치", "잔나비"])
    assert isinstance(result, EnrichResult)
    assert result.mapping["십센치"] == "10CM"


def test_enrich_updates_lineup_and_writes_artists(tmp_path, monkeypatch):
    _seed_output(tmp_path)
    monkeypatch.setattr(enrich, "call_claude", lambda prompt, timeout=120: ENRICH_JSON)
    enrich.enrich(tmp_path)

    with open(tmp_path / "lineup.csv", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["artist_canonical"] == "10CM"
    assert rows[0]["artist_raw"] == "십센치"     # 원문 표기는 보존

    with open(tmp_path / "artists.csv", newline="", encoding="utf-8-sig") as f:
        artists = {r["name_canonical"]: r for r in csv.DictReader(f)}
    assert artists["10CM"]["real_name"] == "권정열"
    assert artists["10CM"]["aliases"] == "십센치"
    assert artists["잔나비"]["needs_review"] == "false"


def test_normalize_uses_extended_timeout(monkeypatch):
    captured = {}

    def fake(prompt, timeout=120):
        captured["timeout"] = timeout
        return ENRICH_JSON

    monkeypatch.setattr(enrich, "call_claude", fake)
    enrich.normalize(["십센치"])
    assert captured["timeout"] == enrich.ENRICH_TIMEOUT_SECONDS


def test_enrich_no_names_is_noop(tmp_path, monkeypatch):
    (tmp_path / "raw").mkdir(parents=True)

    def boom(prompt, timeout=120):
        raise AssertionError("아티스트가 없으면 LLM을 호출하면 안 됨")

    monkeypatch.setattr(enrich, "call_claude", boom)
    enrich.enrich(tmp_path)   # 예외 없이 종료
    assert not (tmp_path / "artists.csv").exists()
