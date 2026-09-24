"""DB 엔진·세션. 공간 연산은 SQL 로 위임하므로 ORM 모델 없이 text() 쿼리를 씁니다."""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

from atlas.core.config import get_settings

_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_settings().database_url, pool_pre_ping=True, pool_size=5,
                         max_overflow=5, future=True)


@contextmanager
def begin(engine: Engine | None = None) -> Iterator[Connection]:
    """트랜잭션 블록. 정상 종료 시 commit, 예외 시 rollback."""
    with (engine or get_engine()).begin() as conn:
        yield conn


def load_sql(name: str) -> str:
    """atlas/sql/ 아래 SQL 파일을 읽습니다 (지표 SQL 은 파일로 관리)."""
    return (_SQL_DIR / name).read_text(encoding="utf-8")


def run_sql_file(conn: Connection, name: str, params: dict | None = None) -> None:
    """';' 로 끝나는 문장 단위로 나눠 실행합니다. 각 문장은 bind 파라미터를 받습니다."""
    for stmt in split_sql(load_sql(name)):
        conn.execute(text(stmt), params or {})


def split_sql(sql: str) -> list[str]:
    stmts, buf = [], []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        # 줄 끝 주석('…;  -- 설명')이 있어도 문장 끝으로 인식 (따옴표 안 '--' 는 SQL 파일에서 쓰지 않음)
        code = line.split("--", 1)[0].rstrip()
        if code.endswith(";"):
            buf.append(code)
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(line)
    tail = "\n".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts
