# DB 이미지 교체 (2026-10) — 계획과 결과

2차 코드 리뷰(2026-10-15)의 결정 Q3 를 따로 처리한 작업입니다. 결정은 [ADR-007](adr/ADR-007-postgis-image.md).

## 1. 왜 바꾸나

| | 지금 로컬 (`imresamu/postgis:16-3.6-bookworm`) | 지금 CI (`postgis/postgis:16-3.5`) |
|---|---|---|
| 마지막 빌드 | 2026-02-09 — 이 저장소의 Debian 태그(bookworm·trixie)가 모두 여기서 멈춤 | 2026-08-31 push |
| PostgreSQL | 16.11 | **16.9** (`pgdg110`) |
| OS · glibc | Debian 12.13 · 2.36 (일반 보안 지원 종료, LTS 단계) | Debian 11 bullseye |
| PostGIS · GEOS · PROJ | 3.6.1 · 3.11.1 · 9.1.1 | 3.5.2 |
| 아키텍처 | arm64·amd64 ("testing only" 표기) | amd64 만 |
| 로케일 | `LANG=C.UTF-8` 로 초기화 | 이미지 기본 `en_US.utf8` |

- `docker compose pull` 로는 PG 16 마이너 보안판을 받을 수 없습니다. 16.12~16.15 에는 보안 수정이 들어 있습니다
  (예: 16.15 의 CVE-2026-16239 — EXECUTE/FETCH 포털 행 형식 불일치로 메모리 노출·임의 코드 실행, CVE-2026-14669 — `to_char()` 버퍼 넘침).
- CI 는 로컬과 PG·PostGIS 판과 로케일이 달라, CI 통과가 로컬 동작을 보장하지 않습니다.

## 2. 후보 (2026-10-15 확인)

Docker Hub API(태그·아키텍처·push 시각), 레지스트리의 이미지 설정(`PG_VERSION` 등), apt.postgresql.org 의 `trixie-pgdg` arm64 색인,
그리고 (a) 를 시험 빌드해 실제 설치된 판으로 확인했습니다.

| 후보 | arm64 | 최근 빌드 | PG | OS · libc | PostGIS · GEOS · PROJ | 판단 |
|---|---|---|---|---|---|---|
| **(a)** 공식 `postgres:16-trixie` + PGDG `postgresql-16-postgis-3` (`db/Dockerfile`) | 네이티브 | 기반 2026-10-06, PGDG 색인 2026-10-11 | 16.15 | Debian 13.7 · glibc 2.41 | 3.6.4 · 3.14.1 · 9.8.1 (GEOS·PROJ 는 PGDG 판) | **채택** |
| (b) 공식 `postgis/postgis:16-3.5` | 없음 (amd64 에뮬레이션) | 2026-08-31 | 16.9 | Debian 11 | 3.5.2 | 제외 — PG 가 더 오래됨, 16-3.6 태그 없음, 3.6→3.5 로 확장을 내릴 수 없음 |
| (c1) `imresamu/postgis:16-3.6-alpine` | 네이티브 | 2026-10-12 | 16.15 | Alpine 3.23 · musl | 3.6.1 (소스 빌드) | 제외 — libc 가 glibc→musl 로 바뀌어 기존 데이터 디렉터리의 정렬·문자 분류 가정이 깨질 수 있음, 여전히 testing 표기 |
| (c2) `imresamu/postgis:16-3.6-trixie` | 네이티브 | 2026-02-09 | 16.11 | Debian 13 | 3.6.1 | 제외 — bookworm 과 함께 멈춤 |
| (c3) `kartoza/postgis:16` | 네이티브 | 2024-03-17 | — | — | 3.4 | 제외 — 16 갱신 중단 |

(a) 는 imresamu bookworm 이미지가 하던 일(공식 postgres 이미지 위에 PGDG 패키지 설치 — 이미지 라벨 `3.6.1+dfsg-1.pgdg12+1`)을
직접 하는 것이고, upstream `postgis/docker-postgis` 의 Debian Dockerfile 과 같은 방식입니다. PG 마이너는 Docker 공식 이미지가,
PostGIS 는 PostgreSQL apt 저장소(PGDG)가 따라갑니다. 시험 빌드 39초, 이미지 957MB(기존 890MB).

## 3. 결정

