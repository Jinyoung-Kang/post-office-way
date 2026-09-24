"""우체국 찾기 XML 파서 (searchPostAreaList / searchPostScopeList 공용).

명세 표와 예시가 다른 부분(lunchTime / lunchtime 등)이 있어 태그 이름을 대소문자 무시로 읽습니다.
빈 태그·'null' 문자열은 None. 파싱 실패 필드는 None 으로 두고 행은 버리지 않습니다(DQ 로 잡음).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from lxml import etree

from atlas.domain.rules import fin_available, is_center, row_hash

_NULLS = {"", "null", "none", "nil", "-"}


@dataclass
class PostPage:
    total_count: int | None = None
    total_page: int | None = None
    now_page: int | None = None
    items: list[dict[str, str | None]] = field(default_factory=list)
    error: str | None = None


def _local(tag: Any) -> str:
    return etree.QName(tag).localname.lower() if isinstance(tag, str) else ""


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return None if v.lower() in _NULLS else v


def _int(v: str | None) -> int | None:
    v = _clean(v)
    try:
        return int(float(v)) if v is not None else None
    except ValueError:
        return None


def parse_post_xml(body: str | bytes) -> PostPage:
    if isinstance(body, str):
        body = body.encode("utf-8")
    page = PostPage()
    if not body.strip():
        page.error = "EMPTY_BODY"
        return page
    try:
        root = etree.fromstring(body, parser=etree.XMLParser(recover=True, resolve_entities=False,
                                                             no_network=True))
    except etree.XMLSyntaxError as e:
        page.error = f"XML_SYNTAX: {e}"
        return page
    if root is None:
        page.error = "NOT_XML"
        return page

    header_vals: dict[str, str | None] = {}
    for el in root.iter():
        name = _local(el.tag)
        if name == "postitem":
            page.items.append({_local(c.tag): _clean(c.text) for c in el if _local(c.tag)})
        elif name in ("totalcount", "totalpage", "nowpage", "returnauthmsg", "returnreasoncode",
                      "errmsg", "resultcode", "resultmsg", "returncode") and el.text:
            header_vals.setdefault(name, _clean(el.text))

    page.total_count = _int(header_vals.get("totalcount"))
    page.total_page = _int(header_vals.get("totalpage"))
    page.now_page = _int(header_vals.get("nowpage"))

    # 공공데이터포털형 오류(cmmMsgHeader) 또는 명세 외 오류 응답
    err = header_vals.get("returnauthmsg") or header_vals.get("errmsg")
    code = header_vals.get("returnreasoncode") or header_vals.get("resultcode") or header_vals.get("returncode")
    if err and not page.items:
        page.error = f"{code or ''} {err}".strip()
    elif code and code not in ("00", "0", "000", "INFO-000") and not page.items and page.total_count is None:
        page.error = f"{code} {header_vals.get('resultmsg') or ''}".strip()
    elif not page.items and page.total_count is None:
        page.error = f"UNEXPECTED_RESPONSE root=<{_local(root.tag)}>"
    return page


def _pick(item: dict[str, str | None], *names: str) -> str | None:
    for n in names:
        v = item.get(n.lower())
        if v is not None:
            return v
    return None


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


_DATE = re.compile(r"^(\d{4})[-./]?(\d{2})[-./]?(\d{2})")


def _date(v: str | None) -> date | None:
    m = _DATE.match(v or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _yn(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip().upper()
    return {"Y": "Y", "N": "N", "1": "Y", "0": "N", "TRUE": "Y", "FALSE": "N"}.get(v, v[:1] or None)


def normalize_item(item: dict[str, str | None], area_code: str) -> dict[str, Any]:
    """원본 필드 → stg.post_facility 컬럼. is_center·fin_available·row_hash 까지 계산."""
    name = _pick(item, "postNm")
    addr = _pick(item, "postAddr")
    post_id = _pick(item, "postId")
    if not post_id:
        # ID 가 없는 응답을 대비한 결정적 대체키 (이름+주소)
        post_id = "NOID-" + hashlib.sha1(f"{name}|{addr}".encode()).hexdigest()[:12]
    rec: dict[str, Any] = {
        "post_id": post_id[:20],
        "post_div": _int(_pick(item, "postDiv", "postDivType")),
        "name": (name or "")[:100] or None,
        "addr": addr,
        "tel": (_pick(item, "postTel") or "")[:30] or None,
        "lat": _float(_pick(item, "postLat", "postLatitude")),
        "lon": _float(_pick(item, "postLon", "postLng", "postLongitude")),
        "post_time": _pick(item, "postTime"),
        "finance_time": _pick(item, "postFinanceTime", "financeTime"),
        "lunch_yn": _yn(_pick(item, "lunchTimeYn", "lunchYn")),
        "lunch_time": _pick(item, "lunchTime", "lunchtime"),
        "post365_yn": _yn(_pick(item, "post365Yn")),
        "area_code": area_code,
        "mod_dt": _date(_pick(item, "modDt")),
    }
    for k in ("post_time", "finance_time", "lunch_time"):
        if rec[k]:
            rec[k] = rec[k][:40]
    rec["is_center"] = is_center(area_code, rec["name"])
    rec["fin_available"] = fin_available(rec["post_div"], rec["finance_time"], rec["is_center"])
    rec["row_hash"] = row_hash(rec)
    return rec
