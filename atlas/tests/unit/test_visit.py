"""⑥ 방문 여건 — 격자 변환·예보 값 해석·권역 매핑·판정 규칙(VISIT-1)·응답 계약."""
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from atlas.collector.weather.air import latest_by_day, parse_announced
from atlas.collector.weather.client import _error_of, items_of
from atlas.collector.weather.kma import latest_base, parse_items
from atlas.domain.visit import Hour, air_region, assess, latlon_to_grid, parse_amount, parse_inform_grade

FIX = Path(__file__).resolve().parents[1] / "contract" / "fixtures"


@pytest.mark.parametrize("lat,lon,grid", [
    (37.5665, 126.9780, (60, 127)),   # 서울시청 — 기상청 격자표
    (33.4996, 126.5312, (53, 38)),    # 제주시
    (35.1796, 129.0756, (98, 76)),    # 부산시청
])
def test_latlon_to_grid(lat, lon, grid):
    assert latlon_to_grid(lat, lon) == grid


@pytest.mark.parametrize("v,x", [("강수없음", 0.0), ("적설없음", 0.0), ("1mm 미만", 0.5), ("1.0mm", 1.0),
                                 ("30.0~50.0mm", 30.0), ("50.0mm 이상", 50.0), ("1cm 미만", 0.5), ("5.0cm 이상", 5.0),
                                 ("-", None), (None, None), ("-999", None)])
def test_parse_amount(v, x):
    assert parse_amount(v) == x


def test_air_region():
    assert air_region("11010", "종로구") == "서울"
    assert air_region("31101", "고양시 덕양구") == "경기북부"
    assert air_region("31130", "남양주시") == "경기북부"
    assert air_region("31011", "수원시 장안구") == "경기남부"
    assert air_region("32030", "강릉시") == "영동"
    assert air_region("32010", "춘천시") == "영서"
    assert air_region("38340", "고성군") == "경남"          # 경남 고성은 영동이 아님
    assert air_region("37520", "의성군") == "경북"
    assert air_region("99010", "지역") is None


def test_parse_inform_grade():
    g = parse_inform_grade("서울 : 보통,제주 : 좋음, 경기북부 : 나쁨,")
    assert g == {"서울": "보통", "제주": "좋음", "경기북부": "나쁨"}
    assert parse_inform_grade("") == {}


def _day(**kw):
    return [Hour(hour=h, tmp=kw.get("tmp", 20), pty=kw.get("pty", {}).get(h, 0), pcp_mm=kw.get("pcp", {}).get(h, 0),
                 sno_cm=kw.get("sno", {}).get(h, 0), wsd=kw.get("wsd", 2), pop=10) for h in range(0, 24)]


def test_assess_good_day():
    a = assess(_day())
    assert a.level == 0 and a.label == "좋음" and a.reasons == [] and a.summary["hours"] == 10


def test_assess_rules():
    assert assess(_day(pty={10: 1}, pcp={10: 0.5})).level == 1                       # 약한 비
    heavy = assess(_day(pty={10: 1, 11: 1}, pcp={10: 10, 11: 5}))                    # 시간당 10mm
    assert heavy.level == 2 and heavy.reasons[0]["code"] == "RAIN"
    assert assess(_day(tmp=31.5)).level == 1 and assess(_day(tmp=33)).level == 2
    assert assess(_day(tmp=-6)).level == 1 and assess(_day(tmp=-10)).level == 2
    assert assess(_day(wsd=9)).level == 1 and assess(_day(wsd=14)).level == 2
    snow = assess(_day(pty={9: 3, 10: 3}, sno={9: 0.5, 10: 1.0}))
    assert snow.level == 2 and [r["code"] for r in snow.reasons] == ["SNOW"]     # 눈만 오면 비로 중복 표시 안 함
    assert assess(_day(pty={20: 1}, pcp={20: 50})).level == 0                        # 운영 시간 밖 비는 제외


def test_assess_air_and_missing():
    a = assess(_day(), pm10="나쁨", pm25="매우나쁨")
    assert a.level == 2 and [r["code"] for r in a.reasons] == ["PM25", "PM10"]
    assert assess([], pm10="나쁨").level is None                                      # 날씨 예보가 없으면 판정 안 함


def test_latest_base():
    assert latest_base(datetime(2026, 9, 24, 5, 9)) == datetime(2026, 9, 24, 2)
    assert latest_base(datetime(2026, 9, 24, 5, 10)) == datetime(2026, 9, 24, 5)
    assert latest_base(datetime(2026, 9, 24, 23, 59)) == datetime(2026, 9, 24, 23)
    assert latest_base(datetime(2026, 9, 24, 1, 0)) == datetime(2026, 9, 23, 23)


def test_kma_contract_fixture():
    body = json.loads((FIX / "kma_vilage_sample.json").read_text())["response"]["body"]
    hours = parse_items(items_of(body))
    h = hours[datetime(2026, 9, 25, 12)]
    assert h["pty"] == 1 and h["pcp_mm"] == 30.0 and h["wsd"] == 9.5 and h["sky"] == 4
    assert hours[datetime(2026, 9, 24, 9)]["pcp_mm"] == 0.0
    day2 = assess([Hour(hour=at.hour, **{k: v for k, v in x.items() if k != "sky"})
                   for at, x in hours.items() if at.date() == date(2026, 9, 25)])
    assert day2.level == 2 and day2.summary["pcpMm"] == 36.5


def test_air_contract_fixture():
    body = json.loads((FIX / "air_frcst_pm10_sample.json").read_text())["response"]["body"]
    best = latest_by_day(items_of(body))
    assert set(best) == {(date(2026, 9, 24), "PM10"), (date(2026, 9, 25), "PM10")}   # 빈 모레 등급은 제외
    today = best[(date(2026, 9, 24), "PM10")]
    assert today["announced_at"] == datetime(2026, 9, 24, 11) and today["grades"]["서울"] == "보통"
    assert best[(date(2026, 9, 25), "PM10")]["grades"]["충북"] == "매우나쁨"
    assert parse_announced("2026-09-24 5시 발표") == datetime(2026, 9, 24, 5)


def test_error_envelopes():
    gw = '{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"errMsg":"SERVICE_KEY_IS_NOT_REGISTERED_ERROR","returnReasonCode":"30"}}}'
    assert _error_of(403, gw) == ("30", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR")
    xml = "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg><returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg><returnReasonCode>22</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
    assert _error_of(200, xml)[0] == "22"
    assert _error_of(200, '{"response":{"header":{"resultCode":"03","resultMsg":"NO_DATA"}}}') == ("03", "NO_DATA")
    assert _error_of(502, "Bad Gateway") == (None, "HTTP 502")
