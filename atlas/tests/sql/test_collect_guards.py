"""수집 데이터 보호 장치 — 이상한 응답(빈 응답·건수 누락·일부 실패)이 기존 자료를 지우지 않는지 (ADR-023)."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from atlas.collector.datago import care

pytestmark = pytest.mark.db


class FakeFetcher:
    calls = errors = 0

    def close(self):
        pass


def _seed_pharmacies(engine, n: int) -> None:
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO mart.care_place (hpid, kind, name, hours, geom, geom_5179, last_seen)
            SELECT 'OLD' || i, 'PHARMACY', '약국' || i, '{}'::jsonb, p, ST_Transform(p, 5179), now() - interval '7 days'
              FROM generate_series(1, :n) i, (SELECT ST_SetSRID(ST_MakePoint(127.0, 37.0), 4326) AS p) s"""), {"n": n})


def _pharmacies(engine) -> int:
    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM mart.care_place WHERE kind = 'PHARMACY'")).scalar_one()


def _item(i: int) -> dict:
    return {"hpid": f"NEW{i}", "dutyName": f"약국{i}", "wgs84Lat": 37.0, "wgs84Lon": 127.0}


def _run_care(monkeypatch, pharmacy_body, clinic_body=None) -> tuple[str, dict]:
    clinic_body = clinic_body if clinic_body is not None else {
        "items": {"item": [{"hpid": "C1", "dutyName": "의원1", "dutyDiv": "C", "dutyDivNam": "의원",
                            "wgs84Lat": 37.0, "wgs84Lon": 127.0}]}, "totalCount": 1}
    monkeypatch.setattr(care, "make_fetcher", lambda *a: FakeFetcher())
    monkeypatch.setattr(care, "call", lambda f, url, p, src: pharmacy_body if src == "NMC_PHARMACY" else clinic_body)
    rid = care.collect_care()
    from atlas.core.db import begin

    with begin() as c:
        return tuple(c.execute(text("SELECT status, stats FROM ops.collect_run WHERE collect_run_id = :r"),
                               {"r": rid}).one())


@pytest.mark.parametrize("body", [
    {},                                                             # 결과 없음(03) → call 이 빈 dict
    {"items": {"item": [_item(1)]}},                                # 전체 건수(totalCount) 없음
    {"items": "", "totalCount": 25000},                             # 건수는 있는데 항목이 빔
])
def test_care_anomalous_response_keeps_existing(clean, engine, monkeypatch, body):
    _seed_pharmacies(engine, 200)
    status, stats = _run_care(monkeypatch, body)
    assert _pharmacies(engine) >= 200                               # 기존 약국을 지우지 않음
    assert status != "DONE" and not stats["pharmacy"]["complete"]


def test_care_mass_removal_is_held(clean, engine, monkeypatch):
    """전체를 받았다고 해도 기존 행의 큰 비율이 한 번에 사라지면 삭제를 보류 (응답 이상으로 봄)."""
    _seed_pharmacies(engine, 200)
    status, stats = _run_care(monkeypatch, {"items": {"item": [_item(i) for i in range(20)]}, "totalCount": 20})
    assert _pharmacies(engine) == 220 and stats["pharmacy"]["removeHeld"] == 200 and status != "DONE"


def test_care_normal_closure_removes_unseen(clean, engine, monkeypatch):
    """정상 — 전체를 받았고 사라진 곳이 적으면 폐업한 곳만 지움."""
    _seed_pharmacies(engine, 2)
    items = [_item(i) for i in range(100)]
    status, stats = _run_care(monkeypatch, {"items": {"item": items}, "totalCount": 100})
    assert _pharmacies(engine) == 100 and stats["pharmacy"]["removed"] == 2 and status == "DONE"


# ---- D4: KOSIS 일부 시도 실패 — 실패한 시도의 기존 고령인구를 지우지 않음 ----

