-- V18 — ① 은행 지점 폐쇄 영향평가 · ② 도보 접근성
--
-- ① mart.bank_impact: calc_run 마다 '은행(시중·지방·특수) 대면 지점이 문을 닫으면'을 지점별로 미리 계산.
--    직선거리 열은 지표 계산(calc/11_bank_impact.sql)이, 도보 열(walk_*)은 도보 계산 작업(walk)이 나중에 채움.
-- ② mart.oa_walk: 집계구마다 걸어서 가장 가까운 금융 우체국 3곳·은행 지점 2곳과 도보 거리(m).
--    mart.walk_run: 도보 계산 실행 기록(그래프·속도·한도) — calc_run 당 하나.

CREATE TABLE mart.bank_impact (
    calc_run_id     uuid NOT NULL REFERENCES mart.calc_run (calc_run_id) ON DELETE CASCADE,
    place_id        varchar(20) NOT NULL,
    brand           text,
    post_agent      boolean NOT NULL,          -- 이 은행 입출금을 우체국에서 할 수 있다고 보는가 (mart.bank_brand)
    adm_cd          varchar(10),               -- 지점이 있는 시군구 (리포트·필터용)
    emd_cd          varchar(10),
    catch_oa        int NOT NULL,              -- 이 지점이 가장 가까운 은행 지점인 집계구 수
    catch_ppltn     int NOT NULL,              -- … 의 인구
    catch_aged      int,                       -- … 65세 이상(읍면동 고령 비율로 추정, KOSIS 없으면 NULL)
    same_brand_m    numeric,                   -- 지점에서 같은 은행 다른 지점까지 직선거리
    other_bank_m    numeric,                   -- 지점에서 다른 은행 지점까지
    post_m          numeric,                   -- 지점에서 금융 우체국까지
    popw_now_m      numeric,                   -- 주민 → 이 지점 (인구 가중 직선거리)
    popw_alt_m      numeric,                   -- 문을 닫으면 → 가장 가까운 대체 창구(다른 은행 지점 또는 은행대리업 우체국)
    lost_ppltn      int NOT NULL,              -- 문을 닫으면 2km 안에 대체 창구가 없는 인구
    lost_aged       int,
    walk_now_m      numeric,                   -- ② 도보 (walk 작업이 채움, 그래프가 없으면 NULL)
    walk_alt_m      numeric,
    walk_lost_ppltn int,                       -- 문을 닫으면 걸어서 30분 안에 대체 창구가 없는 인구
    grade           varchar(4) NOT NULL CHECK (grade IN ('HIGH', 'MID', 'LOW')),
    reasons         text[] NOT NULL DEFAULT '{}',
    rnk             int,                        -- 영향 순위 (lost_ppltn → catch_ppltn)
    n               int,
    PRIMARY KEY (calc_run_id, place_id)
);
CREATE INDEX ix_bank_impact_adm ON mart.bank_impact (calc_run_id, adm_cd);
CREATE INDEX ix_bank_impact_rank ON mart.bank_impact (calc_run_id, rnk);

CREATE TABLE mart.walk_run (
    calc_run_id  uuid PRIMARY KEY REFERENCES mart.calc_run (calc_run_id) ON DELETE CASCADE,
    status       varchar(8) NOT NULL CHECK (status IN ('RUNNING', 'DONE', 'FAILED')),
    speed_mps    numeric NOT NULL,             -- 걷는 속도 (고령자 기준 0.8m/s)
    limit_m      numeric NOT NULL,             -- 이 거리 밖은 '걸어서 갈 수 없음'
    graph        jsonb NOT NULL DEFAULT '{}',  -- 그래프 정보(OSM 기준 시각·꼭짓점·간선 수)
    stats        jsonb NOT NULL DEFAULT '{}',
    error        text,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);

CREATE TABLE mart.oa_walk (
    calc_run_id uuid NOT NULL REFERENCES mart.calc_run (calc_run_id) ON DELETE CASCADE,
    kind        varchar(4) NOT NULL CHECK (kind IN ('POST', 'BANK')),
    oa_cd       varchar(16) NOT NULL,
    rank        smallint NOT NULL,
    target      text NOT NULL,                 -- POST: hist_id, BANK: place_id
    walk_m      real NOT NULL,
    PRIMARY KEY (calc_run_id, kind, oa_cd, rank)
);

