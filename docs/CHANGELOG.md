# 변경 이력

## 2026-09-25 — 생활 거점·영업일, 작업 큐 아키텍처, 보안·성능 강화

**기능**
- **생활 거점** (`/hubs`): 국립중앙의료원 약국·병의원 FullData(약국 25,442 · 의원급 42,514)로 집계구마다 은행·약국·의원·공휴일 진료처 거리 →
  우체국이 마지막 생활 거점인 인구·의료 공백·공휴일 의료 공백 지표 6종, **우체국별 대체 불가능성**(`facility_hub`) 순위.
  What-if 에 '생활 거점 상실 인구', 배치 제안에 경고, 시설 카드에 주변 약국·의원·은행, 지도에 약국·의원 레이어(공휴일 진료만).
- **영업일 달력**: 한국천문연구원 특일 정보 + 주말 → 창구 휴무 판정. 방문 여건 연휴 모드(365코너 없는 읍면동·공휴일 의료 공백),
  머리글 '오늘 휴무' 알림, 시설 카드 '지금 영업 중/휴무', `GET /calendar`.
- UI: 모든 화면 조건을 주소에 저장(공유·새로고침), 주제별 지표 묶음, 불러오는 중 자리 표시, 0 이 많은 지표의 범례 개선,
  키보드 포커스 링·본문 건너뛰기·`Esc`, 데이터·운영 화면에 작업 큐·스케줄, 지표 정의에 규칙 카드.

**아키텍처** ([ADR-012](adr/ADR-012-job-queue-least-privilege.md))
- Postgres 작업 큐 + 워커·스케줄러(compose `worker`): API 는 INSERT+NOTIFY 만, 워커가 `SKIP LOCKED` 로 실행, 수집 뒤 재계산 자동 연결.
- 마이그레이션 전용 단계(compose `migrate`) + API 최소 권한 역할 `atlas_api`. 시계(KST)를 `core.clock` 으로, 공공데이터 클라이언트를 `collector.datago` 로 정리.

**보안** ([ADR-013](adr/ADR-013-api-security.md))
- 속도 제한(신뢰 프록시 기반 IP), API·웹 보안 헤더와 CSP, 비루트·읽기 전용 컨테이너, 관리 작업 감사 기록.
- 의존성 취약점 제거: Next.js 15.1.6 → 15.5.26(critical 1·high 2), FastAPI 0.115 → 0.141(starlette 0.41 → 1.7) 등 → npm·pip 모두 0건.
- CI 에 pip-audit·npm audit·gitleaks·이미지 빌드(비루트 확인), Dependabot.

**성능** ([ADR-014](adr/ADR-014-performance.md), [벤치마크](benchmarks.md))
- 시군구 GeoJSON p50 797 → 49ms, 방문 여건 331 → 38ms, What-if 193 → 18ms, 지역 상세 74 → 28ms, 기상청 수집 288 → 74초.
- Prometheus `/metrics`, `pg_stat_statements`, `make bench`.

**테스트** Python 161개(+36: 생활 거점·달력·작업 큐·워커 NOTIFY·권한·보안 헤더·ETag·속도 제한) · 웹 vitest 7개(신규)

## 2026-09-24 — 방문 여건 · 화면 캡처

**추가**
- ⑥ **방문 여건** (`/today`): 기상청 단기예보(시군구 대표점 5km 격자, 09~18시)와 에어코리아 미세먼지·초미세먼지 예보(19개 권역)로
  시군구마다 좋음·주의·나쁨을 판정(`VISIT-1`)하고, 우체국 2km 밖 65세 이상과 결합해 먼저 살펴볼 지역을 보여 줍니다.
  - 지역 카드에 오늘~모레 판정, 한눈에 화면에 요약 배너
  - `make weather` / `atlas collect weather|kma|air`, 관리 API `collect/kma`·`collect/air`, `make smoke` ⑤
  - API `GET /visit/conditions`, `GET /visit/conditions/{admCd}`
  - 설정 `DATA_GO_KR_KEY` (공공데이터포털 일반 인증키), 마이그레이션 V9, [ADR-011](adr/ADR-011-visit-condition.md)
- README 화면 캡처 7장과 캡처 스크립트 `scripts/capture_screens.py`
- 문서 안내(`docs/README.md`): ADR·API·데이터 구조 목록

**수정**
- 배치 제안·지역 순위·What-if 검색·데이터 품질·지역/시설 카드: 조건을 빠르게 바꿀 때 늦게 도착한 이전 응답이
  새 결과를 덮어쓰던 문제 (예: 의성군을 골랐는데 경상북도 전체가 보임)
- 모바일에서 제목이 낱말 중간에서 줄바꿈되던 문제

**테스트** 125개 (방문 여건 27개 추가: 격자 변환·예보 값 해석·판정 경계·응답 계약·적재·API)

## 2026-09-24 — CI · 정리

- GitHub Actions: `actions/checkout`·`setup-python`·`setup-node` v7(Node 24), 러너 `ubuntu-24.04` 고정
- `make prune`: 오래된 계산 결과(지표·최근접·집계구 최근접·What-if)도 정리 (`KEEP_CALC`, 기본 5)
- 배치 제안: 후보별 단독 영향을 한 번에 계산 (경기도 7.6초 → 3.8초)
- 테스트 98개

## 2026-09-24 — 초기 구현

- 수집: 우체국 찾기(지역코드 탐색·SCD2 이력), SGIS 인구·경계·집계구, KOSIS 주민등록인구,
  카카오 로컬(주소 좌표 검증·은행 지점)·모빌리티(도로 거리)
- 계산: PostGIS 공간 조인·최근접 KNN·집계구 인구 가중 거리·금융 공백 지표 (`calc_run` 단위)
- API: FastAPI — 지역·시설·지표·What-if·배치 제안·데이터 품질·관리 트리거
- 화면: Next.js 15 — 한눈에·지도·지역 순위·What-if·배치 제안·데이터 품질·지표 정의
- 테스트 96개, GitHub Actions CI
