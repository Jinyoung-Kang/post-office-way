-- V6 — KOSIS 주민등록인구(행정안전부, DT_1B04005N) 적재 · 고령인구 지표 · 검색 인덱스
--   SGIS 주요지표에는 고령 인구 '수'가 없어(노령화지수만) FR-205 를 KOSIS 로 채웁니다.

ALTER TABLE ops.collect_run DROP CONSTRAINT collect_run_kind_check;
ALTER TABLE ops.collect_run ADD CONSTRAINT collect_run_kind_check
    CHECK (kind IN ('POST_AREA', 'POST_DISCOVER', 'SGIS_POP', 'SGIS_BND', 'KOSIS_POP'));

ALTER TABLE raw.api_response DROP CONSTRAINT api_response_source_check;
ALTER TABLE raw.api_response ADD CONSTRAINT api_response_source_check
    CHECK (source IN ('POST_AREA', 'SGIS_AUTH', 'SGIS_POP', 'SGIS_BND', 'KOSIS_META', 'KOSIS_POP'));

-- SGIS 행정구역(adm_cd) 기준으로 맞춘 주민등록인구. KOSIS 지역코드(행안부 코드)는 이름으로 매칭(match_method)
CREATE TABLE mart.area_resident_pop (
    adm_cd         varchar(10) NOT NULL,
    stat_year      smallint NOT NULL,
    ref_period     varchar(6) NOT NULL,          -- KOSIS 수록시점 YYYYMM
    tot_ppltn      int,
    aged65_ppltn   int,
    aged65_ratio   numeric,
    kosis_cd       varchar(12),
    kosis_nm       text,
    match_method   varchar(12) NOT NULL CHECK (match_method IN ('NAME', 'SINGLE', 'CHILD_SUM')),
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id),
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (adm_cd, stat_year)
);

ALTER TABLE mart.whatif_result ADD COLUMN affected_aged65 int;

INSERT INTO mart.metric_def (metric_code, name_ko, unit, formula, limitation, higher_is_worse, sort_order) VALUES
('AGED65_PPLTN', '65세 이상 인구', '명',
 'KOSIS 주민등록인구(행정안전부, DT_1B04005N) 65세 이상 5세 구간 합. 기준월은 calc 시점의 적재분.',
 '주민등록 기준(실거주와 다를 수 있음). 행정구역 이름 매칭 실패 지역은 값 없음.', true, 60),
('AGED65_RATIO', '고령인구 비율', '%',
 '65세 이상 주민등록인구 ÷ 총 주민등록인구 × 100.',
 '주민등록 기준. 인구가 적은 지역은 변동이 큼.', true, 61),
('AGED65_FAR_PPLTN', '금융 우체국 2km 밖 고령인구', '명',
 '읍면동: 최근접 금융 가능 우체국 거리가 2km 를 넘으면 그 읍면동의 65세 이상 인구, 아니면 0. 시군구: 하위 읍면동 합.',
 '⚠ 읍면동 대표점 1개로 판정한 추정치(읍면동 안 거주 분포 미반영). 거리 기준은 params.farKm.', true, 62);

-- 시설 이름 검색(What-if 검색창) — 부분 일치용 trigram 인덱스 (V4 의 같은 이름 btree 는 LIKE '%x%' 에 쓰이지 않음)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
DROP INDEX IF EXISTS mart.ix_hist_name_trgm;
CREATE INDEX ix_hist_name_trgm ON mart.post_facility_hist USING gin (name gin_trgm_ops) WHERE is_current;
