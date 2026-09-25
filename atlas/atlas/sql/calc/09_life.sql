-- ⑦ 생활 거점 — 집계구마다 2순위 금융 우체국·은행 지점·약국·의원·공휴일 진료처까지 거리를 구해
--    (1) 약국·의원 거리와 의료/생활 서비스 공백 인구 지표, (2) 우체국별 대체 불가능성(facility_hub)을 만듭니다.
-- 약국·의원 자료(mart.care_place)가 없으면 2순위 우체국·은행 거리만 채우고 지표는 만들지 않음.
-- KNN 은 종류별 임시 테이블 + GiST 로 한 곳씩 (스칼라 서브쿼리 ORDER BY <-> LIMIT 1 = 인덱스 KNN)

CREATE TEMP TABLE calc_pharmacy ON COMMIT DROP AS
SELECT geom_5179 FROM mart.care_place WHERE kind = 'PHARMACY';
CREATE TEMP TABLE calc_clinic ON COMMIT DROP AS
SELECT geom_5179 FROM mart.care_place WHERE kind = 'CLINIC';
CREATE TEMP TABLE calc_hcare ON COMMIT DROP AS
SELECT geom_5179 FROM mart.care_place WHERE open_holiday;

CREATE INDEX ON calc_pharmacy USING gist (geom_5179);
CREATE INDEX ON calc_clinic USING gist (geom_5179);
CREATE INDEX ON calc_hcare USING gist (geom_5179);
ANALYZE calc_pharmacy;
ANALYZE calc_clinic;
ANALYZE calc_hcare;

CREATE TEMP TABLE calc_oa_life (
    oa_cd varchar(16) PRIMARY KEY, post2_m numeric, bank_m numeric, pharmacy_m numeric, clinic_m numeric, hcare_m numeric
) ON COMMIT DROP;

INSERT INTO calc_oa_life
SELECT n.oa_cd,
       (SELECT round(CAST(ST_Distance(f.geom_5179, o.rep_point_5179) AS numeric), 1) FROM calc_fin f
         WHERE f.hist_id <> n.hist_id ORDER BY f.geom_5179 <-> o.rep_point_5179 LIMIT 1),
       (SELECT round(CAST(ST_Distance(b.geom_5179, o.rep_point_5179) AS numeric), 1) FROM calc_bank b
         ORDER BY b.geom_5179 <-> o.rep_point_5179 LIMIT 1),
       (SELECT round(CAST(ST_Distance(p.geom_5179, o.rep_point_5179) AS numeric), 1) FROM calc_pharmacy p
         ORDER BY p.geom_5179 <-> o.rep_point_5179 LIMIT 1),
       (SELECT round(CAST(ST_Distance(x.geom_5179, o.rep_point_5179) AS numeric), 1) FROM calc_clinic x
         ORDER BY x.geom_5179 <-> o.rep_point_5179 LIMIT 1),
       (SELECT round(CAST(ST_Distance(h.geom_5179, o.rep_point_5179) AS numeric), 1) FROM calc_hcare h
         ORDER BY h.geom_5179 <-> o.rep_point_5179 LIMIT 1)
  FROM mart.oa_nearest n
  JOIN mart.oa_area o ON o.oa_cd = n.oa_cd AND o.stat_year = :stat_year
 WHERE n.calc_run_id = :calc_run_id;

UPDATE mart.oa_nearest n
   SET post2_m = l.post2_m, bank_m = l.bank_m, pharmacy_m = l.pharmacy_m, clinic_m = l.clinic_m, hcare_m = l.hcare_m
  FROM calc_oa_life l
 WHERE n.calc_run_id = :calc_run_id AND n.oa_cd = l.oa_cd;

-- 읍면동(집계구 앞 8자리)·시군구(앞 5자리) 단위 집계. 약국·의원 자료가 있을 때만
CREATE TEMP TABLE calc_life_agg (
    adm_cd varchar(10), level smallint, pop numeric, pd_pharmacy numeric, pd_clinic numeric,
    care_desert numeric, sole_hub numeric, life_desert numeric, hcare_gap numeric
) ON COMMIT DROP;

-- 등호 조인 두 번 (OR 조인은 해시 조인이 안 됨)
INSERT INTO calc_life_agg
SELECT a.adm_cd, a.level, sum(n.tot_ppltn), sum(n.tot_ppltn * n.pharmacy_m), sum(n.tot_ppltn * n.clinic_m),
       sum(n.tot_ppltn) FILTER (WHERE n.pharmacy_m > CAST(:far_m AS numeric) AND n.clinic_m > CAST(:far_m AS numeric)),
       sum(n.tot_ppltn) FILTER (WHERE n.dist_m <= CAST(:far_m AS numeric) AND n.bank_m > CAST(:far_m AS numeric)
                                  AND n.pharmacy_m > CAST(:far_m AS numeric) AND n.clinic_m > CAST(:far_m AS numeric)),
       sum(n.tot_ppltn) FILTER (WHERE n.dist_m > CAST(:far_m AS numeric) AND n.bank_m > CAST(:far_m AS numeric)
                                  AND n.pharmacy_m > CAST(:far_m AS numeric) AND n.clinic_m > CAST(:far_m AS numeric)),
       sum(n.tot_ppltn) FILTER (WHERE n.hcare_m > CAST(:far_m AS numeric))
  FROM mart.oa_nearest n
  JOIN calc_area a ON a.level = 3 AND a.adm_cd = n.emd_cd
 WHERE n.calc_run_id = :calc_run_id AND n.pharmacy_m IS NOT NULL AND n.clinic_m IS NOT NULL
 GROUP BY a.adm_cd, a.level;

