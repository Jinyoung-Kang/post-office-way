-- FR-301 시설 ↔ 행정구역 공간 조인 (ADR-001: 우편 지역코드가 아니라 좌표로 판정)
-- ① 폴리곤 안(경계선 위 포함) → CONTAINS. 두 지역 경계에 걸리면 adm_cd 가 작은 쪽(결정적)
INSERT INTO mart.facility_area_map (hist_id, stat_year, level, adm_cd, method)
SELECT DISTINCT ON (f.hist_id, a.level) f.hist_id, :stat_year, a.level, a.adm_cd, 'CONTAINS'
  FROM calc_fac f
  JOIN calc_area_sub a ON ST_Intersects(a.geom, f.geom)
 WHERE NOT EXISTS (SELECT 1 FROM mart.facility_area_map m
                    WHERE m.hist_id = f.hist_id AND m.stat_year = :stat_year AND m.level = a.level)
 ORDER BY f.hist_id, a.level, a.adm_cd
ON CONFLICT DO NOTHING;

-- ② 해안선 단순화 등으로 폴리곤 밖에 떨어진 시설은 :snap_m 이내 최근접 지역에 붙임 → NEAREST
INSERT INTO mart.facility_area_map (hist_id, stat_year, level, adm_cd, method)
SELECT f.hist_id, :stat_year, l.level, n.adm_cd, 'NEAREST'
  FROM calc_fac f
 CROSS JOIN unnest(CAST(:levels AS smallint[])) AS l(level)
 CROSS JOIN LATERAL (
        SELECT a.adm_cd, ST_Distance(a.geom_5179, f.geom_5179) AS d
          FROM calc_area a WHERE a.level = l.level
         ORDER BY a.geom_5179 <-> f.geom_5179, a.adm_cd LIMIT 1) n
 WHERE n.d <= :snap_m
   AND NOT EXISTS (SELECT 1 FROM mart.facility_area_map m
                    WHERE m.hist_id = f.hist_id AND m.stat_year = :stat_year AND m.level = l.level)
ON CONFLICT DO NOTHING;
