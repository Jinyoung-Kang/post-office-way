"""전국 개요 집계 규칙 (domain/overview.py)."""
from decimal import Decimal

from atlas.domain.overview import distance_summary

DIST = [{"d": Decimal("500"), "pop": 100, "aged": 10}, {"d": Decimal("1500"), "pop": 300, "aged": None},
        {"d": Decimal("2500"), "pop": 600, "aged": 60}, {"d": Decimal("8000"), "pop": None, "aged": 5}]


def test_distance_summary():
    s = distance_summary(DIST, 2000, has_aged=True)
    assert s["totPop"] == 1000
    assert s["weightedAvgDistM"] == (500 * 100 + 1500 * 300 + 2500 * 600) / 1000
    assert [b["areas"] for b in s["bands"]] == [1, 1, 1, 0, 1]
    assert [b["share"] for b in s["bands"]] == [10.0, 30.0, 60.0, 0.0, 0.0]
    assert s["bands"][2]["aged65"] == 60
    assert s["farPpltn"] == 600 and s["farAged"] == 65          # 2km 넘는 곳: 2500m(600명, 60), 8000m(인구 없음, 5)


def test_distance_summary_edges():
    assert distance_summary(DIST, 2000, has_aged=False)["bands"][0]["aged65"] is None   # 고령 인구 미적재
    empty = distance_summary([], 2000, has_aged=False)
    assert empty["weightedAvgDistM"] is None and all(b["share"] is None for b in empty["bands"])
    assert distance_summary([{"d": 2000, "pop": 5, "aged": 1}], 2000, True)["farPpltn"] == 0   # 경계값은 '먼 거리' 아님
