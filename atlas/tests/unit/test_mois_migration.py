"""행정안전부 인구이동 — 응답 해석·달 계산·SGIS 시군구 대응 (순수 함수, ADR-028)."""
import json
from datetime import date
from pathlib import Path

import pytest

from atlas.collector.datago.client import _error_of
from atlas.collector.mois.migration import AreaRef, UnitSpan, match_units, sido_recodes
from atlas.domain.migration import (UnitMonth, add_rows, aged65, merge, month_add, needs_recheck,
                                    recent_months)

SAMPLE = Path(__file__).parents[1] / "contract" / "fixtures" / "mois_migration_sample.json"


def _items():
    return json.loads(SAMPLE.read_text())["Response"]["items"]["item"]


def _row(mvin, mvt, tot, old=0, ym="202508", names=("서울특별시", "가구", "서울특별시", "나구")):
    """합성 행 — 65세 이상 old 명을 만 70세 남자에 넣음."""
    return {"statsYm": ym, "mvinAdmmCd": mvin, "mvtAdmmCd": mvt, "mvinCtpvNm": names[0], "mvinSggNm": names[1],
            "mvtCtpvNm": names[2], "mvtSggNm": names[3], "totNmprCnt": str(tot), "male70AgeNmprCnt": str(old),
            "male30AgeNmprCnt": str(tot - old)}


def test_real_response_envelope_and_fields():
    """실응답 봉투 Response.head/items — 결과코드 '0' 을 두 자리로 맞춰 정상으로 봄."""
    body = SAMPLE.read_text()
    assert _error_of(200, body) == ("00", "NORMAL_SERVICE")
    assert _error_of(200, '{"Response":{"head":{"resultCode":"3","resultMsg":"NODATA_ERROR"}}}') == ("03", "NODATA_ERROR")
    assert _error_of(200, '{"Response":{"head":{"resultCode":"10","resultMsg":"INVALID"}}}')[0] == "10"
    it = _items()[0]
    assert {"statsYm", "mvinAdmmCd", "mvtAdmmCd", "mvinSggNm", "mvtSggNm", "totNmprCnt",
            "male65AgeNmprCnt", "male110AgeNmprCnt", "feml0AgeNmprCnt", "feml110AgeNmprCnt"} <= set(it)


def test_aged65_sums_65_to_110_both_sexes():
    a, b, c = _items()
    assert (aged65(a), aged65(b), aged65(c)) == (32, 3, 5)          # 손으로 센 실응답 값
    assert aged65({"male64AgeNmprCnt": "9", "male65AgeNmprCnt": "1", "feml110AgeNmprCnt ": "2"}) == 3   # 키 끝 공백(명세 표기)


def test_add_rows_real_sample_excludes_same_unit():
    acc: dict[str, UnitMonth] = {}
    st = add_rows(acc, _items(), "202508")
    assert st == {"rows": 3, "skipped": 0, "dup": 0}
    jongno = acc["1111000000"]
    assert (jongno.intra_cnt, jongno.in_cnt, jongno.in_aged65) == (241, 56 + 44, 3 + 5)   # 종로→종로는 안쪽 이동
    assert jongno.out_cnt == 0 and acc["1114000000"].out_cnt == 56 and acc["1117000000"].out_aged65 == 5
    assert (acc["1114000000"].ctpv_nm, acc["1114000000"].sgg_nm) == ("서울특별시", "중구")


def test_add_rows_skips_other_month_and_bad_codes_and_counts_duplicates():
    acc: dict[str, UnitMonth] = {}
    seen: set = set()
    st = add_rows(acc, [_row("1111000000", "1114000000", 10), _row("1111000000", "1114000000", 10),
                        _row("1111000000", "11140", 5), _row("1111000000", "1117000000", 7, ym="202507")],
                  "202508", seen)
    assert st == {"rows": 1, "skipped": 2, "dup": 1}
    assert acc["1111000000"].in_cnt == 10 and seen == {("1111000000", "1114000000")}


def test_merge_partial_sums():
    a = {"1": UnitMonth("서울", "가", in_cnt=1, out_cnt=2, in_aged65=1, intra_cnt=4)}
    merge(a, {"1": UnitMonth("서울", "가", in_cnt=10, out_aged65=3), "2": UnitMonth("부산", "나", out_cnt=5)})
    assert (a["1"].in_cnt, a["1"].out_cnt, a["1"].in_aged65, a["1"].out_aged65, a["1"].intra_cnt) == (11, 2, 1, 3, 4)
    assert a["2"].out_cnt == 5


def test_months():
    assert month_add("202601", -1) == "202512" and month_add("202512", 2) == "202602"
    assert recent_months(date(2026, 10, 19), 3) == ["202609", "202608", "202607"]   # 이번 달(10월)은 빼고
    assert len(recent_months(date(2026, 1, 5), 13)) == 13 and recent_months(date(2026, 1, 5), 13)[-1] == "202412"


