"""모든 테스트 공용 — 어떤 테스트도 운영 Redis(캐시·속도 제한 카운터)를 건드리지 않게, 설정을 읽기 전에 Redis 주소를 고정."""
import os

# make test 는 compose 의 redis 15번 DB(운영은 0번), 없으면 닿지 않는 주소(캐시 없음 경로)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:1/0")
