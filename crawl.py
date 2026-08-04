"""FESTA 크롤러 엔트리포인트: 대학 목록 순회 → 수집·추출 → 캐시 → CSV 출력."""
import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

from extract import ExtractError, extract, verify
from fetch import fetch_body


@dataclass
class UniversityRow:
    university: str
    campus: str
    region: str
    year: int
    url: str | None


def load_universities(path: Path) -> list[UniversityRow]:
    rows: list[UniversityRow] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            url = (r.get("url") or "").strip()
            rows.append(
                UniversityRow(
                    university=r["university"].strip(),
                    campus=r["campus"].strip(),
                    region=r["region"].strip(),
                    year=int(r["year"]),
                    url=url or None,
                )
            )
    return rows


FESTIVAL_FIELDS = [
    "university", "campus", "region", "year", "festival_name",
    "start_date", "end_date", "venue_name", "outsider_admission",
    "ticket_info", "poster_image_url", "source_url", "flag",
]
LINEUP_FIELDS = [
    "university", "year", "festival_name", "day_label", "date", "time",
    "artist_canonical", "artist_raw", "is_secret", "source_url",
]


def process_row(row: UniversityRow, out_dir: Path) -> dict:
    """URL 1건 처리. output/raw/<대학명>.json 캐시가 있으면 그대로 반환."""
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache_path = raw_dir / f"{row.university}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("url") == row.url and cached.get("year") == row.year:
            # 시드 전용 필드는 현재 행 기준으로 갱신 (추출 결과에는 영향 없음)
            cached["campus"] = row.campus
            cached["region"] = row.region
            return cached
        # URL 또는 연도가 바뀌었으면 캐시 무시하고 다시 처리 (아래에서 덮어씀)

    record = {
        "university": row.university, "campus": row.campus,
        "region": row.region, "year": row.year, "url": row.url,
        "flag": "no_source", "poster_image_url": None, "extraction": None,
    }
    if row.url is not None:
        fr = fetch_body(row.url)
        record["poster_image_url"] = fr.poster_image_url
        if fr.status != "ok":
            record["flag"] = fr.status
        else:
            try:
                result = extract(fr.body, row.university, row.year)
            except ExtractError:
                record["flag"] = "extract_failed"
            else:
                record["extraction"] = result.model_dump()
                record["flag"] = "ok" if verify(result, row.university, row.year) else "mismatch"

    if row.url is not None and record["flag"] != "fetch_failed":
        cache_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def build_festival_row(record: dict) -> dict:
    ext = record["extraction"] or {}
    return {
        "university": record["university"], "campus": record["campus"],
        "region": record["region"], "year": record["year"],
        "festival_name": ext.get("festival_name") or "",
        "start_date": ext.get("start_date") or "",
        "end_date": ext.get("end_date") or "",
        "venue_name": ext.get("venue_name") or "",
        "outsider_admission": ext.get("outsider_admission") or "",
        "ticket_info": ext.get("ticket_info") or "",
        "poster_image_url": record["poster_image_url"] or "",
        "source_url": record["url"] or "",
        "flag": record["flag"],
    }


def build_lineup_rows(record: dict) -> list[dict]:
    ext = record["extraction"]
    if not ext:
        return []
    rows = []
    for item in ext["lineup"]:
        rows.append({
            "university": record["university"], "year": record["year"],
            "festival_name": ext.get("festival_name") or "",
            "day_label": item.get("day_label") or "",
            "date": item.get("date") or "",
            "time": item.get("time") or "",
            "artist_canonical": item["artist_raw"],   # Task 6(enrich)이 갱신
            "artist_raw": item["artist_raw"],
            "is_secret": "true" if item.get("is_secret") else "false",
            "source_url": record["url"] or "",
        })
    return rows


def _sanitize_cell(value) -> str:
    """Excel 수식 인젝션 방지: 위험 선행문자는 작은따옴표로 무력화."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            [{k: _sanitize_cell(v) for k, v in row.items()} for row in rows]
        )


def run(input_csv: Path, out_dir: Path, limit: int | None = None) -> None:
    rows = load_universities(input_csv)
    if limit:
        rows = rows[:limit]
    festival_rows, lineup_rows = [], []
    for i, row in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {row.university} ...", flush=True)
        record = process_row(row, out_dir)
        print(f"  -> {record['flag']}", flush=True)
        festival_rows.append(build_festival_row(record))
        lineup_rows.extend(build_lineup_rows(record))
    write_csv(out_dir / "festivals.csv", FESTIVAL_FIELDS, festival_rows)
    write_csv(out_dir / "lineup.csv", LINEUP_FIELDS, lineup_rows)
    print(f"완료: festivals {len(festival_rows)}행, lineup {len(lineup_rows)}행")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FESTA 크롤러 v1")
    parser.add_argument("--input", type=Path, default=Path("universities.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--limit", type=int, default=None, help="앞에서 N행만 처리 (스모크용)")
    args = parser.parse_args()
    run(args.input, args.output_dir, args.limit)
