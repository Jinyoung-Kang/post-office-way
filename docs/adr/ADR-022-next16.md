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
3. 실행 환경도 함께 (리뷰 V3~V5): 앱 이미지(api·worker·web)의 Debian 12 bookworm 은 일반 보안 지원이 2026-07-11 에 끝나
   LTS(일부 패키지만) 단계라 **Debian 13 trixie** 로, Python 3.11(보안 수정만, 2027-10 종료) → **3.13**(2029-10),
   Node 22(2027-04) → **24 LTS**(2028-04). 의존성은 모두 cp313 바퀴 파일이 있음을 확인(osmium·numpy·scipy·lxml·psycopg).
   이미지 크기 api 406→369MB · worker 731→686MB · web 447→453MB. 테스트 232개·실데이터 도보 계산(57.5초, 결과 동일)·make qa 통과.
   - DB 이미지(PostGIS, bookworm)는 이번에 바꾸지 않음 — 운영체제가 바뀌면 glibc 정렬 규칙이 달라져 기존 문자열 인덱스를
     다시 만들어야 할 수 있어(기존 데이터에 영향) 점검 시간을 잡아 따로 함.
     → 2026-10-15 에 Debian 13 기반 `db/Dockerfile` 로 교체([ADR-007](ADR-007-postgis-image.md)). DB 로케일 `C.UTF-8` 은 glibc 2.36·2.41 의
       정렬이 같아(바이트 순) 인덱스를 다시 만들 필요가 없었고, amcheck 로 확인.

## 결과
- `make qa`(크롤링·네트워크·접근성·설명 줄바꿈·실패 주입·퍼징) 모두 통과, 지도·지역 카드 화면 확인.
- recharts 2.x 도 '더 이상 유지되지 않음'(npm deprecated)이라 **3.10** 으로 — 말풍선·막대 글자 formatter 와 막대 클릭
  콜백 타입만 맞춤(막대 클릭은 데이터 행이 payload 로 옴).
- Turbopack 으로 옮기려면 Next 가 Pages Router 의 부트스트랩을 외부 파일로 내거나 해시를 제공할 때 다시 본다.
