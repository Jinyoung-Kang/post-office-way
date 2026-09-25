-- V14 — 순위·백분위를 계산 시점에 한 번만 (이전: 조회마다 전체 지역에 창 함수 → 지역 상세 약 50ms, 벤치마크 1위 SQL)
ALTER TABLE mart.access_metric
    ADD COLUMN rnk int,            -- 값이 큰 순 순위 (같은 계산·지표·레벨 안)
    ADD COLUMN pct numeric(5, 1),  -- 백분위 (작은 값 0 → 큰 값 100)
    ADD COLUMN n int;              -- 값이 있는 지역 수

UPDATE mart.access_metric m
   SET rnk = r.rnk, pct = r.pct, n = r.n
  FROM (SELECT calc_run_id, adm_cd, metric_code,
               rank() OVER w AS rnk,
               round(CAST(percent_rank() OVER (PARTITION BY calc_run_id, metric_code, level ORDER BY value) * 100 AS numeric), 1) AS pct,
               count(*) OVER (PARTITION BY calc_run_id, metric_code, level) AS n
          FROM mart.access_metric WHERE value IS NOT NULL
        WINDOW w AS (PARTITION BY calc_run_id, metric_code, level ORDER BY value DESC)) r
 WHERE m.calc_run_id = r.calc_run_id AND m.adm_cd = r.adm_cd AND m.metric_code = r.metric_code;
