"""FESTA 크롤러 엔트리포인트: 대학 목록 순회 → 수집·추출 → 캐시 → CSV 출력."""
import argparse
import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path

from discover import MAX_CANDIDATES, discover_cached, discover_sitemap
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


SCHEMA_VERSION = 2

FESTIVAL_FIELDS = [
    "import_key", "host_name", "name", "start_date", "end_date", "venue_name",
    "poster_url", "image_urls", "description", "hashtags",
    "external_visitor_policy", "verification_method", "ticket_type",
    "ticket_open_at", "admission_raw", "source_url", "discovery", "flag",
    "instagram_url",
]
LINEUP_FIELDS = ["import_key", "day", "order", "artist_raw", "artist_canonical", "revealed"]

ADMISSION_RAW_MAX_CHARS = 200


def import_key(university: str, year: int) -> str:
    """축제 1건의 안정적인 식별자(주최명-연도). 백엔드 명세의 import_key.

    시드에서 university+year 조합이 유일함을 전제한다.
    """
    return f"{university}-{year}"


def _attempt_url(url: str, row: UniversityRow) -> dict:
    """URL 1건을 수집·추출·검증한다. flag/poster_image_url/extraction만 담아 돌려준다."""
    fr = fetch_body(url)
    attempt = {"flag": fr.status, "poster_image_url": fr.poster_image_url,
               "image_urls": fr.image_urls, "extraction": None}
    if fr.status != "ok":
        return attempt
    try:
        result = extract(fr.body, row.university, row.year, fr.instagram_candidates)
    except ExtractError:
        attempt["flag"] = "extract_failed"
        return attempt
    attempt["extraction"] = result.model_dump()
    attempt["flag"] = "ok" if verify(result, row.university, row.year) else "mismatch"
    return attempt


def _try_candidates(
    candidates: list[str], row: UniversityRow, record: dict, source: str
) -> bool:
    """후보를 순서대로 시도해 verify를 통과한 첫 건을 record에 채택한다.

    채택하면 True. 어느 후보도 통과하지 못하면 record를 건드리지 않고 False —
    수동 URL의 실패 사유가 그대로 남는다.
    """
    for candidate in candidates[:MAX_CANDIDATES]:
        attempt = _attempt_url(candidate, row)
        if attempt["flag"] == "ok":
            record.update(attempt)
            record["url"] = candidate
            record["discovery"] = source
            return True
    return False


def process_row(row: UniversityRow, out_dir: Path) -> dict:
    """대학 1곳 처리. 수동 URL → 사이트맵 후보 → 검색 후보 순으로 시도한다."""
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache_path = raw_dir / f"{row.university}.json"
    stale_ok = None
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (cached.get("schema_version") == SCHEMA_VERSION
                and cached.get("seed_url") == row.url
                and cached.get("year") == row.year):
            # 시드 전용 필드는 현재 행 기준으로 갱신 (추출 결과에는 영향 없음)
            cached["campus"] = row.campus
            cached["region"] = row.region
            return cached
        if cached.get("flag") == "ok":
            # 구 스키마(또는 시드 변경)의 성공 캐시 — 재수집 실패 시 폴백으로 쓴다.
            # 재실행은 복원이지 파괴가 아니다 (DEC-0028 원칙).
            stale_ok = cached

    record = {
        "schema_version": SCHEMA_VERSION,
        "university": row.university, "campus": row.campus,
        "region": row.region, "year": row.year,
        "seed_url": row.url, "url": row.url, "discovery": "",
        "flag": "no_source", "poster_image_url": None, "image_urls": [],
        "extraction": None,
    }

    if row.url is not None:
        record.update(_attempt_url(row.url, row))
        record["discovery"] = "manual" if record["flag"] == "ok" else ""

    if record["flag"] != "ok":
        # 사이트맵 우선 — 통과하면 WebSearch(1건 60초 + 세션 한도)를 아예 부르지 않는다
        if not _try_candidates(
            discover_sitemap(row.university, row.year), row, record, "sitemap"
        ):
            candidates = discover_cached(row.university, row.year, out_dir)
            if candidates is None:
                # 탐색 자체가 실패(세션 한도 등) — 일시적이므로 캐시하지 않고 다음 실행에서 재시도
                return _keep_stale_on_failure(record, stale_ok, row)
            if not _try_candidates(candidates, row, record, "search"):
                # 어느 후보도 verify를 통과하지 못함
                if row.url is None:
                    record["flag"] = "no_candidate"

    result = _keep_stale_on_failure(record, stale_ok, row)
    if result is stale_ok:
        return result       # 구 캐시 파일은 그대로 둔다 — 다음 실행에서 다시 시도
    if record["flag"] not in ("fetch_failed", "extract_failed"):
        cache_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def _keep_stale_on_failure(record: dict, stale_ok: dict | None, row: UniversityRow) -> dict:
    """재수집이 실패했고 구 성공 캐시가 있으면 구 데이터를 지키는 쪽을 택한다."""
    if record["flag"] == "ok" or stale_ok is None:
        return record
    stale_ok["campus"] = row.campus
    stale_ok["region"] = row.region
    print("  -> 재수집 실패, 이전 결과 유지", flush=True)
    return stale_ok


