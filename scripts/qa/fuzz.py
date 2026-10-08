"""API 퍼징 — 모든 조회·계산 API 에 경계값·비정상 입력을 보내 5xx 가 하나도 없어야 함.

    python scripts/qa/fuzz.py            (QA_API 로 주소 변경)
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from _common import API, report

BAD = ["", "-1", "0", "abc", "99999999999999999999", "1.5", "'; DROP TABLE x;--", "%00", "../../etc", "가나다", "null", "[]", "3e9"]


def req(method: str, path: str, body=None) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            return x.status, x.read()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200]
    except Exception as e:  # 연결 실패도 문제로 보고
        return 999, str(e).encode()


def q(**k) -> str:
    return "?" + urllib.parse.urlencode(k)


def seg(v: str) -> str:
    return urllib.parse.quote(v, safe="")


def cases() -> list[tuple]:
    out: list[tuple] = []
    for v in BAD:
        out += [("GET", "/meta/collect-runs" + q(page=v)), ("GET", "/meta/collect-runs" + q(size=v)),
                ("GET", "/meta/collect-runs" + q(kind=v)), ("GET", "/meta/regions" + q(year=v)),
                ("GET", "/meta/jobs" + q(limit=v)), ("GET", "/meta/errors" + q(days=v)),
                ("GET", "/overview" + q(calcRunId=v)), ("GET", "/facilities" + q(bbox=v)),
                ("GET", "/facilities" + q(types=v)), ("GET", "/facilities" + q(q=v)), ("GET", "/facilities" + q(page=v)),
                ("GET", "/facilities/" + seg(v)), ("GET", "/banks" + q(bbox=v)), ("GET", "/hubs/facilities" + q(sido=v)),
                ("GET", "/hubs/facilities" + q(page=v)), ("GET", "/hubs/facilities" + q(size=v)),
                ("GET", "/care" + q(bbox=v)), ("GET", "/calendar" + q(start=v)), ("GET", "/calendar" + q(days=v)),
                ("GET", "/areas" + q(level=v)), ("GET", "/areas" + q(metric=v)), ("GET", "/areas" + q(parent=v)),
                ("GET", "/areas" + q(sort=v)), ("GET", "/areas" + q(size=v)),
                ("GET", "/areas/geojson" + q(level=v, metric="ACCESS_GAP_SCORE")),
                ("GET", "/areas/geojson" + q(level=2, metric=v)),
                ("GET", "/areas/geojson" + q(level=3, metric="ACCESS_GAP_SCORE", parent=v)),
                ("GET", "/areas/" + seg(v)), ("GET", "/areas/" + seg(v) + "/report"),
                ("GET", "/whatif/" + seg(v)), ("GET", "/whatif/" + seg(v) + "/geojson"),
                ("GET", "/visit/conditions" + q(date=v)), ("GET", "/visit/conditions" + q(sido=v)),
                ("GET", "/visit/conditions/" + seg(v)), ("GET", "/dq/issues" + q(checkCode=v)),
                ("GET", "/dq/issues" + q(severity=v)), ("GET", "/dq/issues" + q(scope=v)),
                ("GET", "/dq/issues" + q(collectRunId=v)), ("GET", "/dq/summary" + q(calcRunId=v)),
                ("GET", "/banks/impact" + q(sido=v)), ("GET", "/banks/impact" + q(sgg=v)), ("GET", "/banks/impact" + q(grade=v)),
                ("GET", "/banks/impact" + q(sort=v)), ("GET", "/banks/impact" + q(page=v)), ("GET", "/banks/impact" + q(size=v)),
                ("GET", "/banks/impact/" + seg(v)), ("GET", "/banks/impact/" + seg(v) + "/geojson")]
    out += [("GET", "/areas/geojson"), ("GET", "/areas" + q(level=3)), ("GET", "/banks" + q(bbox="1,2,3")),
            ("GET", "/banks" + q(bbox="130,40,120,30")), ("GET", "/care" + q(bbox="127,37,127.1,37.1", kind="X")),
            ("GET", "/areas/geojson" + q(level=3, metric="ACCESS_GAP_SCORE", parent="99")),
            ("GET", "/hubs/facilities" + q(page=100000)), ("GET", "/dq/issues" + q(page=100000)),
            ("GET", "/areas" + q(page=100000)), ("GET", "/facilities" + q(bbox="126,37,127,38", size=100000))]
    for b in [{}, {"removeHistIds": []}, {"removeHistIds": [1, 2, 3, 4, 5, 6]}, {"removeHistIds": ["x"]},
              {"removeHistIds": [99999999999]}, {"removeHistIds": [1], "level": 9}, {"removeHistIds": [-1]}, None, [1, 2]]:
        out.append(("POST", "/whatif", b))
    for b in [{}, {"scope": "", "k": 3}, {"scope": "99999", "k": 3}, {"scope": "37", "k": 0}, {"scope": "37", "k": 100},
              {"scope": "37", "k": 3, "weight": "x"}, {"scope": "x'--", "k": 2}]:
        out.append(("POST", "/plan/close", b))
    out.append(("POST", "/plan/open", {"scope": "3752", "k": 2}))
    for b in [None, {}, [], {"csp-report": None}, {"csp-report": {"blocked-uri": 1, "line-number": "x"}}, [{"type": "csp-violation"}],
              [{"type": "csp-violation", "body": {"blockedURL": "x" * 5000}}], "문자열", 12345]:
        out.append(("POST", "/csp-report", b))
    for d in ("2026-02-30", "2026-13-01", "0001-01-01", "9999-12-31"):        # 형식은 맞지만 없는·극단 날짜
        out.append(("GET", "/calendar" + q(start=d, days=62)))
    for b in [None, {}, {"ids": []}, {"ids": ["api:1"]}, {"ids": ["api:1'--"]}, {"ids": [1]}, {"ids": "api:1"}]:   # 토큰 없음 → 400·401
        out.append(("POST", "/admin/errors/ack", b))
    return out


def main() -> None:
    cs = cases()
    bad = []
    for c in cs:
        st, body = req(*c)
        if st >= 500:
            bad.append(f"{st} {c[0]} {c[1]} {c[2] if len(c) > 2 else ''} → {body[:120]!r}")
    report("fuzz", bad, f"{len(cs)}건 요청, 5xx 0건")


if __name__ == "__main__":
    main()
