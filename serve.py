"""검수 페이지 로컬 서버: output/의 CSV를 브라우저에 보여주고 crawl·enrich를 띄운다.

읽기 전용이다 — output/에 쓰는 주체는 crawl.py와 enrich.py뿐이다.
"""
import csv
from pathlib import Path


class CsvUnreadable(Exception):
    """crawl이 CSV를 쓰는 도중이라 읽지 못했다. 다음 폴링에서 다시 읽는다."""


def read_csv(path: Path) -> list[dict]:
    """CSV를 딕셔너리 목록으로 읽는다. 파일이 없으면 빈 목록 — 첫 실행 전 정상 상태다."""
    if not path.exists():
        return []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except (csv.Error, UnicodeDecodeError) as e:
        raise CsvUnreadable(f"{path.name}: {e}")


def load_data(out_dir: Path) -> dict:
    return {
        "festivals": read_csv(out_dir / "festivals.csv"),
        "lineup": read_csv(out_dir / "lineup.csv"),
        "artists": read_csv(out_dir / "artists.csv"),
    }
