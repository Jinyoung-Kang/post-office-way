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
