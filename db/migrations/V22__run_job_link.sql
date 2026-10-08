-- V22 — 실행 기록(수집·계산·도보)에 그 실행을 돌린 작업 id.
--   워커가 죽어 하트비트가 끊긴 작업을 정리(reap)할 때 그 작업이 연 실행 기록도 FAILED 로 닫음 — RUNNING 으로 남으면
--   같은 종류의 재시도·다음 스케줄이 최대 6시간(계산은 2시간) '이미 실행 중'으로 실패했음 (리뷰 R1).
--   CLI 로 직접 돌린 실행은 작업 id 가 없음(NULL) — 예전처럼 시간 기준(STALE_HOURS)으로만 판단.
--   열 추가만이라 기존 행은 바뀌지 않음.
ALTER TABLE ops.collect_run ADD COLUMN job_id bigint;
ALTER TABLE mart.calc_run ADD COLUMN job_id bigint;
ALTER TABLE mart.walk_run ADD COLUMN job_id bigint;
