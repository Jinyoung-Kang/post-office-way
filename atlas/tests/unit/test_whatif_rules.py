"""What-if 요약 규칙 (domain/whatif.py) — DB 없이."""
from atlas.domain.whatif import fin_access_loss, oa_impact, summarize

R = [{"adm_cd": "A", "dist_before_m": 1000, "dist_after_m": 3000},
     {"adm_cd": "B", "dist_before_m": 500, "dist_after_m": 900},
     {"adm_cd": "C", "dist_before_m": 1500, "dist_after_m": None}]      # 닫은 뒤 남은 시설 없음
POP = {"A": 100, "B": 200, "C": 50}


def test_summarize():
    s = summarize(R, POP, {"A": 30, "B": None})
    assert s == {"affectedAreas": 3, "affectedPpltn": 350, "affectedAged65": 30, "avgDistBeforeM": 1000.0,
                 "avgDistAfterM": 1950.0, "maxIncreaseM": 2000.0, "areasWithoutFacility": 1}
    assert summarize(R, POP)["affectedAged65"] is None          # 고령 인구 미적재는 0 이 아니라 None
    assert summarize([], {})["avgDistBeforeM"] is None


def test_fin_access_loss():
    assert fin_access_loss(R, POP, {}, 2000) == {"lostFinAccessPpltn": None}       # 은행 자료 없음
    # A: 2km 안 → 밖, 은행 5km → 잃음. C: 남은 시설 없음, 은행 1km → 안 잃음. B: 그대로 2km 안
    assert fin_access_loss(R, POP, {"A": 5000, "C": 1000}, 2000) == {"lostFinAccessPpltn": 100}
    assert fin_access_loss(R, POP, {"A": 5000}, 2000) == {"lostFinAccessPpltn": 150}  # C 은행 없음 → 먼 것으로


def test_oa_impact():
    rows = [(10, 1000, 2500, 3000, 3000, 3000),    # 새로 멀어짐 + 생활 거점 모두 멀리
            (20, 1000, 2500, 500, 3000, 3000),     # 새로 멀어졌지만 은행이 가까움
            (40, 2500, 2600, 3000, 3000, 3000),    # 원래 멀었음
            (None, 1000, None, None, None, None)]  # 인구 없음
    assert oa_impact(rows, 2000) == {"oaAffectedPpltn": 70, "oaNewlyFarPpltn": 30, "lifeHubLostPpltn": 10}
    no_life = [(r[0], r[1], r[2], r[3], None, None) for r in rows]
    assert oa_impact(no_life, 2000)["lifeHubLostPpltn"] is None     # 약국·의원 자료 없음
