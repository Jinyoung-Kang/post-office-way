-- V11 — 작업 큐: API 는 작업을 '요청'만 하고(INSERT + NOTIFY), 워커가 FOR UPDATE SKIP LOCKED 로 가져가 실행합니다.
-- 스케줄러(워커 안)는 slot 고유키로 같은 시각 작업을 한 번만 넣습니다. 이전에는 API 프로세스 스레드에서 실행했음.
CREATE TABLE ops.job (
    job_id        bigserial PRIMARY KEY,
    kind          varchar(20) NOT NULL,
    params        jsonb NOT NULL DEFAULT '{}'::jsonb,
    status        varchar(10) NOT NULL DEFAULT 'QUEUED'
                  CHECK (status IN ('QUEUED', 'RUNNING', 'DONE', 'FAILED', 'CANCELLED')),
    source        varchar(10) NOT NULL DEFAULT 'api' CHECK (source IN ('api', 'schedule', 'cli', 'chain')),
    requested_by  text,                          -- 요청 IP 등 (감사 기록)
    slot          text,                          -- 스케줄 작업의 시각 키 (예: kma@2026-09-25T05)
    attempts      smallint NOT NULL DEFAULT 0,
    max_attempts  smallint NOT NULL DEFAULT 2,
    worker        text,
    result        jsonb,
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    started_at    timestamptz,
    heartbeat_at  timestamptz,
    finished_at   timestamptz
);
-- 같은 종류는 대기·실행 중 하나만 (중복 요청은 409), 같은 스케줄 슬롯은 한 번만
CREATE UNIQUE INDEX ux_job_active ON ops.job (kind) WHERE status IN ('QUEUED', 'RUNNING');
CREATE UNIQUE INDEX ux_job_slot ON ops.job (slot) WHERE slot IS NOT NULL;
CREATE INDEX ix_job_queue ON ops.job (created_at) WHERE status = 'QUEUED';
CREATE INDEX ix_job_recent ON ops.job (created_at DESC);
