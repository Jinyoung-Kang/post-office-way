-- V2 — 수집 실행 기록 · 원문 저장 · 품질 이슈

CREATE TABLE ops.collect_run (
    collect_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind           varchar(20) NOT NULL
                   CHECK (kind IN ('POST_AREA', 'POST_DISCOVER', 'SGIS_POP', 'SGIS_BND')),
    status         varchar(12) NOT NULL
                   CHECK (status IN ('RUNNING', 'DONE', 'PARTIAL', 'FAILED')),
    scope          text,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    -- {calls, pages, rows, failedCodes[], doneCodes[], elapsedMs}
    stats          jsonb NOT NULL DEFAULT '{}'::jsonb,
    error          text
);
CREATE INDEX ix_collect_run_kind_started ON ops.collect_run (kind, started_at DESC);

CREATE TABLE raw.api_response (
    response_id        bigserial PRIMARY KEY,
    collect_run_id     uuid NOT NULL REFERENCES ops.collect_run (collect_run_id),
    source             varchar(20) NOT NULL
                       CHECK (source IN ('POST_AREA', 'SGIS_AUTH', 'SGIS_POP', 'SGIS_BND')),
    request_url_masked text NOT NULL,
    params             jsonb,
    http_status        int,
    -- 원문. 1MB 이상(경계 GeoJSON 등)은 gzip 으로 body_gz 에 저장 (U-4 결정)
    body               text,
    body_gz            bytea,
    fetched_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_api_response_run ON raw.api_response (collect_run_id);
CREATE INDEX ix_api_response_source ON raw.api_response (source, fetched_at DESC);

-- 품질 이슈 (행 단위). calc_run_id FK 는 V4 에서 추가
CREATE TABLE ops.dq_issue (
    issue_id       bigserial PRIMARY KEY,
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id),
    calc_run_id    uuid,
    check_code     varchar(40) NOT NULL,
    severity       varchar(8) NOT NULL CHECK (severity IN ('ERROR', 'WARN', 'INFO')),
    target_table   varchar(60),
    target_key     text,
    detail         jsonb,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_dq_issue_collect ON ops.dq_issue (collect_run_id, check_code);
CREATE INDEX ix_dq_issue_calc ON ops.dq_issue (calc_run_id, check_code);

-- 규칙 실행 기록 (건수 0 인 규칙도 '실행했음'을 남김 — FR-601)
CREATE TABLE ops.dq_check (
    check_id       bigserial PRIMARY KEY,
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id),
    calc_run_id    uuid,
    check_code     varchar(40) NOT NULL,
    severity       varchar(8) NOT NULL,
    issue_count    int NOT NULL,
    checked_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_dq_check_collect ON ops.dq_check (collect_run_id);
CREATE INDEX ix_dq_check_calc ON ops.dq_check (calc_run_id);
