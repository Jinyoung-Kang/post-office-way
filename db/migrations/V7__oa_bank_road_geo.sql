-- V7 — 고도화: ① 집계구 인구 ② 도로 거리 ③ 주소 좌표 검증 ④ 금융 공백(은행 지점)
ALTER TABLE ops.collect_run DROP CONSTRAINT collect_run_kind_check;
ALTER TABLE ops.collect_run ADD CONSTRAINT collect_run_kind_check
    CHECK (kind IN ('POST_AREA', 'POST_DISCOVER', 'SGIS_POP', 'SGIS_BND', 'KOSIS_POP',
                    'SGIS_OA', 'KAKAO_GEO', 'KAKAO_BANK', 'KAKAO_ROAD'));
ALTER TABLE raw.api_response DROP CONSTRAINT api_response_source_check;
ALTER TABLE raw.api_response ADD CONSTRAINT api_response_source_check
    CHECK (source IN ('POST_AREA', 'SGIS_AUTH', 'SGIS_POP', 'SGIS_BND', 'KOSIS_META', 'KOSIS_POP',
                      'SGIS_OA_POP', 'SGIS_OA_BND', 'KAKAO_LOCAL', 'KAKAO_NAVI'));

-- ① 집계구(SGIS 통계 최소 단위, 평균 약 500명) — 인구와 경계를 따로 적재해 oa_cd 로 합침
CREATE TABLE mart.oa_area (
    oa_cd          varchar(16) NOT NULL,
    stat_year      smallint NOT NULL,
    emd_cd         varchar(10) NOT NULL,          -- 상위 읍면동(SGIS adm_cd 8자리)
    tot_ppltn      int,
    geom_5179      geometry(MultiPolygon, 5179),  -- 5m 단순화
    rep_point_5179 geometry(Point, 5179),
    pop_run_id     uuid REFERENCES ops.collect_run (collect_run_id),
    bnd_run_id     uuid REFERENCES ops.collect_run (collect_run_id),
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (oa_cd, stat_year)
);
CREATE INDEX ix_oa_emd ON mart.oa_area (stat_year, emd_cd);
CREATE INDEX gx_oa_rep ON mart.oa_area USING gist (rep_point_5179);

-- 계산 run 별 집계구 최근접(1순위) — What-if 가 집계구 단위로 '새로 2km 밖'이 되는 인구를 셈
CREATE TABLE mart.oa_nearest (
    calc_run_id uuid NOT NULL REFERENCES mart.calc_run (calc_run_id) ON DELETE CASCADE,
    oa_cd       varchar(16) NOT NULL,
    emd_cd      varchar(10) NOT NULL,
    hist_id     bigint REFERENCES mart.post_facility_hist (hist_id),
    dist_m      numeric,
    tot_ppltn   int,
    PRIMARY KEY (calc_run_id, oa_cd)
);
CREATE INDEX ix_oa_nearest_hist ON mart.oa_nearest (calc_run_id, hist_id);

-- ② 도로 거리 캐시 (카카오모빌리티 자동차 길찾기) — (지역 대표점, 시설) 쌍. 시설 이력행 좌표는 불변이라 재사용
CREATE TABLE mart.area_road (
    adm_cd     varchar(10) NOT NULL,
    stat_year  smallint NOT NULL,
    hist_id    bigint NOT NULL REFERENCES mart.post_facility_hist (hist_id),
    road_m     int,
    drive_s    int,
    status     varchar(12) NOT NULL CHECK (status IN ('OK', 'NO_ROUTE', 'ERROR')),
    detail     text,
    checked_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (adm_cd, stat_year, hist_id)
);

