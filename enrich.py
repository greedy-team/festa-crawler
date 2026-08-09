"""후처리: 아티스트 표기 정규화 + 마스터 생성 (LLM 1콜)."""
import argparse
import csv
import json
from pathlib import Path

from pydantic import ValidationError

from crawl import (LINEUP_FIELDS, OUTPUT_BASE, load_artist_mapping,
                   save_artist_mapping, write_csv)
from extract import ExtractError, _extract_json, call_claude
from schema import ArtistMaster, EnrichResult, GenreResult

ARTIST_FIELDS = ["name", "other_names", "genre", "image_url", "needs_review"]
OLD_ARTIST_FIELDS = ["name_canonical", "name_en", "real_name", "category",
                     "aliases", "needs_review"]

ENRICH_TIMEOUT_SECONDS = 900  # 실측 578초(대량 배치 정규화) + 여유

PROMPT_TEMPLATE = """다음은 대학 축제 라인업에서 추출한 아티스트 표기 목록입니다.
당신이 아는 지식으로 각 표기를 정식 활동명으로 정규화하고, 아티스트 마스터 정보를 만드세요.

규칙:
- 같은 아티스트의 다른 표기는 하나의 name_canonical로 묶습니다 (예: "십센치" → "10CM").
- 모르는 이름이거나 확실하지 않으면 name_canonical에 원문 표기를 그대로 쓰고
  needs_review를 true로 표시하세요. 절대 추측으로 채우지 마세요.
- mapping에는 입력 목록의 모든 표기가 키로 들어가야 합니다.
- 설명 없이 JSON 객체 하나만 출력하세요.
- other_names에는 별칭·영문 표기·본명 등 그 아티스트를 가리키는 다른 표기를
  모두 넣습니다 (name과 같은 표기는 제외).
- genre는 HIPHOP / BALLAD_RNB / DANCE / BAND 중 확실한 것만 채우고,
  모르거나 넷에 안 맞으면 null로 둡니다.

스키마:
{{"mapping": {{"원문표기": "정식표기"}},
  "artists": [{{"name": str, "other_names": [str],
               "genre": "HIPHOP"|"BALLAD_RNB"|"DANCE"|"BAND"|null,
               "needs_review": bool}}]}}
{known_block}
아티스트 표기 목록:
{names}"""

KNOWN_BLOCK_TEMPLATE = """
이미 정해 둔 정식 표기입니다. 아래 목록에 있는 아티스트와 같은 사람이면
그 표기를 그대로 쓰세요 (새 표기를 만들지 마세요):
{known}
"""


def year_dirs(base_dir: Path) -> list[Path]:
    """output/ 아래의 연도 폴더들. 숫자 이름만 연도로 본다."""
    if not base_dir.exists():
        return []
    return sorted(p for p in base_dir.iterdir() if p.is_dir() and p.name.isdigit())


