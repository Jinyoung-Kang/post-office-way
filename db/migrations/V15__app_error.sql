-- V15 — 오류 로그: API 가 처리하지 못한 예외(500)를 남겨 데이터·운영 화면의 '오류 로그'에서 작업·수집·계산 실패와 함께 봅니다.
-- (컨테이너 로그는 재시작하면 사라지고 화면에서 복사할 수 없음) 30일 지난 행은 make prune 이 정리.
CREATE TABLE ops.app_error (
    error_id   bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    source     varchar(10) NOT NULL DEFAULT 'api' CHECK (source IN ('api', 'worker')),
    trace_id   varchar(32),
    method     varchar(8),
    path       text,
    error_type text NOT NULL,
    message    text
);
CREATE INDEX ix_app_error_at ON ops.app_error (at DESC);

GRANT SELECT, INSERT ON ops.app_error TO atlas_api;
GRANT USAGE ON SEQUENCE ops.app_error_error_id_seq TO atlas_api;
