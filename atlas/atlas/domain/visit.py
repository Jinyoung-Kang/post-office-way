"""오늘의 방문 여건 — 기상청 단기예보 + 에어코리아 미세먼지 예보를 시군구 단위 '창구 방문 부담'으로 판정 (VISIT-1).

창구 운영 시간(09~18시) 시간별 예보만 봅니다. 기준은 기상특보·대기 등급 기준을 참고한 이 프로젝트의 분석 규칙이며
공식 특보가 아닙니다. 규칙을 바꾸면 VISIT_RULE_VERSION 을 올립니다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

VISIT_RULE_VERSION = "VISIT-1"
WINDOW_HOURS = range(9, 19)          # 09:00 ~ 18:00 예보 (창구 운영 시간)
LEVEL_LABEL = {0: "좋음", 1: "주의", 2: "나쁨"}


# --- 기상청 격자 (Lambert Conformal Conic, 5km) — 기상청 동네예보 격자 변환 공식 -------------------------
def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    re_, grid = 6371.00877, 5.0
    slat1, slat2, olon, olat, xo, yo = 30.0, 60.0, 126.0, 38.0, 43, 136
    d = math.pi / 180.0
    r = re_ / grid
    s1, s2, ol, oa = slat1 * d, slat2 * d, olon * d, olat * d
    sn = math.log(math.cos(s1) / math.cos(s2)) / math.log(math.tan(math.pi * 0.25 + s2 * 0.5) / math.tan(math.pi * 0.25 + s1 * 0.5))
    sf = math.tan(math.pi * 0.25 + s1 * 0.5) ** sn * math.cos(s1) / sn
    ro = r * sf / math.tan(math.pi * 0.25 + oa * 0.5) ** sn
    ra = r * sf / math.tan(math.pi * 0.25 + lat * d * 0.5) ** sn
    theta = lon * d - ol
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn
    return int(ra * math.sin(theta) + xo + 0.5), int(ro - ra * math.cos(theta) + yo + 0.5)


# --- 단기예보 값 해석 ---------------------------------------------------------------------------------------
_NUM = re.compile(r"(\d+(?:\.\d+)?)")


def parse_amount(v: str | None) -> float | None:
    """PCP·SNO 문자열 → 숫자(구간 하한). '강수없음'·'적설없음' 0, '1mm 미만' 0.5, '30.0~50.0mm' 30, '50.0mm 이상' 50."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ("-", "강수없음", "적설없음") or s.startswith("-9"):
        return 0.0 if s in ("강수없음", "적설없음") else None
    m = _NUM.search(s)
    if not m:
        return None
    x = float(m.group(1))
    return x / 2 if "미만" in s else x


