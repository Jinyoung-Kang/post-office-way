-- V17 — 은행 지점의 은행(브랜드)과 우체국 은행대리업 대상 여부.
--   카카오 범주 이름 '금융,보험 > 금융서비스 > 은행 > KB국민은행' 의 마지막 칸이 브랜드.
--   대상 여부는 코드가 아닌 표로 둠 — 협약 은행이 늘거나 확인되면 행만 고치면 됨(재배포 없음).

ALTER TABLE mart.bank_place ADD COLUMN brand text;

CREATE TABLE mart.bank_brand (
    brand      text PRIMARY KEY,
    grp        varchar(8) NOT NULL CHECK (grp IN ('BANK', 'MG', 'SAVINGS', 'OTHER')),  -- 은행 / 새마을금고 / 저축은행 / 기타
    post_agent boolean NOT NULL DEFAULT false,   -- 우체국 창구·ATM 에서 이 은행 입출금이 되는가 (은행대리업·공동이용)
    note       text
);

-- 2026-07~10 보도: "국내 14개 시중·지방은행 모두" 우체국 2,400여 곳에서 입출금 무료. 은행별 명단은 공개 자료에서
-- 확인하지 못해 시중·지방·특수은행(개인 창구가 있는 은행) 전체를 대상으로 가정 — 화면에 '가정'으로 표시
INSERT INTO mart.bank_brand (brand, grp, post_agent, note) VALUES
    ('KB국민은행', 'BANK', true, NULL), ('신한은행', 'BANK', true, NULL), ('우리은행', 'BANK', true, NULL),
    ('하나은행', 'BANK', true, NULL), ('SC제일은행', 'BANK', true, NULL), ('한국씨티은행', 'BANK', true, NULL),
    ('iM뱅크', 'BANK', true, NULL), ('BNK부산은행', 'BANK', true, '2026-08 협약'), ('BNK경남은행', 'BANK', true, NULL),
    ('광주은행', 'BANK', true, '2026-08 협약'), ('전북은행', 'BANK', true, NULL), ('제주은행', 'BANK', true, NULL),
    ('NH농협은행', 'BANK', true, NULL), ('IBK기업은행', 'BANK', true, NULL), ('Sh수협은행', 'BANK', true, NULL),
    ('새마을금고', 'MG', false, '은행대리업 대상 아님'), ('저축은행', 'SAVINGS', false, '은행대리업 대상 아님');

-- 기존 행 채우기 — '… > 은행 > 저축은행 > SBI저축은행' 처럼 더 깊으면 '저축은행' 으로 묶음
UPDATE mart.bank_place
   SET brand = CASE WHEN category LIKE '%> 저축은행%' THEN '저축은행'
                    ELSE nullif(trim(split_part(split_part(category, '> 은행 >', 2), ' > ', 1)), '') END
 WHERE category LIKE '%> 은행%';

CREATE INDEX ix_bank_place_brand ON mart.bank_place (brand) WHERE kind = 'BRANCH';
GRANT SELECT ON mart.bank_brand TO atlas_api;

-- 지금 영업 중으로 보는 대면 지점 — 마지막 전수 수집(scope 'FULL;…', DONE)에서 본 지점만.
-- 전수 수집이 없으면 이전 규칙(최근 90일 안에 본 것). 계산(calc/07_bank)과 API 가 같은 규칙을 쓰도록 한곳에 둠
CREATE VIEW mart.bank_branch_current AS
SELECT b.place_id, b.name, b.category, b.brand, b.addr, b.geom, b.geom_5179, b.last_seen
  FROM mart.bank_place b
 WHERE b.kind = 'BRANCH'
   AND b.last_seen >= coalesce(
         (SELECT max(r.started_at) FROM ops.collect_run r
           WHERE r.kind = 'KAKAO_BANK' AND r.status = 'DONE' AND r.scope LIKE 'FULL;%'),
         (SELECT max(x.last_seen) - interval '90 days' FROM mart.bank_place x));
GRANT SELECT ON mart.bank_branch_current TO atlas_api;