-- ③ 주소 → 좌표 캐시 · 시설 좌표 검증
CREATE TABLE mart.geocode_cache (
    addr         text PRIMARY KEY,
    lat          double precision,
    lon          double precision,
    matched_addr text,
    status       varchar(12) NOT NULL CHECK (status IN ('OK', 'NOT_FOUND', 'ERROR')),
    fetched_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE mart.facility_geocheck (
    post_id    varchar(20) PRIMARY KEY,
    row_hash   char(64) NOT NULL,                 -- 시설 정보가 바뀌면 다시 검사
    addr_lat   double precision,
    addr_lon   double precision,
    dist_m     numeric,                           -- API 좌표 ↔ 주소 좌표 거리
    status     varchar(12) NOT NULL CHECK (status IN ('OK', 'MISMATCH', 'NOT_FOUND', 'NO_ADDR')),
    checked_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE stg.post_facility ADD COLUMN coord_source varchar(10) NOT NULL DEFAULT 'API';
ALTER TABLE mart.post_facility_hist ADD COLUMN coord_source varchar(10) NOT NULL DEFAULT 'API';

-- ④ 은행·금고 지점 (카카오 로컬 BK9 범주). ATM·우체국 관련 장소는 kind 로 구분·제외
CREATE TABLE mart.bank_place (
    place_id       varchar(20) PRIMARY KEY,
    name           text NOT NULL,
    category       text,
    kind           varchar(8) NOT NULL CHECK (kind IN ('BRANCH', 'ATM')),
    addr           text,
    geom           geometry(Point, 4326) NOT NULL,
    geom_5179      geometry(Point, 5179) NOT NULL,
    first_seen     timestamptz NOT NULL DEFAULT now(),
    last_seen      timestamptz NOT NULL DEFAULT now(),
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id)
);
CREATE INDEX gx_bank_geom ON mart.bank_place USING gist (geom);
CREATE INDEX gx_bank_geom5179 ON mart.bank_place USING gist (geom_5179) WHERE kind = 'BRANCH';

ALTER TABLE mart.whatif_result ADD COLUMN nearest_bank_m numeric;

INSERT INTO mart.metric_def (metric_code, name_ko, unit, formula, limitation, higher_is_worse, sort_order) VALUES
('POPW_FIN_DIST_M', '인구 가중 최근접 거리 (집계구)', 'm',
 '지역 안 집계구마다 대표점 → 최근접 금융 가능 우체국 거리를 구해 집계구 인구로 가중 평균.',
 '직선거리. 집계구(평균 약 500명) 대표점 기준이라 읍면동 대표점 1개보다 거주 분포를 잘 반영.', true, 11),
('FAR2KM_PPLTN', '2km 밖 인구 (집계구)', '명',
 '최근접 금융 가능 우체국까지 2km 를 넘는 집계구의 인구 합.', '직선거리 기준. 거리 기준은 params.farKm.', true, 12),
('FAR2KM_SHARE', '2km 밖 인구 비율 (집계구)', '%',
 'FAR2KM_PPLTN ÷ 지역 집계구 인구 합 × 100.', '인구가 적은 지역은 변동이 큼.', true, 13),
('NEAREST_FIN_ROAD_M', '최근접 우체국 도로 거리', 'm',
 '지역 대표점 → 직선거리 상위 2개 금융 가능 우체국까지 카카오모빌리티 자동차 경로 중 짧은 쪽.',
 '⚠ 자동차 경로(도보·대중교통 아님). 후보를 직선 상위 2곳으로 한정. 호출 예산 안에서 채워짐.', true, 14),
('NEAREST_FIN_DRIVE_MIN', '최근접 우체국 차량 이동 시간', '분',
 'NEAREST_FIN_ROAD_M 경로의 예상 소요 시간(분).', '⚠ 조회 시점 교통 상황 반영.', true, 15),
('NEAREST_BANK_DIST_M', '최근접 은행·금고 지점 거리', 'm',
 '지역 대표점 → 카카오 로컬 은행 범주(BK9) 지점(ATM·우체국 제외) 최근접 직선거리.',
 '카카오 장소 데이터 기준(폐점 반영 지연 가능). 20km 안에서 찾은 지점만.', true, 70),
('POST_ONLY_PPLTN', '우체국만 있는 인구', '명',
 '읍면동: 2km 안에 금융 가능 우체국은 있지만 은행·금고 지점은 없으면 그 인구. 시군구: 하위 합.',
 '⚠ 읍면동 대표점 기준 추정. 우체국이 유일한 대면 금융 창구인 지역.', true, 71),
('FIN_DESERT_PPLTN', '금융 공백 인구', '명',
 '읍면동: 2km 안에 금융 가능 우체국도, 은행·금고 지점도 없으면 그 인구. 시군구: 하위 합.',
 '⚠ 읍면동 대표점 기준 추정.', true, 72);
