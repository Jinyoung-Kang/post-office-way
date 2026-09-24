import pytest

from atlas.domain.rules import fin_available, is_center, row_hash


@pytest.mark.parametrize("div, ft, center, expected", [
    (0, "09:00~16:30", False, True),     # 총괄국
    (1, "09:00~16:30", False, True),     # 소속 우체국
    (1, "00:00~00:00", False, False),    # 우편취급국 예시 값 → 금융 미제공 (U-5)
    (1, None, False, False),
    (1, "휴무", False, False),
    (2, "09:00~16:30", False, False),    # 우체통
    (3, "00:00~24:00", False, False),    # 365코너 — 우체국이 아님
    (4, "09:00~16:30", False, False),    # 무인창구
    (1, "09:00~16:30", True, False),     # 우편집중국
    (None, "09:00~16:30", False, False),
])
def test_fin_available(div, ft, center, expected):
    assert fin_available(div, ft, center) is expected


def test_is_center():
    assert is_center("c01", None)
    assert is_center("C12", "무엇")
    assert is_center("100", "동서울우편집중국")
    assert not is_center("100", "서울중앙우체국")
    assert not is_center(None, None)


BASE = {"post_div": 1, "name": "서울중앙우체국", "addr": "서울 중구 소공로 70", "tel": "02-1234-5678",
        "lat": 37.5636, "lon": 126.9815, "post_time": "09:00~18:00", "finance_time": "09:00~16:30",
        "lunch_yn": "N", "lunch_time": None, "post365_yn": "Y", "area_code": "100", "mod_dt": None}


def test_row_hash_stable_and_sensitive():
    h = row_hash(BASE)
    assert len(h) == 64 and h == row_hash(dict(BASE))
    # 공백·부동소수 잡음은 같은 해시
    assert row_hash({**BASE, "name": " 서울중앙우체국  ", "lat": 37.56360000001}) == h
    # 업무 필드 하나라도 바뀌면 다른 해시
    for k, v in [("finance_time", "09:00~16:00"), ("lat", 37.5637), ("post365_yn", "N"), ("name", "서울중앙우체국2")]:
        assert row_hash({**BASE, k: v}) != h, k
    # 해시 대상이 아닌 필드는 무시
    assert row_hash({**BASE, "is_center": True, "fin_available": False}) == h


def test_split_sql_handles_trailing_comment():
    from atlas.core.db import split_sql

    sql = "-- 머리 주석\nSELECT 1;   -- 끝 주석\nSELECT 2\n  FROM t;\n"
    assert split_sql(sql) == ["SELECT 1;   -- 끝 주석".split(";")[0], "SELECT 2\n  FROM t"]
