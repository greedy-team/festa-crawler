"""후처리: 아티스트 표기 정규화 + 마스터 생성 (LLM 1콜)."""
import argparse
import csv
import json
from pathlib import Path

from pydantic import ValidationError

from crawl import LINEUP_FIELDS, write_csv
from extract import ExtractError, _extract_json, call_claude
from schema import EnrichResult

ARTIST_FIELDS = ["name_canonical", "name_en", "real_name", "category",
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

스키마:
{{"mapping": {{"원문표기": "정식표기"}},
  "artists": [{{"name_canonical": str, "name_en": str|null, "real_name": str|null,
               "category": str|null, "aliases": [str], "needs_review": bool}}]}}

아티스트 표기 목록:
{names}"""


def collect_raw_names(out_dir: Path) -> list[str]:
    names: set[str] = set()
    for path in sorted((out_dir / "raw").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        ext = record.get("extraction")
        if not ext:
            continue
        for item in ext["lineup"]:
            if not item.get("is_secret"):
                names.add(item["artist_raw"])
    return sorted(names)


def normalize(names: list[str]) -> EnrichResult:
    prompt = PROMPT_TEMPLATE.format(names="\n".join(f"- {n}" for n in names))
    last_error = None
    for attempt in range(2):
        raw = call_claude(prompt, timeout=ENRICH_TIMEOUT_SECONDS)
        try:
            return EnrichResult.model_validate_json(_extract_json(raw))
        except (ValidationError, ValueError) as e:
            last_error = e
            prompt += f"\n\n[재시도] 이전 응답이 유효하지 않았습니다: {e}\nJSON만 다시 출력하세요."
    raise ExtractError(f"정규화 검증 2회 실패: {last_error}")


def enrich(out_dir: Path) -> None:
    names = collect_raw_names(out_dir)
    if not names:
        print("정규화할 아티스트 없음 — 건너뜀")
        return
    result = normalize(names)

    # lineup.csv의 artist_canonical 갱신 (매핑에 없는 표기는 원문 유지)
    lineup_path = out_dir / "lineup.csv"
    if lineup_path.exists():
        with open(lineup_path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            row["artist_canonical"] = result.mapping.get(
                row["artist_raw"], row["artist_raw"]
            )
        write_csv(lineup_path, LINEUP_FIELDS, rows)

    artist_rows = [{
        "name_canonical": a.name_canonical,
        "name_en": a.name_en or "",
        "real_name": a.real_name or "",
        "category": a.category or "",
        "aliases": ";".join(a.aliases),
        "needs_review": "true" if a.needs_review else "false",
    } for a in result.artists]
    write_csv(out_dir / "artists.csv", ARTIST_FIELDS, artist_rows)
    print(f"완료: artists {len(artist_rows)}행, needs_review "
          f"{sum(1 for a in result.artists if a.needs_review)}건")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="아티스트 정규화/마스터 생성")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    args = parser.parse_args()
    enrich(args.output_dir)
