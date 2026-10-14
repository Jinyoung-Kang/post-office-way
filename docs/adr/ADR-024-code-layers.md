# ADR-024 코드 계층 — 라우터(HTTP) · 기능 모듈(흐름·조회) · 도메인(순수 규칙), 화면은 Hook 과 순수 모듈로

- 상태: 채택 (2026-10-09, 리뷰 계획 A0~A2·W0~W4)

## 맥락
- 백엔드: 라우터 10개가 SQL 을 직접 실행했고 `api/services/*` 에는 SQL·규칙·HTTP 상태 코드·캐시·응답 모양이 한 파일에 섞여 있었다.
  의존이 거꾸로인 곳도 있었다 — 계산·API 가 수집기 안의 품질 규칙을, 계산이 API 의 캐시를 import. '최신 완료 계산 실행' 조회 7곳
  (3곳은 동률 처리가 다름), farKm 변환 6곳, 레벨 선택 2곳, 지도 범위 해석 3곳이 따로 있었다.
- 화면: 조회 effect 마다 `let alive` 가드를 따로 두거나(일부는 없음) 오류를 메시지 문자열로만 남겨, '자료 없음' 판정을 메시지 정규식으로 했다.
  단계구분 경계·범례·상위 N 라벨·라벨 겹침 같은 규칙이 페이지·지도 컴포넌트 안에 있었다.

## 결정
백엔드 (`atlas/atlas`):

```
api/routers/*      HTTP 만 — 입력 받기·상태 코드·헤더(ETag·gzip). SQL 없음(테스트로 고정, health 만 예외)
api/errors.py      도메인 오류 → HTTP 상태 (Invalid 400 · NotFound 404 · Conflict 409) 한 곳
      ↓
features/<기능>    흐름·검증·캐시·응답 모양. 큰 기능은 service.py + queries.py(Connection 을 받아 행을 돌려주는 함수)
                   whatif · plan · overview · areas(+report) · banks, 작은 기능은 파일 하나(visit · hubs · meta · quality …)
calc/runs.py       계산 실행 조회('최신 완료'의 정의 하나)·데이터 버전·메타
      ↓
domain/*           DB·웹 없는 순수 규칙 — 배치 제안 탐욕 알고리즘, What-if 요약, 개요 집계, 영업 상태, 파라미터 해석, 오류
core/* · ops/*     설정·DB·캐시·직렬화 / 수집·계산·도보가 함께 쓰는 실행 기록·품질 규칙
```

- 의존은 바깥 → 안쪽으로만: `tests/unit/test_layers.py` 가 import 를 정적으로 읽어 domain 이 DB·웹 프레임워크를, core 가 기능 모듈을,
  features 가 api·jobs·collector 를 import 하면 실패한다.
- 리포지토리 클래스·인터페이스(ABC)·DI 컨테이너는 두지 않는다 — 구현이 하나뿐이고 테스트는 실제 PostGIS 로 하므로 바꿔 끼울 일이 없다.
  작은 중복(한두 곳)은 그대로 둔다.

화면 (`web/`):
- `hooks/useApi` — 조회 상태(data·error·loading)와 부수효과. 경로가 바뀌면 AbortController 로 이전 요청 취소, 늦게 온 응답은 버림,
  오류는 `ApiError`(code·status) 그대로. React 와 무관한 `startRequest` 를 vitest 로 시험.
- `hooks/useKakaoMap`·`useBboxLayer` — 지도 초기화, 화면 범위 레이어(시설·은행·약국) 공통(취소 + 바뀐 점만 갱신).
- `lib/choropleth`·`lib/rules`·`lib/mapGeom` — 단계구분·범례, 화면 규칙(취약 상위 N·순위 문구·진료시간·은행 평가 대상),
  지도 기하(bbox·라벨 겹침·키 비교). React·지도 SDK 없이 값만 → vitest.
- `lib/api` 는 API 클라이언트(경로 검사·캐시·`isNoData` 코드 판정). 표시 컴포넌트·사용자 동작 요청(What-if·배치 제안 실행)은 그대로.
- ESLint 는 React Hook 규칙만(의존성 배열 실수를 기계로) — `eslint-config-next` 는 고정판 없는 high 취약점을 끌어와 쓰지 않음.

## 결과
- 구조 변경 전에 주요 엔드포인트 17개 응답 전체를 스냅숏으로 고정(`tests/sql/test_api_snapshots.py`) — 모든 이동 커밋에서 같은 응답.
- 이 과정에서 찾은 버그는 따로 고침: '자료 없음'을 메시지 정규식으로 판정해 은행 지점 영향평가 '결과 없음'이 오류로 보이던 것,
  목록 실패 때 끝나지 않는 자리 표시, 주소에 조건이 있는 화면의 기본값 중복 요청, 지도 이동마다 모든 점 재생성(docs/benchmarks.md).
- 대가: 기능 하나를 고칠 때 파일이 2~3개(router·service·queries)로 나뉜다. 작은 기능은 파일 하나로 두어 이 비용을 줄였다.

## 2차 리뷰 보완 (2026-10-15)
같은 원칙을 남아 있던 곳에 적용했다. '이미 갈라진 중복'이나 '테스트할 수 없는 구조'인 곳만 옮겼다.
- **도메인 한 곳**: `domain/params` 의 `ascii_digits`·`parse_region_code`(지역 코드 검사 7곳이 갈라져 있었음), `calc_params`·`calc_levels`·
  `calc_job_params`(계산 생성·관리 API·CLI 가 같은 검증).
- **정의 한 곳을 정적 검사로**: 실행 기록을 닫는 except 는 BaseException(ADR-025), '최신 완료 계산 실행'은 `calc/runs.py` 한 곳
  (`tests/unit/test_layers.py`).
- **화면**:
  - 지도 화면의 주소↔상태 변환 → `lib/mapQuery.ts`. 페이지 effect 안에 있어 테스트할 수 없었고, 기본 조건으로 먼저 요청하는 버그가 숨어 있었다.
  - 시도 목록 조회 → `hooks/useRegions`. 6곳이 오류를 제각각 삼켰다.
  - '누를 수 있는 점' → `lib/mapDots.makePickable`. 시설 점만 키보드로 누를 수 있었다.
  - What-if 결과·지도 반영 → `lib/scenario`, 표의 불러오는 중·실패·빈 상태 판정 → `hooks/useApi` 의 `tableView`(React 없는 함수).

