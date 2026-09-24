-- V8 — 도로 거리 출발점 종류: REP(지역 대표점) · OA(인구가 가장 많은 집계구 대표점)
-- 대표점이 산·물 위에 있으면 '주변 도로 없음'(102)이나 고속도로 스냅으로 우회 수십 km 가 나와, 그런 경로만 OA 출발로 다시 구함.
ALTER TABLE mart.area_road ADD COLUMN origin varchar(4) NOT NULL DEFAULT 'REP' CHECK (origin IN ('REP', 'OA'));
