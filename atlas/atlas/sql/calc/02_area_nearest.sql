-- FR-302 지역별 최근접 금융 가능 시설 상위 3개 (What-if 부분 재계산의 핵심 캐시, ADR-005)
-- EPSG:5179 평면거리(미터). 거리가 같으면 hist_id 로 순서를 고정(NFR-03 재현성).
INSERT INTO mart.area_nearest (calc_run_id, adm_cd, rank, hist_id, dist_m)
SELECT :calc_run_id, a.adm_cd, k.rnk, k.hist_id, round(CAST(k.d AS numeric), 2)
  FROM calc_area a
 CROSS JOIN LATERAL (
        SELECT f.hist_id, ST_Distance(f.geom_5179, a.rep_point_5179) AS d,
               CAST(row_number() OVER (ORDER BY ST_Distance(f.geom_5179, a.rep_point_5179), f.hist_id) AS smallint) AS rnk
          FROM (SELECT hist_id, geom_5179 FROM calc_fin
                 ORDER BY geom_5179 <-> a.rep_point_5179 LIMIT 4) f      -- 인덱스 KNN 4곳 → 동률 정리 후 3곳
       ) k
 WHERE k.rnk <= 3;
