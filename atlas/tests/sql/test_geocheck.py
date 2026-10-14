"""③ 카카오 주소 검색 캐시(geocode_cache) — 일시 오류가 '못 찾음'으로 굳지 않아야 함 (2차 리뷰 D5)."""
import httpx
import pytest
from sqlalchemy import text

from atlas.ops import runs

pytestmark = pytest.mark.db
ADDR = "서울 중구 세종대로 110"
FOUND = {"documents": [{"y": "37.5", "x": "126.9", "address_name": ADDR}]}


@pytest.fixture()
def kakao(clean, monkeypatch):
    """geocode() 를 모의 HTTP 로 — state['respond'](query) 가 httpx.Response 를 돌려줌."""
    from atlas.collector import http as http_mod
    from atlas.collector.kakao.client import make_fetcher
    from atlas.core import config

    for k, v in {"KAKAO_REST_API_KEY": "TESTKAKAOKEY", "HTTP_RETRIES": "0", "KAKAO_CALL_DELAY_MS": "0"}.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    state = {"calls": [], "respond": None}

    def handler(req: httpx.Request):
        state["calls"].append(req.url.params["query"])
        return state["respond"](req.url.params["query"])

    orig_init = http_mod.Fetcher.__post_init__

    def patched(self):
        orig_init(self)
        self._client = httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(http_mod.Fetcher, "__post_init__", patched)
    state["fetcher"] = make_fetcher(runs.start_run("KAKAO_GEO", check_running=False), "KAKAO_LOCAL")
    yield state
    state["fetcher"].close()
    config.get_settings.cache_clear()


def _status(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT status FROM mart.geocode_cache WHERE addr = :a"), {"a": ADDR}).scalar()


def test_transient_error_is_retried_later(kakao, engine):
    """카카오가 5xx 로 답한 주소는 다음에 다시 조회 — 예전에는 'ERROR' 가 캐시돼 영영 호출하지 않고 좌표 없음으로 남았음."""
    from atlas.collector.kakao.geocheck import geocode

    kakao["respond"] = lambda q: httpx.Response(503)
    assert geocode(kakao["fetcher"], ADDR) is None
    kakao["respond"] = lambda q: httpx.Response(200, json=FOUND)
    assert geocode(kakao["fetcher"], ADDR) == {"lat": 37.5, "lon": 126.9, "matched": ADDR}
    assert _status(engine) == "OK"


def test_failed_retry_query_is_not_cached_as_not_found(kakao, engine):
    """첫 검색이 0건이고 시도를 뺀 재검색이 실패하면 '못 찾음'이 아니라 오류 — 예전에는 첫 응답(0건)으로 NOT_FOUND 가 굳었음."""
    from atlas.collector.kakao.geocheck import geocode

    kakao["respond"] = lambda q: httpx.Response(200, json={"documents": []}) if q == ADDR else httpx.Response(503)
    assert geocode(kakao["fetcher"], ADDR) is None
    assert _status(engine) == "ERROR"


def test_not_found_is_cached(kakao, engine):
    """정말 못 찾은 주소는 지금처럼 캐시해 다시 부르지 않음."""
    from atlas.collector.kakao.geocheck import geocode

    kakao["respond"] = lambda q: httpx.Response(200, json={"documents": []})
    assert geocode(kakao["fetcher"], ADDR) is None
    n = len(kakao["calls"])
    assert geocode(kakao["fetcher"], ADDR) is None and len(kakao["calls"]) == n
    assert _status(engine) == "NOT_FOUND"
