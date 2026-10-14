"""`atlas collect walk`(make calc 의 둘째 단계·make walk) — 도보 계산을 건너뛰면 이유를 보여야 함 (2차 리뷰 B10)."""
from atlas.collector import cli
from atlas.jobs import registry


def _run(monkeypatch, result):
    monkeypatch.setattr(registry, "run", lambda kind, params=None: result)
    return cli.cmd_collect(cli.build_parser().parse_args(["collect", "walk"]))


def test_walk_skip_reason_is_shown(monkeypatch, capsys):
    """그래프가 없으면 안내만 하고 0 (OSM 을 받지 않은 설치에서 make calc 가 실패하지 않게)."""
    assert _run(monkeypatch, {"skipped": "도보 그래프 없음 — `make osm`"}) == 0
    assert "도보 그래프 없음" in capsys.readouterr().err


def test_stale_graph_needs_action(monkeypatch, capsys):
    """그래프 규칙이 바뀌어 건너뛰면 조치가 필요하므로 1 — 예전에는 아무것도 출력하지 않고 0 이라 도보 지표가 빈 이유를 알 수 없었음."""
    assert _run(monkeypatch, {"skipped": "도보 그래프 규칙이 바뀌었습니다", "stale": True}) == 1
    assert "규칙이 바뀌었습니다" in capsys.readouterr().err


def test_walk_result_is_printed(monkeypatch, capsys):
    assert _run(monkeypatch, {"calcRunId": "x", "oa": 3, "rows": 7}) == 0
    assert '"rows": 7' in capsys.readouterr().out
