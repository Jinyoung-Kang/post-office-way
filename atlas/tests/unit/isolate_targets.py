"""격리 작업 테스트용 자식 프로세스 대상 — spawn 자식이 이름으로 불러올 수 있게 모듈 최상위에 둠."""
import time


class TwoArgError(RuntimeError):
    """생성자 인자가 둘이라 기본 pickle 로는 되살릴 수 없는 예외 (RunInProgress·JobConflict 와 같은 꼴)."""

    def __init__(self, kind: str, run_id: str):
        super().__init__(f"{kind} 실행 중 ({run_id})")
        self.kind, self.run_id = kind, run_id


def sleepy(kind, params):
    time.sleep(params["s"])
    return {"slept": params["s"]}


def two_arg_error(kind, params):
    raise TwoArgError(kind, "r-1")


def open_run_and_sleep(kind, params):
    """실행 기록을 연 채 오래 걸리는 작업 — 시간 초과로 자식이 끝나면 except·finally 가 돌지 않아 기록이 RUNNING 으로 남음."""
    from atlas.ops import runs

    runs.start_run("OSM_WALK", check_running=False)
    time.sleep(params["s"])
    return {}
