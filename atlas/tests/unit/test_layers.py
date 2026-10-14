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


def test_routers_have_no_sql():
    """라우터는 HTTP(입력·상태 코드·헤더)만 — SQL 은 features 의 조회 함수로. health 는 DB 연결 자체를 확인하는 곳이라 예외."""
    bad = [f"{f.name} → {m}" for f in sorted((PKG / "api" / "routers").glob("*.py")) if f.name != "health.py"
           for m in _imports(f) if m == "sqlalchemy" or m.startswith("sqlalchemy.")]
    assert not bad, "라우터에 SQL:\n" + "\n".join(bad)


def _closes_run(handler: ast.ExceptHandler) -> bool:
    src = ast.unparse(handler)
    return "finish_run(" in src or "'FAILED'" in src or '"FAILED"' in src


def test_run_failure_handlers_catch_base_exception():
    """실행 기록(수집·계산·도보)을 FAILED 로 닫는 except 는 BaseException 이어야 함 — Exception 이면 Ctrl-C(KeyboardInterrupt)·
    SystemExit 에서 기록이 RUNNING 으로 남아 수 시간 동안 같은 종류의 실행이 '이미 실행 중'으로 막힘. 닫은 뒤에는 늘 다시 던짐."""
    bad = []
    for f in sorted(PKG.rglob("*.py")):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ExceptHandler) and _closes_run(node):
                caught = ast.unparse(node.type) if node.type else "BaseException"
                reraises = any(isinstance(n, ast.Raise) and n.exc is None for n in ast.walk(node))
                if caught != "BaseException" or not reraises:
                    bad.append(f"{f.relative_to(PKG)}:{node.lineno} except {caught}")
    assert not bad, "실행 기록을 닫는 except 가 BaseException 이 아니거나 다시 던지지 않음:\n" + "\n".join(bad)


def test_latest_done_calc_run_defined_once():
    """'최신 완료 계산 실행' 정의(동률 처리 포함)는 calc/runs.py 한 곳 — prune·기상청 수집에 복사본이 남아 동률 처리가 달랐음."""
    import re

    pat = re.compile(r"FROM mart\.calc_run\s+WHERE status = 'DONE'\s+ORDER BY finished_at", re.S)
    bad = [str(f.relative_to(PKG)) for f in sorted(PKG.rglob("*.py")) if f.name != "runs.py" and pat.search(f.read_text())]
    assert not bad, "최신 완료 계산 실행을 따로 정의: " + ", ".join(bad)
