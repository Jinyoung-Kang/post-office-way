"""단계구분도 입력 검증 — 값마다 새 캐시 키(24시간)가 생기거나 가장 무거운 경계가 나가지 않게 (S3)."""
import pytest

from atlas.domain.errors import Invalid
from atlas.features.areas.service import _check_parent, simplify_step


@pytest.mark.parametrize("ok", [None, "11", "37520"])
def test_parent_accepts_sido_and_sigungu(ok):
    _check_parent(ok)


@pytest.mark.parametrize("bad", ["1", "123", "11%", "١١", "１１", "11\n", "37520\n", "٣٧٥٢٠"])
def test_parent_rejects_non_ascii_digits_and_newline(bad):
    """파이썬 정규식의 \\d 는 아랍·전각 숫자도, $ 는 끝 줄바꿈도 받아 검증을 우회했음."""
    with pytest.raises(Invalid):
        _check_parent(bad)


def test_simplify_step_keeps_small_tolerance_simplified():
    """0 < 값 < 5 가 0(원본 경계 — 가장 무거운 응답)으로 반올림되지 않게, 최소 10m 단계로."""
    assert simplify_step(None) is None
    assert simplify_step(0) == 0.0                 # 0 은 원본 요청 그대로
    assert [simplify_step(v) for v in (0.5, 3, 4.9)] == [10.0, 10.0, 10.0]
    assert [simplify_step(v) for v in (5, 14, 15, 200, 4999)] == [10.0, 10.0, 20.0, 200.0, 5000.0]
