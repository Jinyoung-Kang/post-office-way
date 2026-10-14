"""`atlas enqueue KIND --param k=v` — 값의 형(bool·정수·목록)이 API(JSON)와 같게 전달되는지 (2차 리뷰 B4)."""
import pytest

from atlas.collector import cli


@pytest.fixture()
def captured(monkeypatch):
    got = {}
    monkeypatch.setattr("atlas.jobs.queue.enqueue", lambda kind, params, **kw: got.update(kind=kind, params=params) or 1)
    return got


def _run(*argv):
    return cli.cmd_enqueue(cli.build_parser().parse_args(["enqueue", *argv]))


def test_param_values_keep_types(captured, monkeypatch):
    """예전에는 모든 값이 문자열이라 refresh=false 가 참(집계구 전체 재수집), maxCalls=500 이 TypeError, recalc=false 가 무시됐음."""
    monkeypatch.setattr("atlas.jobs.registry.JobSpec.missing", lambda self, s=None: [])
    assert _run("road", "--param", "maxCalls=500", "--param", "recalc=false") == 0
    assert captured["params"] == {"maxCalls": 500, "recalc": False}
    assert _run("holidays", "--param", "years=[2027]") == 0 and captured["params"] == {"years": [2027]}
    assert _run("calc", "--param", "levels=[2,3]") == 0 and captured["params"] == {"levels": [2, 3]}


def test_string_params_stay_strings(captured, monkeypatch):
    """지역코드 목록·실행 id 는 숫자처럼 보여도 문자열 그대로."""
    monkeypatch.setattr("atlas.jobs.registry.JobSpec.missing", lambda self, s=None: [])
    assert _run("post", "--param", "scope=100", "--param", "resume=123") == 0
    assert captured["params"] == {"scope": "100", "resume": "123"}
    assert _run("walk", "--param", "calcRunId=0") == 0 and captured["params"] == {"calcRunId": "0"}


def test_unknown_kind_and_missing_key_are_messages(captured, monkeypatch, capsys):
    """없는 작업 종류·키 누락은 트레이스백 대신 안내와 종료 코드 2 (API 의 VALIDATION_ERROR·KEY_MISSING 과 같은 판단)."""
    assert _run("nope") == 2 and "작업 종류" in capsys.readouterr().err
    monkeypatch.setattr("atlas.jobs.registry.JobSpec.missing", lambda self, s=None: ["KAKAO_REST_API_KEY"])
    assert _run("road") == 2 and "KAKAO_REST_API_KEY" in capsys.readouterr().err
    assert "kind" not in captured


def test_holidays_accepts_single_year(monkeypatch):
    """years=2027(해 하나)도 목록처럼 — 예전에는 문자열 '2027' 을 순회해 '2','0','2','7' 해를 4번 요청했음."""
    from atlas.collector.datago import holiday
    from atlas.jobs import registry

    got = {}
    monkeypatch.setattr(holiday, "collect_holidays", lambda years=None: got.update(years=years))
    registry.JOBS["holidays"].run({"years": 2027})
    assert got["years"] == [2027]