def build_festival_row(record: dict) -> dict:
    ext = record["extraction"] or {}
    handle = ext.get("instagram_handle") or ""
    return {
        "import_key": import_key(record["university"], record["year"]),
        "host_name": record["university"],
        "name": ext.get("festival_name") or "",
        "start_date": ext.get("start_date") or "",
        "end_date": ext.get("end_date") or "",
        "venue_name": ext.get("venue_name") or "",
        "poster_url": record["poster_image_url"] or "",
        "image_urls": "|".join(record.get("image_urls") or []),
        "description": ext.get("description") or "",
        "hashtags": "|".join(ext.get("hashtags") or []),
        "external_visitor_policy": ext.get("external_visitor_policy") or "",
        "verification_method": ext.get("verification_method") or "",
        "ticket_type": ext.get("ticket_type") or "",
        "ticket_open_at": ext.get("ticket_open_at") or "",
        "admission_raw": (ext.get("admission_raw") or "")[:ADMISSION_RAW_MAX_CHARS],
        "source_url": record["url"] or "",
        "discovery": (record.get("discovery") or "").upper(),
        "flag": record["flag"].upper(),
        "instagram_url": f"https://www.instagram.com/{handle}" if handle else "",
    }


def build_lineup_rows(record: dict, mapping: dict[str, str]) -> list[dict]:
    """라인업 행을 만든다. artist_canonical은 매핑에서 채운다 — 매핑에 없으면 원문 그대로.

    flag가 ok인 축제만 출력한다 — 그 외 행은 백엔드에서 고아 INVALID만 만든다.
    시크릿 게스트는 revealed=false + 이름 빈 값 (명세 검증 규칙).
    """
    ext = record["extraction"]
    if not ext or record["flag"] != "ok":
        return []
    key = import_key(record["university"], record["year"])
    order_by_day: dict = {}
    rows = []
    for item in ext["lineup"]:
        day = item.get("day")
        order_by_day[day] = order_by_day.get(day, 0) + 1
        secret = bool(item.get("is_secret"))
        raw = "" if secret else item["artist_raw"]
        rows.append({
            "import_key": key,
            "day": "" if day is None else day,
            "order": order_by_day[day],
            "artist_raw": raw,
            "artist_canonical": "" if secret else mapping.get(raw, raw),
            "revealed": "false" if secret else "true",
        })
    return rows


