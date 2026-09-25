"""생활 거점 — 국립중앙의료원 약국·병의원 FullData 행 해석 (순수 함수, 네트워크 없음).

진료시간은 dutyTime{1..8}{s,c} — 1=월 … 7=일, 8=공휴일, s=시작 c=끝(HHMM). 같은 응답 안에서도
"0900"(문자열)과 900(숫자)이 섞여 오므로 4자리 문자열로 맞춥니다.
"""
from __future__ import annotations

from typing import Any

# 1차 의료 접근성 기준 — 종합병원·병원·의원·보건소(보건지소·진료소 포함). 치과·한방·요양병원·기타는 제외
CLINIC_DIVS = {"A": "종합병원", "B": "병원", "C": "의원", "R": "보건소"}
KOREA_BBOX = (32.8, 39.7, 124.0, 132.0)   # lat_min, lat_max, lon_min, lon_max


def hhmm(v: Any) -> str | None:
    """900 · "0900" · "09:00" → "0900". 형식이 아니면 None. 24시 넘김(예: 2530)은 새벽 영업으로 허용."""
    if v is None:
        return None
    s = str(v).strip().replace(":", "")
    if not s.isdigit() or len(s) > 4:
        return None
    s = s.zfill(4)
    h, m = int(s[:2]), int(s[2:])
    return s if 0 <= h <= 30 and 0 <= m < 60 else None


def parse_hours(item: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for d in range(1, 9):
        s, c = hhmm(item.get(f"dutyTime{d}s")), hhmm(item.get(f"dutyTime{d}c"))
        if s and c and s != c:
            out[str(d)] = [s, c]
    return out


def to_row(kind: str, item: dict[str, Any]) -> dict[str, Any] | None:
    """FullData 한 건 → mart.care_place 행. 좌표가 없거나 국내 범위 밖, 대상이 아닌 병원분류면 None."""
    hpid, name = str(item.get("hpid") or "").strip(), str(item.get("dutyName") or "").strip()
    try:
        lat, lon = float(item.get("wgs84Lat")), float(item.get("wgs84Lon"))
    except (TypeError, ValueError):
        return None
    la0, la1, lo0, lo1 = KOREA_BBOX
    if not hpid or not name or not (la0 <= lat <= la1 and lo0 <= lon <= lo1):
        return None
    div = str(item.get("dutyDiv") or "").strip() or None
    if kind == "CLINIC" and div not in CLINIC_DIVS:
        return None
    hours = parse_hours(item)
    return {"hpid": hpid[:12], "kind": kind, "div": div if kind == "CLINIC" else None,
            "div_name": (str(item.get("dutyDivNam") or "").strip() or CLINIC_DIVS.get(div or "")) if kind == "CLINIC" else "약국",
            "name": name, "addr": (str(item.get("dutyAddr") or "").strip() or None), "hours": hours,
            "open_holiday": "8" in hours, "open_sunday": "7" in hours, "lat": lat, "lon": lon}
