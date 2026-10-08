"""테스트 DB 안전장치 (S9) — 스키마를 통째로 지우므로 DB 이름이 정확히 atlas_test 일 때만."""
from tests.sql.conftest import is_test_db


def test_only_exact_test_database_name():
    assert is_test_db("postgresql+psycopg://atlas:atlas@db:5432/atlas_test")
    assert not is_test_db("postgresql+psycopg://atlas_test:pw@db:5432/atlas")           # 사용자명에만 있음
    assert not is_test_db("postgresql+psycopg://atlas:pw@db:5432/atlas?app=atlas_test")   # 쿼리 문자열에만 있음
    assert not is_test_db("postgresql+psycopg://atlas:pw@db:5432/atlas_test_old")
    assert not is_test_db("not a url")
