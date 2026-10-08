"""은행 지점 전수 수집(사분할 격자)·지금 영업 중 목록(mart.bank_branch_current) — 카카오 호출은 가짜로."""
import pytest
from sqlalchemy import text

from atlas.collector.kakao import banks
from atlas.collector.kakao.client import bank_brand

pytestmark = pytest.mark.db


class FakeFetcher:
    calls, errors = 0, 0

    def close(self):
        pass


def fake_kakao(points):
    """rect 안의 점을 total_count 와 15개씩 3쪽까지 돌려주는 가짜 범주 검색."""
    def call(_fetcher, _url, params, _source):
        FakeFetcher.calls += 1
        x1, y1, x2, y2 = (float(v) for v in params["rect"].split(","))
        inside = [p for p in points if x1 <= p[1] < x2 and y1 <= p[2] < y2]
        n = params["page"]
        docs = inside[(n - 1) * 15: n * 15] if n <= 3 else []
        return {"meta": {"total_count": len(inside), "is_end": n * 15 >= min(45, len(inside))},
                "documents": [{"id": pid, "place_name": f"{pid} 지점", "x": str(x), "y": str(y),
                               "category_name": "금융,보험 > 금융서비스 > 은행 > KB국민은행", "address_name": "주소"}
                              for pid, x, y in docs]}
    return call


def test_full_crawl_splits_dense_tiles_and_collects_everything(clean, monkeypatch, engine):
    # 서울 한 점 주위에 120곳(빽빽), 전국에 흩어진 10곳
    dense = [(f"D{i}", 127.0 + (i % 12) * 0.004, 37.5 + (i // 12) * 0.004) for i in range(120)]
    sparse = [(f"S{i}", 126.0 + i * 0.4, 34.0 + i * 0.3) for i in range(10)]
    monkeypatch.setattr(banks, "call", fake_kakao(dense + sparse))
    monkeypatch.setattr(banks, "make_fetcher", lambda *_: FakeFetcher())
    rid = banks.collect_banks_full()
    with engine.connect() as c:
        n = c.execute(text("SELECT count(*) FROM mart.bank_place WHERE kind = 'BRANCH' AND brand = 'KB국민은행'")).scalar()
        run = c.execute(text("SELECT status, scope, stats FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).one()
    assert n == 130                                     # 45곳 상한에도 빠짐없이
    assert run.status == "DONE" and run.scope.startswith("FULL;")
    assert run.stats["splits"] > 0 and run.stats["truncated"] == 0


def test_tile_smaller_than_min_side_is_truncated_not_split_forever(clean, monkeypatch, engine):
    same = [(f"P{i}", 127.0001, 37.5001) for i in range(50)]     # 한 건물에 50곳 — 더 나눌 수 없음
    monkeypatch.setattr(banks, "call", fake_kakao(same))
    monkeypatch.setattr(banks, "make_fetcher", lambda *_: FakeFetcher())
    rid = banks.collect_banks_full()
    with engine.connect() as c:
        st = c.execute(text("SELECT stats FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).scalar()
    assert st["truncated"] == 1 and st["branches"] == 45


def test_current_branches_follow_latest_full_crawl(clean, engine):
    with engine.begin() as c:
        for pid, seen in (("OLD", "now() - interval '10 days'"), ("NEW", "now()")):
            c.execute(text(f"""INSERT INTO mart.bank_place (place_id, name, kind, geom, geom_5179, last_seen)
                               VALUES (:p, :n, 'BRANCH', ST_SetSRID(ST_MakePoint(127, 37.5), 4326),
                                       ST_Transform(ST_SetSRID(ST_MakePoint(127, 37.5), 4326), 5179), {seen})"""), {"p": pid, "n": pid})
        cur = lambda: {r[0] for r in c.execute(text("SELECT place_id FROM mart.bank_branch_current"))}  # noqa: E731
        assert cur() == {"OLD", "NEW"}                  # 전수 수집 전: 최근 90일 규칙
        c.execute(text("""INSERT INTO ops.collect_run (kind, status, scope, started_at)
                          VALUES ('KAKAO_BANK', 'DONE', 'FULL;BK9', now() - interval '1 hour')"""))
        assert cur() == {"NEW"}                         # 전수 수집에서 안 보인 지점은 폐점 가능성 → 제외


def test_bank_brand_from_category():
    assert bank_brand("금융,보험 > 금융서비스 > 은행 > KB국민은행") == "KB국민은행"
    assert bank_brand("금융,보험 > 금융서비스 > 은행 > 저축은행 > SBI저축은행") == "저축은행"
    assert bank_brand("금융,보험 > 금융서비스 > 은행") is None
    assert bank_brand(None) is None


def _status(engine, rid):
    with engine.connect() as c:
        return c.execute(text("SELECT status, stats FROM ops.collect_run WHERE collect_run_id = :r"), {"r": rid}).one()


def test_failed_next_page_makes_crawl_partial(clean, monkeypatch, engine):
    """2·3쪽을 받지 못하면 그 칸의 지점이 빠지므로 '전수'가 아님 → PARTIAL (기준 목록이 되면 빠진 지점이 폐점 처리됨)."""
    pts = [(f"P{i}", 127.0 + i * 0.0001, 37.5) for i in range(30)]      # 한 칸에 30곳 → 2쪽 필요
    inner = fake_kakao(pts)
    monkeypatch.setattr(banks, "call", lambda f, u, p, s: None if p["page"] == 2 else inner(f, u, p, s))
    monkeypatch.setattr(banks, "make_fetcher", lambda *_: FakeFetcher())
    status, stats = _status(engine, banks.collect_banks_full())
    assert status == "PARTIAL" and stats["failedPages"] == 1


def test_truncated_tile_makes_crawl_partial(clean, monkeypatch, engine):
    same = [(f"P{i}", 127.0001, 37.5001) for i in range(50)]
    monkeypatch.setattr(banks, "call", fake_kakao(same))
    monkeypatch.setattr(banks, "make_fetcher", lambda *_: FakeFetcher())
    status, stats = _status(engine, banks.collect_banks_full())
    assert status == "PARTIAL" and stats["truncated"] == 1