1. `db/Dockerfile` — `FROM postgres:16-trixie`, PGDG 의 PostGIS 를 `3.6.*` 로 설치(마이너 고정, 패치는 따라감).
   upstream 의 초기화 스크립트(`initdb-postgis.sh`)는 넣지 않음 — 쓰는 확장은 마이그레이션이 만듦(V1 postgis·pgcrypto, V6 pg_trgm, V13 pg_stat_statements).
2. compose 의 db 를 `build: ./db` 로. 다른 설정(명령·볼륨·포트·`LANG=C.UTF-8`)은 그대로.
3. 보안판 받기 `make db-update` — `build --pull --no-cache db`(apt 층이 캐시되면 새 PostGIS 패치를 못 받으므로) → db 재기동 → `postgis_extensions_upgrade()`.
4. CI 는 서비스 컨테이너(미리 만든 이미지만 받음) 대신 같은 `db/Dockerfile` 을 빌드해 `LANG=C.UTF-8` 로 띄움.

## 4. 위험과 대응

| 위험 | 판단 | 확인·대응 |
|---|---|---|
| 데이터 디렉터리 호환 | 같은 메이저(16)는 마이너끼리 저장 형식이 같음(PG 릴리스 노트: dump/restore 불필요). postgres uid 999·`PGDATA` 경로도 같음(시험 빌드) | 그대로 씀 |
| glibc 2.36 → 2.41 정렬 | DB 로케일 `C.UTF-8`(libc, `datcollversion` 없음). 두 이미지에서 무작위 문자열 2만 개(한글 음절·자모·한자·전각·이모지 포함)를 `LC_ALL=C.UTF-8 sort` 하면 둘 다 바이트 순(`LC_ALL=C`)과 같음 — 위험 낮음 | amcheck `bt_index_parent_check(heapallindexed, rootdescend)` 로 btree 355개 전부(텍스트 열 84개) |
| 문자 분류(ctype) | pg_trgm GIN 1개(`mart.ix_hist_name_trgm`, 864kB)가 기대고, PG 16 amcheck 는 GIN 을 못 봄 | `REINDEX INDEX CONCURRENTLY` |
| PostGIS 3.6.1 → 3.6.4 | 라이브러리는 바뀌고 확장 SQL 은 3.6.1 로 남음 | postgis 가 있는 DB 마다 `postgis_extensions_upgrade()`(`make db-update`). atlas_test 는 그 뒤 지우고 `make test` 가 새로 만듦 |
| GEOS 3.11 → 3.14, PROJ 9.1 → 9.8 | 단순화(`ST_SimplifyPreserveTopology`)·좌표 변환의 마지막 자리가 달라질 수 있음 | 같은 데이터·같은 코드로 계산을 두 번(전·후) 돌려 표마다 비교, 차이는 아래 결과에 기록 |
| 16.12~16.15 의 업그레이드 뒤 조치 | btree_gist·ltree·논리 복제·pgcrypto PGP 를 쓰지 않음 | 해당 없음 |

## 5. 절차

워커는 띄우지 않습니다(스케줄이 호출 한도가 있는 외부 API 를 부름). 검증은 `docker compose up -d --build --wait api web`.

0. **기준선(기존 이미지)** — 버전·확장·로케일은 1장. 운영 DB 1,708MB, 데이터 디렉터리 2.0GB, Docker 디스크 여유 226GB.
1. **백업** — `make backup`(LITE 아님) → `backups/atlas-YYYYMMDD-HHMM.dump`, `pg_restore --list` 로 읽히는지 확인.
   db 를 멈추고 볼륨 사본 `postal-access-atlas_db-data-pg1611-bookworm` 도 만듦(빠른 되돌리기용).
2. **비교 계산 A(기존 이미지)** — 운영 DB 를 복사한 임시 DB `atlas_imgcheck`(`CREATE DATABASE … TEMPLATE atlas`)에서 `calc` + `collect walk`.
   운영 DB 의 계산 기록은 늘리지 않음.
