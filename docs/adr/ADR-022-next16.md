# ADR-022 Next.js 16·React 19 전환 — CSP 를 지키려고 webpack 으로 빌드

- 상태: 채택 (2026-10-09, 리뷰 계획 V1·V2)

## 맥락
- Next.js 15 의 지원이 **2026-10-21** 에 끝난다(endoflife.date). React 18 은 2024-12 에 활성 지원이 끝났다.
- Next 16 은 React 19.2 이상, Node 20.9 이상을 요구하고 Pages Router 를 계속 지원한다. `next build` 의 기본 번들러가
  Turbopack 으로 바뀌었다(공식 업그레이드 문서).

## 결정
1. Next **16.4.0**, React·React DOM **19.3.0**, @types/react 19 로 정확히 고정. 코드 변경 없이 타입 검사·테스트 통과
   (Next 가 tsconfig 의 `jsx` 를 `react-jsx` 로 바꿈).
2. **빌드·개발 모두 `--webpack`**. Turbopack 빌드는 Pages Router 페이지마다 인라인 부트스트랩 스크립트
   (`TURBOPACK.push({otherChunks…})`)를 넣는데, 이 서비스의 CSP 는 인라인 스크립트를 허용하지 않아(ADR-013) 모든 화면의
   하이드레이션이 막혔다(네트워크 점검에서 화면마다 `script-src-elem inline` 위반 22건, 실패 주입 점검 8건으로 발견).
   - 대안: 인라인 스크립트 해시를 CSP 에 넣기(청크 이름이 빌드마다 바뀌어 해시도 매번 계산해야 함),
     nonce(정적 페이지를 모두 요청마다 렌더해야 해 성능 손해) — 둘 다 보안·성능을 내주므로 webpack 을 택함.
   - webpack 빌드는 실행 가능한 인라인 스크립트 0개(확인), CSP 를 바꾸지 않음.
3. Node 는 22(2027-04 까지 지원)를 그대로 둔다(Next 16 요구 20.9 이상 충족).

## 결과
- `make qa`(크롤링·네트워크·접근성·설명 줄바꿈·실패 주입·퍼징) 모두 통과, 지도·지역 카드 화면 확인.
- 남은 것: 빌드 중 recharts 2.x 가 '더 이상 유지되지 않음' 경고 — 3.x 로 올리는 것은 별도(차트 API 변경).
- Turbopack 으로 옮기려면 Next 가 Pages Router 의 부트스트랩을 외부 파일로 내거나 해시를 제공할 때 다시 본다.
