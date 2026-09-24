import pytest

from atlas.domain.timeparse import is_valid_format, parse_range


@pytest.mark.parametrize("s, start, end", [
    ("09:00~18:00", 540, 1080),
    ("9:00 ~ 18:00", 540, 1080),
    ("09:00-16:30", 540, 990),
    ("0900~1800", 540, 1080),
    ("00:00~00:00", 0, 0),
    ("00:00~24:00", 0, 1440),
])
def test_parse_valid(s, start, end):
    tr = parse_range(s)
    assert tr is not None and (tr.start_min, tr.end_min) == (start, end)


@pytest.mark.parametrize("s", [None, "", "휴무", "09:00", "25:00~18:00", "09:60~18:00", "24:30~01:00", "9시~6시"])
def test_parse_invalid(s):
    assert parse_range(s) is None
    assert not is_valid_format(s)


def test_zero_and_fmt():
    assert parse_range("00:00~00:00").is_zero
    assert not parse_range("09:00~18:00").is_zero
    assert parse_range("9:5 ~ 18:00") is None  # 분은 두 자리
    assert parse_range("9:05~18:00").fmt() == "09:05~18:00"
