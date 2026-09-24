-- ① 집계구 기반 지표 — 집계구(평균 약 500명)마다 대표점 → 최근접 금융 우체국, 인구 가중으로 올려 계산.
-- mart.oa_area 가 비어 있으면 행이 생기지 않음(지표 비활성).
-- KNN 은 거리만으로 정렬해야 GiST 인덱스 스캔이 되므로(보조 정렬키가 붙으면 20배 느려짐, 실측)
-- 인덱스로 가까운 2곳을 받은 뒤 (거리, hist_id) 로 다시 정렬해 동률을 결정적으로 처리.

INSERT INTO mart.oa_nearest (calc_run_id, oa_cd, emd_cd, hist_id, dist_m, tot_ppltn)
SELECT :calc_run_id, o.oa_cd, o.emd_cd, k.hist_id, round(CAST(k.d AS numeric), 1), o.tot_ppltn
  FROM mart.oa_area o
 CROSS JOIN LATERAL (
        SELECT t.hist_id, t.d FROM (
            SELECT f.hist_id, ST_Distance(f.geom_5179, o.rep_point_5179) AS d
              FROM calc_fin f ORDER BY f.geom_5179 <-> o.rep_point_5179 LIMIT 2) t
         ORDER BY t.d, t.hist_id LIMIT 1) k
 WHERE o.stat_year = :stat_year AND o.rep_point_5179 IS NOT NULL AND o.tot_ppltn IS NOT NULL;

-- 읍면동(= 집계구 코드 앞 8자리)과 시군구(앞 5자리) 단위로 인구 가중 집계 (등호 조인 두 번)
CREATE TEMP TABLE calc_oa_agg (adm_cd varchar(10), level smallint, pop numeric, pop_dist numeric, far_pop numeric)
    ON COMMIT DROP;

INSERT INTO calc_oa_agg
SELECT a.adm_cd, a.level, sum(n.tot_ppltn), sum(n.tot_ppltn * n.dist_m),
       sum(n.tot_ppltn) FILTER (WHERE n.dist_m > CAST(:far_m AS numeric))
  FROM mart.oa_nearest n
  JOIN calc_area a ON a.level = 3 AND a.adm_cd = n.emd_cd
 WHERE n.calc_run_id = :calc_run_id
 GROUP BY a.adm_cd, a.level;

INSERT INTO calc_oa_agg
SELECT a.adm_cd, a.level, sum(n.tot_ppltn), sum(n.tot_ppltn * n.dist_m),
       sum(n.tot_ppltn) FILTER (WHERE n.dist_m > CAST(:far_m AS numeric))
  FROM mart.oa_nearest n
  JOIN calc_area a ON a.level = 2 AND a.adm_cd = left(n.emd_cd, 5)
 WHERE n.calc_run_id = :calc_run_id
 GROUP BY a.adm_cd, a.level;

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, adm_cd, 'POPW_FIN_DIST_M', level, round(pop_dist / nullif(pop, 0), 1) FROM calc_oa_agg;

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, adm_cd, 'FAR2KM_PPLTN', level, coalesce(far_pop, 0) FROM calc_oa_agg;

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, adm_cd, 'FAR2KM_SHARE', level, round(100.0 * coalesce(far_pop, 0) / nullif(pop, 0), 2)
  FROM calc_oa_agg WHERE pop > 0;
