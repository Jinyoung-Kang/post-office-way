# 문서 안내

우체국 가는 길(Postal Access Atlas)의 설계·API·데이터 구조 문서입니다. 설치·사용법은 저장소 [README](../README.md),
시스템 구성은 [아키텍처](architecture.md), 성능 측정은 [벤치마크](benchmarks.md), 버그·접근성·성능 점검 방법과 결과는 [품질 검증](quality.md),
바뀐 내용은 [CHANGELOG](CHANGELOG.md) 를 보세요.

## 설계 결정 (ADR)

| 번호 | 결정 |
|---|---|
| [ADR-001](adr/ADR-001-spatial-join.md) | 시설의 행정구역은 좌표 공간 조인으로 부여 |
| [ADR-002](adr/ADR-002-crs.md) | 저장은 EPSG:4326, 거리는 EPSG:5179 |
| [ADR-003](adr/ADR-003-fastapi-only.md) | 백엔드는 FastAPI 단일 |
| [ADR-004](adr/ADR-004-no-olap.md) | 분석 DB(ClickHouse·BigQuery) 미도입 |
| [ADR-005](adr/ADR-005-whatif-top3.md) | What-if 는 최근접 상위 3개 기반 부분 재계산 |
| [ADR-006](adr/ADR-006-shared-package.md) | api·collector 코드 공유 (단일 패키지 `atlas`) |
| [ADR-007](adr/ADR-007-postgis-image.md) | PostGIS 이미지 선택 |
| [ADR-008](adr/ADR-008-area-code-discovery.md) | 우편 지역코드 seed 자동 탐색 |
| [ADR-009](adr/ADR-009-kosis-resident-pop.md) | KOSIS 주민등록인구로 65세 이상 인구 보강 |
| [ADR-010](adr/ADR-010-advanced-access.md) | 고도화 — 집계구·도로 거리·주소 검증·금융 공백·배치 제안 |
| [ADR-011](adr/ADR-011-visit-condition.md) | 방문 여건 — 기상청 단기예보 + 에어코리아 미세먼지 예보 |
| [ADR-012](adr/ADR-012-job-queue-least-privilege.md) | 작업 큐·워커 분리, 마이그레이션 전용 단계, 최소 권한 DB 역할 |
| [ADR-013](adr/ADR-013-api-security.md) | API·웹 보안 강화 (속도 제한·CSP·컨테이너·공급망) |
| [ADR-014](adr/ADR-014-performance.md) | 측정 기반 성능 개선 |
| [ADR-015](adr/ADR-015-life-hub-calendar.md) | 생활 거점(약국·병의원)과 영업일 달력(특일 정보) — API 선정·제외 이유 |
| [ADR-016](adr/ADR-016-map-display.md) | 지도 표시 방식 — 첫 그리기 보장, 늘 보이는 라벨, 누르면 고정 |
| [ADR-017](adr/ADR-017-worker-lanes-ops.md) | 워커 차선(short·long)·생존 신호, 생존/준비 확인 분리, 백업·복원 |

## API (`http://localhost:8100/api/v1`, 자동 문서 `/docs`)

| 메서드 · 경로 | 내용 |
|---|---|
| `GET /health` · `GET /health/live` | 준비 상태(DB·Redis·스키마·작업 큐·워커 차선별 생존 신호) · 프로세스 생존만 |
| `GET /overview` | 전국 개요 — 시설·거리 분포·고령인구·금융 공백·취약 지역 |
| `GET /areas` · `/areas/geojson` · `/areas/{admCd}` | 지역 목록·순위 / 단계구분도 GeoJSON(캐시) / 지역 상세(최근접 3·은행·지표·인구) |
| `GET /facilities` · `/facilities/{histId}` | 시설 목록(bbox·유형·검색) / 시설 상세 |
| `GET /banks` | 은행·금고 지점 레이어 (bbox 필수) |
| `GET /metrics` | 지표 정의 |
| `POST /whatif` · `GET /whatif/{id}` · `GET /whatif/{id}/geojson` | 문 닫음 가정 시뮬레이션 · 재조회 · 영향 지역 폴리곤 |
| `POST /plan/close` · `POST /plan/open` | 배치 제안 — 닫을 곳 찾기(영향 최소 조합) / 열 곳 찾기(효과 최대 후보지) |
| `GET /visit/conditions` · `GET /visit/conditions/{admCd}` | 방문 여건 — 시군구 전체(`date`, `sido`) / 한 지역 오늘~모레 (창구 휴무 표시) |
| `GET /hubs/summary` · `GET /hubs/facilities` | 생활 거점 — 전국 합계 / 우체국별 대체 불가능성 순위(`sido`, `sort`) |
| `GET /care` | 약국·의원 지도 레이어 (bbox 필수, `kind`, `holidayOnly`) |
| `GET /calendar` | 영업일 달력 — 주말·공휴일 창구 휴무, 3일 이상 연휴 (`start`, `days`) |
| `GET /dq/summary` · `GET /dq/issues` | 데이터 품질 요약 · 이슈 목록 |
| `GET /meta/collect-runs` · `/meta/calc-runs` · `/meta/regions` | 수집·계산 실행 기록 · 시도/시군구 목록 |
| `GET /meta/errors` | 오류 로그 — API 예외·작업·수집·계산 실패·품질 ERROR 를 시간순, 복사용 한 줄(`line`) 포함, 키 마스킹 |
| `GET /meta/jobs` · `GET /meta/schedule` | 작업 큐 최근 기록(요청 IP 제외) · 워커 스케줄과 다음 실행 시각 |
| `POST /admin/jobs` · `GET /admin/jobs` · `POST /admin/jobs/{id}/cancel` | 작업 요청(202, 워커가 실행) · 관리자용 목록 · 대기 작업 취소 (`X-Admin-Token`) |
| `POST /admin/collect/{kind}` · `POST /admin/calc` | 이전 경로 호환 — 작업 큐로 넣음 |
| `GET /metrics` (8100 직접) | Prometheus 지표 — 경로별 응답 시간·속도 제한·캐시 적중·304 |

