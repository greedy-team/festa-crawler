# 축제 좌표 공급과 import_key 캠퍼스 구분 — 설계

- 이슈: [greedy-team/festa-crawler#18](https://github.com/greedy-team/festa-crawler/issues/18)
- 짝 이슈: [greedy-team/festa-backend#69](https://github.com/greedy-team/festa-backend/issues/69) — 임포트가 좌표 컬럼을 받도록
- 날짜: 2026-08-24

## 배경과 목표

백엔드 발행 게이트는 셋을 본다 — 라인업 0건(`LINEUP_EMPTY`), 주최 미연결
(`HOST_NOT_LINKED`), 좌표 없음(`COORDINATES_MISSING`). 앞의 둘은 크롤러 산출물이 채운다.
**세 번째는 어떤 경로로도 채워지지 않는다.** `festival` 테이블에 `latitude`/`longitude`가
있고 `FestivalPublishBlocker.evaluate()`가 그것을 읽지만, CSV에 컬럼이 없고 백엔드에도
값을 넣는 코드가 없다. 임포트로 들어온 축제는 **전부 발행 불가**다.

좌표는 크롤링으로 얻을 수 없다 — 원천이 블로그이고 위경도가 적혀 있지 않다. 사람이
채워야 하며, 문제는 **어디에** 채우느냐다.

`universities-<연도>.csv`는 이미 캠퍼스 단위 행이다 (`university,campus,region,year,url`).
한 행 = 한 캠퍼스 = 한 축제. 좌표를 여기 두면 캠퍼스 단위로 자연스럽게 갈리고,
DB 스키마를 건드리지 않는다.

**목표: 시드가 좌표의 원본이 되고, 산출물이 그대로 발행 가능한 축제가 되게 한다.**

같은 자리에서 열려 있던 `import_key` 형식도 닫는다. 현행 `{주최}-{연도}`는 한 주최가
캠퍼스별로 축제를 열면 키가 겹쳐 백엔드 `uq_festival_import_key`를 위반한다.
**키를 생성하는 쪽이 형식을 정한다** — ERD 확정본 v2의 「열린 질문」이 결정 소유자를
크롤러 담당자로 지정해 뒀다.

### 지금이 가장 싼 시점이다

임포트 커밋(반영)은 **2026-08-24 05:10 UTC에 develop으로 들어왔다** (PR #40 / 이슈 #39).
`POST /admin/imports/{importId}/commit`과 `ImportCommitService`가 축제 행을 만든다.

그래도 **운영 데이터는 아직 없다.** GitHub Environment에 `development` 하나뿐이고
`production`이 없어 `main` 배포가 `DEPLOY_ENABLED` 가드에서 중단된다 — 운영 DB가 아직
서 있지 않다.

- `import_key` 형식을 바꿔도 깨질 운영 데이터가 없다. 나중에 바꾸면 키 변경 마이그레이션이
  붙고, ERD 확정본이 경고한 「임포트가 기존 축제를 못 찾아 중복 행을 만든다」를 직접 밟는다
- 좌표 매핑은 커밋 구현에 **한 번만** 얹으면 된다. 커밋이 갓 머지돼 그 위에 쌓인 것이 없다

> **E2(development)에 시험 임포트한 축제가 있으면 그 행은 새 키와 맞지 않는다.**
> 재임포트 전에 시험 데이터를 비워야 한다 — 그러지 않으면 옛 키의 축제가 남고 새 키로
> 같은 축제가 한 벌 더 생긴다. 확인과 정리는 백엔드 담당자 몫이다.

### 이 설계가 지키는 기존 결정

`host`에 캠퍼스·좌표를 두는 안을 검토했으나 기각했다.

> `host.sub_name` — 제거. **캠퍼스는 주최가 아니라 축제의 속성이다.**
> 한 주최가 캠퍼스별로 축제를 열면 한 행에 못 담는다
> — ERD 확정본 「세션에서 제거·변경한 것」 (확정본 v2가 「반영 완료」로 재확인)

`host`에 캠퍼스 컬럼을 두는 것은 이미 뺀 `sub_name`을 이름만 바꿔 되돌리는 것이다.
그리고 `host`는 대학 전용이 아니라 지자체·기업까지 받으려고 일반화한 이름이라,
`campus`는 그 테이블에 **영원히 대학에만 채워지는 컬럼**이 된다.

## 산출물 스키마

### `universities-<연도>.csv` (시드)

```
university,campus,region,year,url,latitude,longitude
```

- `latitude`/`longitude`는 사람이 채운다. 캠퍼스 정문 또는 축제 주무대 기준
- **빈 값을 허용한다.** 그대로 CSV로 나가고 백엔드 발행 게이트가
  `COORDINATES_MISSING`으로 막는다. 크롤러가 막지 않는다 — 게이트가 있는 이유가 이것이다
- **크롤러는 문자열 그대로 싣는다.** `float` 변환도 범위 검증도 하지 않는다.
  검증은 백엔드 한 곳이다 (작업 원칙 §5 — 같은 규칙을 두 곳에 적지 않는다).
  시드 오타는 업로드 미리보기에서 행 번호와 함께 드러난다

### festivals.csv

```
import_key,host_name,name,start_date,end_date,venue_name,latitude,longitude,poster_url,image_urls,description,hashtags,external_visitor_policy,verification_method,ticket_type,ticket_open_at,admission_raw,source_url,discovery,flag,instagram_url
```

19 → 21. `venue_name` 뒤에 넣는다 — 장소 관련 필드가 모이고,
`festival` 테이블의 `venue_name, address, latitude, longitude` 순서와 같다.

| 컬럼 | 값의 출처 |
| --- | --- |
| `latitude` | 시드의 `latitude` 문자열 그대로 |
| `longitude` | 시드의 `longitude` 문자열 그대로 |

`flag != OK`인 행에도 좌표는 실린다 — 시드에서 오는 값이라 수집 성공 여부와 무관하다.

`address`는 넣지 않는다. 발행을 막지 않고, 「주소 복사」 UI 존재 여부가 미확인이다.
필요해지면 같은 자리(`venue_name` 뒤)에 추가한다.

> **음수 좌표 주의.** `_sanitize_cell()`이 `-`로 시작하는 값 앞에 `'`를 붙인다
> (Excel 수식 인젝션 가드). 국내 좌표는 위도·경도 모두 양수라 지금은 안 걸리지만,
> **국내 한정이라는 전제 위에 서 있다.** 해외 좌표가 들어오면 그 가드를 좌표 컬럼에서
> 예외 처리해야 한다.

### lineup.csv · artists.csv

컬럼 변경 없음. `lineup.csv`의 `import_key` 값만 새 형식을 따라간다.

## import_key 형식

```
{university}-{campus}-{year}
```

```
연세대학교-신촌캠퍼스-2026
성균관대학교-인문사회과학캠퍼스-2026
성균관대학교-자연과학캠퍼스-2026        ← 시드에 행을 추가하면 자동으로 갈린다
```

기존 `{university}-{year}`의 자연스러운 확장이며 **시드 행과 1:1**이다.

**볼트 후보에서 월을 뺐다.** ERD 확정본 v2의 후보는
`{주최}-{연도}-{월}[-{캠퍼스 구분}]`(예: `성균관대학교-2026-05-인문사회`)이었으나,
그 후보 자신이 약점을 달고 있었다 — **키가 데이터에서 파생되어 일정이 월을 넘겨 연기되면
키가 바뀌고, 그때 임포트가 기존 축제를 못 찾아 중복 행을 만든다.** 캠퍼스는 시드 상수라
흔들리지 않는다.

**전 29행의 키가 바뀐다.** 임포트된 축제가 0건이라 지금은 비용이 없다.

남는 한계: 한 캠퍼스가 한 해에 축제를 둘 열면(봄 대동제 + 가을 축제) 여전히 겹친다.
현재 시드는 캠퍼스당 축제 1개이며, 그 상황은 시드 행이 2개가 되어야 성립하므로 그때 가른다.

백엔드는 `import_key`를 재생성하지 않고 불투명한 문자열로 다루므로
(임포트 preview 결정), 형식 변경에 따른 백엔드 로직 변경은 없다.

## 파이프라인 변경

### crawl.py

| 대상 | 변경 |
| --- | --- |
| `UniversityRow` | `latitude: str`, `longitude: str` 추가 |
| `load_universities()` | 두 컬럼 읽기 (`.strip()`, 문자열 유지) + **중복 대학 가드**(아래) |
| `FESTIVAL_FIELDS` | `venue_name` 뒤에 2개 |
| `import_key()` | `(university, campus, year)`로 시그니처 변경 |
| `record` 초기화 (L120) | `latitude`·`longitude` 추가 — `campus`·`region`과 같은 자리 |
| 캐시 히트 갱신 (L109) | `cached["latitude"]`·`cached["longitude"]`를 시드 기준으로 갱신 |
| `_keep_stale_on_failure()` (L159) | 위와 동일 |
| `build_festival_row()` | 두 컬럼을 `record`에서 그대로 |

`import_key()` 호출부는 둘이다 — `build_festival_row()`(L169), `build_lineup_rows()`(L200).

L109·L159의 갱신이 필수다. **이것이 없으면 기존 캐시(좌표 없이 기록됨)로 히트한 대학의
좌표가 빈 값으로 나간다.** 기존 주석이 이미 그 자리를 「시드 전용 필드는 현재 행 기준으로
갱신」으로 규정하고 있으므로 같은 규칙의 적용이다.

### SCHEMA_VERSION은 올리지 않는다 (2 유지)

좌표는 시드에서 오고 **LLM 추출 결과는 한 글자도 바뀌지 않는다.** 올리면 29곳 재크롤이
아무 소득 없이 발생하고, Claude 구독 세션 한도까지 소모한다.

캐시 무효화 결정의 취지는 「추출 결과에 영향을 주는 스키마 변경이면 재수집」이고,
시드 전용 필드는 이미 캐시 밖에서 갱신되는 구조다(L108~110의 기존 주석).
스키마가 바뀌었다는 이유로 반사적으로 올리지 않는다.

### load_universities() — 중복 대학 가드 (신규)

시드에 같은 `university`가 2행 이상이면 **명시적 에러로 중단한다.**

**캐시가 대학 이름으로만 갈리기 때문이다.**

| 위치 | 키 |
| --- | --- |
| `crawl.py` L101 | `output/<연도>/raw/{university}.json` |
| `discover.py` L116 | `output/<연도>/discovered/{university}.json` |
| `serve.py` L99~101 | 검수 화면 「다시 돌리기」가 `university`로 두 캐시를 지운다 |

가드가 없으면 성균관대 두 캠퍼스가 **탐색 후보 캐시를 공유한다.** `discover_cached()`는
`year`만 보고 히트하므로 둘째 캠퍼스가 첫째 캠퍼스의 후보 URL을 그대로 받고,
`verify()`는 대학 이름만 대조하므로(`extract.py` L132~134) 캠퍼스를 구분하지 못한다.
→ **같은 축제가 두 import_key로 조용히 두 번 나간다.**

오류가 나지 않고 결과만 틀리는 종류이며, 이 저장소가 이미 두 번 겪은 유형이다
(식별자 도입 시 마이그레이션 누락, 레이아웃 변경 시 조용한 재작업).

**캐시 키를 캠퍼스 단위로 바꾸는 것은 이번 범위 밖이다** — 파일명 규칙이 바뀌어 기존 캐시
29개가 전부 미스가 되고, 「레이아웃을 바꾸면 옛 사용자에게 조용한 재작업이 생긴다」에 따라
감지·안내 또는 rename 마이그레이션이 함께 필요하다. 다캠퍼스가 실제로 필요해질 때 그
비용을 치른다. 가드는 그때까지 조용한 오염을 막는다.

### 변경 없는 것

`extract.py` · `fetch.py` · `enrich.py` · `discover.py` · `review.html` · `serve.py`.

- `verify()`는 `university`를 그대로 받는다 — 캠퍼스를 붙이지 않는다. 블로그 본문이
  캠퍼스명까지 적을 보장이 없다
- `host_name`은 `university` 그대로다. **주최는 대학이고 캠퍼스는 축제의 속성이다.**
  성균관대 두 캠퍼스는 같은 `host` 행에 붙고 `import_key`로 갈린다
- `review.html`의 「다시 돌리기」는 `host_name`을 넘기므로 그대로 동작한다

## 백엔드 짝 변경 (요구사항)

**헤더가 순서까지 정확히 일치하는 계약이라 양쪽이 동시에 바뀌어야 한다.**
크롤러만 배포하면 업로드가 전부 막힌다. 상세는 `festa-backend` 이슈 문서.

| 대상 | 요구 |
| --- | --- |
| `ImportSection.FESTIVALS` | 헤더 21개, 크롤러와 같은 순서 |
| `ImportCsvParserTest` | 독립 리터럴 계약 동기화 |
| `ImportPreviewService.festivalRow()` | 좌표 파싱·검증 (아래) |
| `normalized` | `latitude`·`longitude` 추가 |
| `ImportCommitService#buildFestival()` (L439) | `Festival.builder()`에 좌표 |
| `ImportCommitService#updateFestival()` (L459) | `Festival.updateFromImport()`에 좌표 (시그니처 +2) |
| 기존 테스트의 CSV 행 픽스처 | 컬럼 2개 증가 반영 |

**좌표 검증이 백엔드 추가분의 핵심이다.** `flag`·enum과 달리 좌표는 값이 틀려도 형식이
맞아 보인다. `37.5`를 `3.75`로 치면 조용히 기니만 앞바다이며, 지도에 찍히기 전까지
아무도 모른다.

- 빈 값 — 통과. 발행 게이트가 막는다
- 숫자 아님 / 위도 ±90 초과 / 경도 ±180 초과 — **error** (해당 행 `INVALID`)
- 국내 범위(위도 33~39, 경도 124~132) 밖 — **warning.** 미리보기에 이미 있는 경고
  체계를 쓴다. 검수자가 보고 판단한다 — 크롤링은 초안 생성기이고 최종 신뢰는 사람이
  담보한다는 이 파이프라인의 축과 같다

## 실행 순서 (운영자 관점)

1. 백엔드 짝 변경 머지·배포
2. 시드 `universities-2026.csv`에 좌표 29행 입력
3. `.venv/bin/python crawl.py --year 2026` — 캐시 히트로 **LLM 호출 없이** CSV만 재생성
4. `output/2026/festivals.csv` 등 3종을 `POST /admin/imports/bundle`에 업로드

역순이면 백엔드가 새 헤더를 거부한다. 산출물을 사람이 올리는 로컬 배치라
**사이에 업로드만 하지 않으면 창이 없다.**

## 테스트·검증

### 크롤러

- `FESTIVAL_FIELDS` 헤더 계약 테스트 갱신 (`tests/test_crawl.py` L121)
- `test_import_key_format()` — `import_key("연세대학교", "신촌캠퍼스", 2026)`
  → `"연세대학교-신촌캠퍼스-2026"`
- `test_import_key_links_festival_and_lineup()` — 축제·라인업이 같은 새 키를 쓰는지
- 좌표가 시드에서 festival 행까지 전달되는지 (빈 값 포함)
- **캐시 히트 경로에서 좌표가 채워지는지** — 좌표 없이 기록된 구 캐시로 히트시켜
  시드 값이 반영되는지. L109 갱신을 빠뜨리면 여기서 잡힌다
- 중복 대학 시드가 중단되는지
- 시드 픽스처의 `fieldnames`(L616) 갱신

### 실측

- `crawl.py --year 2026` 재실행 후: **29행 전부 좌표 채워짐**, LLM 호출 0건,
  `flag` 분포가 이전과 동일(`OK` 26 · `NO_CANDIDATE` 3), 라인업 행 수 유지
- `import_key` 29개가 서로 다른지

### 통합

- 새 CSV 3종을 `POST /admin/imports/bundle`에 업로드 → blocker 0건
- 좌표 오타(`3.75`)를 넣은 행이 warning으로 잡히는지

## 결정 요약

| | |
| --- | --- |
| 좌표의 원본 | 크롤러 시드 `universities-<연도>.csv` |
| 캠퍼스의 위치 | 축제의 속성 — `import_key`에만 반영. `host`는 안 건드린다 |
| `import_key` 형식 | `{university}-{campus}-{year}`. 월은 넣지 않는다 |
| 좌표 검증 주체 | 백엔드 한 곳. 크롤러는 문자열을 그대로 싣는다 |
| `SCHEMA_VERSION` | 2 유지 — 재크롤하지 않는다 |
| DB 스키마 변경 | 없음 |

## 범위 밖

- **캐시 키의 캠퍼스 분리** — 다캠퍼스가 실제로 필요해질 때. 그때까지는 시드 가드가 막는다
- **`address` 컬럼** — 발행을 막지 않는다. 「주소 복사」 UI 존재 여부가 정해지면
- **수동 입력(붙여넣기) 명령** — 백엔드가 `discovery=PASTED`를 이미 허용하고 있으나
  크롤러에 그 경로가 없다. 별건이다
- **`name`에서 주최명을 떼는 주체** — 열린 질문 그대로 둔다
- **해외 좌표** — `_sanitize_cell`의 `-` 가드와 충돌한다. 국내 한정 전제를 벗을 때