GRANT SELECT ON mart.bank_impact, mart.walk_run, mart.oa_walk TO atlas_api;

-- OSM 도로망 내려받기·그래프 만들기도 수집 실행으로 기록
ALTER TABLE ops.collect_run DROP CONSTRAINT collect_run_kind_check;
ALTER TABLE ops.collect_run ADD CONSTRAINT collect_run_kind_check CHECK (kind IN (
    'POST_AREA', 'POST_DISCOVER', 'SGIS_POP', 'SGIS_BND', 'KOSIS_POP', 'SGIS_OA', 'KAKAO_GEO', 'KAKAO_BANK',
    'KAKAO_ROAD', 'KMA_FCST', 'AIR_FCST', 'NMC_CARE', 'KASI_HOLIDAY', 'OSM_WALK'));

INSERT INTO mart.metric_def (metric_code, name_ko, unit, formula, limitation, higher_is_worse, sort_order) VALUES
 ('POPW_FIN_WALK_M', '금융 우체국까지 걷는 거리 (인구 가중)', 'm',
  '집계구 대표점 → OSM 보행 도로망 최단 경로 → 최근접 금융 우체국. 집계구 인구 가중 평균.',
  'OpenStreetMap 도로망 기준(인도·골목이 덜 그려진 곳은 실제보다 멀게). 경사·계단·신호 대기 미반영.', true, 16),
 ('WALK30_NO_FIN_PPLTN', '걸어서 30분 안에 금융 우체국이 없는 인구', '명',
  '고령자 보행 속도 0.8m/s × 30분 = 1,440m 안에 금융 우체국이 없는 집계구 인구 합.',
  'OSM 도로망 기준. 걷는 속도는 서울시 보행약자 신호시간 기준(1m 당 1.25초)을 따름.', true, 17),
 ('WALK30_NO_FIN_SHARE', '걸어서 30분 안에 금융 우체국이 없는 인구 비율', '%',
  'WALK30_NO_FIN_PPLTN ÷ 집계구 인구 × 100.', 'OSM 도로망 기준.', true, 18),
 ('WALK30_NO_CASH_PPLTN', '걸어서 30분 안에 대면 금융 창구가 없는 인구', '명',
  '걸어서 30분(1,440m) 안에 금융 우체국도 은행 지점도 없는 집계구 인구 합.',
  'OSM 도로망 기준. 새마을금고·저축은행은 제외(은행 지점 기준).', true, 19)
ON CONFLICT (metric_code) DO NOTHING;

-- ① 영향 등급 규칙 BANK-IMPACT-1 (2026 은행 점포폐쇄 공동절차 개정 내용을 참고한 분석용 기준 — 공식 평가 아님).
--    지표 계산과 도보 계산이 같은 규칙을 쓰도록 함수 하나로.
CREATE FUNCTION mart.bank_impact_reasons(lost int, same_m numeric, aged int, pop int, walk_lost int)
RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
    SELECT array_remove(ARRAY[
        CASE WHEN lost > 0 THEN 'NO_ALT_2KM' END,                          -- 문을 닫으면 2km 안 대체 창구 없는 주민
        CASE WHEN walk_lost > 0 THEN 'NO_ALT_WALK30' END,                  -- … 걸어서 30분 안 대체 창구 없는 주민
        CASE WHEN same_m IS NULL OR same_m > 10000 THEN 'SAME_BANK_10KM' END,  -- 같은 은행 다음 지점이 10km 밖
        CASE WHEN pop > 0 AND aged IS NOT NULL AND aged >= pop * 0.2 THEN 'AGED_20' END  -- 이용 주민 20% 이상 65세 이상
    ], NULL)
$$;

CREATE FUNCTION mart.bank_impact_grade(lost int, reasons text[])
RETURNS varchar LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN lost >= 1000 OR (lost > 0 AND reasons && ARRAY['SAME_BANK_10KM', 'AGED_20']) THEN 'HIGH'
                WHEN cardinality(reasons) > 0 THEN 'MID'
                ELSE 'LOW' END
$$;
