-- V16 — 워커 생존 신호. 워커는 차선(lane)별로 스레드를 돌리며 주기적으로 last_seen 을 갱신합니다.
--   short: 예보·공휴일·약국/병의원·계산처럼 수 분 안에 끝나는 작업 / long: 집계구·은행·도로·좌표 검증(수십 분)
--   → 긴 작업이 도는 동안에도 예보 갱신이 막히지 않음(헤드 오브 라인 블로킹 해소). /health 와 운영 화면이 이 표로 워커 상태를 보여 줌
CREATE TABLE ops.worker (
    worker     text PRIMARY KEY,                -- 호스트:PID/차선
    lane       varchar(10) NOT NULL CHECK (lane IN ('short', 'long')),
    started_at timestamptz NOT NULL DEFAULT now(),
    last_seen  timestamptz NOT NULL DEFAULT now(),
    job_id     bigint                           -- 지금 실행 중인 작업 (없으면 NULL)
);
GRANT SELECT ON ops.worker TO atlas_api;
