"""PostGIS 가 필요한 SQL 테스트 공용 픽스처.

TEST_DATABASE_URL 이 가리키는 DB 의 스키마를 지우고 마이그레이션을 새로 적용합니다(운영 DB 를 가리키지 마세요).
소형 지형: EPSG:5179 에서 10km 정사각형 지역 4개(2×2) + 시설 5개 — 기대값을 손으로 계산할 수 있게.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

TEST_URL = os.environ.get("TEST_DATABASE_URL")
X0, Y0 = 1_000_000.0, 1_900_000.0   # UTM-K 기준 충북 부근
YEAR = 2024


@pytest.fixture(scope="session")
def engine():
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL 없음 — make test 로 실행하세요")
    if "atlas_test" not in TEST_URL:
        pytest.exit("안전장치: TEST_DATABASE_URL 의 DB 이름에 'atlas_test' 가 있어야 합니다.")
    os.environ["DATABASE_URL"] = TEST_URL
    os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:1/0")  # 기본은 캐시 없음
    from atlas.api import cache
    from atlas.core import config, db
    from atlas.core.migrate import migrate

    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    cache.client.cache_clear()
    eng = create_engine(TEST_URL, future=True)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS raw, stg, mart, ops CASCADE"))
        c.execute(text("DROP TABLE IF EXISTS public.schema_migrations"))
    migrate(eng)
    yield db.get_engine()
    eng.dispose()


@pytest.fixture()
def clean(engine):
    with engine.begin() as c:
        c.execute(text("""TRUNCATE mart.area_grid, mart.weather_hourly, mart.air_forecast, mart.oa_nearest, mart.oa_area, mart.area_road, mart.bank_place, mart.facility_geocheck,
                          mart.geocode_cache, mart.area_resident_pop,
                          mart.whatif_result, mart.whatif_scenario, mart.area_nearest, mart.access_metric,
                          mart.facility_area_map, ops.dq_check, ops.dq_issue, mart.calc_run, mart.post_facility_hist,
                          mart.admin_area, mart.area_population, stg.post_facility, raw.api_response,
                          ops.collect_run CASCADE"""))
    return engine


def add_area(c, cd, x1, y1, x2, y2, level=2, parent="99", nm=None):
    """정사각형 지역. 대표점은 중심(손 계산용으로 명시)."""
    c.execute(text("""
        INSERT INTO mart.admin_area (adm_cd, stat_year, adm_nm, level, parent_cd, geom, geom_5179, geom_simple,
                                     rep_point, rep_point_5179, src_crs)
        SELECT :cd, :y, :nm, :lvl, :parent, ST_Multi(ST_Transform(g, 4326)), ST_Multi(g),
               ST_Multi(ST_Transform(g, 4326)), ST_Transform(p, 4326), p, 'EPSG:5179'
        FROM (SELECT ST_MakeEnvelope(:x1, :y1, :x2, :y2, 5179) AS g,
                     ST_SetSRID(ST_MakePoint((:x1 + :x2) / 2.0, (:y1 + :y2) / 2.0), 5179) AS p) s"""),
              {"cd": cd, "y": YEAR, "nm": nm or f"지역{cd}", "lvl": level, "parent": parent,
               "x1": X0 + x1, "y1": Y0 + y1, "x2": X0 + x2, "y2": Y0 + y2})


def add_fac(c, pid, x, y, div=1, finance="09:00~16:30", fin=True, lunch="N", p365="N", center=False) -> int:
    return c.execute(text("""
        INSERT INTO mart.post_facility_hist (post_id, post_div, name, geom, geom_5179, finance_time, fin_available,
                                             lunch_yn, post365_yn, is_center, row_hash, valid_from, is_current)
        VALUES (:pid, :div, :pid, ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 5179), 4326),
                ST_SetSRID(ST_MakePoint(:x, :y), 5179), :ft, :fin, :lunch, :p365, :center, :h,
                now() - interval '1 day', true) RETURNING hist_id"""),
        {"pid": pid, "div": div, "x": X0 + x, "y": Y0 + y, "ft": finance, "fin": fin, "lunch": lunch,
         "p365": p365, "center": center, "h": pid.ljust(64, "0")[:64]}).scalar_one()


def add_pop(c, cd, tot, aged):
    c.execute(text("""INSERT INTO mart.area_population (adm_cd, stat_year, adm_nm, tot_ppltn, aged_child_idx)
                      VALUES (:cd, :y, :cd, :t, :a)"""), {"cd": cd, "y": YEAR, "t": tot, "a": aged})


@pytest.fixture()
def terrain(clean):
    """
        C(0-10k,10-20k)  D(10-20k,10-20k)        F3 (5k,16k) 총괄국      F4 (12k,12k) 365코너(금융X)
        A(0-10k,0-10k)   B(10-20k,0-10k)         F1 (5k,2k)  우체국      F5 (19k,19k) 00:00~00:00(금융X)
                                                 F2 (15k,9k) 우체국·점심휴무
    """
    with clean.begin() as c:
        add_area(c, "99010", 0, 0, 10_000, 10_000)          # A
        add_area(c, "99020", 10_000, 0, 20_000, 10_000)     # B
        add_area(c, "99030", 0, 10_000, 10_000, 20_000)     # C
        add_area(c, "99040", 10_000, 10_000, 20_000, 20_000)  # D
        for cd, tot, aged in [("99010", 1000, 100), ("99020", 2000, 200), ("99030", 3000, 300), ("99040", 4000, 400)]:
            add_pop(c, cd, tot, aged)
        ids = {
            "F1": add_fac(c, "F1", 5_000, 2_000),
            "F2": add_fac(c, "F2", 15_000, 9_000, lunch="Y"),
            "F3": add_fac(c, "F3", 5_000, 16_000, div=0),
            "F4": add_fac(c, "F4", 12_000, 12_000, div=3, finance=None, fin=False, p365="Y"),
            "F5": add_fac(c, "F5", 19_000, 19_000, finance="00:00~00:00", fin=False),
        }
    return ids