3. **교체** — compose 를 `build: ./db` 로 바꾸고 `make db-update`(빌드 → db 재기동 → 확장 갱신). 로그의 오류·경고, 버전 확인.
4. **인덱스** — amcheck(끝나면 확장 지움), GIN REINDEX.
5. **비교 계산 B(새 이미지)** — `atlas_imgcheck` 에서 같은 계산을 다시 → A 와 표별 행 비교. 끝나면 `atlas_imgcheck` 지움.
6. **검증** — `make test`, 웹 `npm run typecheck`·`npm test`·`npm run lint`, api·web 기동, `make qa`.
7. **CI·문서** — CI, ADR-007·ADR-022, README, quality.md, CHANGELOG.

## 6. 되돌리기

- **볼륨 사본으로(빠름)**: 새 이미지에서 확장을 3.6.4 로 갱신한 뒤라, 지금 데이터 디렉터리를 이전 이미지(3.6.1)로 그대로 띄우지 않습니다.
  ```bash
  docker compose stop db
  git revert <이 작업의 커밋>                       # compose 를 imresamu 이미지로
  docker run --rm --entrypoint sh -v postal-access-atlas_db-data-pg1611-bookworm:/from:ro -v postal-access-atlas_db-data:/to \
    imresamu/postgis:16-3.6-bookworm -c 'find /to -mindepth 1 -delete && cp -a /from/. /to/'
  docker compose up -d db
  ```
- **덤프로**: 이전 이미지로 db 를 띄우고 `make restore FILE=backups/atlas-….dump`(임시 DB 에 복원·검증 뒤 교체).
  볼륨 사본 뒤에 쌓인 데이터까지 살리려면 새 이미지에서 먼저 `make backup` 을 받아 그 파일로 복원합니다(같은 메이저라 덤프가 호환).
- **주의**: 이 변경이 없는 체크아웃(compose 가 아직 `imresamu/postgis:16-3.6-bookworm`)에서 `docker compose up` 을 하면 db 가 이전 이미지로
  다시 만들어져, 3.6.4 로 갱신된 데이터 디렉터리를 PostGIS 3.6.1 로 띄우게 됩니다. 이 변경을 병합하기 전에는 이 브랜치의 compose 로 띄웁니다.
- 볼륨 사본은 새 이미지로 며칠 문제없이 쓴 뒤 `docker volume rm postal-access-atlas_db-data-pg1611-bookworm` 로 지웁니다.

## 7. 결과 (2026-10-15 실행)

| 단계 | 결과 |
|---|---|
| 백업 | `make backup` → `backups/atlas-20261015-1152.dump` (512MB, 42초), 목차 읽힘. 볼륨 사본 `postal-access-atlas_db-data-pg1611-bookworm` (파일 2,752개 일치) |
| 교체 | `make db-update` 33초(빌드 14초 포함). 기존 데이터 디렉터리로 바로 기동(초기화 건너뜀), 오류·콜레이션 경고 없음. postgis·postgis_topology·postgis_tiger_geocoder 3.6.1 → 3.6.4 (atlas·atlas_test·template_postgis) |
| 판 | PostgreSQL 16.15 · PostGIS 3.6.4 · GEOS 3.14.1 · PROJ 9.8.1 · Debian 13.7 · glibc 2.41. PostGIS 패키지는 Debian 의 GEOS 3.13.1·PROJ 9.6.0 으로 빌드됐고, 실행할 때는 PGDG 의 3.14.1·9.8.1 을 씀(같은 soname — PGDG 의 의존성 그대로) |
| 인덱스 | amcheck `bt_index_parent_check(heapallindexed, rootdescend)` — btree 355개 통과, 실패 0 (17초). trigram GIN `REINDEX CONCURRENTLY` 63ms, 유사 검색이 그 인덱스를 씀 |
| 지표 계산 | 운영 DB 복사본에서 같은 코드로 교체 전(A)·후(B) `calc` + `collect walk`. 표 9개의 행 수·내용이 모두 같음(양방향 `EXCEPT ALL` 0행): access_metric 106,473 · area_nearest 11,433 · bank_impact 5,425 · facility_hub 2,305 · oa_bank 105,947 · oa_nearest 105,947 · oa_walk 399,228 · dq_check 2 · dq_issue 5. 계산·도보 통계도 같음. 계산 42.1 → 41.6초, 도보 44.5 → 44.4초 |
| 좌표 변환 (PROJ) | 시설·은행 지점 4326→5179, 대표점 5179→4326 54,821개 중 77개가 마지막 자리만 다름(최대 2나노미터). API 출력(소수 5자리)은 모두 같음 |
| 경계 단순화 (GEOS) | 아래 표 |
| 테스트 | `make test` 284 통과·1 건너뜀(스모크 응답이 필요한 계약 테스트 — 응답 파일을 붙여 따로 돌려 통과). 빈 볼륨에서 CI 단계와 같은 명령으로 띄운 DB(준비까지 약 4초, 확장은 마이그레이션이 만듦)에서도 284 통과. 웹 타입 검사·vitest 41개·린트 통과 |
| QA | api·web 만 띄우고(워커 제외) `make qa` 7분 24초 — 11개 화면 상호작용 오류 0 · 22개 화면 상태 네트워크 문제 0 · axe 위반 0·모바일 넘침 0 · 이어 붙은 설명 문장 0 · 실패 주입 7개 상황 통과 · 퍼징 658건 5xx 0. 그동안 db 로그 오류 0건 |