INSERT INTO calc_life_agg
SELECT a.adm_cd, a.level, sum(n.tot_ppltn), sum(n.tot_ppltn * n.pharmacy_m), sum(n.tot_ppltn * n.clinic_m),
       sum(n.tot_ppltn) FILTER (WHERE n.pharmacy_m > CAST(:far_m AS numeric) AND n.clinic_m > CAST(:far_m AS numeric)),
       sum(n.tot_ppltn) FILTER (WHERE n.dist_m <= CAST(:far_m AS numeric) AND n.bank_m > CAST(:far_m AS numeric)
                                  AND n.pharmacy_m > CAST(:far_m AS numeric) AND n.clinic_m > CAST(:far_m AS numeric)),
       sum(n.tot_ppltn) FILTER (WHERE n.dist_m > CAST(:far_m AS numeric) AND n.bank_m > CAST(:far_m AS numeric)
                                  AND n.pharmacy_m > CAST(:far_m AS numeric) AND n.clinic_m > CAST(:far_m AS numeric)),
       sum(n.tot_ppltn) FILTER (WHERE n.hcare_m > CAST(:far_m AS numeric))
  FROM mart.oa_nearest n
  JOIN calc_area a ON a.level = 2 AND a.adm_cd = left(n.emd_cd, 5)
 WHERE n.calc_run_id = :calc_run_id AND n.pharmacy_m IS NOT NULL AND n.clinic_m IS NOT NULL
 GROUP BY a.adm_cd, a.level;

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, adm_cd, m.code, level, m.v
  FROM calc_life_agg g
 CROSS JOIN LATERAL (VALUES
        ('POPW_PHARMACY_DIST_M', round(g.pd_pharmacy / nullif(g.pop, 0), 1)),
        ('POPW_CLINIC_DIST_M', round(g.pd_clinic / nullif(g.pop, 0), 1)),
        ('CARE_DESERT_PPLTN', coalesce(g.care_desert, 0)),
        ('HOLIDAY_CARE_GAP_PPLTN', coalesce(g.hcare_gap, 0))) AS m(code, v)
 WHERE g.pop > 0;

-- 은행 지점 자료까지 있어야 '마지막 생활 거점'을 판정할 수 있음
INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, adm_cd, m.code, level, m.v
  FROM calc_life_agg g
 CROSS JOIN LATERAL (VALUES ('POST_SOLE_HUB_PPLTN', coalesce(g.sole_hub, 0)),
                            ('LIFE_DESERT_PPLTN', coalesce(g.life_desert, 0))) AS m(code, v)
 WHERE g.pop > 0 AND EXISTS (SELECT 1 FROM calc_bank);

-- 우체국별 대체 불가능성: 이 우체국이 최근접(2km 안)인 집계구 중,
--   다른 금융 우체국·은행 지점도 2km 안에 없음(sole_fin) → 거기에 약국·의원도 없음(sole_hub)
INSERT INTO mart.facility_hub (calc_run_id, hist_id, served_ppltn, sole_fin_ppltn, sole_hub_ppltn, oa_count)
SELECT :calc_run_id, n.hist_id, sum(n.tot_ppltn),
       coalesce(sum(n.tot_ppltn) FILTER (WHERE coalesce(n.post2_m, 1e9) > CAST(:far_m AS numeric)
                                          AND n.bank_m > CAST(:far_m AS numeric)), 0),
       coalesce(sum(n.tot_ppltn) FILTER (WHERE coalesce(n.post2_m, 1e9) > CAST(:far_m AS numeric)
                                          AND n.bank_m > CAST(:far_m AS numeric)
                                          AND n.pharmacy_m > CAST(:far_m AS numeric)
                                          AND n.clinic_m > CAST(:far_m AS numeric)), 0),
       count(*)
  FROM mart.oa_nearest n
 WHERE n.calc_run_id = :calc_run_id AND n.hist_id IS NOT NULL AND n.dist_m <= CAST(:far_m AS numeric)
   AND EXISTS (SELECT 1 FROM calc_bank) AND EXISTS (SELECT 1 FROM calc_pharmacy)
 GROUP BY n.hist_id;
