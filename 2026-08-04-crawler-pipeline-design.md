# FESTA 데이터 파이프라인 크롤러 v1 — 설계 문서

- 날짜: 2026-08-04
- 상태: 승인됨 (사용자 확정)
- 개정: 2026-08-04 — 인스타그램 총학 계정 핸들 수집 추가 (이슈 #1)
- 근거 문서: `crawler/데이터 파이프라인 v1.md`, `crawler/서울 상위 대학 29개.md`, FESTA UI 목업 5종

## 1. 목적

대학 축제 정보(축제 상세 + 라인업)를 큐레이션된 블로그 URL에서 수집·추출해,
운영자가 검토 후 어드민 페이지에 입력할 수 있는 CSV로 만드는 **로컬 배치 크롤러**.

파이프라인 문서의 원칙을 따른다: **크롤링은 초안 생성기이고, 최종 신뢰는 사람이 담보한다.**
사람이 CSV를 검토해 어드민에 입력하는 단계가 곧 검수 큐다.

## 2. 범위

### 포함

- 큐레이션 URL 목록(29개 대학 중 URL 보유분) → 본문 수집 → LLM 구조화 추출 → CSV 3종 출력
- 축제 상세 필드 추출 (기간·장소·외부인 입장·유료/예매 — 블로그에 있을 때)
- 아티스트 표기 정규화 + 아티스트 마스터 생성 (LLM 지식 기반, 후처리 1콜)
- 대학 시드 데이터 (캠퍼스·지역, 29행, 1회 생성)
- 재실행 캐시 (동일 URL 재호출 차단)
- 인스타그램 총학 계정 핸들 수집 (하이브리드: fetch가 HTML에서 후보 수집, LLM이 문맥 판별 —
  실측 기준 21곳 중 15곳에 총학 계정 링크 존재. 기존 21건은 캐시 초기화 후 전체 재실행으로 백필)

### 제외 (이번 범위 아님)

- 탐색 자동화 (검색으로 후보 URL 수집) — 큐레이션 목록으로 대체
- 검수 화면 UI — CSV + 사람 검토로 대체
- DB 적재 / 백엔드·어드민 연동 — 운영자 수동 입력
- 파생 데이터 집계 (자주 온 아티스트, 예정 공연, D-day) — 백엔드 소관
- 아티스트 프로필·포스터 **이미지** 수급 — 사실이 아닌 저작물이라 크롤링 부적합.
  포스터 원본 URL만 기록하고 이미지 정책은 별도 결정.
  (2026-08 확인: Instagram oEmbed는 2026-06-15부터 토큰·App Review 없이 호출 가능함을 실증했으나,
  게시물 URL 필요·프로필 임베드 불가. 실측 결과 블로그 21곳 모두 계정 링크만 있고 게시물 URL은 0건이라
  임베드는 크롤러가 아니라 프론트엔드 소관이며, 게시물 URL은 운영자가 어드민에서 수동 확보하는 경로가 현실적)
- 나무위키 크롤링 — robots.txt상 문서 페이지는 허용되나 CC BY-NC-SA(비영리) 라이선스와
  Cloudflare 봇 방어 문제, 그리고 필요 데이터가 LLM 지식 + 위키백과 API로 충분해 사용하지 않음
- 공지사항·분실물·오시는 길 — 운영자 직접 입력 영역

## 3. 핵심 결정

| 결정 | 내용 | 근거 |
|---|---|---|
| LLM 호출 방식 | **Claude Code 구독** (`claude -p` 헤드리스, 로컬 CLI) | 추가 비용 0. v1은 로컬 배치라 구독 사용 조건과 일치. API 전환은 `extract()` 함수 내부 교체만으로 가능 |
| API 전환 대비 | `extract.py`의 `extract()` 함수가 유일한 LLM 접점 | 추상 클래스·설정 파일 없음(YAGNI). 함수 경계로 충분 |
| 스키마 보장 | JSON 강제 프롬프트 + pydantic 검증 + 실패 시 1회 재시도 | CLI에는 API의 도구 호출 강제가 없음. 20~400건 규모 + 사람 검토가 백스톱이라 실질 차이 없음 |
| 산출물 | CSV 3종 (festivals / lineup / artists) | 목업의 데이터 요구(축제 상세, 아티스트 메타, 정규화된 표기)를 반영 |
| 아티스트 메타데이터 | LLM 지식으로 생성 + 사람 검수, 애매한 것만 위키백과 API 확인 | 시즌당 유니크 아티스트 ~50–150명, 전부 유명인. 크롤링 불필요 |
| 인스타 핸들 수집 방식 | 하이브리드 — fetch가 HTML href에서 후보 정규식 수집, LLM이 본문 문맥으로 총학 계정만 판별 | 실측: 한양대는 핸들이 href에만 있어 LLM 단독으론 누락, 연세대는 정규식 단독으론 블로그 운영사 계정 오탐 |

참고 비용(문서화 목적): API 전환 시 시즌 400회 기준 Haiku ~$5, Sonnet ~$14, Opus ~$23 수준.

## 4. 아키텍처

```
crawler/
├── universities.csv     # 입력 겸 대학 시드: 대학명, 캠퍼스, 지역, 연도, URL
│                        #   (URL 없는 행은 수집 스킵, 시드로만 사용)
├── crawl.py             # 엔트리: 목록 순회, 캐시 확인, 진행 로그, CSV 출력
├── fetch.py             # 본문 수집: robots.txt 확인 → 티스토리 셀렉터 순차 시도 → trafilatura 폴백
│                        #   + og:image·인스타그램 링크 후보 채집 (HTML 메타/href, 추가 요청 없음)
├── extract.py           # LLM 추출: claude -p 호출 + pydantic 검증 + 1회 재시도 (유일한 LLM 접점)
├── enrich.py            # 후처리: 유니크 아티스트 정규화 + 마스터 생성 (LLM 1콜)
├── schema.py            # pydantic 모델
└── output/              # (gitignore) 생성 산출물
    ├── festivals.csv
    ├── lineup.csv
    ├── artists.csv
    └── raw/<대학-slug>.json  # URL별 원본 추출 결과 = 재실행 캐시
```

의존성: `requests`, `beautifulsoup4`, `trafilatura`, `pydantic`. LLM은 로컬 설치된 Claude Code CLI.

## 5. 데이터 흐름

URL 1건당:

1. **캐시 확인** — `output/raw/`에 결과 있으면 스킵 (동일 URL 재호출 차단)
2. **robots.txt 확인** — 차단 경로면 수집하지 않고 `fetch_failed` 기록
3. **요청 간격** — 동일 호스트 요청 사이 최소 3초 대기
4. **본문 수집** — 티스토리 공통 본문 셀렉터 순차 시도 → 실패 시 trafilatura 폴백
   → 둘 다 실패 또는 본문 100자 미만이면(포스터 이미지만 있는 글) `empty_body` 기록.
   이때 HTML `og:image` 메타태그를 `poster_image_url`로, `instagram.com` 링크들을
   `instagram_candidates`로 함께 채집 (LLM 추출과 무관한 fetch 단계 작업)
5. **절단** — 본문 8,000자 상한
6. **추출** — `claude -p`에 본문+스키마 프롬프트(+ 인스타 후보 목록) → JSON 파싱 → pydantic 검증
   → 실패 시 1회 재시도, 그래도 실패면 `extract_failed` 기록.
   인스타 후보는 "이 대학의 축제·총학생회 계정만 채택, 블로그 운영자·무관 계정은 null" 규칙으로 판별.
   `empty_body` 행은 추출이 돌지 않으므로 핸들도 null (미검증 후보를 CSV에 싣지 않는다)
7. **역방향 검증** — 추출 결과의 `found` / `university` / `year`가 입력과 불일치하면 `mismatch` 플래그
8. **저장** — `output/raw/`에 JSON 원본 저장

전체 완료 후:

9. **정규화·마스터 생성** (`enrich.py`) — 전체 결과의 유니크 아티스트 원문 표기 목록을 모아
   LLM 1콜로 {원문 표기 → 정식 표기} 매핑 + 아티스트 마스터(영문명·본명·카테고리) 생성.
   확신 낮은 항목은 `needs_review` 플래그
10. **CSV 3종 출력** — UTF-8 BOM(utf-8-sig)으로 저장해 Excel에서 바로 열리게 함

## 6. 스키마

### 추출 JSON (URL 1건당, 문서 4.1 확장)

```
found: bool                  # 이 글이 해당 대학·연도의 라인업 글인가 (역방향 검증용)
university_name: str
year: int
festival_name: str | null
start_date: str | null       # YYYY-MM-DD
end_date: str | null
venue_name: str | null       # 예: 신촌캠퍼스 노천극장
outsider_admission: str | null   # 원문 표현 그대로 (예: "외부인 입장 가능", "재학생만")
ticket_info: str | null      # 유료/무료, 예매 일정 등 원문 요약
instagram_handle: str | null # 이 대학 축제·총학생회 인스타 계정 (후보+본문 문맥 판별, 확신 없으면 null)
lineup: [
  { artist_raw: str          # 원문 표기 그대로
    day_label: str | null    # 원문 표기 (1일차, DAY1 …)
    date: str | null         # YYYY-MM-DD (정규화 가능할 때만)
    time: str | null
    is_secret: bool }        # '시크릿'·'당일 공개' 표기 여부
]
```

환각 억제 규칙(프롬프트에 명시): 본문에 없는 값은 반드시 null. 추측 금지.

### festivals.csv — 1행 = 축제

`university | campus | region | year | festival_name | start_date | end_date | venue_name | outsider_admission | ticket_info | instagram_handle | poster_image_url | source_url | flag`

`flag` ∈ `ok | fetch_failed | empty_body | extract_failed | mismatch | no_source`

### lineup.csv — 1행 = 아티스트 × 일차

`university | year | festival_name | day_label | date | time | artist_canonical | artist_raw | is_secret | source_url`

### artists.csv — 1행 = 아티스트 마스터

`name_canonical | name_en | real_name | category | aliases | needs_review`

문서 4.2의 출처 메타데이터(`status`, `reviewed_by`, `confidence` 등)는 DB 적재 단계 소관이므로 제외.

## 7. LLM 호출 규약

- 호출: `claude -p <prompt> --output-format json` 서브프로세스, 호출당 타임아웃 120초
- 모델: Claude Code 세션 기본 모델 사용 (별도 지정 안 함)
- 프롬프트: 스키마 + "JSON만 출력" + 환각 억제 규칙 + 인스타 후보 목록(있을 때) + 본문
- 검증: 응답에서 JSON 추출 → pydantic 파싱. 실패 시 오류 내용을 덧붙여 1회 재시도
- API 전환 시: `call_claude()` 내부의 subprocess 호출을 Anthropic SDK 호출(도구 호출 강제)로 교체.
  `extract()` 시그니처(`본문·대학·연도·인스타 후보 → 검증된 모델`) 불변

## 8. 준수 사항 (파이프라인 문서 2.3)

- robots.txt 명시 차단 경로 접근 금지
- 동일 호스트 요청 간 최소 3초 간격
- 원문 전재 금지 — 사실 데이터만 추출 (본문 텍스트는 추출 프롬프트에만 사용, 저장하지 않음)
- 출처 URL을 모든 산출물 행에 표기
- User-Agent 명시

## 9. 에러 처리

- URL별 격리: 한 URL의 실패가 전체 실행을 중단시키지 않는다
- 실패 4종 + 1종을 flag로 기록: `fetch_failed` / `empty_body` / `extract_failed` / `mismatch` / `no_source`
- 네트워크: 타임아웃 10초, HTTP 오류 재시도 1회
- `claude` CLI 비정상 종료(미로그인 포함): 첫 발생 시 명확한 안내 후 해당 건 `extract_failed`
- 운영자는 CSV에서 flag ≠ ok 행만 원본 URL을 열어 판단

## 10. 테스트 전략

- **단위 (pytest)**: 스키마 검증, CSV 변환, 재시도 로직, 역방향 검증 — LLM 호출은 mock
- **fixture**: 실제 티스토리 HTML 1~2개 저장 → 셀렉터/trafilatura 폴백 검증
- **실전 검증 (핵심)**: 로드맵 1주차 그대로 — 큐레이션 URL 전체 실행 → CSV를 사람이 확인.
  본문 추출 성공률과 LLM 정확도를 여기서 확정한다

## 11. 향후 확장 (이번 구현 아님)

- 추출 호출부 API 전환 (어드민 트리거 자동화 시)
- 탐색 자동화 (대학명×연도 검색 → 후보 URL)
- 교차 검증·신뢰도 산정 (복수 출처 대조)
- 포스터 이미지 OCR (비전 모델)
- 어드민 CSV 일괄 업로드 기능 (백엔드 소관)
