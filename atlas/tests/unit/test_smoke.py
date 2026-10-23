"""스모크 — 한 원천이 응답하지 않아도 그 항목만 실패로 적고 끝까지 감 (네트워크 없이 httpx 모의 전송)."""
import json
from pathlib import Path

import httpx
import pytest

from atlas.collector import smoke as smoke_mod

POST_XML = (Path(__file__).resolve().parents[1] / "contract" / "fixtures" / "post_area_sample.xml").read_text(encoding="utf-8")
BODIES = {
    "searchPostScopeList.do": POST_XML,
    "searchPostAreaList.do": POST_XML,
    "authentication.json": json.dumps({"errCd": 0, "result": {"accessToken": "tok", "accessTimeout": "1727000000"}}),
    "population.json": json.dumps({"errCd": 0, "result": [{"adm_cd": "11010", "tot_ppltn": "1"}]}),
    "hadmarea.geojson": json.dumps({"errCd": 0, "features": [{"geometry": {"type": "Point", "coordinates": [953000, 1952000]}}]}),
    "getVilageFcst": json.dumps({"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"}}}),
    "getMinuDustFrcstDspth": json.dumps({"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL_CODE"}}}),
}


@pytest.fixture()
def run(monkeypatch, tmp_path):
    from atlas.core import config
    for k, v in {"POST_SERVICE_KEY": "P", "SGIS_CONSUMER_KEY": "k", "SGIS_CONSUMER_SECRET": "s",
                 "KOSIS_API_KEY": "", "DATA_GO_KR_KEY": "D"}.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    monkeypatch.setattr(smoke_mod, "FIXTURES", tmp_path)
    real_client = httpx.Client

    def go(slow: str) -> bool:
        def handler(req: httpx.Request) -> httpx.Response:
            name = req.url.path.rsplit("/", 1)[-1]
            if name == slow:
                raise httpx.ReadTimeout("The read operation timed out", request=req)
            return httpx.Response(200, text=BODIES[name])
        monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
        return smoke_mod.smoke()

    yield go
    config.get_settings.cache_clear()


@pytest.mark.parametrize("slow, label", [("getMinuDustFrcstDspth", "에어코리아 미세먼지 예보"),
                                         ("searchPostScopeList.do", "우체국 찾기")])
def test_timeout_fails_only_that_item_and_reaches_result(run, capsys, tmp_path, slow, label):
    assert run(slow) is False
    out = capsys.readouterr().out
    assert f"✗ {label}: ReadTimeout" in out and "Traceback" not in out
    assert "결과: 실패 항목이 있습니다 ✗" in out
    assert (tmp_path / "kma_vilage_60_127.json").exists()       # 다른 항목은 계속 받음
    assert (tmp_path / "post_area_100_p1.xml").exists()


def test_sgis_timeout_stops_like_missing_token(run, capsys):
    assert run("authentication.json") is False
    out = capsys.readouterr().out
    assert "✗ SGIS: ReadTimeout" in out and "⑤" not in out


def test_all_reachable_is_ok(run, capsys):
    assert run("") is True
    assert "결과: 모두 정상 ✓" in capsys.readouterr().out
