-- V10 — 생활 거점: 약국·병의원(국립중앙의료원) + 영업일 달력(한국천문연구원 특일)
-- 우체국이 동네의 '마지막 생활 거점'(금융·약국·의원 중 유일하게 남은 곳)인지 집계구 단위로 판정하고,
-- 공휴일·연휴에는 창구 휴무를 반영합니다.
ALTER TABLE ops.collect_run DROP CONSTRAINT collect_run_kind_check;
ALTER TABLE ops.collect_run ADD CONSTRAINT collect_run_kind_check
    CHECK (kind IN ('POST_AREA', 'POST_DISCOVER', 'SGIS_POP', 'SGIS_BND', 'KOSIS_POP',
                    'SGIS_OA', 'KAKAO_GEO', 'KAKAO_BANK', 'KAKAO_ROAD', 'KMA_FCST', 'AIR_FCST',
                    'NMC_CARE', 'KASI_HOLIDAY'));
ALTER TABLE raw.api_response DROP CONSTRAINT api_response_source_check;
ALTER TABLE raw.api_response ADD CONSTRAINT api_response_source_check
    CHECK (source IN ('POST_AREA', 'SGIS_AUTH', 'SGIS_POP', 'SGIS_BND', 'KOSIS_META', 'KOSIS_POP',
                      'SGIS_OA_POP', 'SGIS_OA_BND', 'KAKAO_LOCAL', 'KAKAO_NAVI', 'KMA_VILAGE', 'AIR_FCST',
                      'NMC_PHARMACY', 'NMC_HOSPITAL', 'KASI_HOLIDAY'));

-- 약국·의원급 이상 의료기관 (FullData). 진료시간은 요일(1=월 … 7=일)·8=공휴일 별 [시작, 끝] HHMM
CREATE TABLE mart.care_place (
    hpid           varchar(12) PRIMARY KEY,
    kind           varchar(10) NOT NULL CHECK (kind IN ('PHARMACY', 'CLINIC')),
    div            char(1),                     -- 병원분류 A 종합병원 · B 병원 · C 의원 · R 보건소 …, 약국은 NULL
    div_name       varchar(40),
    name           text NOT NULL,
    addr           text,
    hours          jsonb NOT NULL DEFAULT '{}'::jsonb,
    open_holiday   boolean NOT NULL DEFAULT false,
    open_sunday    boolean NOT NULL DEFAULT false,
    geom           geometry(Point, 4326) NOT NULL,
    geom_5179      geometry(Point, 5179) NOT NULL,
    first_seen     timestamptz NOT NULL DEFAULT now(),
    last_seen      timestamptz NOT NULL DEFAULT now(),
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id) ON DELETE SET NULL
);
CREATE INDEX gx_care_pharmacy ON mart.care_place USING gist (geom_5179) WHERE kind = 'PHARMACY';
CREATE INDEX gx_care_clinic ON mart.care_place USING gist (geom_5179) WHERE kind = 'CLINIC';
CREATE INDEX gx_care_holiday ON mart.care_place USING gist (geom_5179) WHERE open_holiday;
CREATE INDEX gx_care_geom ON mart.care_place USING gist (geom);

-- 공공기관 휴일 (특일 정보 getRestDeInfo). 토·일은 요일로 판정하므로 저장하지 않음
CREATE TABLE mart.holiday (
    locdate        date PRIMARY KEY,
    name           text NOT NULL,
    is_holiday     boolean NOT NULL,
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id) ON DELETE SET NULL,
    fetched_at     timestamptz NOT NULL DEFAULT now()
);

-- 집계구별 생활 서비스 거리 — 계산마다 oa_nearest 에 함께 기록(What-if 가 생활 거점 상실을 셈)
ALTER TABLE mart.oa_nearest
    ADD COLUMN post2_m     numeric,   -- 두 번째로 가까운 금융 우체국 (대체 가능성)
    ADD COLUMN bank_m      numeric,
    ADD COLUMN pharmacy_m  numeric,
    ADD COLUMN clinic_m    numeric,
    ADD COLUMN hcare_m     numeric;   -- 공휴일에 여는 약국·의원 중 최근접

-- 우체국별 대체 불가능성 — 이 우체국이 닫히면 2km 안 금융 창구/모든 생활 거점이 사라지는 인구
CREATE TABLE mart.facility_hub (
    calc_run_id      uuid NOT NULL REFERENCES mart.calc_run (calc_run_id) ON DELETE CASCADE,
    hist_id          bigint NOT NULL REFERENCES mart.post_facility_hist (hist_id),
    served_ppltn     int NOT NULL,     -- 이 우체국이 최근접(2km 안)인 집계구 인구
    sole_fin_ppltn   int NOT NULL,     -- 그중 2km 안 다른 금융 우체국·은행 지점이 없는 인구
    sole_hub_ppltn   int NOT NULL,     -- 그중 약국·의원도 없는 인구 (우체국이 마지막 생활 거점)
    oa_count         int NOT NULL,
    PRIMARY KEY (calc_run_id, hist_id)
);
CREATE INDEX ix_facility_hub_rank ON mart.facility_hub (calc_run_id, sole_hub_ppltn DESC);

INSERT INTO mart.metric_def (metric_code, name_ko, unit, formula, limitation, higher_is_worse, sort_order) VALUES
('POPW_PHARMACY_DIST_M', '약국까지 거리 (인구 가중)', 'm',
 '집계구 대표점 → 최근접 약국 직선거리를 집계구 인구로 가중 평균.',
 '국립중앙의료원 약국 FullData 기준. 직선거리.', true, 80),
('POPW_CLINIC_DIST_M', '의원·병원까지 거리 (인구 가중)', 'm',
 '집계구 대표점 → 최근접 의원·병원·종합병원·보건소 직선거리를 인구 가중 평균.',
 '치과·한의원·요양병원 제외. 직선거리.', true, 81),
('CARE_DESERT_PPLTN', '의료 공백 인구', '명',
 '2km 안에 약국도 의원·병원·보건소도 없는 집계구 인구 합.', '직선거리·집계구 대표점 기준.', true, 82),
('POST_SOLE_HUB_PPLTN', '우체국이 마지막 생활 거점인 인구', '명',
 '2km 안 금융 우체국은 있지만 은행 지점·약국·의원이 모두 없는 집계구 인구 합.',
 '⚠ 우체국이 닫히면 2km 안 생활 거점이 모두 사라지는 곳. 직선거리.', true, 83),
('LIFE_DESERT_PPLTN', '생활 서비스 공백 인구', '명',
 '2km 안에 금융 우체국·은행 지점·약국·의원이 하나도 없는 집계구 인구 합.', '직선거리·집계구 대표점 기준.', true, 84),
('HOLIDAY_CARE_GAP_PPLTN', '공휴일 의료 공백 인구', '명',
 '2km 안에 공휴일 진료시간이 등록된 약국·의원이 없는 집계구 인구 합.',
 '⚠ 등록된 공휴일 진료시간 기준(당번 약국·실제 운영과 다를 수 있음).', true, 85);
