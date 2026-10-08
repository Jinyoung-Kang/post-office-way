-- V23 — 같은 종류 작업은 '대기 중' 하나만 (실행 중 하나 + 대기 중 하나 허용).
--   예전 ux_job_active 는 대기·실행 중을 합쳐 하나만이라, 계산이 '실행 중'일 때 수집이 끝나 재계산을 넣으면 실행 중인
--   계산(이미 스냅샷을 찍음)을 받은 것으로 처리해 새 자료가 다음 재계산까지 반영되지 않았음 (리뷰 R2).
--   같은 종류가 동시에 두 개 돌지 않는 것은 claim() 이 실행 중인 종류를 건너뛰어 지킴. 인덱스만 교체(데이터 변경 없음).
DROP INDEX ops.ux_job_active;
CREATE UNIQUE INDEX ux_job_queued ON ops.job (kind) WHERE status = 'QUEUED';
