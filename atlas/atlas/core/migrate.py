"""아주 작은 마이그레이션 러너 — db/migrations/V*__*.sql 을 버전 순서로 한 번씩 적용.

적용은 소유자 권한으로 한 번만 도는 compose 서비스 `migrate`(= `atlas migrate`)와 테스트 준비에서만 합니다.
API 는 DDL 권한이 없는 역할로 접속하므로 기동 때 pending() 으로 스키마가 최신인지 확인만 합니다(ADR-012).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import Engine, text

from atlas.core.config import get_settings

log = logging.getLogger(__name__)
_VER = re.compile(r"^V(\d+)__.+\.sql$")


def _files(migrations_dir: str | None = None) -> list[Path]:
    root = Path(migrations_dir or get_settings().migrations_dir)
    return sorted((f for f in root.glob("V*__*.sql") if _VER.match(f.name)), key=lambda f: int(_VER.match(f.name).group(1)))


def pending(engine: Engine, migrations_dir: str | None = None) -> list[str]:
    """아직 적용되지 않은 마이그레이션 파일 이름 (읽기 전용 — API 기동·헬스 체크용)."""
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT to_regclass('public.schema_migrations')")).scalar()
        done = {r[0] for r in conn.execute(text("SELECT version FROM public.schema_migrations"))} if exists else set()
    return [f.name for f in _files(migrations_dir) if int(_VER.match(f.name).group(1)) not in done]


def migrate(engine: Engine, migrations_dir: str | None = None) -> list[str]:
    files = _files(migrations_dir)
    applied: list[str] = []
    with engine.begin() as conn:
        # 여러 워커가 동시에 기동해도 한 번만 적용되도록 advisory lock
        conn.execute(text("SELECT pg_advisory_xact_lock(7240001)"))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS public.schema_migrations (
                                 version int PRIMARY KEY, name text NOT NULL,
                                 applied_at timestamptz NOT NULL DEFAULT now())"""))
        done = {r[0] for r in conn.execute(text("SELECT version FROM public.schema_migrations"))}
        for f in files:
            ver = int(_VER.match(f.name).group(1))
            if ver in done:
                continue
            # 파라미터 없이 DBAPI 로 직접 실행 — '%' 가 들어간 SQL 을 플레이스홀더로 오해하지 않게
            with conn.connection.cursor() as cur:
                cur.execute(f.read_text(encoding="utf-8"))
            conn.execute(text("INSERT INTO public.schema_migrations(version, name) VALUES (:v, :n)"),
                         {"v": ver, "n": f.name})
            applied.append(f.name)
            log.info("migration applied", extra={"migration": f.name})
    return applied


def set_role_password(engine: Engine, role: str, password: str) -> None:
    """최소 권한 역할에 로그인 비밀번호 설정 (값은 .env 에서만, 로그에 남기지 않음)."""
    from psycopg import sql

    if not password:
        return
    with engine.begin() as conn, conn.connection.cursor() as cur:
        cur.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
    log.info("role password set", extra={"role": role})

