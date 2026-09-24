-- 계산 입력 스냅샷 — facility_as_of 시점에 유효했던 시설 + 대상 연도·레벨 행정구역.
-- 같은 calc_run 입력이면 같은 결과가 나오도록(NFR-03) 이력 테이블을 시점으로 자릅니다.
-- (psycopg 서버측 바인딩은 DDL 에 파라미터를 못 쓰므로 CREATE 후 INSERT)

CREATE TEMP TABLE calc_fac (
    hist_id bigint PRIMARY KEY, post_div smallint, geom geometry(Point, 4326),
    geom_5179 geometry(Point, 5179), fin_available boolean, is_center boolean,
    post365_yn char(1), lunch_yn char(1)
) ON COMMIT DROP;

INSERT INTO calc_fac
SELECT hist_id, post_div, geom, geom_5179, fin_available, is_center, post365_yn, lunch_yn
  FROM mart.post_facility_hist
 WHERE valid_from <= :as_of AND (valid_to IS NULL OR valid_to > :as_of);

CREATE INDEX ON calc_fac USING gist (geom);
CREATE INDEX ON calc_fac USING gist (geom_5179);
CREATE INDEX ON calc_fac (hist_id) WHERE fin_available AND NOT is_center;
ANALYZE calc_fac;

CREATE TEMP TABLE calc_area (
    adm_cd varchar(10) PRIMARY KEY, level smallint, geom geometry(MultiPolygon, 4326),
    geom_5179 geometry(MultiPolygon, 5179), rep_point_5179 geometry(Point, 5179)
) ON COMMIT DROP;

INSERT INTO calc_area
SELECT adm_cd, level, geom, geom_5179, rep_point_5179
  FROM mart.admin_area
 WHERE stat_year = :stat_year AND level = ANY(CAST(:levels AS smallint[]));

CREATE INDEX ON calc_area USING gist (geom);
CREATE INDEX ON calc_area USING gist (geom_5179);
ANALYZE calc_area;

-- 점-폴리곤 판정용 잘게 나눈 폴리곤 (SGIS 경계는 원본 해상도라 시군구 하나가 5만 점까지 있음).
-- ST_Subdivide 로 128점 이하 조각으로 나누면 공간 조인이 434초 → 1초 미만 (실측 2026-09-24)
CREATE TEMP TABLE calc_area_sub (adm_cd varchar(10), level smallint, geom geometry) ON COMMIT DROP;

INSERT INTO calc_area_sub SELECT adm_cd, level, ST_Subdivide(geom, 128) FROM calc_area;

CREATE INDEX ON calc_area_sub USING gist (geom);
ANALYZE calc_area_sub;

-- 금융 가능 시설만 모은 KNN 전용 테이블
CREATE TEMP TABLE calc_fin ON COMMIT DROP AS
SELECT hist_id, geom_5179 FROM calc_fac WHERE fin_available AND NOT is_center;

CREATE INDEX ON calc_fin USING gist (geom_5179);
ANALYZE calc_fin;
