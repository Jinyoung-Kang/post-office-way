-- ① 은행 지점 폐쇄 영향평가 — 은행(시중·지방·특수) 대면 지점마다 '이 지점이 문을 닫으면'.
--   이용 주민 = 이 지점이 가장 가까운 은행 지점인 집계구. 대체 창구 = 다른 은행 지점 + (그 은행이 은행대리업 대상이면) 금융 우체국.
--   새마을금고·저축은행은 공동절차 대상이 아니어서 평가하지 않고 대체 창구에도 넣지 않음(보수적).
--   '잃는 주민'(lost) = 지금은 2km 안에 이 지점이 있는데, 닫히면 2km 안에 대체 창구가 없어지는 주민.
--   이미 2km 밖에 사는 주민은 '새로 잃는' 것이 아니므로 세지 않고, 그 부담은 인구 가중 거리 증가(popw_alt − popw_now)로 봄.
--   집계구가 없으면(mart.oa_area 비어 있음) 이용 주민 0 으로 지점 자체 지표만 남김.

CREATE TEMP TABLE calc_bankx ON COMMIT DROP AS
SELECT b.place_id, b.brand, bb.post_agent, b.geom, b.geom_5179
  FROM mart.bank_branch_current b
  JOIN mart.bank_brand bb ON bb.brand = b.brand AND bb.grp = 'BANK';
CREATE INDEX ON calc_bankx USING gist (geom_5179);
ANALYZE calc_bankx;

-- 집계구별 가장 가까운 은행 지점 2곳 (+ 금융 우체국까지 거리는 06_oa 의 oa_nearest.dist_m).
-- 같은 좌표(같은 건물)의 지점은 id 가 작은 쪽이 1순위 — KNN 은 동률 순서를 정하지 않아 실행마다 이용 주민이 다른 지점으로 갈 수
-- 있었음(R11 이 이 문장에 빠짐). 후보 5곳을 (거리, id)로 정렬하고, 5곳이 모두 같은 거리면(같은 좌표 5곳 이상 — 실데이터 최대 4곳)
-- 그 거리 안에서 다시 찾음. 정렬 키를 KNN 에 넣으면 인덱스를 못 써 120초를 넘겼고, 이 방식은 +6%(4.1 → 4.4초, 집계구 10만 곳)
CREATE TEMP TABLE calc_oa_bank ON COMMIT DROP AS
SELECT n.oa_cd, n.emd_cd, coalesce(n.tot_ppltn, 0) AS pop, n.dist_m AS post_m,
       CASE WHEN k.ds[5] = k.ds[1]
            THEN (SELECT b.place_id FROM calc_bankx b WHERE ST_DWithin(b.geom_5179, o.rep_point_5179, k.ds[1])
                   ORDER BY ST_Distance(b.geom_5179, o.rep_point_5179), b.place_id LIMIT 1)
            ELSE k.ids[1] END AS b1,
       k.ds[1] AS d1, k.ds[2] AS d2
  FROM mart.oa_nearest n
  JOIN mart.oa_area o ON o.oa_cd = n.oa_cd AND o.stat_year = :stat_year
 CROSS JOIN LATERAL (SELECT array_agg(t.place_id ORDER BY t.d, t.place_id) AS ids, array_agg(t.d ORDER BY t.d, t.place_id) AS ds
                       FROM (SELECT b.place_id, ST_Distance(b.geom_5179, o.rep_point_5179) AS d FROM calc_bankx b
                              ORDER BY b.geom_5179 <-> o.rep_point_5179 LIMIT 5) t) k
 WHERE n.calc_run_id = :calc_run_id AND k.ids IS NOT NULL;

-- 집계구 65세 이상 = 인구 × 읍면동 고령 비율(KOSIS 최신 기준월) — 추정
CREATE TEMP TABLE calc_oa_bank2 ON COMMIT DROP AS
SELECT ob.*, x.post_agent,
       least(ob.d2, CASE WHEN x.post_agent THEN ob.post_m END) AS alt,
       round(ob.pop * r.aged65_ratio / 100) AS aged
  FROM calc_oa_bank ob
  JOIN calc_bankx x ON x.place_id = ob.b1
  LEFT JOIN LATERAL (SELECT aged65_ratio FROM mart.area_resident_pop
                      WHERE adm_cd = ob.emd_cd AND stat_year = :stat_year ORDER BY ref_period DESC LIMIT 1) r ON true;

INSERT INTO mart.oa_bank (calc_run_id, oa_cd, b1, d1, alt_m, aged)
SELECT :calc_run_id, oa_cd, b1, d1, alt, aged FROM calc_oa_bank2;

