-- FR-303 지표 (5장). access_metric 은 지표 하나 = 지역 하나 = 행 하나 (long format)

-- NEAREST_FIN_DIST_M — area_nearest rank 1
INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, 'NEAREST_FIN_DIST_M', a.level, n.dist_m
  FROM calc_area a
  LEFT JOIN mart.area_nearest n ON n.calc_run_id = :calc_run_id AND n.adm_cd = a.adm_cd AND n.rank = 1;

-- HAS_365 — 지역 안 365코너(post_div=3) 또는 post365_yn='Y' 시설 존재
INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, 'HAS_365', a.level,
       CASE WHEN EXISTS (SELECT 1 FROM mart.facility_area_map m JOIN calc_fac f ON f.hist_id = m.hist_id
                          WHERE m.stat_year = :stat_year AND m.level = a.level AND m.adm_cd = a.adm_cd
                            AND (f.post365_yn = 'Y' OR f.post_div = 3)) THEN 1 ELSE 0 END
  FROM calc_area a;

-- LUNCH_CLOSED_RATIO — 지역 안 우체국(0·1, 집중국 제외) 중 점심 휴무 비율. 5개 미만이면 NULL
INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, 'LUNCH_CLOSED_RATIO', a.level,
       CASE WHEN c.n >= 5 THEN round(100.0 * c.lunch / c.n, 2) END
  FROM calc_area a
  LEFT JOIN (SELECT m.adm_cd, m.level, count(*) AS n, count(*) FILTER (WHERE f.lunch_yn = 'Y') AS lunch
               FROM mart.facility_area_map m JOIN calc_fac f ON f.hist_id = m.hist_id
              WHERE m.stat_year = :stat_year AND f.post_div IN (0, 1) AND NOT f.is_center
              GROUP BY m.adm_cd, m.level) c ON c.adm_cd = a.adm_cd AND c.level = a.level;
