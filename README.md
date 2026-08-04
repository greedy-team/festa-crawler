# FESTA 크롤러

대학 축제 정보(축제 상세 + 라인업)를 큐레이션된 블로그 URL에서 수집·추출해 사람이 검토할 CSV로
만드는 로컬 배치 크롤러다. 설계 근거는 [`2026-08-04-crawler-pipeline-design.md`](./2026-08-04-crawler-pipeline-design.md) 참고.

## 설치

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

LLM 추출은 로컬 Claude Code CLI(`claude`)를 헤드리스로 호출한다 — 실행 전 `claude` 로그인이
되어 있어야 한다.

## 실행

```bash
.venv/bin/python crawl.py [--limit N]   # --limit: 앞에서 N행만 처리 (스모크용)
```

`universities.csv`를 순회해 `output/festivals.csv`, `output/lineup.csv`를 만든다. 완료 후:

```bash
.venv/bin/python enrich.py
```

라인업의 아티스트 표기를 정규화하고 `output/artists.csv`(아티스트 마스터)를 만든다.

## flag 의미

`festivals.csv`의 `flag` 컬럼:

| flag | 의미 |
|---|---|
| `ok` | 수집·추출·검증 모두 성공 |
| `fetch_failed` | 본문 수집 실패 (네트워크 오류, robots.txt 차단 등) |
| `empty_body` | 본문이 100자 미만 (포스터 이미지만 있는 글 등) |
| `extract_failed` | LLM 추출이 2회 시도 후에도 유효한 JSON을 내지 못함 |
| `mismatch` | 추출은 됐지만 결과가 요청한 대학·연도 글이 아닌 것으로 판정 |
| `no_source` | `universities.csv`에 URL이 없는 행 (시드 전용) |

`flag != ok` 행은 운영자가 `source_url`을 직접 열어 확인한다.

## 캐시 동작

URL 1건의 결과는 `output/raw/<대학명>.json`에 저장된다. 같은 URL·연도로 다시 실행하면
캐시를 그대로 반환하고 재수집하지 않는다 (URL 또는 연도가 바뀌면 캐시를 무시하고 재처리).

- **강제 재수집하려면** 해당 대학의 `output/raw/<대학명>.json` 파일을 삭제하고 다시 실행한다.
- `fetch_failed`는 캐시에 저장되지 않는다 — 다음 실행에서 자동으로 재시도된다 (네트워크 오류
  같은 일시적 실패를 영구히 막지 않기 위함). `empty_body`·추출 결과는 캐시된다.

## 운영 팁

- Claude 구독 세션 한도에 걸리면 크롤러가 중단된다. 한도가 리셋된 뒤 같은 명령으로 재실행하면
  이미 처리된 대학은 캐시로 건너뛰고 나머지만 이어서 처리한다.
- `enrich.py`는 전체 아티스트 목록을 한 번에 정규화하는 대형 LLM 호출 1건이라 수 분(최대
  15분 타임아웃) 걸릴 수 있다.
- 크롤러 산출물은 초안이다. **CSV를 사람이 검토한 뒤 어드민 페이지에 입력한다** — 최종 신뢰는
  검수 단계가 담보한다.