def _kosis_area(c, cd, nm, level, parent):
    c.execute(text("""INSERT INTO mart.admin_area (adm_cd, stat_year, adm_nm, level, parent_cd, geom, geom_5179,
                                                  geom_simple, rep_point, rep_point_5179, src_crs)
                      SELECT :cd, 2024, :nm, :lvl, :p, g, ST_Transform(g, 5179), g, ST_Centroid(g),
                             ST_Transform(ST_Centroid(g), 5179), 'EPSG:4326'
                        FROM (SELECT ST_Multi(ST_MakeEnvelope(127, 37, 127.1, 37.1, 4326)) AS g) s"""),
              {"cd": cd, "nm": nm, "lvl": level, "p": parent})


def _run_kosis(monkeypatch, fail: set[str], no_data: set[str] = frozenset(), empty: set[str] = frozenset(),
               extra_sidos: dict[str, str] | None = None):
    """fail: 일시 오류(31) · no_data: '조회결과 없음'(30) · empty: 오류 없이 빈 목록 · extra_sidos: SGIS 에 없는 KOSIS 시도"""
    from atlas.collector.kosis import pipeline
    from atlas.core import config

    monkeypatch.setenv("KOSIS_API_KEY", "TESTKEY")
    config.get_settings.cache_clear()
    meta = [{"OBJ_ID": "A", "ITM_ID": "11", "ITM_NM": "서울특별시"}, {"OBJ_ID": "A", "ITM_ID": "11110", "ITM_NM": "종로구"},
            {"OBJ_ID": "A", "ITM_ID": "26", "ITM_NM": "부산광역시"}, {"OBJ_ID": "A", "ITM_ID": "26110", "ITM_NM": "중구"},
            *[{"OBJ_ID": "A", "ITM_ID": cd, "ITM_NM": nm} for cd, nm in (extra_sidos or {}).items()],
            {"OBJ_ID": "B", "ITM_ID": "0", "ITM_NM": "계"}, {"OBJ_ID": "B", "ITM_ID": "70", "ITM_NM": "65 - 69세"}]

    def fetch_sido(_f, sido, _codes, _period):
        if sido in fail:
            raise pipeline.KosisError("31", "일시 오류")
        if sido in no_data or sido in (extra_sidos or {}):
            raise pipeline.KosisError("30", "데이터가 존재하지 않습니다.")
        if sido in empty:
            return []
        sgg = sido + "110"
        return [{"C1": sgg, "C1_NM": meta[[m["ITM_ID"] for m in meta].index(sgg)]["ITM_NM"], "C2": "0", "DT": "1000",
                 "PRD_DE": "202412"},
                {"C1": sgg, "C2": "70", "DT": "200", "PRD_DE": "202412"}]

    monkeypatch.setattr(pipeline, "fetch_meta", lambda f: meta)
    monkeypatch.setattr(pipeline, "fetch_sido", fetch_sido)
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    rid = pipeline.collect_kosis(year=2024)
    config.get_settings.cache_clear()
    return rid


def test_kosis_partial_failure_keeps_failed_sido(clean, engine, monkeypatch):
    with engine.begin() as c:
        _kosis_area(c, "11010", "종로구", 2, "11")
        _kosis_area(c, "21010", "중구", 2, "21")
        c.execute(text("""INSERT INTO mart.area_population (adm_cd, stat_year, adm_nm, tot_ppltn)
                          VALUES ('11', 2024, '서울특별시', 1), ('21', 2024, '부산광역시', 1)"""))
    _run_kosis(monkeypatch, fail=set())
    resident = lambda: dict(c2.execute(text("SELECT adm_cd, aged65_ppltn FROM mart.area_resident_pop "   # noqa: E731
                                            "WHERE stat_year = 2024")).all())
    with engine.connect() as c2:
        assert resident() == {"11010": 200, "21010": 200}
    _run_kosis(monkeypatch, fail={"26"})                    # 부산만 일시 오류
    with engine.connect() as c2:
        assert resident() == {"11010": 200, "21010": 200}   # 부산(21010)의 기존 값 유지


