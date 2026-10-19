-- 인구 추세 (ADR-028) — 행안부 인구이동의 최근 12개 연속 달 합을 시군구 지표로.
-- 계산 시점(as_of) 이전에 받은 달 가운데 최근 12개가 빠짐없이 이어질 때만 만들고, 아니면 행이 생기지 않음(지표 비활성).
-- 일반구가 있는 시(수원시 장안구 등)는 원천이 시 단위라 시 전체 값을 각 구에 씀 — 분모도 그 시의 구 인구 합(CITY).
-- 읍면동은 만들지 않음(원천 행렬이 시군구 단위).

CREATE TEMP TABLE calc_migr_win ON COMMIT DROP AS
WITH months AS (SELECT DISTINCT ref_ym FROM mart.migration_month
                 WHERE ref_ym <= to_char(CAST(:as_of AS timestamptz) AT TIME ZONE 'Asia/Seoul', 'YYYYMM')
                 ORDER BY ref_ym DESC LIMIT 12)
SELECT min(ref_ym) AS ym_from, max(ref_ym) AS ym_to, count(*) AS n,
       count(*) = 12 AND to_date(min(ref_ym), 'YYYYMM') = to_date(max(ref_ym), 'YYYYMM') - interval '11 months' AS ok
  FROM months;

-- 단위별 12개월 합 — 시도 코드만 바뀐 개편은 별칭(V26)으로 최신 코드에 이어 붙이고, 12개 달이 한 번씩 다 있는 단위만
-- (구가 새로 생기거나 없어진 개편으로 중간에 생기거나 없어진 단위는 빠짐. 같은 달이 두 번이면 겹친 것이라 뺌)
CREATE TEMP TABLE calc_migr_unit ON COMMIT DROP AS
SELECT coalesce(al.unit_cd, m.mois_cd) AS mois_cd, sum(m.in_cnt) AS in_cnt, sum(m.out_cnt) AS out_cnt,
       sum(m.in_aged65) AS in65, sum(m.out_aged65) AS out65
  FROM mart.migration_month m
  LEFT JOIN mart.migration_unit_alias al ON al.mois_cd = m.mois_cd
  JOIN calc_migr_win w ON w.ok AND m.ref_ym BETWEEN w.ym_from AND w.ym_to
 GROUP BY 1
HAVING count(*) = 12 AND count(DISTINCT m.ref_ym) = 12;

-- 단위별 분모 — 그 단위에 대응된 시군구의 주민등록 인구 합. 대응된 시군구 중 하나라도 인구가 없으면 분모를 만들지 않음
CREATE TEMP TABLE calc_migr_pop ON COMMIT DROP AS
SELECT mp.mois_cd,
       CASE WHEN count(r.tot_ppltn) = count(*) THEN sum(r.tot_ppltn) END AS pop,
       CASE WHEN count(r.aged65_ppltn) = count(*) THEN sum(r.aged65_ppltn) END AS aged
  FROM mart.area_migration_map mp
  LEFT JOIN mart.area_resident_pop r ON r.adm_cd = mp.adm_cd AND r.stat_year = mp.stat_year
 WHERE mp.stat_year = :stat_year
 GROUP BY mp.mois_cd;

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, 'NET_OUT_12M_PER_1K', a.level, round((u.out_cnt - u.in_cnt) * 1000.0 / p.pop, 2)
  FROM calc_area a
  JOIN mart.area_migration_map mp ON mp.adm_cd = a.adm_cd AND mp.stat_year = :stat_year
  JOIN calc_migr_unit u ON u.mois_cd = mp.mois_cd
  JOIN calc_migr_pop p ON p.mois_cd = mp.mois_cd AND p.pop > 0
 WHERE a.level = 2;

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, 'AGED65_NET_IN_12M_PER_1K', a.level, round((u.in65 - u.out65) * 1000.0 / p.aged, 2)
  FROM calc_area a
  JOIN mart.area_migration_map mp ON mp.adm_cd = a.adm_cd AND mp.stat_year = :stat_year
  JOIN calc_migr_unit u ON u.mois_cd = mp.mois_cd
  JOIN calc_migr_pop p ON p.mois_cd = mp.mois_cd AND p.aged > 0
 WHERE a.level = 2;
