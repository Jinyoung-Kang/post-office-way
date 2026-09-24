"""아주 작은 마이그레이션 러너 — db/migrations/V*__*.sql 을 버전 순서로 한 번씩 적용.

api 기동 시와 테스트 DB 준비 시 같은 코드를 씁니다(initdb 마운트 대신 단일 경로).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import Engine, text

from atlas.core.config import get_settings

log = logging.getLogger(__name__)
_VER = re.compile(r"^V(\d+)__.+\.sql$")


def migrate(engine: Engine, migrations_dir: str | None = None) -> list[str]:
    root = Path(migrations_dir or get_settings().migrations_dir)
    files = sorted((f for f in root.glob("V*__*.sql") if _VER.match(f.name)),
                   key=lambda f: int(_VER.match(f.name).group(1)))
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
