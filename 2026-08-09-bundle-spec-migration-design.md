# 산출물을 백엔드 번들 업로드 명세로 전환 — 설계

- 이슈: [#16](https://github.com/greedy-team/festa-crawler/issues/16)
- 근거 명세: `docs/크롤링 번들 업로드.md` (백엔드 어드민 API `POST /admin/imports/bundle`, 검토 단계)
- 날짜: 2026-08-09

## 배경과 목표

백엔드가 크롤러 산출 CSV 3종(`festivals.csv` · `lineup.csv` · `artists.csv`)을 일괄
업로드해 미리보기·커밋하는 어드민 API 명세를 작성 중이다. 현재 크롤러 산출물은 컬럼
구성·값 형식이 그 명세와 다르고, 명세가 요구하는 필드 일부(소개, 해시태그, 이미지 목록,
입장·티켓 분류, 라인업 일차·순서, 아티스트 장르)는 아예 수집하지 않는다.

**목표: `output/<연도>/` 산출물이 그대로 업로드 가능한 번들이 되게 한다.**
내부 스키마와 업로드 스키마를 한 벌로 유지한다(제자리 전환). 별도 export 변환 단계는
두지 않는다 — 신규 필드가 추출 단계까지 거슬러 올라가는 이상 파이프라인 전 단계를
손대야 하고, 스키마 두 벌은 반드시 어긋난다.

기존 2026년 수집분(29곳)은 전체 재크롤로 새 형식으로 재생성한다. 아티스트 정규화
결과(`artist_mapping.json`)는 보존한다.

## 산출물 스키마

### festivals.csv

```
import_key,host_name,name,start_date,end_date,venue_name,poster_url,image_urls,description,hashtags,external_visitor_policy,verification_method,ticket_type,ticket_open_at,admission_raw,source_url,discovery,flag,instagram_url
```

명세 헤더 순서 그대로. `instagram_url`은 명세 표에만 있고 헤더 코드블록에 없어
맨 끝에 둔다(백엔드 확인 항목 6).

| 컬럼 | 값의 출처 |
| --- | --- |
| `import_key` | 기존 `festival_id` 값 그대로 (`대학명-연도`) — 이름만 변경 |
| `host_name` | 시드의 `university` |
| `name` | LLM `festival_name`. 프롬프트에 "주최명 제외" 규칙 추가 |
| `start_date` / `end_date` / `venue_name` | 기존 유지 |
| `poster_url` | 기존 `og:image` (구 `poster_image_url`) |
| `image_urls` | 신규 — 본문 컨테이너의 `<img>` 수집, 최대 5장, `\|` 구분 |
| `description` | 신규 — LLM이 본문 사실만으로 2~3문장 생성 |
| `hashtags` | 신규 — 본문에 실제 있는 해시태그만, `#` 제거, `\|` 구분 |
| `external_visitor_policy` | 신규 — `ALLOWED` · `CONDITIONAL` · `DENIED`, 근거 없으면 빈 값 |
| `verification_method` | 신규 — `NONE` · `STUDENT_ID` · `PRE_BOOKING` · `INVITATION` · `OTHER` |
| `ticket_type` | 신규 — `FREE` · `PAID` |
| `ticket_open_at` | 신규 — `YYYY-MM-DDTHH:mm:ss` |
| `admission_raw` | 입장·티켓 판단 근거가 된 본문 원문 인용, 200자 컷. 구 `outsider_admission`+`ticket_info`를 대체 |
| `source_url` | 기존 유지 |
| `discovery` | 대문자화: `MANUAL` · `SITEMAP` · `SEARCH`. 실패 행은 빈 값(백엔드 확인 항목 5) |
| `flag` | 대문자화: `OK` `FETCH_FAILED` `EMPTY_BODY` `EXTRACT_FAILED` `MISMATCH` `NO_CANDIDATE` `NO_SOURCE` |
| `instagram_url` | 기존 handle → `https://www.instagram.com/<handle>` |

삭제: `campus` `region` `year` (year는 키에 내포, campus/region은 시드에 남는다).

### lineup.csv

```
import_key,day,order,artist_raw,artist_canonical,revealed
```

- `day`: LLM이 본문 근거(일차 표기·날짜·시작일)로 정수 산출. 불명이면 빈 값
  (백엔드에서 INVALID → 검수자가 채운다)
- `order`: 일차 내 본문 등장 순서로 1부터 부여(build 단계 enumerate). 헤드라이너
  판정은 검수자의 몫 — 수집 모듈은 판단하지 않는다는 기존 결정과 일관
- `revealed`: 구 `is_secret`의 반전. 시크릿 게스트는 `revealed=false` +
  `artist_raw`/`artist_canonical` 빈 값 (명세 검증 규칙 준수)
- `flag != OK`인 축제의 lineup 행은 출력하지 않는다 — 백엔드에서 고아
  INVALID 행만 만든다
- 삭제: `day_label` `date` `time` `source_url` (원본 확인은 festivals의
  `source_url`로)

### artists.csv

```
name,other_names,genre,category,image_url,needs_review
```

- `name` ← 구 `name_canonical`
- `other_names` ← 구 `aliases` ∪ `name_en` ∪ `real_name` 병합, `name` 중복 제거,
  구분자 `;` → `\|`
- `genre`: 신규 — `HIPHOP` · `BALLAD_RNB` · `DANCE` · `BAND`, 확실치 않으면 빈 값
- `image_url`: 항상 빈 값 (크롤러는 아티스트 이미지를 수집하지 않는다, 선택 필드)
- `needs_review`: 명세에 없지만 유지 — 백엔드에 스펙 추가를 제안하고(확인 항목 3),
  거부되면 컬럼을 제거한다

### 공통 규칙

- 인코딩 `utf-8-sig`(BOM) 유지 — Excel 호환용. 백엔드에 BOM 허용 명시 요청(확인 항목 2)
- 다중값 구분자 `\|`, 불확실하면 빈 칸, 날짜 `YYYY-MM-DD`
- CSV 원자적 쓰기(`os.replace`)와 수식 새니타이즈는 기존 그대로

## 파이프라인 변경

### schema.py

- `ExtractionResult`: `outsider_admission` `ticket_info` 제거.
  추가 — `description: str | None`, `hashtags: list[str]`,
  `external_visitor_policy` · `verification_method` · `ticket_type`은
  `Literal[...] | None`(pydantic이 enum 검증 — 벗어나면 기존 재시도 경로),
  `ticket_open_at: str | None`, `admission_raw: str | None`
- `LineupItem`: `day_label` `date` `time` 제거, `day: int | None` 추가
- `ArtistMaster`: `name` `other_names: list[str]` `genre` `category`
  `needs_review`로 재편 — LLM이 별칭·영문표기·본명을 처음부터 `other_names`
  하나로 합쳐 내놓는다

### extract.py

프롬프트에 추가: 축제명은 주최명 제외 / description은 본문 사실만 2~3문장,
수식·과장 금지 / hashtags는 본문에 실제 있는 것만 / enum은 본문 근거 있을 때만,
없으면 null / `admission_raw`는 판단 근거 문장을 그대로 인용 / `day`는 일차
표기·날짜·시작일로 정수 판단, 불명이면 null. 재시도 로직은 기존 그대로.

### fetch.py

`parse_html`이 본문 컨테이너 안의 `<img>` src(+지연로딩 `data-src`)를 절대 URL로
수집, 등장순 중복 제거, 최대 5장 → `FetchResult.image_urls`. trafilatura 폴백
경로(컨테이너 못 찾음)면 빈 리스트.

### crawl.py

- `FESTIVAL_FIELDS` / `LINEUP_FIELDS`를 위 확정 헤더로 교체. build 함수에서
  대문자 변환, `\|` 조인, 인스타 URL 변환, `admission_raw` 200자 컷,
  order 부여, revealed 반전
- **캐시 스키마 버전**: 레코드에 `schema_version: 2` 기록. `process_row`가
  버전 불일치 캐시를 만나면 그 대학만 자동 재수집한다. 중단·안내 방식이 아닌
  이유: 이번 재수집은 의도된 동작이고 진행 로그가 대학별로 이미 보인다.
  `output/<연도>/discovered/`(탐색 후보 캐시)는 유지 — 재크롤이 WebSearch를
  다시 부르지 않는다
- **재수집 실패 시 구 캐시 폴백**: 재수집 시도가 실패했는데 구 캐시가 `ok`였다면
  구 캐시를 유지하고 그 행은 구 데이터로 출력한다(신규 필드만 빈 값).
  원본 글이 그새 삭제됐을 때 멀쩡한 데이터를 날리지 않는다 — "재실행은 복원이지
  파괴가 아니다"(DEC-0028)와 같은 원칙

### enrich.py

- `ARTIST_FIELDS` → 위 확정 헤더. 프롬프트에 genre 분류 추가
- **1회성 마이그레이션**: `artists.csv`가 구 헤더면 기계적 변환(별칭류 →
  `other_names` 병합) + 기존 아티스트 name 목록으로 genre 분류 LLM 1콜.
  `artist_mapping.json`은 건드리지 않는다

### review.html (serve.py는 변경 없음)

컬럼명 교체(`import_key` `host_name`), 상세 표에 입장·티켓 구조화 필드와
`admission_raw` · `description` · `hashtags` · `image_urls` 표시, lineup은
`day일차 · order번` + `revealed=false`에 🔒(반전 주의), artists는
`name` / `other_names` / `genre` + `needs_review` ⚠️ 유지.
serve.py의 캐시 삭제는 시드 `university`와 캐시 파일명 기준이라 무관.

## 실행 순서 (운영자 관점)

```
python crawl.py --year 2026   # 버전 불일치 캐시 자동 재수집 (~30-50분, 세션 한도 유의)
python enrich.py              # artists.csv 마이그레이션 + genre 분류
```

손잡이 추가 없음 — `--year` 하나 유지(DEC-0031).

## 백엔드 확인·전달 리스트

| # | 항목 | 유형 |
| --- | --- | --- |
| 1 | flag 나머지 5종: `FETCH_FAILED` `EMPTY_BODY` `EXTRACT_FAILED` `MISMATCH` `NO_SOURCE` | 전달 (명세 🚧 채움) |
| 2 | BOM 붙은 UTF-8(utf-8-sig) 허용 명시 요청 — Excel 호환용 | 확인 |
| 3 | `artists.csv`에 `needs_review` 컬럼 스펙 추가 제안 | 제안 |
| 4 | 명세 오탈자: festivals 헤더 코드블록 `instagram_url` 누락, artists 헤더 끝 `, `, `\|` 구분자가 표 마크다운을 깨뜨림 | 전달 |
| 5 | 실패 행(`flag != OK`)의 `discovery` 빈 값 허용 확인 (명세상 필수지만 어차피 SKIP) | 확인 |
| 6 | `instagram_url` 컬럼 위치(맨 끝) 확정 | 확인 |

## 테스트·검증

- 기존 테스트(138개)를 새 컬럼·필드로 갱신
- 신규: 헤더가 명세 문자열과 정확히 일치 / order 부여 / 시크릿 게스트
  (빈 값 + `revealed=false`) / enum 대문자 변환 / `admission_raw` 200자 컷 /
  인스타 handle→URL / 이미지 수집(셀렉터·폴백) / 캐시 버전 불일치 재수집 /
  재수집 실패 시 구 캐시 폴백 / artists.csv 구 스키마 마이그레이션
- 완료 기준: ① 전체 테스트 통과 ② `--limit 1` 스모크 ③ 전체 재크롤 후
  `ok` 26곳 유지 + 정규화 보존 확인 ④ review.html 육안 확인
- 백엔드 API가 구현 전이라 업로드 E2E는 불가 — 헤더 일치 테스트가 명세와의
  계약을 고정한다

## 결정 요약

| 결정 | 이유 |
| --- | --- |
| 제자리 전환 (export 단계 없음) | 신규 필드가 추출까지 거슬러 올라감. 스키마 두 벌은 반드시 어긋난다 |
| 전체 재크롤로 신규 필드 채움 | 명세상 빈 값도 유효하지만 소개·분류가 비면 검수자가 전부 손으로 채워야 한다 |
| `order`는 본문 등장 순서 | 헤드라이너 판정은 검수자 몫 — 수집 모듈은 판단하지 않는다 |
| `description`은 본문 근거 요약 생성 | 검수자가 검토하는 초안이라는 전체 설계 철학 안에서 허용 |
| `flag != OK` lineup 미출력 | 백엔드에서 고아 INVALID 행만 만든다 |
| `real_name` → `other_names` 병합 | 컬럼이 사라지므로, 본명도 검색 매칭에 유용해 별칭으로 보존 |
| `needs_review` 유지 + 스펙 제안 | 크롤러가 이미 만드는 신호. 백엔드 프리뷰에 같은 개념 존재 |
| 캐시 버전 불일치는 자동 재수집 | 의도된 동작이고 진행 로그가 보인다. 탐색 캐시는 유지 |
| 재수집 실패 시 구 캐시 폴백 | 재실행이 데이터를 파괴하면 안 된다 (DEC-0028 원칙) |
