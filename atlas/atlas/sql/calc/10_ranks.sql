-- 순위·백분위 (V14) — 모든 지표를 넣은 뒤 마지막에 한 번. 조회 API 는 이 열을 그대로 읽음
UPDATE mart.access_metric m
   SET rnk = r.rnk, pct = r.pct, n = r.n
  FROM (SELECT adm_cd, metric_code,
               rank() OVER (PARTITION BY metric_code, level ORDER BY value DESC) AS rnk,
               round(CAST(percent_rank() OVER (PARTITION BY metric_code, level ORDER BY value) * 100 AS numeric), 1) AS pct,
               count(*) OVER (PARTITION BY metric_code, level) AS n
          FROM mart.access_metric WHERE calc_run_id = :calc_run_id AND value IS NOT NULL) r
 WHERE m.calc_run_id = :calc_run_id AND m.adm_cd = r.adm_cd AND m.metric_code = r.metric_code;
