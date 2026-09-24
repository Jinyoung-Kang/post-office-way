"""SCD2 병합 멱등성(FR-106) · 우편 DQ 규칙 양/음성(FR-601) · 우체국 수집 파이프라인(모의 HTTP)."""

import httpx
import pytest
from sqlalchemy import text

from atlas.collector import runs
from atlas.collector.post.parser import normalize_item
from atlas.collector.post.pipeline import _INSERT_STG, _merge_hist, _run_post_dq
from atlas.collector.dq.rules import DQRecorder

pytestmark = pytest.mark.db


def item(pid="P1", **kw):
    base = {"postid": pid, "postdiv": "1", "postnm": f"우체국{pid}", "postaddr": "충북 괴산군 괴산읍 1",
            "postlat": "36.81", "postlon": "127.79", "posttime": "09:00~18:00",
            "postfinancetime": "09:00~16:30", "lunchtimeyn": "N", "post365yn": "N", "moddt": "2025-01-01"}
    base.update({k.lower(): v for k, v in kw.items()})
    return base


def load(engine, items, code="367"):
    rid = runs.start_run("POST_AREA", check_running=False)
    with engine.begin() as c:
        for it in items:
            c.execute(_INSERT_STG, {"run": rid, **normalize_item(it, code)})
        merge = _merge_hist(c, rid, [code])
    return rid, merge


def current(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT post_id, finance_time FROM mart.post_facility_hist WHERE is_current ORDER BY 1")).all()


def test_scd2_idempotent_change_and_close(clean, engine):
    _, m1 = load(engine, [item("P1"), item("P2")])
    assert m1["newHistRows"] == 2
    _, m2 = load(engine, [item("P1"), item("P2")])
    assert m2["newHistRows"] == 0                                     # 같은 데이터 재수집 → 새 이력 0
    _, m3 = load(engine, [item("P1", postFinanceTime="09:00~16:00"), item("P2")])
    assert m3["newHistRows"] == 1                                     # 한 필드 변경 → 1
    assert current(engine) == [("P1", "09:00~16:00"), ("P2", "09:00~16:30")]
    _, m4 = load(engine, [item("P1", postFinanceTime="09:00~16:00")])
    assert m4["currentAfter"] == 1                                    # P2 사라짐 → 이력 닫힘
    with engine.connect() as c:
        hist = c.execute(text("SELECT count(*), count(*) FILTER (WHERE valid_to IS NOT NULL) FROM mart.post_facility_hist")).one()
    assert tuple(hist) == (3, 2)


def test_failed_code_does_not_close(clean, engine):
    load(engine, [item("P1")], code="367")
    rid = runs.start_run("POST_AREA", check_running=False)
    with engine.begin() as c:   # 367 이 실패해 done_codes 에 없으면 P1 은 유지
        m = _merge_hist(c, rid, ["100"])
    assert m["currentAfter"] == 1


def test_post_dq_rules(clean, engine):
    rid = runs.start_run("POST_AREA", check_running=False)
    rows = [item("OK"), item("NULLC", postLat=""), item("OUT", postLat="45.0"),
            item("BADT", postFinanceTime="9시~4시"), item("OLD", modDt="2018-05-30"),
            item("BOX", postDiv="2", postFinanceTime="이상한값")]  # 우체통은 시간 규칙 대상 아님
    dq = DQRecorder(collect_run_id=rid)
    with engine.begin() as c:
        for it in rows:
            c.execute(_INSERT_STG, {"run": rid, **normalize_item(it, "367")})
        _run_post_dq(c, dq, rid)
        counts = dq.record_checks(c, ("COORD_NULL", "COORD_OUT_OF_KR", "TIME_FORMAT", "STALE_MOD_DT"))
        keys = dict(c.execute(text("SELECT check_code, string_agg(target_key, ',') FROM ops.dq_issue "
                                   "WHERE collect_run_id = :r GROUP BY 1"), {"r": rid}).all())
    assert counts == {"COORD_NULL": 1, "COORD_OUT_OF_KR": 1, "TIME_FORMAT": 1, "STALE_MOD_DT": 1}
    assert keys == {"COORD_NULL": "NULLC", "COORD_OUT_OF_KR": "OUT", "TIME_FORMAT": "BADT", "STALE_MOD_DT": "OLD"}


XML = """<postListResponse><postMsgHeader><totalCount>{total}</totalCount><totalPage>{pages}</totalPage>
<nowPage>{page}</nowPage></postMsgHeader>{items}</postListResponse>"""
ITEM = ("<postItem><postId>{pid}</postId><postDiv>1</postDiv><postNm>우체국{pid}</postNm><postLat>36.8</postLat>"
        "<postLon>127.8</postLon><postFinanceTime>09:00~16:30</postFinanceTime></postItem>")


def test_collect_pipeline_pagination_failure_and_resume(clean, engine, monkeypatch, tmp_path):
    """코드 100: 2페이지(51건) · 코드 200: 계속 500 → PARTIAL · 재개 시 200 만 다시 호출."""
    from atlas.collector import http as http_mod
    from atlas.collector.post import pipeline, seed
    from atlas.core import config

    monkeypatch.setenv("POST_SERVICE_KEY", "TESTKEY+/=")
    monkeypatch.setenv("POST_CALL_DELAY_MS", "0")
    config.get_settings.cache_clear()
    monkeypatch.setattr(config.get_settings(), "seed_dir", str(tmp_path))
    seed.write_area_codes([seed.AreaCode("100"), seed.AreaCode("200")])
    state = {"fail200": True, "calls": []}

    def handler(req: httpx.Request):
        code, page = req.url.params["postOffiId"], int(req.url.params["nowPage"])
        state["calls"].append((code, page))
        if code == "200" and state["fail200"]:
            return httpx.Response(500)
        if code == "200":
            return httpx.Response(200, text=XML.format(total=1, pages=1, page=1, items=ITEM.format(pid="B1")))
        n = 50 if page == 1 else 1
        items = "".join(ITEM.format(pid=f"A{(page - 1) * 50 + i}") for i in range(n))
        return httpx.Response(200, text=XML.format(total=51, pages=2, page=page, items=items))

    orig_init = http_mod.Fetcher.__post_init__

    def patched(self):
        orig_init(self)
        self._client = httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(http_mod.Fetcher, "__post_init__", patched)
    rid = pipeline.collect_post(sleep=lambda s: None)
    with engine.connect() as c:
        st, stats = c.execute(text("SELECT status, stats FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).one()
        raw_leak = c.execute(text("SELECT count(*) FROM raw.api_response WHERE request_url_masked LIKE '%TESTKEY%' "
                                  "OR params::text LIKE '%TESTKEY%' OR body LIKE '%TESTKEY%'")).scalar_one()
    assert st == "PARTIAL" and stats["failedCodes"] == ["200"] and stats["rows"] == 51
    assert raw_leak == 0                                               # FR-103 키 평문 0건
    state["fail200"], state["calls"] = False, []
    pipeline.collect_post(resume=rid, sleep=lambda s: None)
    assert {c for c, _ in state["calls"]} == {"200"}                  # 이미 끝난 100 은 다시 안 부름
    with engine.connect() as c:
        st, stats = c.execute(text("SELECT status, stats FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).one()
        n = c.execute(text("SELECT count(*) FROM mart.post_facility_hist WHERE is_current")).scalar_one()
    assert st == "DONE" and stats["failedCodes"] == [] and n == 52
    config.get_settings.cache_clear()
