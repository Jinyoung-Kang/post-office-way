-- V26 — 인구이동 단위 별칭 (ADR-028 보완). 시도 코드만 바뀐 개편(2026-07 광주·전남 → 전남광주통합특별시, 29·46 → 12)은
--   시군구 경계가 그대로라 옛 코드와 새 코드를 같은 단위로 잇는다. 첫 백필에서 확인 — 잇지 않으면 27개 시군구가 '12개월 미충족'으로 값이 없었음.
--   수집기가 받아 둔 달 전체로 매번 다시 만들고(옛 시도의 단위가 모두 같은 달에 사라지고 다음 달 새 시도에 같은 이름으로 나타날 때만),
--   계산·조회는 coalesce(alias.unit_cd, mois_cd) 로 묶는다. 대응표(area_migration_map)의 mois_cd 는 별칭을 따라간 최신 코드.

CREATE TABLE mart.migration_unit_alias (
    mois_cd        varchar(10) PRIMARY KEY CHECK (mois_cd ~ '^[0-9]{10}$'),   -- 옛 코드
    unit_cd        varchar(10) NOT NULL CHECK (unit_cd ~ '^[0-9]{10}$'),       -- 이어지는 새 코드
    from_ym        char(6) NOT NULL,                                            -- 새 코드가 처음 나온 달
    collect_run_id uuid REFERENCES ops.collect_run (collect_run_id),
    CHECK (mois_cd <> unit_cd)
);

GRANT SELECT ON mart.migration_unit_alias TO atlas_api;
