"""계산 설정·요청 파라미터 해석 (domain/params.py)."""
import uuid

import pytest

from atlas.domain.errors import Invalid
from atlas.domain.params import MAX_PAGE, far_meters, page_params, parse_uuid, pick_level


def test_far_meters():
    assert far_meters({}) == 2000
    assert far_meters({"farKm": 3}) == 3000
    assert far_meters({"farKm": "1.5"}) == 1500


def test_pick_level():
    assert pick_level({"levels": [2, 3]}, None) == 3
    assert pick_level({"levels": [2, 3]}, 2) == 2
    assert pick_level({}, None) == 2
    with pytest.raises(Invalid, match="level 3"):
        pick_level({"levels": [2]}, 3)


def test_parse_uuid_and_page():
    u = uuid.uuid4()
    assert parse_uuid(str(u)) == u and parse_uuid(None) is None and parse_uuid("") is None
    with pytest.raises(Invalid, match="whatIfId"):
        parse_uuid("x", "whatIfId")
    assert page_params(3, 20) == (3, 20, 40)
    for page, size in ((0, 20), (MAX_PAGE + 1, 20), (1, 0), (1, 201)):
        with pytest.raises(Invalid):
            page_params(page, size)
    assert page_params(1, 5000, cap=5000)[1] == 5000


def test_parse_bbox():
    from atlas.domain.params import parse_bbox

    assert parse_bbox("126.9,37.5,127.1,37.6") == (126.9, 37.5, 127.1, 37.6)
    for bad in ("1,2,3", "1,2,3,4,5", "a,b,c,d", ""):
        with pytest.raises(Invalid, match="bbox"):
            parse_bbox(bad)
