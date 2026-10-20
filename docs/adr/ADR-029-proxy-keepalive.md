# ADR-029 웹 프록시의 API 연결 — keep-alive 는 유지하고 노는 연결은 프록시가 먼저 닫는다, 끊긴 GET·HEAD 는 한 번 다시

- 상태: 채택 (2026-10-20)

## 맥락
- `make qa` 크롤에서 실행마다 한 건씩 502 `UPSTREAM_UNAVAILABLE` 이 났다(10-20, 지도의 `/api/v1/meta/regions`, 데이터·운영의
  `/api/v1/meta/errors?days=14`). 크롤만 다시 돌리면 0건이었고, 5초 간격 curl 12회로도 재현되지 않았다. 프록시가 오류 내용을 버려 원인을 볼 수 없었다.
- 프록시(`web/pages/api/v1/[...path].ts`, [ADR-026](ADR-026-proxy-request-framing.md))는 Node 전역 Agent 를 썼다. web 컨테이너 Node v24.22.0 의
  전역 Agent 는 keep-alive 를 켜고, 노는 연결을 5초 뒤 닫는다(`timeout: 5000`). API 의 uvicorn 0.54 도 `timeout-keep-alive` 기본값 5초로 노는 연결을 닫는다.
- 서버가 `Keep-Alive: timeout=N` 머리글을 보내면 Node 는 N초보다 1초 먼저 닫는다(`agentKeepAliveTimeoutBuffer` 1000ms). 그런데 uvicorn 은 이 머리글을 보내지 않는다.
  그래서 두 쪽이 같은 5초에 닫고, uvicorn 이 연결을 닫는 바로 그때 Node 가 그 연결을 꺼내 요청을 보내는 경우가 생겼다. 크롤은 단계 사이에 2.5초·5초씩 쉬어서 이 경계를 자주 밟는다.
- 확인: 프록시가 연결 오류를 기록하게 한 뒤 재현했다. 20개를 동시에 보내고 4.95~5.05초 쉬기를 60회 반복했다(연결 재사용 1,200번).
  - 502 가 33건(2.75%) 났다. 기록 33건은 모두 `ECONNRESET`(`socket hang up` 27·`read ECONNRESET` 6), `reused: true` 였다.
  - 연결이 놀던 시간은 4,984~5,044ms 였다.

## 결정
- 프록시 전용 `http.Agent({ keepAlive: true, timeout: UPSTREAM_IDLE_MS })`, `UPSTREAM_IDLE_MS = 4000`(`web/lib/proxy.ts`).
  노는 연결을 uvicorn(5초)보다 1초 먼저 프록시가 닫는다. 1초는 Node 가 서버 힌트에서 빼는 여유와 같다.
- 다시 쓴 연결에서 응답 전에 `ECONNRESET`·`EPIPE` 가 나면, GET·HEAD 만 새 연결(`agent: false`)로 한 번 더 보낸다.
  API 재시작처럼 서버가 노는 연결을 한꺼번에 닫는 경우를 위한 것이다. 풀의 다른 연결도 같이 닫혔을 수 있어 풀을 쓰지 않는다.
  POST(What-if·배치 제안)는 계산이 두 번 돌 수 있어 그대로 502 를 돌려준다.
- 연결 오류는 web 로그에 JSON 한 줄로 남긴다(`proxy_upstream_error`). 항목은 메서드·경로(쿼리 제외)·`code`·`message`·`reused`·`idleMs`·`retry` 다.
  브라우저가 먼저 끊어서 난 오류는 기록하지 않고 다시 보내지도 않는다.

## 검토한 대안
- **keep-alive 끄기**: 경쟁은 사라지지만 API 호출마다 TCP 연결을 새로 맺는다. ADR-026 에서도 같은 이유로 고르지 않았다.
- **uvicorn `--timeout-keep-alive` 만 늘리기**: 이러면 경쟁을 막는 시간을 API 띄우는 방식이 정한다. `make api-dev` 처럼 기본값(5초)으로 띄우면 경쟁이 다시 생긴다.
  그래서 연결 풀을 가진 프록시가 스스로 규칙을 지키게 했다.
- **다시 보내기만 하기**: GET 은 막지만 POST 는 여전히 502 가 난다.

## 감수한 단점
- 4초 넘게 논 연결은 다음 요청 때 새로 맺는다. 도커 내부망이라 비용은 작다. `make bench` 는 API 에 바로 붙어 이 변경과 무관하다.
- API 의 `timeout-keep-alive` 를 4초 이하로 줄이면 경쟁이 다시 생긴다. GET 은 다시 보내기로 막히지만 POST 는 아니다.
  그 값을 바꿀 때는 `UPSTREAM_IDLE_MS` 도 함께 바꾼다(`atlas/Dockerfile.api` 주석).

## 확인
- `web/lib/proxyRoute.test.ts` 는 uvicorn 처럼 머리글 없이 5초 뒤 닫는 가짜 API 를 쓴다. 다음 세 가지를 확인한다.
  - 노는 연결을 프록시가 먼저 닫는다. 전역 Agent 로 되돌리면 API 가 먼저 닫아 실패한다.
  - 다시 쓴 연결이 끊긴 GET 은 200, POST 는 502 다.
  - 브라우저가 끊은 요청은 기록하지도 다시 보내지도 않는다.
- 수정 뒤 같은 재현을 두 번 돌렸다. 옛 경계(4.95~5.05초)와 새 경계(3.95~4.05초)에서 각 1,200번 했고 502 는 둘 다 0건이었다.
  `make qa` 는 3회 돌렸고 크롤 오류는 0건, 그동안 web 로그의 연결 오류 기록도 0건이었다.
