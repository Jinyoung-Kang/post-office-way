-- KOSIS 주민등록인구 기반 고령인구 지표 (FR-205). area_resident_pop 이 비어 있으면 행이 생기지 않음(지표 비활성).

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, 'AGED65_PPLTN', a.level, r.aged65_ppltn
  FROM calc_area a
  JOIN mart.area_resident_pop r ON r.adm_cd = a.adm_cd AND r.stat_year = :stat_year;

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, 'AGED65_RATIO', a.level, r.aged65_ratio
  FROM calc_area a
  JOIN mart.area_resident_pop r ON r.adm_cd = a.adm_cd AND r.stat_year = :stat_year;

-- 금융 우체국 :far_m 밖 고령인구 — 읍면동은 대표점 거리로 판정, 시군구는 하위 읍면동 합
-- (읍면동을 계산하지 않은 run 이면 시군구 자신의 거리로 판정)
INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, 'AGED65_FAR_PPLTN', a.level,
       CASE WHEN d.value > CAST(:far_m AS numeric) THEN r.aged65_ppltn ELSE 0 END
  FROM calc_area a
  JOIN mart.area_resident_pop r ON r.adm_cd = a.adm_cd AND r.stat_year = :stat_year
  JOIN mart.access_metric d ON d.calc_run_id = :calc_run_id AND d.adm_cd = a.adm_cd
                           AND d.metric_code = 'NEAREST_FIN_DIST_M'
 WHERE r.aged65_ppltn IS NOT NULL
   AND (a.level = 3 OR NOT EXISTS (SELECT 1 FROM calc_area x WHERE x.level = 3));

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, 'AGED65_FAR_PPLTN', a.level, sum(m.value)
  FROM calc_area a
  JOIN calc_area ch ON ch.level = 3 AND left(ch.adm_cd, 5) = a.adm_cd
  JOIN mart.access_metric m ON m.calc_run_id = :calc_run_id AND m.adm_cd = ch.adm_cd
                           AND m.metric_code = 'AGED65_FAR_PPLTN'
 WHERE a.level = 2
 GROUP BY a.adm_cd, a.level;
