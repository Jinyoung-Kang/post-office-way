"""⑤ 배치 제안 탐욕 알고리즘 · ③④ 카카오 보조 함수 — 손 계산 기대값."""
import pytest

from atlas.api.services.plan import Area, greedy_close, greedy_open
from atlas.collector.kakao.client import classify_bank, clean_addr, haversine_m


def test_greedy_close_picks_least_harm_and_handles_interaction():
    # 지역 X(가중 10): 시설 1(100m) → 2(300m) → 3(900m) / 지역 Y(가중 1): 2(100m) → 1(2500m)
    x = Area("X", 10, [(1, 100), (2, 300), (3, 900)])
    y = Area("Y", 1, [(2, 100), (1, 2500)])
    steps = greedy_close([x, y], [1, 2, 3], k=2, far_m=2000)
    # 단독: 1 닫기 = 10×200 = 2000 / 2 닫기 = 1×2400 = 2400 / 3 닫기 = 0 → 3 먼저
    assert steps[0]["histId"] == 3 and steps[0]["addedCost"] == 0
    # 다음: 1 → X 300(+200×10=2000), 2 → Y 2500(+2400) 이므로 1
    assert steps[1]["histId"] == 1 and steps[1]["addedCost"] == pytest.approx(2000)


def test_greedy_close_counts_newly_far():
    a = Area("A", 50, [(1, 1500), (2, 2600)])
    steps = greedy_close([a], [1, 2], k=1, far_m=2000)
    assert steps[0]["histId"] == 2 and steps[0]["newlyFar"] == 0      # 2 닫기는 영향 0
    steps = greedy_close([a], [1], k=1, far_m=2000)
    assert steps[0]["newlyFar"] == 50                                 # 1.5km → 2.6km: 2km 밖으로


def test_greedy_open_prefers_weighted_gain():
    cur = {"A": 3000.0, "B": 500.0}
    w = {"A": 10.0, "B": 100.0}
    near = {"sA": [("A", 0.0), ("B", 2500.0)], "sB": [("B", 0.0), ("A", 2600.0)]}
    steps = greedy_open(cur, w, near, k=2, far_m=2000)
    # sA: 10×3000=30000 / sB: 100×500 + 10×400 = 54000 → sB 먼저
    assert steps[0]["siteCd"] == "sB" and steps[0]["gain"] == pytest.approx(54000)
    assert steps[1]["siteCd"] == "sA" and steps[1]["gain"] == pytest.approx(10 * 2600)
    assert steps[1]["newlyNear"] == 10   # A: 2600 → 0 (2km 안으로)


def test_greedy_open_stops_when_no_gain():
    assert greedy_open({"A": 0.0}, {"A": 5.0}, {"s": [("A", 100.0)]}, k=3, far_m=2000) == []


@pytest.mark.parametrize("name, cat, kind", [
    ("KB국민은행 종로지점", "금융,보험 > 금융서비스 > 은행 > KB국민은행", "BRANCH"),
    ("화전새마을금고 안계지점", "금융,보험 > 금융서비스 > 은행 > 새마을금고", "BRANCH"),
    ("의성농협 안평지점 ATM", "금융,보험 > 금융서비스 > 은행 > ATM", "ATM"),
    ("하나은행365 파라지오CC", "금융,보험 > 금융서비스 > 은행 > ATM", "ATM"),
    ("우체국365코너", "금융,보험 > 금융서비스 > 은행 > ATM", None),
    ("한국산업은행 본점", "금융,보험 > 금융서비스 > 은행 > 한국산업은행", None),
    ("한국은행 대구경북본부", "금융,보험 > 금융서비스 > 은행 > 한국은행", None),
])
def test_classify_bank(name, cat, kind):
    assert classify_bank(name, cat) == kind


def test_clean_addr_and_haversine():
    assert clean_addr("서울 중구 소공로 70 (충무로1가)") == "서울 중구 소공로 70"
    assert clean_addr(None) == ""
    assert clean_addr("서울 중구 을지로 154-2 (을지로4가), ☎ 02-2265-3117") == "서울 중구 을지로 154-2"
    assert clean_addr("서울 강남구 언주로 508 1F(역삼동)") == "서울 강남구 언주로 508"
    assert clean_addr("서울 강남구 학동로101길 26, 312-1호(청담동)") == "서울 강남구 학동로101길 26"
    assert clean_addr("경기 구리시 산마루로 6, 101~102호 (갈매중심타워)") == "경기 구리시 산마루로 6"
    assert haversine_m(37.0, 127.0, 37.0, 127.0) == 0
    assert haversine_m(37.0, 127.0, 37.009, 127.0) == pytest.approx(1000.8, abs=2)   # 위도 0.009° ≈ 1km


def test_single_impacts_matches_greedy_one_step():
    """단독 영향(한 번에 계산)이 탐욕법 1단계를 시설마다 따로 돌린 결과와 같아야 함."""
    from atlas.api.services.plan import single_impacts

    areas = [Area("X", 10, [(1, 100), (2, 300), (3, 900)]), Area("Y", 1, [(2, 100), (1, 2500)]),
             Area("Z", 5, [(3, 1800), (1, 2600)])]
    si = single_impacts(areas, far_m=2000)
    for h in (1, 2, 3):
        g = greedy_close(areas, [h], 1, far_m=2000)[0]
        assert si[h]["addedCost"] == pytest.approx(g["addedCost"]) and si[h]["newlyFar"] == g["newlyFar"], h
        assert si[h]["areasAffected"] == g["areasAffected"], h
