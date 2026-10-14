# ADR-026 웹 프록시는 요청 본문의 경계를 다시 세운다 — GET·HEAD 본문 거절, 쓰지 않는 메서드 405

- 상태: 채택 (2026-10-15, 2차 리뷰 S2)

## 맥락
- 브라우저 → web(Next 프록시 라우트 `pages/api/v1/[...path].ts`) → api 구조다. 프록시는 받은 X-Forwarded-For 를 버리고 실제 접속 주소로 덮어쓴다(ADR-013, 1차 S1).
- 프록시는 모든 메서드에서 요청 본문을 그대로 `pipe` 했다. 전달 헤더에서는 `transfer-encoding` 을 뺐는데, Node 의 ClientRequest 는
  GET·HEAD 에 chunked 를 붙이지 않는다. 그래서 chunked 본문을 붙인 GET 은 본문이 길이 표시 없이 uvicorn 으로 흘러갔다.
- uvicorn 은 그 본문을 같은 keep-alive 연결의 다음 요청으로 읽었다. 운영 빌드로 재현한 결과는 두 가지였다.
  - 숨긴 요청이 위조 XFF 로 신뢰받았다(신뢰 프록시에서 온 요청이므로).
  - 느린 요청의 응답이 다른 사용자 요청의 응답으로 붙었다.
- 지금은 127.0.0.1 바인딩이라 피해가 작다. 그러나 웹 포트를 외부에 열면 1차 S1 수정이 무력화된다.

## 결정
- API 가 쓰는 메서드만 넘긴다: GET·HEAD·POST. 그 밖의 메서드는 API 에 닿기 전에 405 `METHOD_NOT_ALLOWED` 와 `Allow` 헤더로 끝낸다.
- GET·HEAD 는 본문을 절대 넘기지 않는다(`up.end()`). `transfer-encoding` 이 있거나 `content-length > 0` 이면 400 `VALIDATION_ERROR` 를 돌려준다.
- POST 는 지금처럼 흘려보낸다. Node 가 chunked 로 다시 감싸므로 본문 경계가 유지된다(테스트로 확인).

## 검토한 대안
- **전용 Agent 로 keep-alive 끄기(요청마다 새 연결)** — 응답 뒤섞임은 사라지지만 증상 처리다. 숨긴 요청이 uvicorn 에 닿는 것 자체는
  막지 못하고(위조 XFF, 프록시가 원래 넘기지 않는 경로), API 호출마다 TCP 연결 비용이 생긴다.
- **앞단 리버스 프록시(nginx)에 맡기기** — 배포 구성에 따라 달라지고, 로컬 구성(Next 가 바로 받음)에는 앞단이 없다.

## 감수한 단점
- GET 에 본문을 보내는 비표준 클라이언트는 400 을 받는다. API 에는 본문을 읽는 GET 경로가 없다.
- 새 메서드(PUT·DELETE)를 쓰는 API 를 만들면 프록시의 허용 목록(`web/lib/proxy.ts` 의 `ALLOWED_METHODS`)도 함께 고쳐야 한다
  (`web/lib/proxyRoute.test.ts` 가 405 를 고정).
