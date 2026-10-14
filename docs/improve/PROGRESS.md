# 개선 작업 진행 기록 (improve/20261015)

이 파일만 읽고 이어서 작업할 수 있게 씁니다. 계획은 [PLAN.md](PLAN.md), 최종 보고는 [REPORT.md](REPORT.md).

## 작업 방식 (사용자 지시)

- 2026-10-15 사용자 지시: "모든 작업을 권장안으로 진행, 중간에 멈추지 말 것, 중요한 선택·직접 할 일이 있을 때만 물어볼 것".
  → 계획(PLAN.md)의 권장안을 승인된 것으로 보고 진행. "멈추는 경우"(되돌릴 수 없는 작업·공개 API 호환 깨짐·유료/새 인프라·
  사용자가 넣어야 하는 값)는 즉시 멈추고, 판단이 애매한 것·메이저 업그레이드는 아래 "승인 대기"에 모았다가 한 번에 묻는다.
- 브랜치 `improve/20261015` (main `d91dccf` 에서). push·병합은 하지 않음.
- 워커(`worker`)는 띄우지 않음 — 스케줄 작업이 외부 API(공공데이터포털 등, 호출 한도)를 부르기 때문. 외부 API 는 목·저장 응답만.

## 0단계 기준선 (2026-10-15, main d91dccf, 작업 전 깨끗한 상태)

| 항목 | 명령 | 결과 |
|---|---|---|
| Python 테스트 | `make test` | **285 passed**, 1 warning(StarletteDeprecationWarning: httpx → httpx2), 36.1초 |
| Python 린트 | ruff 0.16.9 `check --select F,E9 .` | All checks passed |
| Python 의존성 취약점 | `pip-audit --skip-editable` (python:3.13-slim, `atlas[dev,walk]`) | No known vulnerabilities |
| 웹 타입 검사 | `npx tsc --noEmit` | 통과 (0 오류) |
| 웹 린트 | `npx eslint .` | 통과 (0) |
| 웹 테스트 | `npx vitest run` | **41 passed** (9 파일) |
| 웹 빌드 | `npm run build` (Next 16.4.0 webpack) | 성공, 14 페이지 |
| 웹 의존성 취약점 | `npm audit` | 0 vulnerabilities |

기준선에서 이미 실패하는 항목: 없음.
관찰: 차가운 상태에서 첫 `make test` 가 `docker compose up -d db redis` 직후 `psql` 이 소켓 연결에 실패해 중단(DB 준비 전) — 두 번째 실행은 통과.

런타임 확인: PostgreSQL 16.11 + PostGIS 3.6.1 (이미지 Debian 12.13 bookworm), Redis 7.4.11,
API 이미지 Python 3.13.16 · FastAPI 0.141.1 · SQLAlchemy 2.1.1 · Starlette 1.7.0 · Pydantic 2.13.5, Node 24 · Next 16.4.0 · React 19.3.0.

## 진행 상황

- [x] 0단계 기준선
- [x] 1단계 리뷰(영역 8개 + 영역별 반박 검증) → PLAN.md (커밋 e1004ec). 원자료: 세션 스크래치의 review.json
- [x] 2단계 실행 — 아래 표
- [x] 3단계 독립 검토 — 영역 4개 + 반박 검증, 17건(확인 10·추정 5·반박 2). 정확성 6건 수정(6f47e29·32f6504·8be9768·6840146·b719d5f·e60bd90) + 테스트 공백 2건(4db0172), 문서 38e4638
- [x] 4단계 REPORT.md

### 2단계 실행 기록

빠른 테스트: 이미지 재빌드 없이 소스를 읽기 전용으로 붙여 pytest
(`docker compose --profile batch run --rm -T --entrypoint pytest -v "$PWD/atlas:/src:ro" -w /src -e PYTHONPATH=/src -e TEST_DATABASE_URL=…atlas_test -e TEST_REDIS_URL=redis://redis:6379/15 collector -q`).
이 방식에서는 계약 테스트 1개(`make smoke` 응답 필요)가 skip 되므로 '통과 N + skip 1' 로 보임 — `make test` 에서는 실행됨.

화면 수정(S2·B3·W1~W7·B2 화면)은 별도 작업 트리(브랜치 `improve/20261015-web`)에서 에이전트가 진행 → 끝나면 이 브랜치로 가져옴.

