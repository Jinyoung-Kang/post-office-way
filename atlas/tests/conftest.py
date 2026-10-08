"""모든 테스트 공용 — 어떤 테스트도 운영 DB·운영 Redis 를 건드리지 않게, 설정을 읽기 전에 접속 주소를 고정.

테스트 컨테이너는 compose 의 DATABASE_URL(운영 DB)을 물려받으므로, 그대로 두면 DB 픽스처를 쓰지 않는 단위 테스트가
운영 DB 에 쓸 수 있음 — 2026-10-08 실제로 단위 테스트의 run_walk() 가 운영 도보 결과를 덮어쓴 일이 있었음(바로 다시 계산해 복구).
"""
import os

# DB: TEST_DATABASE_URL(atlas_test) 또는 닿지 않는 주소. SQL 테스트는 tests/sql/conftest.py 가 DB 이름을 다시 확인
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://nobody@127.0.0.1:1/no_db")
# Redis: make test 는 compose 의 redis 15번 DB(운영은 0번), 없으면 닿지 않는 주소(캐시 없음 경로)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:1/0")
