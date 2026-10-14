# ADR-025 실행 기록은 중단(Ctrl-C)에도 닫는다 — `except BaseException` + 정적 검사

- 상태: 채택 (2026-10-15, 2차 리뷰 D9)

## 맥락
- 수집·계산·도보·OSM 은 시작할 때 실행 기록(`ops.collect_run`·`mart.calc_run`·`mart.walk_run`)을 RUNNING 으로 커밋한다.
  실패하면 `except Exception` 에서 FAILED 로 닫고 다시 던진다(17곳, 모두 같은 꼴).
- `KeyboardInterrupt`·`SystemExit` 는 `Exception` 이 아니다. 그래서 `make calc`·`make osm` 을 Ctrl-C 로 멈추면 기록이 RUNNING 으로 남았다.
  CLI 실행은 job_id 가 없어 워커의 `close_runs`·`reap` 도 닫지 못한다(V22 는 job_id 로만 닫음).
- 그 결과 '이미 실행 중' 판정이 계산은 2시간, 수집은 6시간 동안 같은 종류의 새 실행을 막았다. 예를 들어 수집 뒤 이어지는 재계산과
  도보 계산이 모두 실패했다.

## 결정
- 실행 기록을 닫는 `except` 17곳을 `except BaseException` 으로 바꾼다. 모두 기록을 닫은 뒤 다시 던지므로 중단 자체는 그대로 전달되고,
  기록만 남는다.
- 새 수집기가 같은 실수를 하지 않도록 정적 검사를 둔다. `tests/unit/test_layers.py::test_run_failure_handlers_catch_base_exception` 은
  `finish_run(` 이나 `'FAILED'` 를 쓰는 `except` 가 `BaseException` 이면서 다시 던지는지 확인한다.

## 검토한 대안
- **컨테이너 관리자 `with runs.tracked(kind) as run_id:`** — 구조로는 가장 깔끔하다. 그러나 17곳의 함수 본문을 한 단계씩 들여 써야 해
  diff 가 수백 줄이 되고, 수집기마다 PARTIAL·DONE 판정과 통계가 달라 공통 인터페이스가 억지스러워진다. 같은 효과를 정적 검사가 준다.
- **CLI 에 SIGINT 처리기를 두고 정리** — 어느 기록을 닫을지 처리기가 알 수 없고, 워커의 격리 자식에는 적용되지 않는다.
- **'이미 실행 중' 판단 시간을 줄이기** — 정상적인 긴 실행(도로 거리 25분, 계산 40초~수 분)을 잘못 끊을 위험이 있다.

## 감수한 단점
- `kill -9`·전원 차단처럼 잡을 수 없는 종료는 여전히 RUNNING 으로 남는다. 이 경우는 지금처럼 시간 기준(계산 2시간·수집 6시간)으로 풀린다.
- 정적 검사는 휴리스틱이다(본문의 `finish_run(`·`'FAILED'` 문자열로 판단). 다른 방식으로 기록을 닫는 코드를 새로 만들면 검사가 놓친다.
