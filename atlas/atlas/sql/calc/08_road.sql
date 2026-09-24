-- ② 도로 거리 — 캐시된 경로(mart.area_road) 중 이번 스냅샷에 유효한 금융 우체국까지 가장 짧은 경로.
-- 아직 경로를 못 받은 지역은 행이 없음(값 없음 '—').

CREATE TEMP TABLE calc_road (adm_cd varchar(10), level smallint, road_m int, drive_s int) ON COMMIT DROP;

INSERT INTO calc_road
SELECT DISTINCT ON (a.adm_cd) a.adm_cd, a.level, r.road_m, r.drive_s
  FROM calc_area a
  JOIN mart.area_road r ON r.adm_cd = a.adm_cd AND r.stat_year = :stat_year AND r.status = 'OK'
  JOIN calc_fin f ON f.hist_id = r.hist_id
 ORDER BY a.adm_cd, r.road_m, r.hist_id;

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, adm_cd, 'NEAREST_FIN_ROAD_M', level, road_m FROM calc_road;

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, adm_cd, 'NEAREST_FIN_DRIVE_MIN', level, round(drive_s / 60.0, 1) FROM calc_road;