def _kosis_seed(engine):
    with engine.begin() as c:
        _kosis_area(c, "11010", "종로구", 2, "11")
        _kosis_area(c, "21010", "중구", 2, "21")
        c.execute(text("""INSERT INTO mart.area_population (adm_cd, stat_year, adm_nm, tot_ppltn)
                          VALUES ('11', 2024, '서울특별시', 1), ('21', 2024, '부산광역시', 1)"""))


def _kosis_state(engine, rid):
    with engine.connect() as c:
        return (dict(c.execute(text("SELECT adm_cd, aged65_ppltn FROM mart.area_resident_pop WHERE stat_year = 2024")).all()),
                c.execute(text("SELECT status FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).scalar())


def test_kosis_no_data_for_every_sido_keeps_year(clean, engine, monkeypatch):
    """아직 공표되지 않은 기간(KOSIS_PERIOD) 등으로 모든 시도가 '조회결과 없음(30)'이면 그 해 고령인구를 지우지 않고 실패로.
    예전에는 30 을 '그 시점에 없던 시도'로만 보고 건너뛰어, 받은 값 없이 그 해 전체를 지우고 DONE 으로 끝났음(재계산까지 이어짐)."""
    from atlas.collector.kosis import pipeline

    _kosis_seed(engine)
    _run_kosis(monkeypatch, fail=set())
    with pytest.raises(pipeline.KosisError):
        _run_kosis(monkeypatch, fail=set(), no_data={"11", "26"})
    with engine.connect() as c:
        rid = c.execute(text("SELECT collect_run_id FROM ops.collect_run ORDER BY started_at DESC LIMIT 1")).scalar()
    assert _kosis_state(engine, rid) == ({"11010": 200, "21010": 200}, "FAILED")


@pytest.mark.parametrize("how", ["no_data", "empty"])
def test_kosis_active_sido_without_data_keeps_its_values(clean, engine, monkeypatch, how):
    """SGIS 에 있는 시도가 30 이나 빈 목록을 주면 그 시도는 실패로 보고 기존 값을 남김(일부 실패와 같은 처리)."""
    _kosis_seed(engine)
    _run_kosis(monkeypatch, fail=set())
    rid = _run_kosis(monkeypatch, fail=set(), **{how: {"26"}})
    assert _kosis_state(engine, rid) == ({"11010": 200, "21010": 200}, "PARTIAL")


def test_kosis_sido_missing_in_sgis_is_skipped(clean, engine, monkeypatch):
    """SGIS 경계에 이름이 없는 KOSIS 시도(그 시점에 없던 폐지·신설 시도)의 30 은 지금처럼 건너뛰고 DONE."""
    _kosis_seed(engine)
    rid = _run_kosis(monkeypatch, fail=set(), extra_sidos={"12": "전남광주통합특별시"})
    assert _kosis_state(engine, rid) == ({"11010": 200, "21010": 200}, "DONE")


# ---- D5: 공휴일 응답이 비면(아직 발표 전·일시 이상) 그 해 기존 휴일을 지우지 않음 ----

def test_empty_holiday_year_keeps_existing(clean, engine, monkeypatch):
    from atlas.collector.datago import holiday

    with engine.begin() as c:
        c.execute(text("INSERT INTO mart.holiday (locdate, name, is_holiday) VALUES ('2027-01-01', '1월1일', true)"))
    monkeypatch.setattr(holiday, "make_fetcher", lambda *a: FakeFetcher())
    monkeypatch.setattr(holiday, "call", lambda f, u, p, s: {})              # 결과 없음(03)
    holiday.collect_holidays(years=[2027])
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM mart.holiday")).scalar_one() == 1


# ---- SGIS 경계: 일시 오류가 직전 연도 경계로 바꾸면 안 됨 (2차 리뷰 D4) ----

def _feature(cd, nm, x0):
    ring = [[x0, 1_950_000], [x0 + 1000, 1_950_000], [x0 + 1000, 1_951_000], [x0, 1_951_000], [x0, 1_950_000]]
    return {"type": "Feature", "properties": {"adm_cd": cd, "adm_nm": nm}, "geometry": {"type": "Polygon", "coordinates": [ring]}}


def _run_bnd(engine, monkeypatch, bnd):
    """실제 SgisClient(토큰·HTTP 오류 처리)를 거치게 모의 HTTP 로 — bnd(year, adm_cd) 가 httpx.Response 를 돌려줌."""
    import httpx

    from atlas.collector import http as http_mod
    from atlas.collector.sgis import pipeline
    from atlas.core import config

    for k, v in {"SGIS_CONSUMER_KEY": "TESTKEY1", "SGIS_CONSUMER_SECRET": "TESTSECRET", "SGIS_SIDO": "all",
                 "HTTP_RETRIES": "0"}.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()

    def handler(req: httpx.Request):
        if req.url.path.endswith("/auth/authentication.json"):
            return httpx.Response(200, json={"errCd": 0, "result": {"accessToken": "TOKEN123", "accessTimeout": 9e9}})
        return bnd(int(req.url.params["year"]), req.url.params["adm_cd"])

    orig_init = http_mod.Fetcher.__post_init__

    def patched(self):
        orig_init(self)
        self._client = httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(http_mod.Fetcher, "__post_init__", patched)
    monkeypatch.setattr(pipeline, "_sido_list", lambda sgis, y: {"11": "서울특별시", "21": "부산광역시"})
    rid = pipeline.collect_boundaries(year=2024, levels=[2])
    config.get_settings.cache_clear()
    with engine.connect() as c:
        st, stats = c.execute(text("SELECT status, stats FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).one()
        codes = [r[0] for r in c.execute(text("SELECT adm_cd FROM mart.admin_area WHERE stat_year = 2024 ORDER BY 1"))]
    return st, stats, codes


def test_sgis_transient_error_does_not_switch_year(clean, engine, monkeypatch):
    """첫 시도(서울)의 2024 경계 호출이 502 면 그 시도만 실패 — 예전에는 2023 경계로 대체하고 그 연도를 모든 시도에 고정해
    전국을 직전 연도 경계로 덮어쓰고 DONE 이었음(다른 해 코드가 섞여 남음)."""
    import httpx

    def bnd(year, cd):
        if cd == "11" and year == 2024:
            return httpx.Response(502)
        feats = {("11", 2023): [_feature("11999", "서울특별시 옛구", 950_000)],
                 ("21", 2024): [_feature("21010", "부산광역시 중구", 1_100_000)],
                 ("21", 2023): [_feature("21999", "부산광역시 옛구", 1_100_000)]}.get((cd, year), [])
        return httpx.Response(200, json={"errCd": 0, "features": feats})

    st, stats, codes = _run_bnd(engine, monkeypatch, bnd)
    assert codes == ["21010"]                       # 2023 코드(11999·21999)가 2024 로 들어가지 않음
    assert st == "PARTIAL" and stats["failedCodes"] == ["11:L2"] and stats["sourceYear"] == 2024


def test_sgis_year_without_data_falls_back(clean, engine, monkeypatch):
    """그 해 경계가 아직 없으면(정상 응답인데 0건, 또는 SGIS 가 오류 코드로 '결과 없음') 직전 연도로 대체 — 의도된 동작 유지."""
    import httpx

    def bnd(year, cd):
        if year == 2024:
            return httpx.Response(200, json={"errCd": -100, "errMsg": "검색결과가 존재하지 않습니다"} if cd == "11"
                                  else {"errCd": 0, "features": []})
        return httpx.Response(200, json={"errCd": 0, "features": [_feature(cd + "010", "옛 경계", 950_000)]})

    st, stats, codes = _run_bnd(engine, monkeypatch, bnd)
    assert st == "DONE" and stats["sourceYear"] == 2023 and codes == ["11010", "21010"]