| ID | 커밋 | 테스트(수정 뒤 전체) | 비고 |
|---|---|---|---|
| D1 | b9b59fd | 286 | 도보 지표 연도 조인 |
| D2 | 876157c | 289 | KOSIS 30·빈 목록 |
| D3 | 3f0a6a8 | 293 | 우체국 빈 쪽·잘린 쪽. 운영 원문 2,248건 중 해당 0 |
| D4 | f71cbe6 | 295 | SGIS 일시 오류 연도 대체. 남은 코드 정리는 Q2 |
| D5 | ee47b4e | 298 | 주소 검색 ERROR 캐시 |
| D6 | 4f441f4 | 300 | 도보 재계산 은행 열·계산 스냅숏 은행 목록(운영 5,425=5,425) |
| D7 | 95a2591 | 301 | 판정 열 제자리 갱신(지금 차이 0건) |
| D8 | 7aba2dc | 302 | 은행 지점 경계 밖 최근접 지역 |
| D9 | eb41fcb | 305 | BaseException 17곳 + 정적 검사 |
| D11 | b47d557 | 307 | 기상청 중단 시 받은 격자 저장 |
| S1 | a554ace | 309 | CSP 보고 500·app_error 시간당 상한 |
| S3 | aaefc1c | 311 | simplify 9단계(기대값 120→100 변경은 의도) |
| S4 | 787aa33 | 319 | bbox 검증 |
| S5 | 9ce9aa7 | 335 | 지역 코드 검사 한 곳 |
| B1 | 63e00c2 | 336 | 방문 여건 캐시 버전(격자 커밋마다) |
| B2 | 1579e20 | 338 | 점심시간 상태 lunch |
| B4 | 7c19d37 | 342 | CLI --param 형 |
| B5 | 753f888 | 357 | 계산 설정 검증(관리 API 400) |
| B6 | ae3ba68 | 359 | 해석 불가 본문 VALIDATION_ERROR |
| B7 | 0dcf1d5 | 362 | MASS_CHANGE_HELD·PARTIAL 사유 |
| 웹 S2·B3·W1~W7·B2 화면 | 7102666…c9dfbfe (14개, cherry-pick) | 웹 95 | 작업 트리 에이전트 + 독립 리뷰(정확성 결함 0, 낮음 4) |
| 웹 리뷰 후속 | bb7d681·4437d2f·3178a15 | 웹 96 | 로더 재시도 간격, 은행 점 clickable, 카드 닫기 |
| B9 | f9b0f36 | 363 | 최신 완료 실행 정의 한 곳(리팩터링) |
| B10 | 398c96b | 366 | collect walk 출력 |
| J1 | b1134b4 | 367 | close_runs 소유 확인 |
| J2 | 4ea9a64 | 369 | 단일 차선 예외·reap 경쟁 |
| B8 | d1c0cde | 371 | 동률 id — 측정 +6%(대안 비교는 ADR-027) |
| D10 | 19d64df | — | 임시 DB 로 재현·확인(셸) |
| O1 | b2c8334 | 371+2 skip | compose walk 설정 |
| O2 | 1b367d6 | make test 372 + 2 skip | --wait (DB 멈춘 상태에서 확인) |
| O3·O4·O6·O5 | 86d31ae·4cac97b·67bbaa0·4dd97fe | 372 + 2 skip | all-data·respx·호스트 개발·문서 |

### 검증 (2026-10-15, 커밋 4dd97fe 기준)
- `make test`(이미지 다시 빌드) 372 passed, 2 skipped(저장소 루트가 있어야 하는 compose 설정 검사 — CI 에서 실행). ruff 통과.
- 웹: tsc·eslint 통과, vitest 96 passed, `npm run build` 성공.
- 성능: docs/benchmarks.md '2차 코드 리뷰' — B8 +6%(대안 비교), B1·방문 여건 경로 차이 없음, make bench 는 환경 잡음으로 판정 못 함.
  make bench 4회(수정 전 2·후 2) 뒤 운영 DB 의 What-if 시나리오 표는 그대로 113행(벤치의 무작위 조합이 이미 있는 시나리오라 새 행 없음).
- QA(`make qa`, api·web 만 띄움 — 워커 없음, 8분 16초): crawl 11개 화면 오류 0 · requests 24개 상태(지도 주소 조건 상태 추가) 중복·기본 조건
  선요청 0 · a11y axe 위반 0·모바일 넘침 0 · sentences 0 · failures 11개 실패 상황 통과(속도 제한 1회 재시도) · fuzz 658건 5xx 0.
- 브라우저(앱 내장 브라우저, http://localhost:3100):
  - `/?adm=37520&metric=FAR2KM_SHARE` 첫 로드 — GeoJSON 은 그 지표로 1번, 지역 카드는 calcRunId 를 붙여 1번(네트워크 기록).
  - 시설·은행·약국 레이어를 함께 켜면 문구 '시설 62곳 · 확대하면 약국·의원이 보입니다'(W7).
  - 은행 점 59개 중 영향평가 대상 26개만 role=button·tabIndex 0·aria-label, 초점 + Enter → /banks?id=…(W6).
  - 머리글 '지도'(/)로 가면 지표가 기본값·카드 닫힘(B3).
  - 없는 지역 코드의 오류 카드에도 닫기 단추(B3 후속).
  - 점심 상태(lunch)는 지금 시각(새벽)이라 화면으로 확인하지 못함 — API 테스트로 대신.

## 남은 일
- 사용자 결정 대기: Q1~Q3 (REPORT.md 5장). 그 밖에 남은 작업 없음
- 작업 트리 정리 완료(화면 작업 트리·기준 측정용 main 작업 트리 제거, 브랜치 improve/20261015-web 은 남김)

## 승인 대기 (모아 두었다가 한 번에 묻기)

PLAN.md 4장 Q1(생활 거점 '은행 지점' 범위 문구)·Q2(SGIS 사라진 코드 정리)·Q3(DB 이미지 교체). 실행하지 않음.
