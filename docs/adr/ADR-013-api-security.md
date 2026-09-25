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
| 공급망 | CI 에서 `pip-audit`·`npm audit --audit-level=high`·gitleaks(전체 이력) 실패 시 병합 불가. Dependabot(pip·npm·actions·docker) |

## 조치 기록 (2026-09-25)
- `npm audit`: Next.js 15.1.6 critical 1·high 2 → **15.5.26** + Next 내부 PostCSS 를 `overrides` 로 8.5.28 → **0건**.
- `pip-audit`: starlette 0.41.3(FastAPI 0.115.6) 등 32건 → FastAPI 0.141.1(starlette 1.7), lxml 6.1.3, pytest 9.1.1,
  이미지의 pip·setuptools 업그레이드 → **0건**. 전체 테스트 통과로 호환 확인.

## 남는 위험
- 로컬 전용 서비스라 TLS·HSTS 는 없다(공개 배포 시 리버스 프록시에서 종료).
- 신뢰 프록시 대역에 호스트(도커 브리지)가 포함되어, 호스트에서 직접 8100 을 호출하면 `X-Forwarded-For` 를 믿는다(127.0.0.1 바인딩이라 외부 노출 없음).
