"""계층 의존 방향 — 바깥(api·jobs)에서 안쪽(features → domain·core)으로만. import 를 정적으로 읽어 확인.

    api.routers → features → domain / calc.runs / core
    domain 은 DB·웹 프레임워크를 모름, core 는 기능 모듈을 모름.
"""
import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "atlas"

# 패키지 → import 하면 안 되는 모듈 접두어
FORBIDDEN = {
    "domain": ("atlas.api", "atlas.features", "atlas.calc", "atlas.collector", "atlas.jobs", "atlas.walk", "atlas.core.db",
               "sqlalchemy", "fastapi", "starlette", "redis"),
    "core": ("atlas.api", "atlas.features", "atlas.calc", "atlas.collector", "atlas.jobs", "atlas.walk", "atlas.domain"),
    "features": ("atlas.api", "atlas.jobs", "atlas.collector", "fastapi", "starlette"),
    "calc": ("atlas.api", "atlas.features", "atlas.collector"),
    "walk": ("atlas.api", "atlas.features", "atlas.collector"),
    "ops": ("atlas.api", "atlas.features", "atlas.collector"),
    "collector": ("atlas.api", "atlas.features"),
}


def _imports(path: Path) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append(node.module)
    return out


@pytest.mark.parametrize("pkg", sorted(FORBIDDEN))
def test_dependency_direction(pkg):
    bad = []
    for f in sorted((PKG / pkg).rglob("*.py")):
        for m in _imports(f):
            if any(m == p or m.startswith(p + ".") for p in FORBIDDEN[pkg]):
                bad.append(f"{f.relative_to(PKG)} → {m}")
    assert not bad, "안쪽 계층이 바깥을 import:\n" + "\n".join(bad)