오류는 `{code, message, traceId}` 형식입니다(예: `CALC_RUN_NOT_FOUND`, `VISIT_NO_DATA`, `VALIDATION_ERROR`, `RATE_LIMITED`, `JOB_IN_PROGRESS`).
조회 응답에는 `ETag`(조건부 GET → 304), 모든 응답에 `X-Trace-Id`·`Server-Timing`·`X-RateLimit-*` 가 붙습니다.

## 데이터 구조 (`db/migrations`)

| 마이그레이션 | 내용 |
|---|---|
| V1–V3 | 스키마 raw·stg·mart·ops, 원본 응답(키 마스킹)·수집 실행·품질 이슈, 수집 스냅샷 |
| V4–V5 | 시설 이력(SCD2), 행정구역·인구, 계산 실행·지표·최근접, What-if, 지표 정의 |
| V6 | KOSIS 주민등록인구(65세 이상) |
| V7–V8 | 집계구 인구·경계·최근접, 도로 거리 캐시(출발점 종류), 주소 좌표 캐시·검증, 은행 지점 |
| V9 | 방문 여건 — 시군구 기상청 격자(`area_grid`), 시간 예보(`weather_hourly`), 미세먼지 권역 예보(`air_forecast`) |
| V10 | 생활 거점 — 약국·의원(`care_place`), 공휴일(`holiday`), 집계구별 생활 서비스 거리(`oa_nearest` 열), 우체국별 대체 불가능성(`facility_hub`), 지표 6종 |
| V11 | 작업 큐(`ops.job`) — 종류별 대기·실행 하나, 스케줄 슬롯 고유 |
| V12 | 최소 권한 역할 `atlas_api` — 권한·기본 권한·역할 단위 타임아웃 |
| V13 | `pg_stat_statements` (성능 분석) |
| V14 | 순위·백분위 사전 계산(`access_metric.rnk·pct·n`) + 기존 계산 채움 |
| V15 | 오류 로그(`ops.app_error`) — API 가 처리하지 못한 예외, 30일 보관(make prune) |
| V16 | 워커 생존 신호(`ops.worker`) — 차선별 마지막 신호·실행 중 작업, API 는 읽기만 |

- 지표 계산 SQL: `atlas/atlas/sql/calc/00_snapshot.sql` ~ `10_ranks.sql` (계산 실행 `calc_run` 단위로 결과 보존)
- 판정 규칙: 금융 가능 `R-FIN-01` (`domain/rules.py`), 방문 여건 `VISIT-1` (`domain/visit.py`), 영업일 (`domain/calendar.py`),
  약국·병의원 행 해석 (`domain/care.py`)
- 작업: 종류 목록·차선 `jobs/registry.py` · 큐·생존 신호 `jobs/queue.py` · 스케줄 `jobs/scheduler.py` · 워커(차선별 스레드) `jobs/worker.py`

## 화면 캡처

[`images/`](images/) 의 README 캡처는 서비스를 띄운 상태에서 다시 찍을 수 있습니다(설치된 Google Chrome 사용).

```bash
pip install playwright
python scripts/capture_screens.py
```
