"""SGIS 토큰 캐시·만료 60초 전 재발급·-401 재시도 (FR-201) — 네트워크 없이 Fetcher 를 흉내."""
import json
from dataclasses import dataclass, field

import pytest

from atlas.collector.http import FetchResult
from atlas.collector.sgis.client import SgisClient, SgisError, parse_timeout
from atlas.collector.sgis.pipeline import detect_srid, parse_population


@dataclass
class FakeFetcher:
    responses: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    secrets: list = field(default_factory=list)

    def get(self, url, params, source=None, sleep=None):
        self.calls.append((url.rsplit("/", 1)[-1], dict(params)))
        body = self.responses.pop(0)
        return FetchResult(True, 200, json.dumps(body))


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    from atlas.core import config
    monkeypatch.setenv("SGIS_CONSUMER_KEY", "k")
    monkeypatch.setenv("SGIS_CONSUMER_SECRET", "s")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def auth(tok, timeout):
    return {"errCd": 0, "result": {"accessToken": tok, "accessTimeout": timeout}}


def test_parse_timeout_seconds_and_ms():
    assert parse_timeout("1727000000") == 1727000000
    assert parse_timeout("1727000000000") == 1727000000


def test_token_cached_then_refreshed_60s_before_expiry():
    t0 = 1_727_000_000.0                  # 실제 epoch 초 규모 (ms 판별이 의미 있도록)
    now = [t0]
    f = FakeFetcher([auth("t1", str(int((t0 + 3600) * 1000))), auth("t2", str(int(t0 + 7200)))])
    c = SgisClient(f, now=lambda: now[0])
    assert c.token() == "t1" and c.token() == "t1"
    now[0] = t0 + 3600 - 61
    assert c.token() == "t1"              # 아직 61초 남음
    now[0] = t0 + 3600 - 59
    assert c.token() == "t2"              # 60초 안 → 재발급
    assert c.token_issued == 2 and "t1" in f.secrets


def test_get_retries_once_on_401():
    f = FakeFetcher([auth("t1", "9999999999"), {"errCd": -401, "errMsg": "expired"},
                     auth("t2", "9999999999"), {"errCd": 0, "result": [{"adm_cd": "11010"}]}])
    c = SgisClient(f)
    data = c.get("stats/population.json", {"year": 2024}, "SGIS_POP")
    assert data["result"][0]["adm_cd"] == "11010"
    assert f.calls[3][1]["accessToken"] == "t2"


def test_get_raises_on_other_error():
    f = FakeFetcher([auth("t1", "9999999999"), {"errCd": -100, "errMsg": "검색결과가 존재하지 않습니다"}])
    with pytest.raises(SgisError):
        SgisClient(f).get("boundary/hadmarea.geojson", {}, "SGIS_BND")


def test_detect_srid_and_population_parse():
    assert detect_srid({"type": "Polygon", "coordinates": [[[126.97, 37.57], [126.98, 37.57]]]}) == 4326
    assert detect_srid({"type": "MultiPolygon", "coordinates": [[[[953000.1, 1952000.2]]]]}) == 5179
    rows = parse_population({"result": [
        {"adm_cd": "11010", "adm_nm": "종로구", "tot_ppltn": "141,000", "aged_child_idx": "231.5",
         "ppltn_dnsty": "5900.1", "avg_age": "46.2"},
        {"adm_cd": "11020", "adm_nm": "중구", "tot_ppltn": "N/A"}, {"adm_cd": ""}]})
    assert rows[0]["tot_ppltn"] == 141000 and rows[0]["aged_child_idx"] == 231.5
    assert rows[1]["tot_ppltn"] is None and len(rows) == 2
