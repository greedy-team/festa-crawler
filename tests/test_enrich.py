import csv
import json
from pathlib import Path

import pytest

import crawl
import enrich
from crawl import LINEUP_FIELDS, write_csv
from schema import EnrichResult
from test_crawl import _seed_row, _write_seed

ENRICH_JSON = """{
  "mapping": {"십센치": "10CM", "잔나비": "잔나비"},
  "artists": [
    {"name": "10CM", "other_names": ["십센치"], "name_en": "10CM", "real_name": "권정열",
     "category": "가수", "needs_review": false},
    {"name": "잔나비", "other_names": [], "name_en": "JANNABI", "real_name": null,
     "category": "밴드", "needs_review": false}
  ]
}"""


def _seed_year(base_dir: Path, year: int, names: list[str]) -> None:
    """연도 폴더 하나에 raw 캐시와 lineup.csv를 심는다."""
    ydir = base_dir / str(year)
    raw_dir = ydir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "연세대학교.json").write_text(json.dumps({
        "university": "연세대학교", "campus": "신촌캠퍼스", "region": "서울 서대문구",
        "year": year, "url": "https://example.com/post", "flag": "ok",
        "poster_image_url": None,
        "extraction": {
            "found": True, "university_name": "연세대학교", "year": year,
            "festival_name": "아카라카", "start_date": None, "end_date": None,
            "venue_name": None, "outsider_admission": None, "ticket_info": None,
            "lineup": [
                {"artist_raw": n, "day_label": "1일차", "date": None,
                 "time": None, "is_secret": False} for n in names
            ] + [{"artist_raw": "시크릿", "day_label": "2일차", "date": None,
                  "time": None, "is_secret": True}],
        },
    }, ensure_ascii=False), "utf-8")
    write_csv(ydir / "lineup.csv", LINEUP_FIELDS, [
        {"festival_id": f"연세대학교-{year}", "day_label": "1일차",
         "date": "", "time": "", "artist_canonical": n, "artist_raw": n,
         "is_secret": "false", "source_url": "https://example.com/post"}
        for n in names
    ])


def test_collect_raw_names_spans_years(tmp_path):
    _seed_year(tmp_path, 2026, ["십센치"])
    _seed_year(tmp_path, 2027, ["잔나비"])
    assert enrich.collect_raw_names(tmp_path) == ["십센치", "잔나비"]


def test_enrich_saves_mapping(tmp_path, monkeypatch):
    _seed_year(tmp_path, 2026, ["십센치", "잔나비"])
    monkeypatch.setattr(enrich, "call_claude",
                        lambda prompt, timeout=120: ENRICH_JSON)
    enrich.enrich(tmp_path)
    assert crawl.load_artist_mapping(tmp_path)["십센치"] == "10CM"


def test_enrich_skips_names_already_mapped(tmp_path, monkeypatch):
    _seed_year(tmp_path, 2026, ["십센치", "잔나비"])
    crawl.save_artist_mapping(tmp_path, {"십센치": "10CM", "잔나비": "잔나비"})

    def boom(prompt, timeout=120):
        raise AssertionError("전부 매핑에 있으면 LLM을 부르면 안 됨")

    monkeypatch.setattr(enrich, "call_claude", boom)
    enrich.enrich(tmp_path)      # 예외 없이 종료


def test_enrich_sends_only_new_names_with_known_canonicals(tmp_path, monkeypatch):
    _seed_year(tmp_path, 2026, ["십센치", "잔나비"])
    crawl.save_artist_mapping(tmp_path, {"십센치": "10CM"})
    captured = {}

    def fake(prompt, timeout=120):
        captured["prompt"] = prompt
        return ENRICH_JSON

    monkeypatch.setattr(enrich, "call_claude", fake)
    enrich.enrich(tmp_path)

    body = captured["prompt"]
    assert "- 잔나비" in body          # 새 이름은 목록에 있다
    assert "\n- 십센치" not in body    # 이미 매핑된 이름은 목록에 없다
    assert "10CM" in body             # 기존 정식 표기는 참고로 전달된다


