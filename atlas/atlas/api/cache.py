"""Redis 캐시 — GeoJSON(calc_run 단위 무효화)·What-if(TTL 1h). Redis 가 없어도 API 는 동작합니다."""
from __future__ import annotations

import logging
from functools import lru_cache

import redis

from atlas.core.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=1.0, socket_connect_timeout=1.0)


def get(key: str) -> bytes | None:
    from atlas.api.metrics import CACHE

    try:
        v = client().get(key)
    except redis.RedisError:
        return None
    CACHE.labels("hit" if v is not None else "miss").inc()
    return v


def set(key: str, value: str | bytes, ttl: int | None = None) -> None:  # noqa: A001
    try:
        client().set(key, value, ex=ttl)
    except redis.RedisError:
        log.warning("cache set failed", extra={"key": key})


def delete_prefix(prefix: str) -> int:
    n = 0
    try:
        for k in client().scan_iter(match=f"{prefix}*", count=500):
            n += client().delete(k)
    except redis.RedisError:
        log.warning("cache delete failed", extra={"prefix": prefix})
    return n


def ping() -> bool:
    try:
        return bool(client().ping())
    except redis.RedisError:
        return False
