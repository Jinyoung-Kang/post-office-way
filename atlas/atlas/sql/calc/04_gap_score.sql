-- ACCESS_GAP_SCORE = 100 × (w_dist × minmax(거리) + w_aged × minmax(노령화지수)), 같은 level·calc_run 안
-- 거리나 노령화지수가 없으면 NULL. 인구가 0/없음인 지역(접경 무인 면 등)의 노령화지수 0 은 '값 없음'으로 봄. 최대=최소(분모 0)이면 해당 항은 0.
INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
WITH base AS (
    SELECT a.adm_cd, a.level, d.value AS dist,
           CASE WHEN coalesce(p.tot_ppltn, 0) > 0 THEN p.aged_child_idx END AS aged
      FROM calc_area a
      LEFT JOIN mart.access_metric d ON d.calc_run_id = :calc_run_id AND d.adm_cd = a.adm_cd
                                    AND d.metric_code = 'NEAREST_FIN_DIST_M'
      LEFT JOIN mart.area_population p ON p.adm_cd = a.adm_cd AND p.stat_year = :stat_year
), mm AS (
    SELECT level, min(dist) AS dmin, max(dist) AS dmax, min(aged) AS amin, max(aged) AS amax
      FROM base WHERE dist IS NOT NULL AND aged IS NOT NULL GROUP BY level
)
SELECT :calc_run_id, b.adm_cd, 'ACCESS_GAP_SCORE', b.level,
       CASE WHEN b.dist IS NULL OR b.aged IS NULL THEN NULL
            ELSE round(100 * (CAST(:w_dist AS numeric) * coalesce((b.dist - mm.dmin) / nullif(mm.dmax - mm.dmin, 0), 0)
                            + CAST(:w_aged AS numeric) * coalesce((b.aged - mm.amin) / nullif(mm.amax - mm.amin, 0), 0)), 2)
       END
  FROM base b LEFT JOIN mm ON mm.level = b.level;
