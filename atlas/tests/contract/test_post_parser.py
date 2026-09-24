"""우체국 XML 계약 테스트 — 명세 구조 표본 + (있으면) 스모크에서 저장한 실제 응답."""
from datetime import date
from pathlib import Path

import pytest

from atlas.collector.post.parser import normalize_item, parse_post_xml

HERE = Path(__file__).parent
REAL = HERE.parents[2] / "fixtures" / "post_area_100_p1.xml"


def test_sample_header_and_items():
    page = parse_post_xml((HERE / "fixtures" / "post_area_sample.xml").read_bytes())
    assert page.error is None
    assert (page.total_count, page.total_page, page.now_page) == (3, 1, 1)
    assert len(page.items) == 3


def test_field_mapping_snapshot():
    page = parse_post_xml((HERE / "fixtures" / "post_area_sample.xml").read_bytes())
    a, b, c = (normalize_item(i, "100") for i in page.items)
    assert {k: a[k] for k in ("post_id", "post_div", "name", "lat", "lon", "finance_time", "lunch_yn",
                              "post365_yn", "area_code", "mod_dt", "fin_available", "is_center")} == {
        "post_id": "110001", "post_div": 0, "name": "가상중앙우체국", "lat": 37.5636, "lon": 126.9815,
        "finance_time": "09:00~16:30", "lunch_yn": "N", "post365_yn": "Y", "area_code": "100",
        "mod_dt": date(2024, 3, 2), "fin_available": True, "is_center": False}
    # 소문자 lunchtime 수용, 'null' → None, 00:00~00:00 → 금융 불가
    assert b["lunch_time"] == "12:00~13:00" and b["tel"] is None and b["fin_available"] is False
    # 빈 위도 → None (행은 유지, DQ 가 COORD_NULL 로 잡음)
    assert c["lat"] is None and c["lon"] == 126.98 and c["post_time"] is None and c["finance_time"] is None


@pytest.mark.parametrize("body, needle", [
    (b"", "EMPTY_BODY"),
    (b"<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
     b"<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode>"
     b"</cmmMsgHeader></OpenAPI_ServiceResponse>", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"),
    (b"<html><body>error</body></html>", "UNEXPECTED_RESPONSE"),
])
def test_error_responses(body, needle):
    assert needle in (parse_post_xml(body).error or "")


def test_zero_result_is_not_error():
    xml = b"<postListResponse><postMsgHeader><totalCount>0</totalCount><totalPage>0</totalPage></postMsgHeader></postListResponse>"
    page = parse_post_xml(xml)
    assert page.error is None and page.total_count == 0 and page.items == []


@pytest.mark.skipif(not REAL.exists(), reason="make smoke 로 실제 응답을 저장하면 실행됩니다")
def test_real_smoke_response():
    page = parse_post_xml(REAL.read_bytes())
    assert page.error is None, page.error
    assert page.items, "실제 응답에 postItem 이 없습니다"
    rec = normalize_item(page.items[0], "100")
    assert rec["post_id"] and rec["name"]
    assert rec["lat"] is not None and 33 <= rec["lat"] <= 39
