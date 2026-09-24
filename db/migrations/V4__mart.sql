-- V4 — 분석 영역
-- 저장은 EPSG:4326, 거리·반경은 EPSG:5179(미터) 컬럼으로 계산 (ADR-002, NFR-04)

-- 시설 이력 (SCD Type 2) --------------------------------------------------------
CREATE TABLE mart.post_facility_hist (
    hist_id       bigserial PRIMARY KEY,
    post_id       varchar(20) NOT NULL,
    post_div      smallint,
    name          varchar(100),
    addr          text,
    tel           varchar(30),
    geom          geometry(Point, 4326) NOT NULL,
    geom_5179     geometry(Point, 5179) NOT NULL,
    post_time     varchar(40),
    finance_time  varchar(40),
    fin_available boolean NOT NULL,
    lunch_yn      char(1),
    lunch_time    varchar(40),
    post365_yn    char(1),
    area_code     varchar(6),
    is_center     boolean NOT NULL DEFAULT false,
    mod_dt        date,
    row_hash      char(64) NOT NULL,
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id),
    valid_from    timestamptz NOT NULL,
    valid_to      timestamptz,
    is_current    boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX ux_hist_current_post ON mart.post_facility_hist (post_id) WHERE is_current;
CREATE INDEX gx_hist_geom_current ON mart.post_facility_hist USING gist (geom) WHERE is_current;
CREATE INDEX gx_hist_geom5179 ON mart.post_facility_hist USING gist (geom_5179);
CREATE INDEX ix_hist_area_code ON mart.post_facility_hist (area_code);
CREATE INDEX ix_hist_validity ON mart.post_facility_hist (valid_from, valid_to);
CREATE INDEX ix_hist_name_trgm ON mart.post_facility_hist (name);

-- 행정구역 경계 / 인구 ----------------------------------------------------------
CREATE TABLE mart.admin_area (
    adm_cd         varchar(10) NOT NULL,
    stat_year      smallint NOT NULL,
    adm_nm         varchar(100) NOT NULL,
    level          smallint NOT NULL CHECK (level BETWEEN 1 AND 3),
    parent_cd      varchar(10),
    geom           geometry(MultiPolygon, 4326) NOT NULL,
    geom_5179      geometry(MultiPolygon, 5179) NOT NULL,
    -- 지도용 단순화 지오메트리 (level2=200m, level3=50m 허용오차)
    geom_simple    geometry(MultiPolygon, 4326),
    rep_point      geometry(Point, 4326) NOT NULL,
    rep_point_5179 geometry(Point, 5179) NOT NULL,
    src_crs        varchar(12),
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id),
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (adm_cd, stat_year)
);
CREATE INDEX gx_area_geom ON mart.admin_area USING gist (geom);
CREATE INDEX gx_area_geom5179 ON mart.admin_area USING gist (geom_5179);
CREATE INDEX ix_area_level ON mart.admin_area (stat_year, level, adm_cd);

CREATE TABLE mart.area_population (
    adm_cd         varchar(10) NOT NULL,
    stat_year      smallint NOT NULL,
    adm_nm         varchar(100),
    tot_ppltn      int,
    ppltn_dnsty    numeric,
    aged_child_idx numeric,
    avg_age        numeric,
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id),
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (adm_cd, stat_year)
);

-- 시설 ↔ 행정구역 매핑 (공간 조인, ADR-001) ---------------------------------------
CREATE TABLE mart.facility_area_map (
    hist_id    bigint NOT NULL REFERENCES mart.post_facility_hist (hist_id),
    stat_year  smallint NOT NULL,
    level      smallint NOT NULL,
    adm_cd     varchar(10) NOT NULL,
    method     varchar(10) NOT NULL CHECK (method IN ('CONTAINS', 'NEAREST')),
    matched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hist_id, stat_year, level)
);
CREATE INDEX ix_fam_area ON mart.facility_area_map (stat_year, adm_cd);

-- 계산 실행 · 지표 ---------------------------------------------------------------
CREATE TABLE mart.calc_run (
    calc_run_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    stat_year      smallint NOT NULL,
    facility_as_of timestamptz NOT NULL,
    -- {radiusKm:[1,2,5], weights:{dist:0.6, aged:0.4}, levels:[2,3], ruleVersion}
    params         jsonb NOT NULL,
    status         varchar(12) NOT NULL CHECK (status IN ('RUNNING', 'DONE', 'FAILED')),
    stats          jsonb NOT NULL DEFAULT '{}'::jsonb,
    error          text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz
);
CREATE INDEX ix_calc_run_created ON mart.calc_run (status, created_at DESC);

ALTER TABLE ops.dq_issue
    ADD CONSTRAINT fk_dq_issue_calc FOREIGN KEY (calc_run_id) REFERENCES mart.calc_run (calc_run_id);
ALTER TABLE ops.dq_check
    ADD CONSTRAINT fk_dq_check_calc FOREIGN KEY (calc_run_id) REFERENCES mart.calc_run (calc_run_id);

CREATE TABLE mart.metric_def (
    metric_code     varchar(30) PRIMARY KEY,
    name_ko         varchar(60) NOT NULL,
    unit            varchar(10) NOT NULL,
    formula         text NOT NULL,
    limitation      text,
    higher_is_worse boolean NOT NULL,
    rule_version    varchar(10) NOT NULL DEFAULT 'v1',
    sort_order      smallint NOT NULL DEFAULT 0
);

CREATE TABLE mart.access_metric (
    calc_run_id uuid NOT NULL REFERENCES mart.calc_run (calc_run_id) ON DELETE CASCADE,
    adm_cd      varchar(10) NOT NULL,
    metric_code varchar(30) NOT NULL REFERENCES mart.metric_def (metric_code),
    level       smallint NOT NULL,
    value       numeric,
    PRIMARY KEY (calc_run_id, adm_cd, metric_code)
);
CREATE INDEX ix_access_metric_lookup ON mart.access_metric (calc_run_id, metric_code, level);

CREATE TABLE mart.area_nearest (
    calc_run_id uuid NOT NULL REFERENCES mart.calc_run (calc_run_id) ON DELETE CASCADE,
    adm_cd      varchar(10) NOT NULL,
    rank        smallint NOT NULL CHECK (rank BETWEEN 1 AND 3),
    hist_id     bigint NOT NULL REFERENCES mart.post_facility_hist (hist_id),
    dist_m      numeric NOT NULL,
    PRIMARY KEY (calc_run_id, adm_cd, rank)
);
CREATE INDEX ix_area_nearest_hist ON mart.area_nearest (calc_run_id, hist_id) WHERE rank = 1;

-- What-if -------------------------------------------------------------------------
CREATE TABLE mart.whatif_scenario (
    scenario_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    calc_run_id      uuid NOT NULL REFERENCES mart.calc_run (calc_run_id) ON DELETE CASCADE,
    level            smallint NOT NULL,
    removed_hist_ids bigint[] NOT NULL,   -- 정렬 후 저장 (멱등 키)
    status           varchar(12) NOT NULL DEFAULT 'DONE',
    summary          jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (calc_run_id, level, removed_hist_ids)
);

CREATE TABLE mart.whatif_result (
    scenario_id         uuid NOT NULL REFERENCES mart.whatif_scenario (scenario_id) ON DELETE CASCADE,
    adm_cd              varchar(10) NOT NULL,
    affected_ppltn      int,
    dist_before_m       numeric,
    dist_after_m        numeric,
    new_nearest_hist_id bigint REFERENCES mart.post_facility_hist (hist_id),
    PRIMARY KEY (scenario_id, adm_cd)
);
