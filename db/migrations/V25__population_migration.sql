-- V25 — 행정안전부 지역별 인구이동(1741000/ppltnDataStus) · 인구 추세 지표 2개 (ADR-028)
--   행안부는 시군구 단위로 주되 일반구가 있는 시(수원시 장안구 등)는 시 하나로 묶어 줍니다(lv=2).
--   그래서 원천 단위 그대로 월별 합계를 두고(mart.migration_month), SGIS 시군구와의 대응은 경계 연도별 표로 따로 둡니다.

ALTER TABLE ops.collect_run DROP CONSTRAINT collect_run_kind_check;
ALTER TABLE ops.collect_run ADD CONSTRAINT collect_run_kind_check CHECK (kind IN (
    'POST_AREA', 'POST_DISCOVER', 'SGIS_POP', 'SGIS_BND', 'KOSIS_POP', 'SGIS_OA', 'KAKAO_GEO', 'KAKAO_BANK',
    'KAKAO_ROAD', 'KMA_FCST', 'AIR_FCST', 'NMC_CARE', 'KASI_HOLIDAY', 'OSM_WALK', 'MOIS_MIGR'));

ALTER TABLE raw.api_response DROP CONSTRAINT api_response_source_check;
ALTER TABLE raw.api_response ADD CONSTRAINT api_response_source_check CHECK (source IN (
    'POST_AREA', 'SGIS_AUTH', 'SGIS_POP', 'SGIS_BND', 'KOSIS_META', 'KOSIS_POP', 'SGIS_OA_POP', 'SGIS_OA_BND',
    'KAKAO_LOCAL', 'KAKAO_NAVI', 'KMA_VILAGE', 'AIR_FCST', 'NMC_PHARMACY', 'NMC_HOSPITAL', 'KASI_HOLIDAY', 'MOIS_MIGR'));

-- 행안부 시군구 단위 × 달. 한 달은 전국→전국 행렬을 모두 받았을 때만 통째로 넣음(일부만 받으면 합이 틀림)
CREATE TABLE mart.migration_month (
    mois_cd        varchar(10) NOT NULL CHECK (mois_cd ~ '^[0-9]{10}$'),   -- 행정기관코드 (시군구 단위)
    ref_ym         char(6) NOT NULL CHECK (ref_ym ~ '^[0-9]{4}(0[1-9]|1[0-2])$'),
    ctpv_nm        text NOT NULL,
    sgg_nm         text NOT NULL,
    in_cnt         int NOT NULL,          -- 다른 시군구 단위에서 전입
    out_cnt        int NOT NULL,          -- 다른 시군구 단위로 전출
    in_aged65      int NOT NULL,          -- 그중 만 65세 이상
    out_aged65     int NOT NULL,
    intra_cnt      int NOT NULL,          -- 같은 단위 안 이동 — 지표에서 빼고 검증용으로만
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id),
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (mois_cd, ref_ym)
);
CREATE INDEX ix_migration_month_ym ON mart.migration_month (ref_ym);

-- SGIS 시군구(경계 연도별) → 행안부 시군구 단위. KOSIS_CD: 주민등록인구 대응의 KOSIS 코드(같은 행안부 체계),
-- NAME: 시도·시군구 이름, CITY: 일반구 → 그 시(시 전체 값을 씀)
CREATE TABLE mart.area_migration_map (
    stat_year      smallint NOT NULL,
    adm_cd         varchar(10) NOT NULL,
    mois_cd        varchar(10) NOT NULL,
    match_method   varchar(10) NOT NULL CHECK (match_method IN ('KOSIS_CD', 'NAME', 'CITY')),
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id),
    PRIMARY KEY (stat_year, adm_cd)
);
CREATE INDEX ix_area_migration_map_unit ON mart.area_migration_map (stat_year, mois_cd);

GRANT SELECT ON mart.migration_month, mart.area_migration_map TO atlas_api;

INSERT INTO mart.metric_def (metric_code, name_ko, unit, formula, limitation, higher_is_worse, sort_order) VALUES
 ('NET_OUT_12M_PER_1K', '12개월 순유출(천 명당)', '‰',
  '(다른 시군구로 전출 − 다른 시군구에서 전입) 최근 12개월 합 ÷ 주민등록 인구(KOSIS) × 1,000. 행정안전부 지역별 인구이동(주민등록 전입신고 기준).',
  '시군구 사이 이동만 셈(같은 시군구 안 이동 제외). 일반구가 있는 시는 원천이 시 단위라 구마다 시 전체 값. 최근 12개월이 다 모이지 않았거나 행정구역이 바뀐 지역은 값 없음. 공식 통계가 아님.',
  true, 90),
 ('AGED65_NET_IN_12M_PER_1K', '65세 이상 12개월 순유입(천 명당)', '‰',
  '(만 65세 이상 전입 − 전출) 최근 12개월 합 ÷ 65세 이상 주민등록 인구(KOSIS) × 1,000. 시군구 사이 이동만.',
  '주민등록 기준이라 실제 거주 이동과 다를 수 있음(거주불명자·재외국민 포함). 일반구가 있는 시는 시 전체 값. 공식 통계가 아님.',
  false, 91)
ON CONFLICT (metric_code) DO NOTHING;
