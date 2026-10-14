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
    """0 < 값 < 5 가 0(원본 경계 — 가장 무거운 응답)으로 반올림되지 않게, 가장 작은 단계(10m)로."""
    assert simplify_step(None) is None
    assert simplify_step(0) == 0.0                 # 0 은 원본 요청 그대로
    assert [simplify_step(v) for v in (0.5, 3, 4.9)] == [10.0, 10.0, 10.0]
    # 2차 리뷰 S3: 10m 단위(501단계)가 아니라 정해진 단계 중 가장 가까운 값(비율 기준)으로
    assert [simplify_step(v) for v in (5, 14, 15, 200, 4999)] == [10.0, 10.0, 20.0, 200.0, 5000.0]
    assert [simplify_step(v) for v in (123.4567, 300, 700, 1300, 1500)] == [100.0, 200.0, 500.0, 1000.0, 2000.0]


def test_simplify_has_few_steps():
    """단순화 허용 오차는 몇 단계로만 — 값마다 전국 경계 단순화(요청당 DB 약 1.3초)와 24시간 캐시 항목이 생기지 않게.
    예전 10m 단위는 0~5000 에서 501가지 × 지표 28개가 모두 캐시 미스였음(리뷰 S3 수정이 덜 됨)."""
    assert len({simplify_step(v / 10) for v in range(0, 50_001)}) <= 10


@pytest.mark.parametrize("tiny", [5e-324, 1e-320, 1.2e-320])
def test_simplify_step_tiny_positive_is_smallest_step(tiny):
    """아주 작은 양수(비정규 실수)도 가장 작은 단계로 — 단계와 나눈 값이 0 으로 내려가 log(0) 의 ValueError 가 500 이 됐음(독립 검토)."""
    assert simplify_step(tiny) == 10.0

