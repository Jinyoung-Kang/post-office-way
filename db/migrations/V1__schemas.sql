-- V1 — 확장·스키마
--   raw  : 외부 API 응답 원문 (append-only, 키 마스킹)
--   stg  : 정규화 스냅샷 (collect_run 단위)
--   mart : 분석 테이블 (시설 이력·행정구역·지표·What-if)
--   ops  : 수집 실행·품질 이슈
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS mart;
CREATE SCHEMA IF NOT EXISTS ops;
