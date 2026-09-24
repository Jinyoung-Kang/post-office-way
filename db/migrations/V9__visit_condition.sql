-- V9 — 오늘의 방문 여건: 기상청 단기예보(시군구 대표점 격자) + 에어코리아 미세먼지 예보(권역)
-- 정적 접근성 지표(거리·인구)에 '오늘·내일 창구까지 가기 어려운 날씨·대기'라는 시간 축을 더합니다.
ALTER TABLE ops.collect_run DROP CONSTRAINT collect_run_kind_check;
ALTER TABLE ops.collect_run ADD CONSTRAINT collect_run_kind_check
    CHECK (kind IN ('POST_AREA', 'POST_DISCOVER', 'SGIS_POP', 'SGIS_BND', 'KOSIS_POP',
                    'SGIS_OA', 'KAKAO_GEO', 'KAKAO_BANK', 'KAKAO_ROAD', 'KMA_FCST', 'AIR_FCST'));
ALTER TABLE raw.api_response DROP CONSTRAINT api_response_source_check;
ALTER TABLE raw.api_response ADD CONSTRAINT api_response_source_check
    CHECK (source IN ('POST_AREA', 'SGIS_AUTH', 'SGIS_POP', 'SGIS_BND', 'KOSIS_META', 'KOSIS_POP',
                      'SGIS_OA_POP', 'SGIS_OA_BND', 'KAKAO_LOCAL', 'KAKAO_NAVI', 'KMA_VILAGE', 'AIR_FCST'));

-- 시군구 → 기상청 5km 격자(nx, ny). 대표점이 바뀌면(경계 연도 변경) 다시 계산
CREATE TABLE mart.area_grid (
    adm_cd    varchar(10) NOT NULL,
    stat_year smallint NOT NULL,
    nx        smallint NOT NULL,
    ny        smallint NOT NULL,
    PRIMARY KEY (adm_cd, stat_year)
);

-- 격자별 시간 예보 — 같은 시각은 더 최근 발표로 덮어씀(지난 시각은 마지막 예보가 남음)
CREATE TABLE mart.weather_hourly (
    nx             smallint NOT NULL,
    ny             smallint NOT NULL,
    fcst_at        timestamp NOT NULL,          -- 한국 표준시(KST) 벽시계 시각
    base_at        timestamp NOT NULL,          -- 발표 시각 (KST)
    tmp            numeric,                     -- 기온 ℃
    pop            smallint,                    -- 강수확률 %
    pty            smallint,                    -- 강수형태 0 없음 1 비 2 비/눈 3 눈 4 소나기
    pcp_mm         numeric,                     -- 1시간 강수량 (구간 하한)
    sno_cm         numeric,                     -- 1시간 신적설 (구간 하한)
    wsd            numeric,                     -- 풍속 m/s
    sky            smallint,                    -- 하늘 1 맑음 3 구름많음 4 흐림
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id) ON DELETE SET NULL,
    PRIMARY KEY (nx, ny, fcst_at)
);
CREATE INDEX ix_weather_hourly_at ON mart.weather_hourly (fcst_at);

-- 미세먼지·초미세먼지 예보 (권역 등급) — 같은 예보일은 가장 최근 발표만
CREATE TABLE mart.air_forecast (
    inform_date    date NOT NULL,
    inform_code    varchar(4) NOT NULL CHECK (inform_code IN ('PM10', 'PM25')),
    region         varchar(10) NOT NULL,        -- 서울·경기북부·영동 …
    grade          varchar(8),                  -- 좋음·보통·나쁨·매우나쁨
    announced_at   timestamp NOT NULL,          -- 발표 시각 (KST)
    overall        text,                        -- 예보 개황
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id) ON DELETE SET NULL,
    PRIMARY KEY (inform_date, inform_code, region)
);
