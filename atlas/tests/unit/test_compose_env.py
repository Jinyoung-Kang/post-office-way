"""설정이 실제로 컨테이너에 닿는지 — .env.example 이 안내하는 변수는 compose 가 넘겨야 하고, compose 기본값은 config 와 같아야 함.
README·.env.example 은 OSM_PBF_URL·WALK_* 를 .env 로 바꾸라고 했지만 compose 가 넘기지 않아 조용히 무시됐음(2차 리뷰 O1).
저장소 전체가 있어야 하므로(CI·저장소를 붙인 실행) compose 파일이 없으면(make test 이미지) 건너뜀."""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
COMPOSE, EXAMPLE = REPO / "docker-compose.yml", REPO / ".env.example"
pytestmark = pytest.mark.skipif(not COMPOSE.exists(), reason="저장소 루트(docker-compose.yml)가 없는 실행 — CI 에서 확인")
HOST_ONLY = {"DATABASE_URL", "REDIS_URL", "NEXT_PUBLIC_KAKAO_JS_KEY"}   # 호스트 개발용·web 이 따로 받는 값


def test_env_example_vars_reach_containers():
    names = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", EXAMPLE.read_text(), re.M)) - HOST_ONLY
    compose = COMPOSE.read_text()
    missing = sorted(n for n in names if not re.search(rf"^\s+{n}:", compose, re.M))
    assert not missing, f".env.example 에 있지만 compose 가 컨테이너에 넘기지 않는 변수: {missing}"


def test_walk_defaults_match_config():
    from atlas.core.config import Settings

    compose = COMPOSE.read_text()
    s = Settings(_env_file=None)
    for name, attr in (("OSM_PBF_URL", "osm_pbf_url"), ("WALK_LIMIT_M", "walk_limit_m"), ("WALK_SNAP_MAX_M", "walk_snap_max_m")):
        m = re.search(rf"^\s+{name}: \$\{{{name}:-([^}}]+)\}}", compose, re.M)
        assert m, name
        assert type(getattr(s, attr))(m.group(1)) == getattr(s, attr), name


def test_walk_env_reaches_worker_and_collector_only():
    """도보 설정은 계산하는 worker·collector 에만 — api 는 쓰지 않음(외부 설정을 받을 이유가 없음)."""
    compose = COMPOSE.read_text()

    def env_merge(service):
        block = re.search(rf"^  {service}:\n(.*?)(?=^  [a-z]+:\n|^volumes:)", compose, re.M | re.S).group(1)
        return re.search(r"environment:\n\s+<<: (.+)", block).group(1)

    assert "*walk-env" in env_merge("worker") and "*walk-env" in env_merge("collector")
    assert "*walk-env" not in env_merge("api")

