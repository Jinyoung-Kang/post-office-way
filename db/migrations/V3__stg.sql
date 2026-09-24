-- V3 — 우체국 시설 정규화 스냅샷 (collect_run 단위)

CREATE TABLE stg.post_facility (
    collect_run_id uuid NOT NULL REFERENCES ops.collect_run (collect_run_id),
    post_id        varchar(20) NOT NULL,
    post_div       smallint,
    name           varchar(100),
    addr           text,
    tel            varchar(30),
    lat            double precision,
    lon            double precision,
    post_time      varchar(40),
    finance_time   varchar(40),
    lunch_yn       char(1),
    lunch_time     varchar(40),
    post365_yn     char(1),
    area_code      varchar(6) NOT NULL,
    mod_dt         date,
    -- 도메인 규칙 결과 (파이썬에서 계산해 단위 테스트로 검증)
    is_center      boolean NOT NULL DEFAULT false,
    fin_available  boolean NOT NULL DEFAULT false,
    row_hash       char(64) NOT NULL,
    PRIMARY KEY (collect_run_id, post_id)
);
CREATE INDEX ix_stg_post_area ON stg.post_facility (collect_run_id, area_code);
