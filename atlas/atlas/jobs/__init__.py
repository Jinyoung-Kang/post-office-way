"""작업 실행 계층 — 수집·계산 작업의 단일 목록(registry), Postgres 작업 큐(queue), 스케줄(scheduler), 워커(worker).

CLI(`atlas collect …`)는 같은 registry 를 바로 실행하고, API 는 queue 에 넣기만 하며, 워커가 가져가 실행합니다.
"""
