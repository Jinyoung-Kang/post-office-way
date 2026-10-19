"""인구 추세(행안부 인구이동, ADR-028) — 수집 보호 장치 · 지표 계산 · API 응답.

수집: 한 달은 전국 행렬을 빠짐·겹침 없이 다 받았을 때만 통째로 넣음 — 한도 초과·쪽 실패·건수 불일치는 그 달을 넣지 않고
기존 값을 남김. 계산: 최근 12개 연속 달 합 ÷ 주민등록 인구, 일반구는 시 전체 값(분모도 시 전체).
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atlas.calc.runner import run_calc
from atlas.collector.datago.client import DataGoStop
from atlas.collector.mois import migration

pytestmark = pytest.mark.db
GA, NA, BUSAN = "1111000000", "1114000000", "2611000000"
NAMES = {GA: ("서울특별시", "가구"), NA: ("서울특별시", "나구"), BUSAN: ("부산광역시", "중구")}


class FakeFetcher:
    calls = errors = 0

    def close(self):
        pass


def _row(ym, mvin, mvt, tot, old):
    return {"statsYm": ym, "mvinAdmmCd": mvin, "mvtAdmmCd": mvt, "mvinCtpvNm": NAMES[mvin][0], "mvinSggNm": NAMES[mvin][1],
            "mvtCtpvNm": NAMES[mvt][0], "mvtSggNm": NAMES[mvt][1], "totNmprCnt": str(tot),
            "male70AgeNmprCnt": str(old), "male30AgeNmprCnt": str(tot - old)}


def _matrix(ym):
    """가구: 안쪽 5 · 나구에서 30(65+ 3) · 부산 중구에서 4 전입 / 나구로 10(65+ 1) 전출."""
    return [_row(ym, GA, GA, 5, 0), _row(ym, GA, NA, 30, 3), _row(ym, NA, GA, 10, 1), _row(ym, GA, BUSAN, 4, 0)]


def _fake_call(log, fail=None, total_extra=0):
    """쪽 크기 2 — 한 달 4행 = 2쪽. fail(ym, page) 가 값을 돌려주면 그 쪽 응답 대신 (None·{}·예외)."""
    def call(fetcher, url, params, source, empty_codes=("03",)):
        ym, page = params["srchFrYm"], params["pageNo"]
        log.append((ym, page))
        if fail and (r := fail(ym, page)) is not False:
            if isinstance(r, BaseException):
                raise r
            return r
        rows = _matrix(ym)
        return {"items": {"item": rows[(page - 1) * 2: page * 2]}, "totalCount": str(len(rows) + total_extra)}
    return call


def _setup_areas(engine):
    from tests.sql.conftest import add_area

    with engine.begin() as c:
        add_area(c, "99010", 0, 0, 10_000, 10_000, nm="가구")
        add_area(c, "99020", 10_000, 0, 20_000, 10_000, nm="나구")
        for cd, k, tot, aged in (("99010", "11110", 1000, 100), ("99020", "11140", 2000, 200)):
            c.execute(text("""INSERT INTO mart.area_resident_pop (adm_cd, stat_year, ref_period, tot_ppltn, aged65_ppltn,
                                  aged65_ratio, kosis_cd, match_method) VALUES (:cd, 2024, '202412', :t, :a, 10, :k, 'NAME')"""),
                      {"cd": cd, "t": tot, "a": aged, "k": k})


def _collect(monkeypatch, log, today=datetime(2026, 10, 19), **kw):
    monkeypatch.setattr(migration, "make_fetcher", lambda *a, **kw: FakeFetcher())
    monkeypatch.setattr(migration, "call", _fake_call(log, **kw))
    monkeypatch.setattr(migration, "PAGE_ROWS", 2)
    monkeypatch.setattr(migration, "now_kst", lambda: today)
    rid, changed = migration.collect_migration(months=3)
    from atlas.core.db import begin

    with begin() as c:
        st, stats = c.execute(text("SELECT status, stats FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).one()
    return rid, changed, st, stats


def _months(engine):
    with engine.connect() as c:
        return {r[0]: r[1:] for r in c.execute(text("""SELECT ref_ym || ':' || mois_cd, in_cnt, out_cnt, in_aged65, out_aged65,
                                                         intra_cnt FROM mart.migration_month"""))}


def test_collect_months_and_map(clean, engine, monkeypatch):
    _setup_areas(engine)
    log: list = []
    rid, changed, st, stats = _collect(monkeypatch, log)
    assert st == "DONE" and changed and stats["months"] == ["202609", "202608", "202607"]
    m = _months(engine)
    assert m[f"202609:{GA}"] == (34, 10, 3, 1, 5)          # 전입 30+4 · 전출 10 · 65+ 3/1 · 안쪽 5 (지표에서 제외)
    assert m[f"202609:{NA}"] == (10, 30, 1, 3, 0) and m[f"202609:{BUSAN}"] == (0, 4, 0, 0, 0)
    with engine.connect() as c:
        mp = dict(c.execute(text("SELECT adm_cd, mois_cd || '/' || match_method FROM mart.area_migration_map")).all())
        orphan = c.execute(text("""SELECT target_key FROM ops.dq_issue WHERE collect_run_id = :r
                                   AND check_code = 'MIGR_UNMATCHED'"""), {"r": rid}).scalars().all()
    assert mp == {"99010": f"{GA}/KOSIS_CD", "99020": f"{NA}/KOSIS_CD"}
    assert orphan == [BUSAN]                               # 어느 시군구에도 대응되지 않은 원천 단위
    # 다시 실행 — 받을 달도 대응 변화도 없으면 changed=False (워커가 재계산을 넣지 않음)
    log.clear()
    _, changed, st, stats = _collect(monkeypatch, log)
    assert st == "DONE" and not changed and log == [] and stats["pending"] == []


def test_limit_stop_keeps_received_months_and_resumes(clean, engine, monkeypatch):
    _setup_areas(engine)
    log: list = []
    stop = DataGoStop("MOIS_MIGR 중단 (코드 22): LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR")
    _, changed, st, stats = _collect(monkeypatch, log, fail=lambda ym, p: stop if (ym, p) == ("202608", 2) else False)
    assert st == "PARTIAL" and changed and stats["months"] == ["202609"] and "코드 22" in stats["stoppedBy"]
    assert {k.split(":")[0] for k in _months(engine)} == {"202609"}       # 멈춘 달은 반쯤 넣지 않음
    log.clear()
    _, _, st, stats = _collect(monkeypatch, log)                           # 다음 실행이 DB 상태로 이어받음
    assert st == "DONE" and stats["months"] == ["202608", "202607"] and ("202609", 1) not in log


def test_newest_month_not_published_is_not_failure(clean, engine, monkeypatch):
    _setup_areas(engine)
    _, _, st, stats = _collect(monkeypatch, [], fail=lambda ym, p: {} if ym == "202609" else False)
    assert st == "DONE" and stats["notYet"] == ["202609"] and stats["months"] == ["202608", "202607"]


def test_failed_page_is_retried_before_giving_up_month(clean, engine, monkeypatch):
    """쪽 하나가 실패해도(시간 초과) 그 달 끝에 한 번 더 받아 성공하면 그 달을 넣음 — 첫 백필에서 쪽 하나 때문에 9개월을 버렸음."""
    _setup_areas(engine)
    tries: dict = {}

    def flaky(ym, p):
        tries[(ym, p)] = tries.get((ym, p), 0) + 1
        return None if (ym, p) == ("202608", 2) and tries[(ym, p)] == 1 else False

    _, _, st, stats = _collect(monkeypatch, [], fail=flaky)
    assert st == "DONE" and "202608" in stats["months"] and stats["perMonth"]["202608"]["retried"] == 1
    assert _months(engine)[f"202608:{GA}"] == (34, 10, 3, 1, 5)


@pytest.mark.parametrize("how", ["page_fail", "count_mismatch", "empty_old_month"])
def test_incomplete_month_keeps_existing(clean, engine, monkeypatch, how):
    """다시 받는 달(공표 직후 받은 202607)이 일부 실패·건수 불일치·빈 응답이면 기존 값을 그대로 둠."""
    _setup_areas(engine)
    with engine.begin() as c:
        c.execute(text("""INSERT INTO mart.migration_month (mois_cd, ref_ym, ctpv_nm, sgg_nm, in_cnt, out_cnt, in_aged65,
                              out_aged65, intra_cnt, loaded_at) VALUES (:cd, '202607', '서울특별시', '가구', 99, 99, 9, 9, 9,
                              '2026-08-15T00:00:00+09:00')"""), {"cd": GA})
    kw = {"page_fail": {"fail": lambda ym, p: None if (ym, p) == ("202607", 2) else False},
          "count_mismatch": {"total_extra": 1},
          "empty_old_month": {"fail": lambda ym, p: {} if ym == "202607" else False}}[how]
    rid, _, st, stats = _collect(monkeypatch, [], **kw)
    assert "202607" in stats["failedMonths"]
    assert _months(engine)[f"202607:{GA}"] == (99, 99, 9, 9, 9)
    assert st == ("FAILED" if how == "count_mismatch" else "PARTIAL")   # 건수 불일치는 모든 달이 실패
    with engine.connect() as c:
        assert c.execute(text("""SELECT count(*) FROM ops.dq_issue WHERE collect_run_id = :r
                                 AND check_code = 'FETCH_FAILED'"""), {"r": rid}).scalar_one() >= 1


def test_sido_recode_keeps_area_continuous(terrain, engine, monkeypatch):
    """시도 코드만 바뀐 개편(광주·전남 → 전남광주통합특별시 같은): 옛 코드 6월까지 + 새 코드 7월부터를 한 단위로 이어 12개월 지표를 만듦."""
    old_cd, new_cd, other = "1111000000", "1211000000", "2611000000"
    months = [f"2025{m:02d}" for m in range(9, 13)] + [f"2026{m:02d}" for m in range(1, 10)]
    with engine.begin() as c:
        c.execute(text("""INSERT INTO mart.area_resident_pop (adm_cd, stat_year, ref_period, tot_ppltn, aged65_ppltn,
                              aged65_ratio, kosis_cd, match_method) VALUES ('99010', 2024, '202412', 1000, 100, 10, '11110', 'NAME')"""))
        for ym in months:
            cd, ctpv = (old_cd, "서울특별시") if ym <= "202606" else (new_cd, "통합특별시")
            for unit, nm, i_, o in ((cd, "지역99010", 10, 20), (other, "중구", 20, 10)):
                c.execute(text("""INSERT INTO mart.migration_month (mois_cd, ref_ym, ctpv_nm, sgg_nm, in_cnt, out_cnt,
                                      in_aged65, out_aged65, intra_cnt) VALUES (:u, :ym, :c, :nm, :i, :o, 0, 0, 0)"""),
                          {"u": unit, "ym": ym, "c": ctpv if unit == cd else "부산광역시", "nm": nm, "i": i_, "o": o})
    log: list = []
    _, changed, st, stats = _collect(monkeypatch, log)            # 받을 달 없음 — 별칭·대응표만 다시
    assert log == [] and st == "DONE" and changed and stats["recoded"] == 1
    with engine.connect() as c:
        assert c.execute(text("SELECT mois_cd, unit_cd, from_ym FROM mart.migration_unit_alias")).all() == \
            [(old_cd, new_cd, "202607")]
        assert c.execute(text("SELECT mois_cd, match_method FROM mart.area_migration_map WHERE adm_cd = '99010'")).one() == \
            (new_cd, "KOSIS_CD")                                   # KOSIS 코드(경계 연도)로 옛 코드를 찾고 최신 코드로
    rid = run_calc(stat_year=2024, levels=[2])
    assert _metric(engine, rid)[("99010", "NET_OUT_12M_PER_1K")] == 120.0      # (20 − 10) × 12 ÷ 1000 × 1000
    from atlas.api.main import app

    with TestClient(app) as cl:
        d = cl.get("/api/v1/areas/99010").json()["migration"]
    assert (d["inCnt"], d["outCnt"], d["basis"]) == (120, 240, "AREA")


# ------------------------------------------------------------------------------------------------ 계산 · API
U1, U2, U3 = "9901000000", "9902000000", "9903000000"


def _seed_trend(engine, months_u2=11):
    """terrain 4개 지역: A→U1, B→U2(11개월만), C·D→U3(일반구 — 시 전체). 202509~202609 13개월, 가장 오래된 달은 창 밖."""
    with engine.begin() as c:
        for cd, tot, aged in (("99010", 1000, 100), ("99020", 2000, 200), ("99030", 3000, 300), ("99040", 4000, 400)):
            c.execute(text("""INSERT INTO mart.area_resident_pop (adm_cd, stat_year, ref_period, tot_ppltn, aged65_ppltn,
                                  aged65_ratio, match_method) VALUES (:cd, 2024, '202412', :t, :a, 10, 'NAME')"""),
                      {"cd": cd, "t": tot, "a": aged})
        for adm, unit, how in (("99010", U1, "KOSIS_CD"), ("99020", U2, "KOSIS_CD"), ("99030", U3, "CITY"),
                               ("99040", U3, "CITY")):
            c.execute(text("""INSERT INTO mart.area_migration_map (stat_year, adm_cd, mois_cd, match_method)
                              VALUES (2024, :a, :u, :h)"""), {"a": adm, "u": unit, "h": how})
        months = [f"2025{m:02d}" for m in range(9, 13)] + [f"2026{m:02d}" for m in range(1, 10)]
        for i, ym in enumerate(months):
            rows = [(U1, 1000 if i == 0 else 10, 20, 1, 0), (U3, 30, 10, 2, 4)]
            if i >= len(months) - months_u2:
                rows.append((U2, 5, 5, 0, 0))
            for unit, i_, o, i65, o65 in rows:
                c.execute(text("""INSERT INTO mart.migration_month (mois_cd, ref_ym, ctpv_nm, sgg_nm, in_cnt, out_cnt,
                                      in_aged65, out_aged65, intra_cnt) VALUES (:u, :ym, '시도', :nm, :i, :o, :i65, :o65, 0)"""),
                          {"u": unit, "ym": ym, "nm": "가시" if unit == U3 else "구", "i": i_, "o": o, "i65": i65, "o65": o65})


def _metric(engine, rid):
    with engine.connect() as c:
        return {(a, m): float(v) for a, m, v in c.execute(text("""SELECT adm_cd, metric_code, value FROM mart.access_metric
                    WHERE calc_run_id = :r AND metric_code IN ('NET_OUT_12M_PER_1K', 'AGED65_NET_IN_12M_PER_1K')"""),
                    {"r": rid})}


def test_migration_metrics(terrain, engine):
    _seed_trend(engine)
    rid = run_calc(stat_year=2024, levels=[2])
    m = _metric(engine, rid)
    # U1: (20 − 10) × 12 ÷ 1000 × 1000 = 120 (창 밖 202509 의 전입 1000 은 빠짐) · 65+: (1 − 0) × 12 ÷ 100 × 1000 = 120
    assert m[("99010", "NET_OUT_12M_PER_1K")] == 120.0 and m[("99010", "AGED65_NET_IN_12M_PER_1K")] == 120.0
    # U3(시 단위): (10 − 30) × 12 ÷ (3000 + 4000) × 1000 = −34.29 — 구 둘 다 같은 시 전체 값
    assert m[("99030", "NET_OUT_12M_PER_1K")] == m[("99040", "NET_OUT_12M_PER_1K")] == -34.29
    assert m[("99030", "AGED65_NET_IN_12M_PER_1K")] == -34.29                 # (2 − 4) × 12 ÷ 700 × 1000
    assert ("99020", "NET_OUT_12M_PER_1K") not in m                           # 11개월뿐인 단위 → 값 없음
    with engine.connect() as c:
        stats = c.execute(text("SELECT stats FROM mart.calc_run WHERE calc_run_id = :r"), {"r": rid}).scalar_one()
        dq = c.execute(text("""SELECT target_key FROM ops.dq_issue WHERE calc_run_id = :r
                               AND check_code = 'MIGR_WINDOW_INCOMPLETE'"""), {"r": rid}).scalars().all()
        rnk = c.execute(text("""SELECT adm_cd, rnk FROM mart.access_metric WHERE calc_run_id = :r
                                AND metric_code = 'NET_OUT_12M_PER_1K' ORDER BY rnk"""), {"r": rid}).all()
    assert stats["migrationWindow"] == {"from": "202510", "to": "202609"} and dq == ["99020"]
    assert rnk[0] == ("99010", 1)                                             # 순유출이 큰 곳이 1위


def test_migration_window_incomplete_disables_metrics(terrain, engine):
    _seed_trend(engine)
    with engine.begin() as c:
        c.execute(text("DELETE FROM mart.migration_month WHERE ref_ym = '202603'"))   # 가운데 한 달이 빔
    rid = run_calc(stat_year=2024, levels=[2])
    assert _metric(engine, rid) == {}
    with engine.connect() as c:
        stats = c.execute(text("SELECT stats FROM mart.calc_run WHERE calc_run_id = :r"), {"r": rid}).scalar_one()
        dq = c.execute(text("""SELECT target_key, detail FROM ops.dq_issue WHERE calc_run_id = :r
                               AND check_code = 'MIGR_WINDOW_INCOMPLETE'"""), {"r": rid}).all()
    assert stats["migrationWindow"] is None and dq == [("202509~202609", {"months": 12})]


def test_migration_api_blocks(terrain, engine):
    _seed_trend(engine)
    run_calc(stat_year=2024, levels=[2])
    from atlas.api.main import app

    with TestClient(app) as cl:
        d = cl.get("/api/v1/areas/99030").json()["migration"]
        assert d["refFrom"] == "202510" and d["refTo"] == "202609" and d["basis"] == "CITY" and d["basisName"] == "가시"
        assert (d["inCnt"], d["outCnt"], d["netOut"], d["aged65NetIn"]) == (360, 120, -240, -24)
        assert cl.get("/api/v1/areas/99010").json()["migration"]["basis"] == "AREA"
        assert cl.get("/api/v1/areas/99020").json()["migration"] is None         # 12개월이 안 됨
        rep = cl.get("/api/v1/areas/99010/report").json()
        assert rep["area"]["migration"]["netOut"] == 120
        assert any(x["code"] == "NET_OUT_12M_PER_1K" for x in rep["metrics"])
        close = cl.post("/api/v1/plan/close", json={"scope": "99", "k": 1}).json()
        st = close["steps"][0]
        want = {"99010": 120.0, "99030": -34.29, "99040": -34.29}.get(
            {terrain["F1"]: "99010", terrain["F2"]: "99020", terrain["F3"]: "99030"}[st["histId"]])
        assert st["netOutPer1k"] == want and "netOutPct" in st
        assert all("netOutPer1k" in r for r in close["leastImpact"] + close["mostCritical"])
        opened = cl.post("/api/v1/plan/open", json={"scope": "99", "k": 1}).json()
        assert "netOutPer1k" in opened["steps"][0]
        defs = {x["code"]: x for x in cl.get("/api/v1/metrics").json()["items"]}
        assert defs["NET_OUT_12M_PER_1K"]["available"] and defs["AGED65_NET_IN_12M_PER_1K"]["available"]
        assert defs["NET_OUT_12M_PER_1K"]["levels"] == [2]                      # 시군구만 — 화면이 읍면동에서 안내