def test_enrich_updates_every_year_lineup(tmp_path, monkeypatch):
    _seed_year(tmp_path, 2026, ["십센치"])
    _seed_year(tmp_path, 2027, ["십센치"])
    monkeypatch.setattr(enrich, "call_claude",
                        lambda prompt, timeout=120: ENRICH_JSON)
    enrich.enrich(tmp_path)

    for year in (2026, 2027):
        with open(tmp_path / str(year) / "lineup.csv",
                  newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["artist_canonical"] == "10CM", f"{year} 갱신 안 됨"


def test_enrich_accumulates_artists_csv(tmp_path, monkeypatch):
    _seed_year(tmp_path, 2026, ["십센치"])
    write_csv(tmp_path / "artists.csv", enrich.ARTIST_FIELDS, [
        {"name_canonical": "아이유", "name_en": "IU", "real_name": "이지은",
         "category": "가수", "aliases": "", "needs_review": "false"},
    ])
    monkeypatch.setattr(enrich, "call_claude",
                        lambda prompt, timeout=120: ENRICH_JSON)
    enrich.enrich(tmp_path)

    with open(tmp_path / "artists.csv", newline="", encoding="utf-8-sig") as f:
        names = {r["name_canonical"] for r in csv.DictReader(f)}
    assert names == {"아이유", "10CM", "잔나비"}    # 기존 행이 살아 있다


def test_collect_raw_names_dedup_and_skip_secret(tmp_path):
    _seed_year(tmp_path, 2026, ["십센치", "잔나비"])
    names = enrich.collect_raw_names(tmp_path)
    assert names == ["십센치", "잔나비"]   # 정렬됨, '시크릿'(is_secret) 제외


def test_normalize_parses_llm_response(monkeypatch):
    monkeypatch.setattr(enrich, "call_claude", lambda prompt, timeout=120: ENRICH_JSON)
    result = enrich.normalize(["십센치", "잔나비"], [])
    assert isinstance(result, EnrichResult)
    assert result.mapping["십센치"] == "10CM"


def test_enrich_updates_lineup_and_writes_artists(tmp_path, monkeypatch):
    _seed_year(tmp_path, 2026, ["십센치"])
    monkeypatch.setattr(enrich, "call_claude", lambda prompt, timeout=120: ENRICH_JSON)
    enrich.enrich(tmp_path)

    with open(tmp_path / "2026" / "lineup.csv", newline="", encoding="utf-8-sig") as f:
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
    enrich.normalize(["십센치"], [])
    assert captured["timeout"] == enrich.ENRICH_TIMEOUT_SECONDS


def test_enrich_no_names_is_noop(tmp_path, monkeypatch):
    (tmp_path / "2026" / "raw").mkdir(parents=True)

    def boom(prompt, timeout=120):
        raise AssertionError("아티스트가 없으면 LLM을 호출하면 안 됨")

    monkeypatch.setattr(enrich, "call_claude", boom)
    enrich.enrich(tmp_path)   # 예외 없이 종료
    assert not (tmp_path / "artists.csv").exists()


def test_enrich_old_schema_lineup_fails_before_llm(tmp_path, monkeypatch):
    _seed_year(tmp_path, 2026, ["십센치"])   # raw/*.json은 새 스키마 그대로 — collect_raw_names는 영향 없음
    old_header = ["university", "year", "festival_name", "day_label", "date", "time",
                  "artist_canonical", "artist_raw", "is_secret", "source_url"]
    with open(tmp_path / "2026" / "lineup.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=old_header)
        w.writeheader()
        w.writerow({"university": "연세대학교", "year": "2026", "festival_name": "아카라카",
                    "day_label": "1일차", "date": "", "time": "",
                    "artist_canonical": "십센치", "artist_raw": "십센치",
                    "is_secret": "false", "source_url": "https://example.com/post"})

    def boom(prompt, timeout=120):
        raise AssertionError("스키마 검증 전에 LLM을 호출하면 안 됨")

    monkeypatch.setattr(enrich, "call_claude", boom)
    with pytest.raises(SystemExit):
        enrich.enrich(tmp_path)


def test_enrich_refreshes_lineup_even_when_no_new_names(tmp_path, monkeypatch):
    # lineup.csv의 artist_canonical은 seed 시점의 원문("십센치")으로 고정된다.
    _seed_year(tmp_path, 2026, ["십센치"])
    # 매핑은 이미 그 이름을 다른 정식 표기("10CM")로 갖고 있다 — 예: 사람이 매핑 파일을 손으로 고친 경우.
    crawl.save_artist_mapping(tmp_path, {"십센치": "10CM"})

    def boom(prompt, timeout=120):
        raise AssertionError("모든 이름이 매핑에 있으면 LLM을 부르면 안 됨")

    monkeypatch.setattr(enrich, "call_claude", boom)
    enrich.enrich(tmp_path)   # 예외 없이 종료

    with open(tmp_path / "2026" / "lineup.csv", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["artist_canonical"] == "10CM"   # 매핑 값으로 갱신됨 (LLM 없이도)


def test_enrich_ignores_mapping_keys_not_sent(tmp_path, monkeypatch):
    """LLM이 안 물어본 이름까지 매핑에 넣어도 확정된 표기를 덮으면 안 된다.

    프롬프트가 기존 정식 표기 목록을 보여주므로 모델이 그 키를 되돌려줄 수 있다.
    한 번 덮이면 그 이름은 다시 LLM에 가지 않으니 잘못된 표기가 영구히 굳는다.
    """
    _seed_year(tmp_path, 2026, ["십센치", "잔나비"])
    crawl.save_artist_mapping(tmp_path, {"십센치": "10CM"})
    # 새 이름은 "잔나비" 하나뿐인데 응답이 기존 키("십센치")까지 다시 매핑한다
    rogue = json.dumps({
        "mapping": {"잔나비": "JANNABI", "십센치": "십센치"},
        "artists": [{"name": "JANNABI", "other_names": [], "name_en": "JANNABI", "real_name": None,
                     "category": "밴드", "needs_review": False}],
    }, ensure_ascii=False)
    monkeypatch.setattr(enrich, "call_claude", lambda prompt, timeout=120: rogue)
    enrich.enrich(tmp_path)

    assert crawl.load_artist_mapping(tmp_path)["십센치"] == "10CM"   # 확정 표기 유지
    with open(tmp_path / "2026" / "lineup.csv", newline="", encoding="utf-8-sig") as f:
        canonical = {r["artist_raw"]: r["artist_canonical"] for r in csv.DictReader(f)}
    assert canonical["십센치"] == "10CM"
    assert canonical["잔나비"] == "JANNABI"     # 물어본 이름은 정상 반영


def test_enrich_then_crawl_keeps_normalized_names(tmp_path, monkeypatch):
    """이슈 #14의 실제 순서 — enrich가 정한 표기가 crawl 재실행 뒤에도 lineup.csv에 남는다."""
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "output"
    _seed_year(base, 2026, ["십센치"])
    _write_seed(tmp_path, 2026, [_seed_row()])
    monkeypatch.setattr(enrich, "call_claude", lambda prompt, timeout=120: ENRICH_JSON)

    def boom(url):
        raise AssertionError("raw 캐시가 있으므로 fetch하면 안 됨")

    monkeypatch.setattr(crawl, "fetch_body", boom)

    enrich.enrich(base)
    crawl.run(2026, base)

    with open(base / "2026" / "lineup.csv", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["artist_raw"] == "십센치"
    assert rows[0]["artist_canonical"] == "10CM"
