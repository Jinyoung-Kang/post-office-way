-- V13 — 쿼리 통계(pg_stat_statements): 벤치마크·튜닝 때 느린 SQL 상위를 봅니다 (make bench 가 함께 출력).
-- db 는 shared_preload_libraries=pg_stat_statements 로 기동. 확장이 없는 환경이면 조용히 건너뜀.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_stat_statements 를 쓸 수 없어 건너뜁니다: %', SQLERRM;
END $$;
