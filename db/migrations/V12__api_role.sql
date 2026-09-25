-- V12 — 최소 권한 역할 atlas_api: API 는 이 역할로 접속합니다 (소유자 atlas 는 migrate·worker·collector 만).
--   · mart/ops 조회, What-if 결과 저장, 작업 요청(ops.job INSERT, 대기 작업 취소 UPDATE)만 허용
--   · raw(원본 응답)·stg(수집 스냅샷) 접근 없음, DDL 없음
--   · 역할 단위 statement_timeout 으로 느린 쿼리가 커넥션을 붙잡지 못하게
-- 로그인 비밀번호는 `atlas migrate` 가 .env API_DB_PASSWORD 로 설정합니다(SQL 파일에 비밀값을 두지 않음).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'atlas_api') THEN
        CREATE ROLE atlas_api NOLOGIN;
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO atlas_api', current_database());
END $$;

REVOKE ALL ON SCHEMA raw, stg FROM atlas_api;
GRANT USAGE ON SCHEMA mart, ops TO atlas_api;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO atlas_api;
GRANT SELECT ON ops.collect_run, ops.dq_issue, ops.dq_check, ops.job TO atlas_api;
GRANT SELECT ON public.schema_migrations TO atlas_api;

GRANT INSERT ON mart.whatif_scenario, mart.whatif_result TO atlas_api;
GRANT INSERT ON ops.job TO atlas_api;
GRANT UPDATE (status, finished_at) ON ops.job TO atlas_api;
GRANT USAGE ON SEQUENCE ops.job_job_id_seq TO atlas_api;

-- 이후 마이그레이션이 mart 에 만드는 표도 자동으로 조회 가능 (소유자 atlas 가 만든 객체 기준)
ALTER DEFAULT PRIVILEGES IN SCHEMA mart GRANT SELECT ON TABLES TO atlas_api;

ALTER ROLE atlas_api SET statement_timeout = '15s';
ALTER ROLE atlas_api SET lock_timeout = '3s';
ALTER ROLE atlas_api SET idle_in_transaction_session_timeout = '30s';