def parse_number(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x <= -900 or x >= 900 else x   # 결측 -999·+900 이상


# --- 에어코리아 권역 ----------------------------------------------------------------------------------------
# 시도 코드(SGIS 앞 2자리) → 예보 권역. 경기·강원은 시군 이름으로 나눔
SIDO_AIR_REGION = {"11": "서울", "21": "부산", "22": "대구", "23": "인천", "24": "광주", "25": "대전", "26": "울산",
                   "29": "세종", "33": "충북", "34": "충남", "35": "전북", "36": "전남", "37": "경북", "38": "경남",
                   "39": "제주"}
GYEONGGI_NORTH = ("고양", "의정부", "파주", "양주", "동두천", "포천", "연천", "남양주", "구리", "가평")
GANGWON_EAST = ("강릉", "동해", "속초", "삼척", "태백", "고성", "양양")   # 영동 (태백은 경계 — 영동으로 봄)


def air_region(adm_cd: str, adm_nm: str) -> str | None:
    sido = adm_cd[:2]
    if sido == "31":
        return "경기북부" if adm_nm.startswith(GYEONGGI_NORTH) else "경기남부"
    if sido == "32":
        return "영동" if adm_nm.startswith(GANGWON_EAST) else "영서"
    return SIDO_AIR_REGION.get(sido)


def parse_inform_grade(s: str | None) -> dict[str, str]:
    """'서울 : 보통,제주 : 좋음,…' → {'서울': '보통', …}"""
    out: dict[str, str] = {}
    for part in (s or "").split(","):
        if ":" in part:
            k, v = (x.strip() for x in part.split(":", 1))
            if k and v:
                out[k] = v
    return out


AIR_LEVEL = {"좋음": 0, "보통": 0, "나쁨": 1, "매우나쁨": 2}


# --- 판정 ---------------------------------------------------------------------------------------------------
@dataclass
class Hour:
    hour: int
    tmp: float | None = None
    pop: float | None = None
    pty: int | None = None
    pcp_mm: float | None = None
    sno_cm: float | None = None
    wsd: float | None = None


@dataclass
class Assessment:
    level: int | None                                  # None = 예보 없음
    reasons: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return "예보 없음" if self.level is None else LEVEL_LABEL[self.level]


def _maxv(xs):
    xs = [x for x in xs if x is not None]
    return max(xs) if xs else None


def _minv(xs):
    xs = [x for x in xs if x is not None]
    return min(xs) if xs else None


def assess(hours: list[Hour], pm10: str | None = None, pm25: str | None = None) -> Assessment:
    """창구 운영 시간 예보 + 미세먼지 예보 → 0 좋음 / 1 주의 / 2 나쁨 과 사유.

    비   : 강수 시간 있음 → 주의, 합계 30mm 이상 또는 시간당 10mm 이상 → 나쁨
    눈   : 눈·진눈깨비 시간 있음 → 주의, 신적설 합 1cm 이상 → 나쁨 (빙판·낙상)
    더위 : 최고 31℃ 이상 → 주의, 33℃ 이상 → 나쁨 (폭염특보 기준 참고)
    추위 : 최저 -5℃ 이하 → 주의, -10℃ 이하 → 나쁨
    바람 : 풍속 9m/s 이상 → 주의, 14m/s 이상 → 나쁨 (강풍주의보 육상 기준 참고)
    대기 : PM10·PM2.5 예보 나쁨 → 주의, 매우나쁨 → 나쁨
    """
    hs = [h for h in hours if h.hour in WINDOW_HOURS]
    reasons: list[dict[str, Any]] = []

    def add(code: str, level: int, text: str) -> None:
        reasons.append({"code": code, "level": level, "text": text})

    tmax, tmin = _maxv(h.tmp for h in hs), _minv(h.tmp for h in hs)
    pop_max, wsd_max = _maxv(h.pop for h in hs), _maxv(h.wsd for h in hs)
    rain_h = sum(1 for h in hs if h.pty in (1, 2, 4))
    snow_h = sum(1 for h in hs if h.pty in (2, 3))
    pcp = sum(h.pcp_mm or 0 for h in hs)
    pcp_peak = _maxv(h.pcp_mm for h in hs) or 0
    sno = sum(h.sno_cm or 0 for h in hs)

    if hs:
        if snow_h or sno > 0:
            add("SNOW", 2 if sno >= 1 else 1, f"눈 {snow_h}시간" + (f" · {sno:g}cm" if sno else ""))
        if rain_h and not (snow_h and rain_h == snow_h):
            add("RAIN", 2 if pcp >= 30 or pcp_peak >= 10 else 1,
                f"비 {rain_h}시간" + (f" · {pcp:g}mm" if pcp >= 1 else ""))
        if tmax is not None and tmax >= 31:
            add("HEAT", 2 if tmax >= 33 else 1, f"더위 최고 {tmax:g}℃")
        if tmin is not None and tmin <= -5:
            add("COLD", 2 if tmin <= -10 else 1, f"추위 최저 {tmin:g}℃")
        if wsd_max is not None and wsd_max >= 9:
            add("WIND", 2 if wsd_max >= 14 else 1, f"바람 {wsd_max:g}m/s")
    for code, name, g in (("PM10", "미세먼지", pm10), ("PM25", "초미세먼지", pm25)):
        lv = AIR_LEVEL.get(g or "")
        if lv:
            add(code, lv, f"{name} {g}")

    # 운영 시간 날씨 예보가 없으면(지난 날·발표 전) 대기 등급만으로 판정하지 않음
    level = max([r["level"] for r in reasons] or [0]) if hs else None
    reasons.sort(key=lambda r: -r["level"])
    return Assessment(level, reasons, {
        "hours": len(hs), "tmpMin": tmin, "tmpMax": tmax, "popMax": pop_max, "pcpMm": round(pcp, 1),
        "snoCm": round(sno, 1), "wsdMax": wsd_max, "pm10": pm10, "pm25": pm25})
