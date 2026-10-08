-- V19 — 집계구별 가장 가까운 은행 지점과 '그 지점이 닫히면' 대체 창구까지 거리 (calc_run 마다, calc/11_bank_impact.sql).
--   은행 지점 영향평가 화면의 '이용 주민' 지도·지역 보고서가 지점마다 다시 KNN 하지 않고 이 표를 읽음.
CREATE TABLE mart.oa_bank (
    calc_run_id uuid NOT NULL REFERENCES mart.calc_run (calc_run_id) ON DELETE CASCADE,
    oa_cd       varchar(16) NOT NULL,
    b1          varchar(20) NOT NULL,       -- 가장 가까운 은행(시중·지방·특수) 지점
    d1          real NOT NULL,              -- 그 지점까지 직선거리(m)
    alt_m       real,                       -- 그 지점이 닫히면 가장 가까운 대체 창구(다른 은행 지점 또는 은행대리업 우체국)
    aged        real,                       -- 65세 이상 추정(읍면동 고령 비율 × 인구)
    PRIMARY KEY (calc_run_id, oa_cd)
);
CREATE INDEX ix_oa_bank_b1 ON mart.oa_bank (calc_run_id, b1);
GRANT SELECT ON mart.oa_bank TO atlas_api;
