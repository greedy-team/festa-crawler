"""검수 페이지 로컬 서버: output/의 CSV를 브라우저에 보여주고 crawl·enrich를 띄운다.

읽기 전용이다 — output/에 쓰는 주체는 crawl.py와 enrich.py뿐이다.
"""
import argparse
import csv
import json
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


JOB_SCRIPTS = {"crawl": "crawl.py", "enrich": "enrich.py"}


class Job:
    """동시에 하나만 도는 서브프로세스. LLM 세션 한도를 공유하므로 둘을 띄우지 않는다."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lines: list[str] = []
        self._lock = threading.Lock()

    def running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def start(self, script: str, cwd: Path) -> bool:
        """확인과 시작을 락 하나로 묶는다 — 그래야 두 요청이 동시에 잡을 못 띄운다.
        경합에서 졌으면 False."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return False
            proc = subprocess.Popen(
                [sys.executable, script], cwd=str(cwd),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
            self._proc = proc
            self._lines = [f"$ {sys.executable} {script}"]
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
        return True

    def _pump(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            with self._lock:
                self._lines.append(line.rstrip("\n"))
        proc.wait()
        with self._lock:
            self._lines.append(f"[종료 코드 {proc.returncode}]")

    def snapshot(self, from_index: int) -> dict:
        with self._lock:
            proc = self._proc
            returncode = None if proc is None else proc.poll()  # poll()은 한 번만
            return {
                "lines": self._lines[from_index:],
                "running": proc is not None and returncode is None,
                "returncode": returncode,
            }


JOB = Job()


def load_allowed_universities(seed_path: Path) -> set[str]:
    """허용 목록. 임의 문자열이 파일 경로로 들어가는 것을 막는 유일한 방어선이다."""
    with open(seed_path, newline="", encoding="utf-8-sig") as f:
        return {r["university"].strip() for r in csv.DictReader(f)}


def clear_cache(out_dir: Path, university: str, rediscover: bool) -> None:
    """행 단위 재실행을 위해 캐시를 지운다. 없어도 통과한다 — 버튼을 두 번 눌러도 무해해야 한다."""
    (out_dir / "raw" / f"{university}.json").unlink(missing_ok=True)
    if rediscover:
        (out_dir / "discovered" / f"{university}.json").unlink(missing_ok=True)


def handle_run(payload: dict, out_dir: Path, allowed: set[str], start) -> tuple[int, dict]:
    """POST /api/run 의 순수 로직. start(script) 는 잡 시작 함수다."""
    job = payload.get("job")
    if job not in JOB_SCRIPTS:
        return 400, {"error": f"알 수 없는 job: {job!r}"}

    university = payload.get("university")
    if university is not None:
        if job != "crawl":
            return 400, {"error": "university는 crawl에서만 쓸 수 있습니다"}
        # 허용 목록 검사가 경로 조립보다 먼저다. 정규화·이스케이프로 막지 않는다.
        if university not in allowed:
            return 400, {"error": f"시드에 없는 대학: {university!r}"}

    if JOB.running():
        return 409, {"error": "이미 실행 중입니다"}

    if university is not None:
        clear_cache(out_dir, university, bool(payload.get("rediscover")))

    if not start(JOB_SCRIPTS[job]):
        return 409, {"error": "이미 실행 중입니다"}
    return 200, {"started": job, "university": university}


def parse_from_index(query: str) -> int | None:
    """?from=N 파싱. 값이 없으면 0, 숫자가 아니면 None(= 400)."""
    for part in query.split("&"):
        if part.startswith("from="):
            value = part[5:]
            if not value:
                return 0
            try:
                return int(value)
            except ValueError:
                return None
    return 0


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output"
ALLOWED: set[str] = set()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: dict) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            html = (ROOT / "review.html").read_bytes()
            return self._send(200, html, "text/html; charset=utf-8")
        if path == "/api/data":
            try:
                return self._json(200, load_data(OUT_DIR))
            except CsvUnreadable as e:
                return self._json(503, {"error": str(e)})
        if path == "/api/log":
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            from_index = parse_from_index(query)
            if from_index is None:
                return self._json(400, {"error": "잘못된 from 파라미터"})
            return self._json(200, JOB.snapshot(from_index))
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/api/run":
            return self._json(404, {"error": "not found"})
        # 단순 크로스오리진 <form>은 Content-Type을 application/json으로 보낼 수 없다 —
        # 이 검사가 사실상의 CSRF 방어선이다. "단순화"한답시고 지우면 안 된다.
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._json(400, {"error": "잘못된 Content-Type"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json(400, {"error": "잘못된 Content-Length"})
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "잘못된 JSON"})
        if not isinstance(payload, dict):
            return self._json(400, {"error": "요청 본문은 객체여야 합니다"})
        status, body = self._run(payload)
        self._json(status, body)

    def _run(self, payload: dict) -> tuple[int, dict]:
        return handle_run(payload, OUT_DIR, ALLOWED,
                          start=lambda script: JOB.start(script, ROOT))

    def log_message(self, fmt, *args) -> None:
        pass          # 접근 로그는 잡 로그를 가린다


def main() -> None:
    global ALLOWED
    parser = argparse.ArgumentParser(description="FESTA 검수 페이지 (로컬 전용)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    ALLOWED = load_allowed_universities(ROOT / "universities.csv")

    # 소켓을 먼저 열고 나서 브라우저를 연다 — 반대 순서면 두 번째 실행이 첫 번째 인스턴스의
    # 탭을 열어놓고서 "Address already in use"로 죽는다.
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"검수 페이지: {url}  (Ctrl+C로 종료)")
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
