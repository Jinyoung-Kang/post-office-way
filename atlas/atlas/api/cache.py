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


def set_nx(key: str, value: str, ttl: int) -> bool:
    """처음이면 True (중복 억제용). Redis 가 없으면 False — 공개 쓰기 경로(CSP 보고)에서 중복 억제·상한을 지킬 수 없을 때
    무제한으로 기록하지 않게 닫힌 쪽으로 (S7). 기록이 빠져도 서버 로그에는 남음."""
    try:
        return bool(client().set(key, value, ex=ttl, nx=True))
    except redis.RedisError:
        return False


def incr(key: str, ttl: int) -> int | None:
    """창 단위 카운터 — 처음 늘릴 때 만료를 걺. Redis 가 없으면 None."""
    try:
        with client().pipeline(transaction=True) as p:
            n, _ = p.incr(key).expire(key, ttl, nx=True).execute()
        return int(n)
    except redis.RedisError:
        return None


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
