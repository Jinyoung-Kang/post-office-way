-- ④ 금융 공백 — 은행·금고 대면 지점(kind=BRANCH)까지 거리와, 우체국만 있는/둘 다 없는 인구.
-- 카카오 장소는 최근 수집에서 본 것만(90일) 사용. mart.bank_place 가 비어 있으면 행이 생기지 않음.

CREATE TEMP TABLE calc_bank ON COMMIT DROP AS
SELECT place_id, geom_5179 FROM mart.bank_place
 WHERE kind = 'BRANCH' AND last_seen >= (SELECT max(last_seen) - interval '90 days' FROM mart.bank_place);

CREATE INDEX ON calc_bank USING gist (geom_5179);
ANALYZE calc_bank;

-- 20km 밖은 수집 반경 밖이라 값 없음
INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, 'NEAREST_BANK_DIST_M', a.level, round(CAST(k.d AS numeric), 2)
  FROM calc_area a
 CROSS JOIN LATERAL (SELECT ST_Distance(b.geom_5179, a.rep_point_5179) AS d FROM calc_bank b
                      ORDER BY b.geom_5179 <-> a.rep_point_5179 LIMIT 1) k
 WHERE k.d <= 20000;

-- 읍면동: 대표점 기준 판정 (시군구는 하위 합, 읍면동을 계산하지 않았으면 자기 판정)
CREATE TEMP TABLE calc_fin_gap (adm_cd varchar(10), level smallint, pop int, post_near boolean, bank_near boolean)
    ON COMMIT DROP;

INSERT INTO calc_fin_gap
SELECT a.adm_cd, a.level, p.tot_ppltn AS pop,
       (fd.value <= CAST(:far_m AS numeric)) AS post_near,
       (coalesce(bd.value, 1e9) <= CAST(:far_m AS numeric)) AS bank_near
  FROM calc_area a
  JOIN mart.access_metric fd ON fd.calc_run_id = :calc_run_id AND fd.adm_cd = a.adm_cd AND fd.metric_code = 'NEAREST_FIN_DIST_M'
  LEFT JOIN mart.access_metric bd ON bd.calc_run_id = :calc_run_id AND bd.adm_cd = a.adm_cd AND bd.metric_code = 'NEAREST_BANK_DIST_M'
  LEFT JOIN mart.area_population p ON p.adm_cd = a.adm_cd AND p.stat_year = :stat_year
 WHERE EXISTS (SELECT 1 FROM calc_bank)
   AND (a.level = 3 OR NOT EXISTS (SELECT 1 FROM calc_area x WHERE x.level = 3));

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, adm_cd, 'POST_ONLY_PPLTN', level, CASE WHEN post_near AND NOT bank_near THEN coalesce(pop, 0) ELSE 0 END
  FROM calc_fin_gap;

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, adm_cd, 'FIN_DESERT_PPLTN', level, CASE WHEN NOT post_near AND NOT bank_near THEN coalesce(pop, 0) ELSE 0 END
  FROM calc_fin_gap;

INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, m.metric_code, a.level, sum(m.value)
  FROM calc_area a
  JOIN calc_area ch ON ch.level = 3 AND left(ch.adm_cd, 5) = a.adm_cd
  JOIN mart.access_metric m ON m.calc_run_id = :calc_run_id AND m.adm_cd = ch.adm_cd
                           AND m.metric_code IN ('POST_ONLY_PPLTN', 'FIN_DESERT_PPLTN')
 WHERE a.level = 2
 GROUP BY a.adm_cd, a.level, m.metric_code;