경계 단순화는 같은 입력을 이전 이미지(볼륨 사본을 한 번 더 복사해 띄움)와 새 이미지에서 돌려 비교했습니다.
Hausdorff 거리는 두 결과 사이 최대 거리(5179, m), 꼭짓점 수 변화는 새 판 − 이전 판 합계입니다.

| 대상 | 허용 오차 | 개수 | 꼭짓점이 다름 | 최대 Hausdorff | 꼭짓점 수 변화 | 잘못된 다각형 (이전 → 새) |
|---|---|---|---|---|---|---|
| 행정구역 (API `simplify`) | 10m | 3,811 | 1,141 | 9.99m | −1,581 | 0 → 0 |
| | 50m | 3,811 | 1,613 | 50.0m | −2,087 | 1 → 0 |
| | 200m | 3,811 | 1,437 | 199.9m | −2,522 | 13 → 0 |
| | 1000m | 3,811 | 1,838 | 999.7m | −3,724 | 33 → 0 |
| 집계구 (은행 지점 이용 범위 지도) | 30m | 108,510 | 42,236 | 30.0m | −52,428 | 73 → 0 |
| 집계구 수집 (5m 단순화 + `ST_MakeValid`) | 5m | 108,510 | 56,333 | 5.0m | −63,344 | 0 → 0 |

- '마지막 자리' 수준이 아니라 **고르는 꼭짓점이 다릅니다**. 다만 두 결과의 차이는 늘 허용 오차 안이고(둘 다 허용 오차 안의 단순화),
  새 판이 꼭짓점이 적고 잘못된 다각형을 만들지 않습니다. 원인은 GEOS `TopologyPreservingSimplifier` 수정 — 3.12 링 시작점도 지울 수 있게(GH-784),
  3.13 끝점 처리로 자기 교차 방지(GH-986)·링 끝점을 안전하게 지우기(GH-1110), 3.14 구성 요소가 건너뛰지 않게(JTS-1096) (GEOS NEWS).
- 화면 지도는 수집 때 저장한 `geom_simple` 을 쓰고(웹은 `simplify` 를 넘기지 않음, 저장값은 `ST_MakeValid` 를 거쳐 모두 유효) 다음 `make sgis` 때
  새 GEOS 로 다시 만들어집니다. 바로 달라지는 것은 은행 지점 이용 범위 지도(30m)와 API 에 `simplify` 를 직접 준 요청뿐입니다. 지표 계산에는 영향이 없습니다(위).

**따로 발견한 것 (이번에 바꾸지 않음)**: 비교 쿼리(28만 행 해시 조인)가 `could not resize shared memory segment … No space left on device` 로 실패했습니다.
db 컨테이너의 `/dev/shm` 이 Docker 기본 64MB 인데 `work_mem=64MB` 병렬 해시 조인이 그보다 큰 공유 메모리를 요구해서입니다. 이전·새 컨테이너가 같아
이번 교체와는 무관하고, 지금 앱 쿼리에서는 나지 않았습니다. compose 의 db 에 `shm_size` 를 주는 것은 후속 과제로 남깁니다.

남은 것: 볼륨 사본은 며칠 써 본 뒤 지웁니다(6장). 워커는 이번 검증에서 띄우지 않았습니다 — 다음 `docker compose up -d` 때 새 DB 에 붙습니다.
