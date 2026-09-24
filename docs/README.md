# 문서 안내

우체국 접근성 아틀라스의 설계·API·데이터 구조 문서입니다. 설치·사용법은 저장소 [README](../README.md),
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

## API (`http://localhost:8100/api/v1`, 자동 문서 `/docs`)

| 메서드 · 경로 | 내용 |
|---|---|
| `GET /health` | DB·Redis 연결 상태 |
| `GET /overview` | 전국 개요 — 시설·거리 분포·고령인구·금융 공백·취약 지역 |
| `GET /areas` · `/areas/geojson` · `/areas/{admCd}` | 지역 목록·순위 / 단계구분도 GeoJSON(캐시) / 지역 상세(최근접 3·은행·지표·인구) |
| `GET /facilities` · `/facilities/{histId}` | 시설 목록(bbox·유형·검색) / 시설 상세 |
| `GET /banks` | 은행·금고 지점 레이어 (bbox 필수) |
| `GET /metrics` | 지표 정의 |
| `POST /whatif` · `GET /whatif/{id}` · `GET /whatif/{id}/geojson` | 폐국 가정 시뮬레이션 · 재조회 · 영향 지역 폴리곤 |
| `POST /plan/close` · `POST /plan/open` | 배치 제안 — 폐국 영향 최소 조합 / 신설 효과 최대 후보지 |
| `GET /visit/conditions` · `GET /visit/conditions/{admCd}` | 방문 여건 — 시군구 전체(`date`, `sido`) / 한 지역 오늘~모레 |
| `GET /dq/summary` · `GET /dq/issues` | 데이터 품질 요약 · 이슈 목록 |
| `GET /meta/collect-runs` · `/meta/calc-runs` · `/meta/regions` | 수집·계산 실행 기록 · 시도/시군구 목록 |
| `POST /admin/collect/{kind}` · `POST /admin/calc` | 수집·계산 트리거 (`X-Admin-Token`). kind = post·sgis-pop·sgis-bnd·kosis·oa·banks·road·geocheck·kma·air |

오류는 `{code, message, traceId}` 형식입니다(예: `CALC_RUN_NOT_FOUND`, `VISIT_NO_DATA`, `VALIDATION_ERROR`).

## 데이터 구조 (`db/migrations`)

| 마이그레이션 | 내용 |
|---|---|
| V1–V3 | 스키마 raw·stg·mart·ops, 원본 응답(키 마스킹)·수집 실행·품질 이슈, 수집 스냅샷 |
| V4–V5 | 시설 이력(SCD2), 행정구역·인구, 계산 실행·지표·최근접, What-if, 지표 정의 |
| V6 | KOSIS 주민등록인구(65세 이상) |
| V7–V8 | 집계구 인구·경계·최근접, 도로 거리 캐시(출발점 종류), 주소 좌표 캐시·검증, 은행 지점 |
| V9 | 방문 여건 — 시군구 기상청 격자(`area_grid`), 시간 예보(`weather_hourly`), 미세먼지 권역 예보(`air_forecast`) |

- 지표 계산 SQL: `atlas/atlas/sql/calc/00_snapshot.sql` ~ `08_road.sql` (계산 실행 `calc_run` 단위로 결과 보존)
- 판정 규칙: 금융 가능 `R-FIN-01` (`atlas/atlas/domain/rules.py`), 방문 여건 `VISIT-1` (`atlas/atlas/domain/visit.py`)

## 화면 캡처

[`images/`](images/) 의 README 캡처는 서비스를 띄운 상태에서 다시 찍을 수 있습니다(설치된 Google Chrome 사용).

```bash
pip install playwright
python scripts/capture_screens.py
```