def _sanitize_cell(value) -> str:
    """Excel 수식 인젝션 방지: 위험 선행문자는 작은따옴표로 무력화."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """CSV를 원자적으로 쓴다: 임시 파일에 쓴 뒤 os.replace()로 교체.

    이렇게 하면 concurrent reader가 truncated file을 보지 않는다.
    임시 파일과 대상이 같은 파일시스템에 있어야 os.replace() atomicity가 보장된다.
    """
    temp_path = path.parent / f"{path.name}.tmp"
    try:
        with open(temp_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(
                [{k: _sanitize_cell(v) for k, v in row.items()} for row in rows]
            )
        os.replace(temp_path, path)
    except Exception:
        # 쓰기 실패하면 임시 파일을 치운다
        if temp_path.exists():
            temp_path.unlink()
        raise


ARTIST_MAPPING_NAME = "artist_mapping.json"


def load_artist_mapping(base_dir: Path) -> dict[str, str]:
    """표기 → 정식 표기 매핑. 연도 공통이므로 연도 폴더가 아니라 그 상위에 둔다.

    파일이 없으면 빈 매핑 — 첫 실행의 정상 상태다. 파일이 깨졌으면 중단한다.
    빈 매핑으로 진행하면 lineup.csv의 정규화가 전부 원문으로 되돌아간다.
    """
    path = base_dir / ARTIST_MAPPING_NAME
    if not path.exists():
        return {}
    try:
        mapping = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"{path} 를 읽을 수 없습니다: {e}\n"
            "빈 매핑으로 진행하면 정규화 결과가 사라집니다. 파일을 고치거나 지우세요."
        )
    if not isinstance(mapping, dict):
        raise SystemExit(f"{path} 는 객체여야 합니다")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
        raise SystemExit(f"{path} 의 키와 값은 모두 문자열이어야 합니다")
    return mapping


def save_artist_mapping(base_dir: Path, mapping: dict[str, str]) -> None:
    """write_csv와 같은 이유로 원자적으로 쓴다 — 읽는 쪽이 반쪽 파일을 보면 안 된다."""
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / ARTIST_MAPPING_NAME
    temp_path = path.parent / f"{path.name}.tmp"
    try:
        temp_path.write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


OUTPUT_BASE = Path("output")


def seed_path(year: int) -> Path:
    """그 해의 시드 파일. 지난 시즌 시드는 동결되므로 연도마다 파일이 하나씩 늘어난다."""
    return Path(f"universities-{year}.csv")


def run(year: int, base_dir: Path = OUTPUT_BASE, limit: int | None = None) -> None:
    seed = seed_path(year)
    if not seed.exists():
        available = sorted(p.name for p in Path(".").glob("universities-*.csv"))
        raise SystemExit(
            f"{seed} 가 없습니다. 있는 시드: {', '.join(available) or '없음'}"
        )
    rows = load_universities(seed)
    wrong = sorted({r.year for r in rows if r.year != year})
    if wrong:
        raise SystemExit(
            f"{seed} 의 year 컬럼에 {wrong} 가 있습니다 — --year {year} 와 다릅니다"
        )
    if limit:
        rows = rows[:limit]

    # 연도 폴더가 도입되기 전 레이아웃. 그냥 두면 캐시를 하나도 못 찾아 29곳을 조용히
    # 다시 수집한다 (30~50분 + 세션 한도). 옮기면 LLM 재실행 없이 그대로 이어진다.
    if (base_dir / "festivals.csv").exists():
        raise SystemExit(
            f"{base_dir}/festivals.csv 가 있습니다 — 연도 폴더가 없는 예전 레이아웃입니다.\n"
            f"이대로 실행하면 {base_dir}/{year}/ 가 비어 있어 전체를 다시 수집합니다.\n"
            "아래대로 옮긴 뒤 다시 실행하세요:\n"
            f"  1. mkdir {base_dir}/{year}\n"
            f"     mv {base_dir}/{{festivals.csv,lineup.csv,raw,discovered}} {base_dir}/{year}/\n"
            f"  2. {base_dir}/{year}/lineup.csv 에서 artist_mapping.json 생성\n"
            f"     (artist_raw → artist_canonical 대응을 {base_dir}/artist_mapping.json 에 저장)\n"
            f"  3. {base_dir}/artists.csv 는 {base_dir}/ 에 그대로 둔다"
        )

    out_dir = base_dir / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping = load_artist_mapping(base_dir)

    festival_rows, lineup_rows = [], []
    for i, row in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {row.university} ...", flush=True)
        record = process_row(row, out_dir)
        print(f"  -> {record['flag']}", flush=True)
        festival_rows.append(build_festival_row(record))
        lineup_rows.extend(build_lineup_rows(record, mapping))
    write_csv(out_dir / "festivals.csv", FESTIVAL_FIELDS, festival_rows)
    write_csv(out_dir / "lineup.csv", LINEUP_FIELDS, lineup_rows)
    print(f"완료: festivals {len(festival_rows)}행, lineup {len(lineup_rows)}행")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FESTA 크롤러 v1")
    parser.add_argument("--year", type=int, required=True,
                        help="대상 연도. universities-<연도>.csv 를 읽어 output/<연도>/ 에 쓴다")
    parser.add_argument("--limit", type=int, default=None, help="앞에서 N행만 처리 (스모크용)")
    args = parser.parse_args()
    run(args.year, limit=args.limit)