@pytest.mark.parametrize("ym, loaded, today, want", [
    ("202609", date(2026, 10, 19), date(2026, 10, 27), False),   # 공표 직후 받음 — 아직 한 달이 안 지남
    ("202609", date(2026, 10, 19), date(2026, 11, 3), True),     # 11월이 되면 한 번 더
    ("202609", date(2026, 11, 3), date(2026, 11, 10), False),    # 다시 받은 뒤로는 굳은 달
    ("202508", date(2026, 10, 19), date(2026, 10, 19), False),   # 오래된 달은 처음부터 굳은 달
])
def test_needs_recheck_once(ym, loaded, today, want):
    assert needs_recheck(ym, loaded, today) is want


UNITS = {"1111000000": ("서울특별시", "종로구"), "4111000000": ("경기도", "수원시"), "4374000000": ("충청북도", "영동군"),
         "3611000000": ("세종특별자치시", "세종특별자치시"), "5113000000": ("강원특별자치도", "원주시"),
         "4119000000": ("경기도", "부천시")}


def test_match_units_methods():
    areas = [AreaRef("11010", "종로구", "서울특별시", "11110"),             # KOSIS 코드 그대로
             AreaRef("31011", "수원시 장안구", "경기도", "41111"),           # 일반구 → 시 (코드 앞 4자리)
             AreaRef("31012", "수원시 권선구", "경기도", None),              # KOSIS 없음 → 이름으로 시
             AreaRef("29010", "세종시", "세종특별자치시", "36110"),          # 이름이 달라도 코드로
             AreaRef("32020", "원주시", "강원특별자치도", "42130"),          # 옛 코드(42) → 이름
             AreaRef("33044", "증평군", "충청북도", "43745"),               # 43740 영동군에 붙으면 안 됨
             AreaRef("31050", "부천시 원미구", "경기도", "41192")]           # 구 부활(2024) — 원천은 시 단위
    got = match_units(areas, UNITS)
    assert got == {"11010": ("1111000000", "KOSIS_CD"), "31011": ("4111000000", "CITY"),
                   "31012": ("4111000000", "CITY"), "29010": ("3611000000", "KOSIS_CD"),
                   "32020": ("5113000000", "NAME"), "31050": ("4119000000", "CITY")}


MONTHS = ["202604", "202605", "202606", "202607", "202608", "202609"]


def test_sido_recode_links_whole_sido_with_same_names():
    """2026-07 광주(29)·전남(46) → 전남광주통합특별시(12): 옛 시도의 단위가 모두 6월에 끝나고 7월에 같은 이름으로 나타남 → 잇기.
    인천(28)은 일부 구만 바뀌어(넓이가 바뀜) 잇지 않음."""
    old, new = ("202604", "202606"), ("202607", "202609")
    spans = [UnitSpan("2911000000", "동구", *old), UnitSpan("2914000000", "서구", *old),
             UnitSpan("4611000000", "목포시", *old),
             UnitSpan("1221000000", "동구", *new), UnitSpan("1224000000", "서구", *new), UnitSpan("1211000000", "목포시", *new),
             UnitSpan("2811000000", "중구", *old), UnitSpan("2826000000", "서구", *old),          # 인천 — 일부만 사라짐
             UnitSpan("2817700000", "미추홀구", "202604", "202609"),
             UnitSpan("2812500000", "제물포구", *new), UnitSpan("2827500000", "서해구", *new),
             UnitSpan("1111000000", "종로구", "202604", "202609")]
    assert sido_recodes(spans, MONTHS) == {"2911000000": ("1221000000", "202607"), "2914000000": ("1224000000", "202607"),
                                           "4611000000": ("1211000000", "202607")}


def test_sido_recode_refuses_ambiguous_or_unfinished():
    old, new = ("202604", "202606"), ("202607", "202609")
    # 새 시도에 같은 이름이 없으면(시군구가 바뀜) 그 옛 시도는 잇지 않음
    assert sido_recodes([UnitSpan("2911000000", "동구", *old), UnitSpan("2914000000", "서구", *old),
                         UnitSpan("1221000000", "동구", *new)], MONTHS) == {}
    # 두 옛 단위가 같은 새 단위로 가면 잇지 않음 (옛 두 시도에 같은 이름)
    assert sido_recodes([UnitSpan("2911000000", "동구", *old), UnitSpan("3011000000", "동구", *old),
                         UnitSpan("1221000000", "동구", *new)], MONTHS) == {}
    # 받아 둔 마지막 달까지 있는 시도는 사라진 게 아님
    assert sido_recodes([UnitSpan("1111000000", "종로구", "202604", "202609")], MONTHS) == {}
    # 다음 달 사이에 빈 달이 있어도 받아 둔 다음 달 기준 (6월 자료가 아직 없을 때 5월 → 7월)
    assert sido_recodes([UnitSpan("2911000000", "동구", "202604", "202605"), UnitSpan("1221000000", "동구", *new)],
                        ["202604", "202605", "202607", "202608", "202609"]) == {"2911000000": ("1221000000", "202607")}