-- 요인·등급·순위까지 INSERT 한 번에 — 넣은 뒤 UPDATE 로 순위를 매기면 같은 트랜잭션의 새 행이 통계에 없어
-- 계획이 어긋나 12초 걸렸음(따로 돌리면 0.07초). 계산 순서: 지점별 집계(s) → 요인(r) → 등급·순위
INSERT INTO mart.bank_impact (calc_run_id, place_id, brand, post_agent, adm_cd, emd_cd, catch_oa, catch_ppltn, catch_aged,
                              same_brand_m, other_bank_m, post_m, popw_now_m, popw_alt_m, lost_ppltn, lost_aged,
                              grade, reasons, rnk, n)
SELECT :calc_run_id, place_id, brand, post_agent, adm_cd, emd_cd, catch_oa, catch_ppltn, catch_aged,
       same_brand_m, other_bank_m, post_m, popw_now_m, popw_alt_m, lost_ppltn, lost_aged,
       mart.bank_impact_grade(lost_ppltn, reasons), reasons,
       rank() OVER (ORDER BY lost_ppltn DESC, catch_ppltn DESC), count(*) OVER ()
  FROM (
    SELECT s.*, mart.bank_impact_reasons(s.lost_ppltn, s.same_brand_m, s.catch_aged, s.catch_ppltn, NULL) AS reasons
      FROM (
        SELECT x.place_id, x.brand, x.post_agent,
               -- 소속 지역은 우체국(01_facility_area_map)과 같은 규칙: 폴리곤 안(경계 위면 코드가 작은 쪽, R11), 없으면 :snap_m 안
               -- 최근접 지역. 예전에는 폴리곤 안만 봐서 해안선 단순화로 밖에 떨어진 지점의 지역이 비었음(경계 밖 16m 의 HIGH 지점)
               coalesce((SELECT a.adm_cd FROM calc_area_sub a WHERE a.level = 2 AND ST_Intersects(a.geom, x.geom)
                          ORDER BY a.adm_cd LIMIT 1),
                        (SELECT a.adm_cd FROM calc_area a WHERE a.level = 2
                            AND ST_DWithin(a.geom_5179, x.geom_5179, CAST(:snap_m AS float8))
                          ORDER BY a.geom_5179 <-> x.geom_5179, a.adm_cd LIMIT 1)) AS adm_cd,
               coalesce((SELECT a.adm_cd FROM calc_area_sub a WHERE a.level = 3 AND ST_Intersects(a.geom, x.geom)
                          ORDER BY a.adm_cd LIMIT 1),
                        (SELECT a.adm_cd FROM calc_area a WHERE a.level = 3
                            AND ST_DWithin(a.geom_5179, x.geom_5179, CAST(:snap_m AS float8))
                          ORDER BY a.geom_5179 <-> x.geom_5179, a.adm_cd LIMIT 1)) AS emd_cd,
               coalesce(c.catch_oa, 0) AS catch_oa, CAST(coalesce(c.pop, 0) AS int) AS catch_ppltn, CAST(c.aged AS int) AS catch_aged,
               (SELECT round(CAST(ST_Distance(y.geom_5179, x.geom_5179) AS numeric)) FROM calc_bankx y
                 WHERE y.brand = x.brand AND y.place_id <> x.place_id ORDER BY y.geom_5179 <-> x.geom_5179 LIMIT 1) AS same_brand_m,
               (SELECT round(CAST(ST_Distance(y.geom_5179, x.geom_5179) AS numeric)) FROM calc_bankx y
                 WHERE y.brand <> x.brand ORDER BY y.geom_5179 <-> x.geom_5179 LIMIT 1) AS other_bank_m,
               (SELECT round(CAST(ST_Distance(f.geom_5179, x.geom_5179) AS numeric)) FROM calc_fin f
                 ORDER BY f.geom_5179 <-> x.geom_5179 LIMIT 1) AS post_m,
               round(CAST(c.popw_now AS numeric)) AS popw_now_m, round(CAST(c.popw_alt AS numeric)) AS popw_alt_m,
               CAST(coalesce(c.lost, 0) AS int) AS lost_ppltn, CAST(c.lost_aged AS int) AS lost_aged
          FROM calc_bankx x
          LEFT JOIN (SELECT b1 AS place_id, count(*) AS catch_oa, sum(pop) AS pop, sum(aged) AS aged,
                            sum(pop * d1) / nullif(sum(pop), 0) AS popw_now,
                            sum(pop * alt) FILTER (WHERE alt IS NOT NULL) / nullif(sum(pop) FILTER (WHERE alt IS NOT NULL), 0) AS popw_alt,
                            sum(pop) FILTER (WHERE d1 <= CAST(:far_m AS float8) AND coalesce(alt, 1e9) > CAST(:far_m AS float8)) AS lost,
                            sum(aged) FILTER (WHERE d1 <= CAST(:far_m AS float8) AND coalesce(alt, 1e9) > CAST(:far_m AS float8)) AS lost_aged
                       FROM calc_oa_bank2 GROUP BY b1) c ON c.place_id = x.place_id) s) r;
