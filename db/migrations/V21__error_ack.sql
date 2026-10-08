-- V21 — 오류 로그 '지우기' = 확인 표시. 해결했거나 지난 항목을 데이터·운영 오류 로그에서 뺀다.
--   원본(ops.app_error·ops.job·ops.collect_run·mart.calc_run·ops.dq_check)은 작업 큐·품질 이력이기도 해서 지우지 않고,
--   API 역할에는 DELETE 대신 INSERT 만 준다. 누가(IP) 언제 지웠는지 남는다.
--   entry_id 형식: api:{error_id} · job:{job_id} · collect:{collect_run_id} · calc:{calc_run_id} · dq:{check_id}
CREATE TABLE ops.error_ack (
    entry_id  varchar(60) PRIMARY KEY CHECK (entry_id ~ '^(api|job|collect|calc|dq):[0-9a-f-]{1,40}$'),
    acked_at  timestamptz NOT NULL DEFAULT now(),
    acked_by  varchar(64)
);

GRANT SELECT, INSERT ON ops.error_ack TO atlas_api;
