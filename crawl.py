"""FESTA 크롤러 엔트리포인트. Task 5에서 오케스트레이션이 추가된다."""
import csv
from dataclasses import dataclass
from pathlib import Path


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
