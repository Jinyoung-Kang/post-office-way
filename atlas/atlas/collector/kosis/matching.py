"""KOSIS(행안부 지역코드) ↔ SGIS(adm_cd) 행정구역 매칭 — 순수 함수(단위 테스트 대상).

두 체계의 코드는 서로 다르므로 '시도 이름 + 시군구 이름 (+ 읍면동 이름)'으로 맞춥니다.
- KOSIS 계층: 시도(2) → [시(5)] → 구·군·시(5) → 읍면동(10). "수원시 > 장안구" 는 "수원시 장안구" 로 합칩니다.
- SGIS 이름: 시군구 "수원시 장안구", 읍면동 "파장동".
- 한 시도에 이름으로 안 맞는 시군구가 양쪽에 1개씩만 남으면 짝지음(세종처럼 이름 체계가 다른 경우) → SINGLE.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_STRIP = re.compile(r"[\s·ㆍ.()\-]")
_JE = re.compile(r"제(?=\d+[동가]$)")  # 행안부 표기 "창신제1동"·"홍제제1동" ↔ SGIS "창신1동"·"홍제1동"


def norm(name: str | None) -> str:
    return _STRIP.sub("", name or "")


def kosis_keys(name: str | None) -> list[str]:
    """KOSIS 이름의 비교 키 — 원래 이름과 '제N동'의 '제'를 뗀 이름 둘 다 (SGIS 쪽은 원래 이름만)."""
    n = norm(name)
    alt = _JE.sub("", n, count=1) if n.count("제") else n
    return [n] if alt == n else [n, alt]


def infer_parent(code: str, names: dict[str, str]) -> str | None:
    """코드만으로 상위 추정 — 그 시점 자료의 계층을 쓰기 위함(메타는 현재 계층만 있어 과거 시점과 다를 수 있음).
    10자리 → 앞 5자리. 5자리 → 앞 4자리+'0' 이 '…시' 이름으로 있으면 그 시의 구(수원시 장안구), 아니면 시도.
    (이름 조건: 43745 증평군이 43740 영동군 아래로 잘못 붙지 않도록)"""
    if len(code) == 10:
        return code[:5]
    if len(code) == 5:
        city = code[:4] + "0"
        return city if city != code and (names.get(city) or "").endswith("시") else code[:2]
    return None


def aged_codes(age_items: list[tuple[str, str]], min_age: int = 65) -> tuple[str | None, list[str]]:
    """5세별 분류 [(코드, 이름)] → (합계 코드, 65세 이상 구간 코드들). 이름 예: '65 - 69세', '100+'."""
    total, aged = None, []
    for code, name in age_items:
        n = (name or "").strip()
        if n in ("계", "합계", "전체"):
            total = code
            continue
        m = re.match(r"^(\d+)", n)
        if m and int(m.group(1)) >= min_age:
            aged.append(code)
    return total, aged


@dataclass
class KosisRegion:
    code: str
    name: str
    parent: str | None


@dataclass
class KosisTree:
    """KOSIS 지역 분류(meta ITM, OBJ_ID=A)를 시도·시군구·읍면동 이름 경로로 정리."""

    regions: dict[str, KosisRegion] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, items: list[tuple[str, str, str | None]]) -> "KosisTree":
        t = cls()
        for code, name, parent in items:
            t.regions[code] = KosisRegion(code, (name or "").strip(), parent or None)
            if parent:
                t.children.setdefault(parent, []).append(code)
        return t

    def sido_of(self, code: str) -> str:
        return code[:2]

    def is_branch(self, code: str) -> bool:
        return "출장소" in self.regions[code].name

    def sgg_fullname(self, code: str) -> str:
        """5자리 시군구 이름. 부모도 5자리(시)면 '시 구' 로 합침."""
        r = self.regions[code]
        p = self.regions.get(r.parent or "")
        if p and len(p.code) == 5:
            return f"{p.name} {r.name}"
        return r.name

    def sgg_codes(self, sido: str) -> list[str]:
        """구가 있는 시(수원시 등)는 제외하고 말단 시군구만."""
        return [c for c in self.regions
                if len(c) == 5 and c.startswith(sido) and not self.is_branch(c)
                and not any(len(ch) == 5 for ch in self.children.get(c, []))]

    def emd_codes(self, sgg: str) -> list[str]:
        return [c for c in self.children.get(sgg, []) if len(c) == 10]


@dataclass
class SgisArea:
    adm_cd: str
    name: str
    level: int
    parent_cd: str | None


def match(tree: KosisTree, sido_names: dict[str, str], sgis: list[SgisArea],
          kosis_sido_names: dict[str, str], available: set[str] | None = None) -> dict[str, tuple[str, str]]:
    """SGIS adm_cd → (KOSIS 코드, 방법 NAME|SINGLE). available 이면 값이 있는 KOSIS 코드만 후보로."""
    ok = (lambda c: True) if available is None else (lambda c: c in available)
    by_sido_name = {norm(v): k for k, v in kosis_sido_names.items()}
    out: dict[str, tuple[str, str]] = {}
    l2 = [a for a in sgis if a.level == 2]
    l3 = [a for a in sgis if a.level == 3]
    sgis_l2_by_sido: dict[str, list[SgisArea]] = {}
    for a in l2:
        sgis_l2_by_sido.setdefault(a.adm_cd[:2], []).append(a)

    sgg_pair: dict[str, str] = {}  # SGIS 시군구 → KOSIS 시군구
    for s_sido, areas in sgis_l2_by_sido.items():
        k_sido = by_sido_name.get(norm(sido_names.get(s_sido)))
        if not k_sido:
            continue
        cands = {norm(tree.sgg_fullname(c)): c for c in tree.sgg_codes(k_sido) if ok(c)}
        # '수원시 장안구' 와 '장안구' 둘 다로 찾을 수 있게
        short = {}
        for c in tree.sgg_codes(k_sido):
            if ok(c):
                short.setdefault(norm(tree.regions[c].name), []).append(c)
        left_s, used = [], set()
        for a in areas:
            k = cands.get(norm(a.name))
            last = norm((a.name.split() or [""])[-1])
            if not k and len(short.get(last, [])) == 1:
                k = short[last][0]
            if k and k not in used:
                out[a.adm_cd] = (k, "NAME")
                sgg_pair[a.adm_cd] = k
                used.add(k)
            else:
                left_s.append(a)
        left_k = [c for c in cands.values() if c not in used]
        if len(left_s) == 1 and len(left_k) == 1:
            out[left_s[0].adm_cd] = (left_k[0], "SINGLE")
            sgg_pair[left_s[0].adm_cd] = left_k[0]

    for a in l3:
        k_sgg = sgg_pair.get(a.parent_cd or a.adm_cd[:5])
        if not k_sgg:
            continue
        # 대체 키('제' 뗀 이름)를 먼저 넣고 원래 이름으로 덮어써, 실제 이름이 항상 우선하게
        emds: dict[str, str] = {}
        for c in tree.emd_codes(k_sgg):
            if ok(c):
                for key in reversed(kosis_keys(tree.regions[c].name)):
                    emds[key] = c
        # SGIS 일부 읍면동 이름에 구가 붙어 있음("덕진구 금암2동") → 마지막 낱말로도 시도
        k = emds.get(norm(a.name)) or emds.get(norm((a.name.split() or [""])[-1]))
        if k:
            out[a.adm_cd] = (k, "NAME")
    return out
