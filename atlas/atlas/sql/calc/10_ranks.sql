-- 순위·백분위 (V14) — 모든 지표를 넣은 뒤 마지막에 한 번. 조회 API 는 이 열을 그대로 읽음
-- 같은 트랜잭션에서 넣은 지표 10만 행이 통계에 없으면 이 UPDATE 가 나쁜 계획을 골라 20초 걸렸음(따로 돌리면 1.8초) → 먼저 통계 갱신
ANALYZE mart.access_metric;
UPDATE mart.access_metric m
   SET rnk = r.rnk, pct = r.pct, n = r.n
  FROM (SELECT adm_cd, metric_code,
               rank() OVER (PARTITION BY metric_code, level ORDER BY value DESC) AS rnk,
               round(CAST(percent_rank() OVER (PARTITION BY metric_code, level ORDER BY value) * 100 AS numeric), 1) AS pct,
               count(*) OVER (PARTITION BY metric_code, level) AS n
          FROM mart.access_metric WHERE calc_run_id = :calc_run_id AND value IS NOT NULL) r
 WHERE m.calc_run_id = :calc_run_id AND m.adm_cd = r.adm_cd AND m.metric_code = r.metric_code;
