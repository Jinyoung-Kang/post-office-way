"""지수 백오프 재시도 (FR-104) — raw 저장 없이 httpx 모의 전송으로 검증."""
import uuid

import httpx

from atlas.collector.http import Fetcher


def make(handler):
    f = Fetcher(uuid.uuid4(), "POST_AREA", store_raw=False)
    f._client = httpx.Client(transport=httpx.MockTransport(handler))
    return f


def test_retries_then_succeeds():
    n = {"i": 0}
    sleeps = []

    def handler(req):
        n["i"] += 1
        return httpx.Response(503 if n["i"] < 3 else 200, text="<ok/>")

    res = make(handler).get("https://x/y", {"a": 1}, sleep=sleeps.append)
    assert res.ok and n["i"] == 3 and sleeps == [1, 2]


def test_gives_up_after_3_retries():
    sleeps = []
    f = make(lambda req: httpx.Response(500))
    res = f.get("https://x/y", {}, sleep=sleeps.append)
    assert not res.ok and f.calls == 4 and sleeps == [1, 2, 4] and f.errors == 1


def test_4xx_not_retried():
    f = make(lambda req: httpx.Response(401, text="unauthorized"))
    res = f.get("https://x/y", {}, sleep=lambda s: None)
    assert not res.ok and f.calls == 1 and res.status == 401


def test_network_error_retried():
    def handler(req):
        raise httpx.ConnectError("boom serviceKey=SECRET")

    f = make(handler)
    res = f.get("https://x/y", {}, sleep=lambda s: None)
    assert not res.ok and f.calls == 4 and "SECRET" not in res.error