def collect_raw_names(base_dir: Path) -> list[str]:
    """전 연도의 raw 캐시에서 아티스트 원문 표기를 모은다. is_secret은 제외한다."""
    names: set[str] = set()
    for ydir in year_dirs(base_dir):
        for path in sorted((ydir / "raw").glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            ext = record.get("extraction")
            if not ext:
                continue
            for item in ext["lineup"]:
                if not item.get("is_secret"):
                    names.add(item["artist_raw"])
    return sorted(names)


def normalize(names: list[str], known: list[str]) -> EnrichResult:
    known_block = (
        KNOWN_BLOCK_TEMPLATE.format(known="\n".join(f"- {k}" for k in known))
        if known else ""
    )
    prompt = PROMPT_TEMPLATE.format(
        names="\n".join(f"- {n}" for n in names), known_block=known_block)
    last_error = None
    for attempt in range(2):
        raw = call_claude(prompt, timeout=ENRICH_TIMEOUT_SECONDS)
        try:
            return EnrichResult.model_validate_json(_extract_json(raw))
        except (ValidationError, ValueError) as e:
            last_error = e
            prompt += f"\n\n[재시도] 이전 응답이 유효하지 않았습니다: {e}\nJSON만 다시 출력하세요."
    raise ExtractError(f"정규화 검증 2회 실패: {last_error}")


def _merge_artists(base_dir: Path, artists: list[ArtistMaster]) -> None:
    """기존 artists.csv를 유지하고 새 아티스트만 덧붙인다 — 연도 사이에 누적된다."""
    path = base_dir / "artists.csv"
    rows: list[dict] = []
    if path.exists():
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    known = {r["name"] for r in rows}
    for a in artists:
        if a.name in known:
            continue
        rows.append({
            "name": a.name,
            "other_names": "|".join(a.other_names),
            "genre": a.genre or "",
            "image_url": "",
            "needs_review": "true" if a.needs_review else "false",
        })
        known.add(a.name)
    write_csv(path, ARTIST_FIELDS, rows)


GENRE_PROMPT = """다음 아티스트들의 장르를 분류하세요.

규칙:
- HIPHOP / BALLAD_RNB / DANCE / BAND 중 확실한 것만 채우고, 모르거나 넷에 안 맞으면 null.
- 절대 추측으로 채우지 마세요.
- 설명 없이 JSON 객체 하나만 출력하세요: {{"genres": {{"아티스트명": "HIPHOP"|null}}}}

아티스트 목록:
{names}"""


def classify_genres(names: list[str]) -> dict[str, str | None]:
    """아티스트 name 목록의 장르를 LLM 1콜로 분류한다. 실패하면 예외가 전파돼 중단된다."""
    if not names:
        return {}
    raw = call_claude(GENRE_PROMPT.format(names="\n".join(f"- {n}" for n in names)),
                      timeout=ENRICH_TIMEOUT_SECONDS)
    return GenreResult.model_validate_json(_extract_json(raw)).genres


def _migrate_artists_csv(base_dir: Path) -> None:
    """구 스키마 artists.csv를 새 컬럼으로 1회 변환한다 (genre는 LLM 1콜로 분류).

    변환 실패 시 파일은 건드리지 않으므로 다음 실행에서 다시 시도된다.
    """
    path = base_dir / "artists.csv"
    if not path.exists():
        return
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != OLD_ARTIST_FIELDS:
            return
        old_rows = list(reader)
    genres = classify_genres([r["name_canonical"] for r in old_rows])
    rows = []
    for r in old_rows:
        name = r["name_canonical"]
        others = [x for x in [r["name_en"], r["real_name"]] + r["aliases"].split(";")
                  if x and x != name]
        rows.append({
            "name": name,
            "other_names": "|".join(dict.fromkeys(others)),   # 순서 유지 중복 제거
            "genre": genres.get(name) or "",
            "image_url": "",
            "needs_review": r["needs_review"],
        })    # 구 category는 버린다 — 장르로 일원화
    write_csv(path, ARTIST_FIELDS, rows)
    print(f"artists.csv 마이그레이션 완료: {len(rows)}명, "
          f"genre 분류 {sum(1 for r in rows if r['genre'])}건")


def _refresh_lineups(ydirs: list[Path], mapping: dict[str, str]) -> None:
    """모든 연도의 lineup.csv를 현재 매핑에 맞춰 다시 쓴다 (매핑에 없는 표기는 원문 유지)."""
    for ydir in ydirs:
        lineup_path = ydir / "lineup.csv"
        if not lineup_path.exists():
            continue
        with open(lineup_path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            row["artist_canonical"] = mapping.get(row["artist_raw"], row["artist_raw"])
        write_csv(lineup_path, LINEUP_FIELDS, rows)


def enrich(base_dir: Path) -> None:
    _migrate_artists_csv(base_dir)
    names = collect_raw_names(base_dir)
    if not names:
        print("정규화할 아티스트 없음 — 건너뜀")
        return

    ydirs = year_dirs(base_dir)

    # lineup.csv 스키마를 LLM 호출 전에 검증한다 — normalize()는 578초짜리 LLM 호출이라,
    # 구 스키마(festival_id 없음)로 뒤늦게 write_csv에서 실패하면 그 호출이 통째로 낭비된다.
    for ydir in ydirs:
        lineup_path = ydir / "lineup.csv"
        if not lineup_path.exists():
            continue
        with open(lineup_path, newline="", encoding="utf-8-sig") as f:
            header = csv.DictReader(f).fieldnames
        if header != LINEUP_FIELDS:
            raise SystemExit(
                f"{lineup_path} 가 예전 스키마입니다 (import_key 없음) — "
                "crawl.py를 먼저 다시 실행해 새 스키마로 재생성하세요."
            )

    mapping = load_artist_mapping(base_dir)
    new_names = [n for n in names if n not in mapping]

    result = None
    if new_names:
        result = normalize(new_names, sorted(set(mapping.values())))
        # 이번에 물어본 이름만 받는다. 프롬프트가 기존 정식 표기를 보여주므로 모델이
        # 그 키를 되돌려줄 수 있는데, 한 번 덮이면 다시 LLM에 가지 않아 영구히 굳는다.
        asked = set(new_names)
        mapping.update({k: v for k, v in result.mapping.items() if k in asked})
        save_artist_mapping(base_dir, mapping)

    # 매핑 값이 손으로 바뀌었을 수도 있으니 새 이름이 없어도 항상 반영한다.
    _refresh_lineups(ydirs, mapping)

    if result is None:
        print(f"새 아티스트 없음 — 정규화 건너뜀 (매핑 {len(mapping)}건)")
        return

    _merge_artists(base_dir, result.artists)
    print(f"완료: 신규 {len(new_names)}명 정규화, 매핑 누적 {len(mapping)}건, "
          f"needs_review {sum(1 for a in result.artists if a.needs_review)}건")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="아티스트 정규화/마스터 생성")
    parser.parse_args()
    enrich(OUTPUT_BASE)
