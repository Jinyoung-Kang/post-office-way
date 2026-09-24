-- FAC_CNT_R{n}KM — 대표점 반경 n km 안 금융 가능 우체국 수 (ST_DWithin 은 GiST 인덱스 사용)
INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, :metric_code, a.level,
       (SELECT count(*) FROM calc_fin f WHERE ST_DWithin(f.geom_5179, a.rep_point_5179, CAST(:radius_m AS float8)))
  FROM calc_area a;
