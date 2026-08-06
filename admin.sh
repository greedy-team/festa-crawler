#!/bin/sh
# 크롤러 관리자 페이지 실행. venv가 없으면 만들고 나서 띄운다.
# 인자는 그대로 넘어간다: ./admin.sh --year 2026 --port 8790
set -e
cd "$(dirname "$0")"
[ -d .venv ] || {
    echo "venv가 없어 새로 만든다..."
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
}
exec .venv/bin/python serve.py "$@"
