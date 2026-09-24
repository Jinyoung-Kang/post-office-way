# 변경 이력

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
