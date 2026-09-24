"""KOSIS ↔ SGIS 행정구역 매칭 — 실데이터에서 발견한 사례를 그대로 표로 검증."""
from atlas.collector.kosis.matching import (KosisTree, SgisArea, aged_codes, infer_parent, kosis_keys, match,
                                            norm)
from atlas.collector.kosis.pipeline import aggregate


def test_aged_codes_from_real_meta():
    items = [("0", "계"), ("5", "0 - 4세"), ("65", "60 - 64세"), ("70", "65 - 69세"), ("75", "70 - 74세"),
             ("100", "95 - 99세"), ("105", "100+")]
    assert aged_codes(items) == ("0", ["70", "75", "100", "105"])


def test_norm_and_je_keys():
    assert norm("수원시 장안구") == "수원시장안구"
    assert kosis_keys("창신제1동") == ["창신제1동", "창신1동"]
    assert kosis_keys("홍제제1동") == ["홍제제1동", "홍제1동"]      # '홍제' 의 제는 남김
    assert kosis_keys("홍제1동")[0] == "홍제1동"           # 원래 이름이 첫 키(매칭에서 우선)
    assert kosis_keys("제기동") == ["제기동"]                        # 숫자 앞이 아닌 '제'
    assert kosis_keys("종로1·2·3·4가동") == ["종로1234가동"]


def test_infer_parent():
    names = {"41110": "수원시", "41111": "장안구", "43740": "영동군", "43745": "증평군", "11110": "종로구"}
    assert infer_parent("41111", names) == "41110"       # 구가 있는 시
    assert infer_parent("43745", names) == "43"          # 영동군 아래가 아님 (이름이 '…시' 가 아님)
    assert infer_parent("11110", names) == "11"
    assert infer_parent("1111051500", names) == "11110"
    assert infer_parent("11", names) is None


def _tree(rows):
    names = {c: n for c, n in rows}
    return KosisTree.build([(c, n, infer_parent(c, names)) for c, n in rows])


def test_match_city_gu_je_single_and_suffix():
    tree = _tree([("11", "서울특별시"), ("11410", "서대문구"), ("1141061000", "홍제제1동"),
                  ("1141062000", "창천동"), ("1141063000", "홍1동"),     # 가상: 대체 키와 같은 실제 이름
                  ("41", "경기도"), ("41110", "수원시"), ("41111", "장안구"), ("4111156000", "파장동"),
                  ("36", "세종특별자치시"), ("36110", "세종특별자치시"), ("3611025000", "조치원읍"),
                  ("45", "전북특별자치도"), ("45113", "덕진구"), ("45110", "전주시"), ("4511362000", "금암1동")])
    sgis = [SgisArea("11130", "서대문구", 2, "11"), SgisArea("11130710", "홍제1동", 3, "11130"),
            SgisArea("31011", "수원시 장안구", 2, "31"), SgisArea("31011540", "파장동", 3, "31011"),
            SgisArea("29010", "세종시", 2, "29"), SgisArea("29010250", "조치원읍", 3, "29010"),
            SgisArea("35012", "전주시 덕진구", 2, "35"), SgisArea("35012580", "덕진구 금암1동", 3, "35012"),
            SgisArea("11130999", "없는동", 3, "11130"), SgisArea("11130720", "홍1동", 3, "11130")]
    sido_names = {"11": "서울특별시", "31": "경기도", "29": "세종특별자치시", "35": "전북특별자치도"}
    kosis_sidos = {"11": "서울특별시", "41": "경기도", "36": "세종특별자치시", "45": "전북특별자치도"}
    got = match(tree, sido_names, sgis, kosis_sidos)
    assert got["11130"] == ("11410", "NAME")
    assert got["11130710"] == ("1141061000", "NAME")    # 홍제제1동 ↔ 홍제1동
    assert got["31011"] == ("41111", "NAME")            # 수원시 장안구
    assert got["31011540"] == ("4111156000", "NAME")
    assert got["29010"] == ("36110", "SINGLE")          # 세종: 이름 체계가 달라 1:1 로 짝지음
    assert got["29010250"] == ("3611025000", "NAME")
    assert got["35012580"] == ("4511362000", "NAME")    # SGIS 이름에 구가 붙은 경우
    assert got["11130720"] == ("1141063000", "NAME")    # 실제 이름이 대체 키보다 우선
    assert "11130999" not in got


def test_aggregate_sums_65_plus():
    rows = [{"C1": "11110", "C2": "0", "DT": "140000", "PRD_DE": "202412", "C1_NM": "종로구"},
            {"C1": "11110", "C2": "70", "DT": "9,000", "PRD_DE": "202412"},
            {"C1": "11110", "C2": "105", "DT": "100", "PRD_DE": "202412"},
            {"C1": "11", "C2": "0", "DT": "9000000", "PRD_DE": "202412"}]
    out = aggregate(rows, "0", ["70", "105"])
    assert out["11110"]["tot"] == 140000 and out["11110"]["aged65"] == 9100
    assert out["11"]["aged65"] is None       # 65+ 구간이 안 오면 0 이 아니라 '모름'
