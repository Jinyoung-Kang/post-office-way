"""우편 지역코드 seed (seed/area_codes.csv) 읽기·쓰기.

명세서 지역코드표를 옮겨 적거나, `atlas discover post` 로 코드 범위를 훑어 자동 생성합니다.
형식: code,region,subregion,is_center,total_count
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from atlas.core.config import get_settings


@dataclass
class AreaCode:
    code: str
    region: str = ""
    subregion: str = ""
    is_center: bool = False
    total_count: int | None = None


def seed_path() -> Path:
    return Path(get_settings().seed_dir) / "area_codes.csv"


def load_area_codes(path: Path | None = None) -> list[AreaCode]:
    p = path or seed_path()
    if not p.exists():
        return []
    out: list[AreaCode] = []
    with p.open(encoding="utf-8") as f:
        for row in csv.DictReader(line for line in f if not line.lstrip().startswith("#")):
            code = (row.get("code") or "").strip()
            if not code:
                continue
            tc = (row.get("total_count") or "").strip()
            out.append(AreaCode(
                code=code, region=(row.get("region") or "").strip(),
                subregion=(row.get("subregion") or "").strip(),
                is_center=(row.get("is_center") or "").strip().lower() in ("1", "true", "y", "yes")
                or code.lower().startswith("c"),
                total_count=int(tc) if tc.isdigit() else None))
    return out


def write_area_codes(codes: list[AreaCode], path: Path | None = None) -> Path:
    p = path or seed_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        f.write("# 우편 지역코드 seed — `make discover` 로 생성. 명세서 지역코드표로 교체·보완 가능\n")
        w = csv.writer(f)
        w.writerow(["code", "region", "subregion", "is_center", "total_count"])
        for c in codes:
            w.writerow([c.code, c.region, c.subregion, "true" if c.is_center else "false",
                        "" if c.total_count is None else c.total_count])
    return p
