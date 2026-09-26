# ADR-013 API·웹 보안 강화

- 상태: 채택 (2026-09-25)

## 결정
| 영역 | 적용 |
|---|---|
| 속도 제한 | Redis 고정 1분 창(`INCR`+`EXPIRE`, 파이프라인). 관리 10/분(토큰 대입 방지), What-if·배치 제안 30/분(계산 비용), 나머지 600/분. 429 + `Retry-After`·`X-RateLimit-*`. Redis 가 없으면 통과(fail-open, 캐시와 같은 선택 요소) |
| 클라이언트 IP | 브라우저 → web(Next 프록시) → api 구조라 api 가 보는 주소는 web 컨테이너. **신뢰 프록시 대역(`TRUSTED_PROXIES`)에서 온 요청만** `X-Forwarded-For` 첫 값을 믿음 → 외부에서 헤더를 위조해 제한을 피하지 못함. uvicorn `--no-proxy-headers` 로 이중 해석 방지 |
| 보안 헤더 (API) | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `CORP: same-origin`, JSON 응답 CSP `default-src 'none'`, 관리 API·POST 는 `Cache-Control: no-store` |
| 보안 헤더 (웹) | CSP — 스크립트는 자기 출처 + 카카오 지도 SDK(`dapi.kakao.com`, `*.daumcdn.net`)만, `object-src 'none'`, `frame-ancestors 'none'`, `base-uri 'self'`. 스타일은 SSR style 속성·SDK 때문에 `'unsafe-inline'` 만 허용(스크립트는 인라인 불허). `Permissions-Policy`, COOP |
| 관리 API | 토큰 상수 시간 비교, 작업 `kind` 정규식 검증 후 허용 목록 확인, 요청 IP 를 작업 행(`requested_by`)과 감사 로그(`atlas.audit`)에 기록 — 공개 작업 목록에는 IP 를 내보내지 않음 |
| 컨테이너 | api·worker·migrate 비루트(uid 10001), web 비루트(node). `read_only` 루트 파일시스템 + `/tmp` tmpfs, `cap_drop: ALL`, `no-new-privileges`. 포트는 모두 `127.0.0.1` 바인딩 |
| DB | 최소 권한 역할(ADR-012), 역할 단위 타임아웃 |
| 공급망 | CI 에서 `pip-audit`(러너 pip·setuptools 포함)·`npm audit --audit-level=high`·gitleaks(전체 이력) 실패 시 병합 불가. Dependabot 은 minor·patch 만 묶어서 주 1회(메이저·런타임 이미지 버전은 계획해서 수동) |

## 조치 기록 (2026-09-25)
- `npm audit`: Next.js 15.1.6 critical 1·high 2 → **15.5.26** + Next 내부 PostCSS 를 `overrides` 로 8.5.28 → **0건**.
- `pip-audit`: starlette 0.41.3(FastAPI 0.115.6) 등 32건 → FastAPI 0.141.1(starlette 1.7), lxml 6.1.3, pytest 9.1.1,
  이미지의 pip·setuptools 업그레이드 → **0건**. 전체 테스트 통과로 호환 확인.

## 조치 기록 (2026-09-26)
- **혼합 콘텐츠**: 카카오 지도 SDK 로더는 https 로 받지만, 로더가 본체(`kakao.js`)·이미지·타일을 **페이지 프로토콜**로 받아
  로컬(http)에서는 제3자 스크립트 포함 24건이 평문이었다(중간자 스크립트 주입 경로). SDK 에 https 강제 옵션이 없어
  CSP 에 `upgrade-insecure-requests` 를 넣고 외부 출처를 `https://*.daumcdn.net` 처럼 스킴까지 적었다. Chrome 은 자기 출처
  `http://localhost` 를 올리지 않으므로 앱은 그대로 동작하고, 외부 요청은 모두 https(지도·방문 여건·배치 제안에서 확인).
- **SDK 의 eval**: 카카오 SDK 가 `eval` 을 시도해 CSP 위반이 콘솔에 남지만, SDK 는 대체 경로로 정상 동작한다.
  `'unsafe-eval'` 을 허용하면 모든 스크립트에 eval 이 열리므로 **허용하지 않는다**(Lighthouse 모범 사례 점수 일부 감점을 감수).
- **입력 범위**: 퍼징에서 범위를 넘는 정수가 DB 형 변환에서 500 을 내던 4곳 → 쿼리 매개변수 범위 검사 + DB `DataError` → 400.
  내부 오류가 SQL 원문을 응답에 드러내지는 않았지만(응답은 `INTERNAL_ERROR` 와 traceId 뿐), 오류 로그에 SQL·바인드 값이 남던 것을
  한 줄 요약으로 바꿨다(바인드 값은 사용자 입력일 수 있음).
- **GitHub**: CodeQL(기본 설정)·Dependabot 보안 업데이트·비밀값 스캔·푸시 보호를 켰다. CodeQL 경고 3건 중 2건 조치
  (클라이언트 요청 경로 검사 `SAFE_PATH`, 주소창 값은 `encodeURIComponent` 로 한 조각만), 1건은 오탐으로 닫음.

## 남는 위험
- 로컬 전용 서비스라 TLS·HSTS 는 없다(공개 배포 시 리버스 프록시에서 종료).
- 신뢰 프록시 대역에 호스트(도커 브리지)가 포함되어, 호스트에서 직접 8100 을 호출하면 `X-Forwarded-For` 를 믿는다(127.0.0.1 바인딩이라 외부 노출 없음).
