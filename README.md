# FESTA 크롤러

대학 축제 정보(축제 상세 + 라인업)를 웹에서 수집·추출해 사람이 검토할 CSV로 만드는 로컬 배치
크롤러다. 출처는 손으로 넣은 URL을 우선하고, 없거나 실패한 대학은 검색으로 후보를 찾는다.
설계 근거는 [`2026-08-04-crawler-pipeline-design.md`](./2026-08-04-crawler-pipeline-design.md) 참고.

**크롤러는 초안 생성기다.** 최종 신뢰는 사람이 담보한다 — CSV를 검토하는 단계가 곧 검수
큐다. 크롤러를 돌리고 그 결과를 검수하는 조작판이 [관리자 페이지](#관리자-페이지)(`./admin.sh`)이고, 검토를 마친
CSV는 백엔드 어드민에 첨부해 가공·발행한다.

## 파이프라인

```mermaid
flowchart TD
    seed["universities-2026.csv<br/>대학 29곳 시드"] --> has{"시드에 URL이<br/>적혀 있나?"}

    has -->|"있음"| manual["수동 URL 1건 시도"]
    has -->|"없음"| sm

    manual --> mok{"성공?"}
    mok -->|"ok"| adopted["출처 확정<br/>discovery = manual"]
    mok -->|"실패"| sm["사이트맵 후보<br/>정식 표기 + 연도 매칭"]

    sm --> smok{"verify 통과한<br/>후보가 있나?"}
    smok -->|"있음"| adoptedM["출처 확정<br/>discovery = sitemap"]
    smok -->|"없음"| search["discover.py<br/>웹 검색으로 후보 수집"]

    search --> cand["후보를 순서대로<br/>최대 3개 시도"]
    cand --> cok{"verify 통과한<br/>후보가 있나?"}
    cok -->|"있음"| adoptedS["출처 확정<br/>discovery = search"]
    cok -->|"없음"| failed["no_candidate<br/>(수동 URL이 있었다면<br/>그 실패 사유 유지)"]

    adopted --> csv["festivals.csv<br/>lineup.csv"]
    adoptedM --> csv
    adoptedS --> csv
    failed --> csv

    csv --> enrich["enrich.py<br/>아티스트 표기 정규화"]
    enrich --> artists["artists.csv"]

    csv --> review["admin.sh<br/>관리자 페이지 (로컬)"]
    artists --> review
    review --> admin["백엔드 어드민에 CSV 첨부<br/>→ 가공·발행"]

    admin -.-> note["아직 미구현<br/>백엔드는 스켈레톤 상태"]
```

크롤러의 책임은 **검토를 마친 CSV까지**다. 그 뒤 적재·가공·발행은 백엔드 어드민 소관이며,
현재 백엔드에는 해당 기능이 없다 — 지금은 CSV가 최종 산출물이다.

산출물 3종의 컬럼·값 형식은 백엔드 **크롤링 번들 업로드 API** 명세의 CSV 스펙에 맞춰져
있어, 검토를 마친 파일을 그대로 업로드하면 된다. 전환 설계는
[`2026-08-09-bundle-spec-migration-design.md`](./2026-08-09-bundle-spec-migration-design.md) 참고.

**URL 1건을 처리하는 과정**은 출처가 수동이든 사이트맵이든 검색이든 동일하다.

```mermaid
flowchart LR
    url["URL"] --> robots["robots.txt 확인<br/>동일 호스트 3초 간격"]
    robots --> body["본문 추출<br/>셀렉터 → trafilatura 폴백"]
    body --> llm["claude -p<br/>구조화 추출 (JSON)"]
    llm --> ver{"verify<br/>이 글이 정말<br/>그 대학·그 연도인가?"}
    ver -->|"통과"| ok["ok"]
    ver -->|"불일치"| mis["mismatch"]
```

마지막 `verify` 단계가 검색 탐색의 안전장치다. LLM이 URL을 지어내도 열리지 않으면 탈락하고,
엉뚱한 대학 글이면 `mismatch`로 걸러진다. 그래서 검색이 지저분한 후보를 주더라도 잘못된
출처가 채택될 여지가 작다.

## 정보 구조

산출물은 CSV 3종이다. `output/`에 생성되며 git에 커밋하지 않는다.

```mermaid
erDiagram
    festivals ||--o{ lineup : "import_key"
    lineup }o--|| artists : "artist_canonical"

    festivals {
        string import_key "축제 식별자 (주최명-연도)"
        string host_name "주최명 (대학명)"
        string name "축제명"
        date start_date "시작일"
        date end_date "종료일"
        string venue_name "장소"
        string poster_url "포스터 이미지 URL"
        string image_urls "이미지 URL (|로 연결)"
        string description "축제 설명"
        string hashtags "해시태그 (|로 연결)"
        string external_visitor_policy "외부인 입장 (ALLOWED/CONDITIONAL/DENIED)"
        string verification_method "본인 확인 방법"
        string ticket_type "FREE / PAID"
        string ticket_open_at "예매 오픈 시각"
        string admission_raw "입장 조건 원문"
        string source_url "출처 URL"
        string discovery "MANUAL | SITEMAP | SEARCH"
        string flag "처리 결과"
        string instagram_url "인스타그램 URL"
    }
    lineup {
        string import_key "축제 식별자"
        int day "n일차 (원문 없으면 빈 값)"
        int order "그 날 안에서의 공연 순서"
        string artist_raw "원문 표기 (시크릿 게스트는 빈 값)"
        string artist_canonical "정식 표기 (시크릿 게스트는 빈 값)"
        bool revealed "공개 여부 (시크릿 게스트는 false)"
    }
    artists {
        string name "정식 활동명"
        string other_names "다른 표기 (|로 연결)"
        string genre "HIPHOP / BALLAD_RNB / DANCE / BAND"
        string image_url "이미지 URL"
        bool needs_review "확신 낮음"
    }
```

`artist_raw`는 원문 표기를 그대로 보존하고 `artist_canonical`이 정규화된 이름을 담는다
(`십센치` → `10CM`). 원문을 남겨두는 이유는 검수할 때 출처와 대조할 수 있어야 하기 때문이다.

## 모듈 구조

```mermaid
flowchart TD
    crawl["crawl.py<br/>오케스트레이션 · 캐시 · flag · CSV"]
    crawl --> discover["discover.py<br/>후보 URL 수집"]
    crawl --> fetch["fetch.py<br/>본문 · og:image · 인스타 후보"]
    crawl --> extract["extract.py<br/>추출 · 검증 · verify"]
    enrich["enrich.py<br/>아티스트 정규화"] --> extract
    discover --> extract
    extract --> claude(["claude CLI<br/>유일한 LLM 접점"])
    schema["schema.py<br/>pydantic 스키마"]
```

| 파일 | 하는 일 | LLM 호출 |
|---|---|---|
| `crawl.py` | 시드 순회, 출처 결정, 캐시 판정, flag 부여, CSV 출력 | 없음 |
| `discover.py` | 웹 검색으로 후보 URL 수집. **판단하지 않는다** | 탐색 1콜 (도구 ON) |
| `fetch.py` | robots·간격 준수 수집, 본문·`og:image`·인스타 후보 채집 | 없음 |
| `extract.py` | 구조화 추출, 역방향 검증(`verify`), `call_claude` | 추출 1콜 (도구 OFF) |
| `enrich.py` | 아티스트 표기 정규화, 마스터 생성 | 후처리 1콜 (도구 OFF) |
| `schema.py` | pydantic 스키마 | 없음 |

`claude` CLI 호출은 전부 `extract.call_claude` 하나를 지난다. 나중에 API로 옮길 때 그 함수
내부만 바꾸면 된다. **웹 검색 도구는 탐색 호출에서만 켜고**, 신뢰할 수 없는 블로그 본문을
읽는 추출·정규화 호출에서는 모든 도구를 차단한다.

## 설치

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

수집·추출·탐색 모두 로컬 Claude Code CLI(`claude`)를 헤드리스로 호출한다 — 실행 전 `claude`
로그인이 되어 있어야 한다. 별도의 API 키는 필요 없다.

## 실행

```bash
./admin.sh --year 2026          # 관리자 페이지 — venv가 없으면 만들고 띄운다
```

**이거 하나면 된다.** 수집·정규화·검수가 전부 그 화면 안에서 끝난다 — `crawl`·`enrich` 전체
실행도, 특정 대학만 다시 돌리는 것도 버튼이다 ([관리자 페이지](#관리자-페이지) 참고).
어느 디렉터리에서 실행해도 되고, 인자는 그대로 넘어간다 (`./admin.sh --year 2026 --port 8790`).

터미널에서 직접 부를 수도 있다. 화면 없이 배치로 돌리거나 `--limit`으로 스모크할 때 쓴다.

```bash
.venv/bin/python crawl.py --year 2026 [--limit N]   # --limit: 앞에서 N행만 처리 (스모크용)
.venv/bin/python enrich.py                          # crawl 완료 후 실행
.venv/bin/python serve.py --year 2026               # admin.sh 없이 서버만 직접 띄울 때
```

`crawl.py`가 `output/<연도>/festivals.csv`·`output/<연도>/lineup.csv`를, `enrich.py`가
`output/artists.csv`를 만든다. `artists.csv`는 연도 공통이다 — 시즌이 바뀌어도 새로 만들지
않고 계속 누적된다. 화면의 버튼이 실행하는 것도 정확히 이 두 명령이다.

**아티스트 정규화 매핑.** `enrich.py`가 만드는 `output/artist_mapping.json`은 `artist_raw` →
`artist_canonical` 대응을 연도 공통으로 누적한다. `crawl.py`는 실행할 때마다 이 매핑을 읽어
`lineup.csv`의 `artist_canonical`을 채우므로, `crawl.py`를 다시 돌려도 이미 정규화된 표기가
원문으로 되돌아가지 않는다.

**한 번 매핑된 이름은 다시 LLM에 가지 않는다.** `enrich.py`는 매핑에 키로 없는 이름만
정규화 대상으로 보낸다. `needs_review=true`로 확정된 아티스트(LLM이 확신하지 못해 원문
표기를 그대로 쓴 경우)도 매핑에는 이미 들어가 있으므로, `enrich.py`를 몇 번 더 돌려도
그 이름들은 재시도되지 않는다 — 같은 답을 578초 주고 다시 받지 않기 위해서다.
**고치는 방법은 손으로 고치는 것이다.** `output/artist_mapping.json`에서 해당 값을
정식 표기로 바꾸고 `enrich.py`를 다시 실행하면, 새 이름이 없어도 모든 연도의
`lineup.csv`가 그 값으로 갱신된다 (LLM 호출 없음). `output/artists.csv`의
`needs_review` 컬럼이 손볼 대상 목록이다.

**스키마 변경 시 재생성.** 캐시 레코드는 `schema_version`을 담고 있다. 버전이 다른
`output/<연도>/raw/*.json` 캐시는 `crawl.py` 실행 시 자동으로 재수집된다. 재수집이
실패하면 이전 성공 결과가 그대로 유지된다 — 캐시 파일은 지우지 않아도 되고, 다음 실행에서
다시 재시도한다.

**소요 시간.** 캐시가 빈 상태에서 29곳 전체를 돌면 30~50분 걸린다. 대부분이 LLM 호출 대기
시간이고, 특히 검색 탐색은 1건에 60초 이상이다. 중간에 끊겨도 캐시가 남으니 같은 명령으로
다시 실행하면 이어서 처리한다.

## 관리자 페이지

`./admin.sh`로 띄우는 로컬 화면(`serve.py` + `review.html`)이다. 크롤러를 돌리고 그 결과를
검수하는 조작판이며, 크롤러를 쓰는 정상 경로다.

**값을 고치는 기능은 없다.** 화면이 하는 일은 "무엇이 잘못됐는지 찾아내고 다시 돌리는 것"
까지고, 값 교정은 백엔드 어드민에 CSV를 첨부하는 단계에서 처리한다.

```
┌────────────────────────────────────────────────────────┐
│ [전체 크롤] [enrich]   ● 대기 중        로그 ▾          │
├──────────────────────┬─────────────────────────────────┤
│ [문제만] [검색출처]   │ 건국대학교-2026                  │
│ [전체]  [아티스트]    │  [다시 돌리기] [탐색부터]        │
│                      │  축제명 / 기간 / 장소 / 외부인   │
│ ● NO_CANDIDATE 숙명   │  티켓 / 인스타 / 포스터 / 출처   │
│ ● NO_CANDIDATE 동덕   ├─────────────────────────────────┤
│ ○ OK      건국       │ 라인업 8건                       │
│ ○ OK      고려       │  10CM ← 십센치   1일차 19:00    │
│ ...                  ├─────────────────────────────────┤
│                      │ 원본 (iframe)   [새 탭 ↗]        │
└──────────────────────┴─────────────────────────────────┘
```

**할 수 있는 것**

| | |
| --- | --- |
| 필터 `문제만` | `flag != OK` 행만. 진입 시 기본값 — 사람이 볼 것부터 보여준다 |
| 필터 `검색출처` | `discovery`가 `SITEMAP` 또는 `SEARCH`인 행. 손으로 고른 출처가 아니라 우선 확인 대상이다 |
| 필터 `전체` | 축제 29곳 전부 |
| 탭 `아티스트` | `artists.csv`를 `needs_review` 우선으로 정렬해 표시 (정렬만, 필터 아님) |
| 상세 보기 | 축제 필드 전체 + 그 축제의 라인업. `artist_canonical ← artist_raw`로 정규화 전후를 나란히 |
| 원본 대조 | `source_url`을 iframe으로 임베드. 막는 사이트가 많아 `새 탭 ↗`이 실질적 주경로다 |
| 버튼 `전체 크롤` | `crawl.py` 전체 실행 (캐시 비면 30~50분) |
| 버튼 `enrich` | `enrich.py` 실행 |
| 버튼 `다시 돌리기` | 그 대학의 `raw/` 캐시만 지우고 재실행. `MISMATCH`·`EMPTY_BODY`처럼 출처는 맞고 추출이 틀린 행에 |
| 버튼 `탐색부터` | `raw/`+`discovered/`를 지우고 재실행. `NO_CANDIDATE`처럼 후보 목록 자체가 쓸모없던 행에 |
| 로그 | 실행 중인 잡의 stdout을 1초 간격으로 흘려보낸다. 끝나면 상태가 바뀌고 목록이 자동 갱신된다 |
| 키보드 | `j`/`k`로 목록 이동 |

**행 단위 재실행이 전체 실행인 이유.** `crawl.py`에 "한 곳만" 옵션이 없다. 대신 그 대학의
캐시 파일을 지우고 `crawl.py`를 통째로 돌린다 — 나머지 28곳은 캐시 히트로 즉시 지나가고,
CSV 재생성까지 따라온다.

**제약**

- `127.0.0.1`에만 바인드한다. 외부에 열지 않는다
- 잡은 한 번에 하나만 돈다. 실행 중에 또 누르면 "이미 실행 중입니다" — `crawl`과 `enrich`가
  같은 Claude 구독 세션 한도를 쓰기 때문에 둘을 동시에 띄우면 양쪽이 깨진다
- 재실행 대상 대학명은 그 해의 시드(`universities-<연도>.csv`)에 실재하는 값만 받는다
- 원본 임베드·링크는 `http(s)` URL만 연다

## 대학 시드 (`universities-<연도>.csv`)

| 컬럼 | 내용 |
|---|---|
| `university` `campus` `region` | 대학 정보. CSV에만 있고 크롤링하지 않는다 |
| `year` | 수집 대상 연도 |
| `url` | 알고 있는 출처 URL. **비워도 된다** — 비면 검색으로 찾는다 |

나무위키는 라이선스(비영리) 문제로, 검색 엔진 결과 페이지는 `robots.txt` 차단 때문에 검색
후보에서 제외한다.

## flag 의미

`festivals.csv`의 `flag` 컬럼:

| flag | 의미 |
|---|---|
| `OK` | 수집·추출·검증 모두 성공 |
| `FETCH_FAILED` | 본문 수집 실패 (네트워크 오류, robots.txt 차단 등) |
| `EMPTY_BODY` | 본문이 100자 미만 (포스터 이미지만 있는 글 등) |
| `EXTRACT_FAILED` | LLM 추출이 2회 시도 후에도 유효한 JSON을 내지 못함 |
| `MISMATCH` | 추출은 됐지만 결과가 요청한 대학·연도 글이 아닌 것으로 판정 |
| `NO_CANDIDATE` | 검색까지 했으나 쓸 만한 후보를 찾지 못함 |
| `NO_SOURCE` | 출처를 확보하지 못한 그 밖의 경우 |

손으로 넣은 URL이 실패하고 검색도 실패하면 **`NO_CANDIDATE`가 아니라 그 URL의 실패 사유가
남는다** (`FETCH_FAILED` 등). URL이 깨졌다는 정보가 더 쓸모 있기 때문이다.

`flag != OK` 행은 운영자가 `source_url`을 직접 열어 확인한다.

## 캐시 동작

캐시는 두 종류다. 이 절의 `fetch_failed` 같은 **소문자 값은 캐시·내부 상태 표기**다 —
CSV로 쓸 때만 대문자(`FETCH_FAILED`)로 변환된다. 오타가 아니다.

**수집·추출 결과** — `output/<연도>/raw/<대학명>.json`. 시드의 **`url`과 `year`가
그대로면** 캐시를 반환하고 재수집하지 않는다. 둘 중 하나라도 바뀌면 캐시를 무시하고 다시
처리한다. 검색으로 찾은 URL이 아니라 **시드에 적힌 URL**이 판정 기준이라, 검색으로 채운
대학도 시드가 그대로면 재실행 때 검색을 반복하지 않는다.

**검색 후보 목록** — `output/<연도>/discovered/<대학명>.json`. 연도가 같으면 재사용한다. 검색
1건이 60초 이상 걸리기 때문에 이 캐시가 없으면 재실행 비용이 크다.

- **강제 재수집하려면** 해당 대학의 `output/<연도>/raw/<대학명>.json`을 지우고 다시 실행한다.
  검색까지 다시 하려면 `output/<연도>/discovered/<대학명>.json`도 함께 지운다.
- `fetch_failed`와 `extract_failed`는 캐시에 저장되지 않는다 — 네트워크 오류나 LLM 호출 실패
  같은 일시적 문제를 영구히 굳히지 않기 위함이다. `empty_body`·`mismatch`·성공 결과는 캐시된다.
- **새 시즌을 시작할 때** — 지난 시즌 시드는 그대로 두고 `universities-<연도>.csv`를 새로
  만든다. 이때 `url` 컬럼은 비워 둔다. 지난 시즌 URL을 그대로 채워 넣으면 죽은 링크라도
  그 URL은 verify에서 걸러지기 전에 추출 LLM 호출을 1건 쓴다 — 시드 URL 21건이 전부
  이전 연도 글이라면 21건의 회피 가능한 LLM 호출이다. `url` 컬럼을 비워 두면 그 호출 없이
  곧장 사이트맵 단계로 넘어간다.

## 운영 팁

- Claude 구독 세션 한도에 걸리면 크롤러가 중단된다. 한도가 리셋된 뒤 같은 명령으로 재실행하면
  이미 처리된 대학은 캐시로 건너뛰고 나머지만 이어서 처리한다.
- `enrich.py`는 매핑에 없는 아티스트를 한 번에 정규화하는 LLM 호출 1건이라 수 분(최대
  15분 타임아웃) 걸릴 수 있다. 첫 실행이 가장 오래 걸리고, 그 뒤로는 새 이름 수만큼만 든다.
- 자동으로 채워진 행(`discovery=SITEMAP` 또는 `SEARCH`)은 손으로 고른 출처가 아니므로
  **검수 때 우선 확인한다.** 대학 공식 홈페이지나 학보사가 잡히면 신뢰도가 높고,
  커뮤니티·티켓 플랫폼이면 한 번 더 본다.
- `discovery=SITEMAP`은 특정 블로그 몇 곳에서만 나온다. 시즌 종료 후 `discovery` 분포를 세어
  단일 출처 편중이 심해지지 않았는지 확인하고, 심해졌으면 탐색 순서를 재검토한다.
- 크롤러 산출물은 초안이다. **`./admin.sh`로 검토한 뒤 백엔드 어드민에 CSV를 첨부한다** —
  최종 신뢰는 검수 단계가 담보한다.
