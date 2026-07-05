"""
cache.py — Redis 缓存工具（策略查询结果缓存 + 连接池管理）
============================================================

用法:
    from core.cache import get_cache

    cache = await get_cache()
    data = await cache.get("strategy:backtest:123")
    if not data:
        data = await compute_expensive_thing()
        await cache.set("strategy:backtest:123", data, ttl=300)
"""

import json
from collections.abc import Callable
from functools import wraps
from typing import Any

from core.config import settings

# 全局连接池
_pool = None


def _get_pool():
    """懒加载 Redis 连接池"""
    global _pool
    if _pool is None:
        try:
            import redis.asyncio as aioredis

            _pool = aioredis.ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=20,
                decode_responses=True,
                socket_timeout=3,
                socket_connect_timeout=3,
                retry_on_timeout=True,
            )
        except ImportError:
            return None
    return _pool


async def get_cache():
    """获取 Redis 缓存实例（连接失败返回 NoneCache）"""
    pool = _get_pool()
    if pool is None:
        return NoneCache()

    try:
        import redis.asyncio as aioredis

        r = aioredis.Redis(connection_pool=pool)
        await r.ping()
        return RedisCache(r)
    except Exception:
        return NoneCache()


class RedisCache:
    """Redis 缓存封装"""

    def __init__(self, client):
        self.client = client

    async def get(self, key: str, default=None) -> Any:
        try:
            raw = await self.client.get(key)
            if raw is None:
                return default
            return json.loads(raw)
        except Exception:
            return default

    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        try:
            return await self.client.setex(
                key, ttl, json.dumps(value, ensure_ascii=False, default=str)
            )
        except Exception:
            return False

    async def delete(self, key: str) -> bool:
        try:
            return bool(await self.client.delete(key))
        except Exception:
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """按模式批量清除缓存（如 clear_pattern("strategy:backtest:*")）"""
        try:
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await self.client.scan(cursor, match=pattern, count=100)
                if keys:
                    deleted += await self.client.delete(*keys)
                if cursor == 0:
                    break
            return deleted
        except Exception:
            return 0

    async def close(self):
        try:
            await self.client.close()
        except Exception:
            pass


class NoneCache:
    """兜底空缓存（Redis 不可用时静默降级）"""

    async def get(self, key: str, default=None) -> Any:
        return default

    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        return True

    async def delete(self, key: str) -> bool:
        return True

    async def clear_pattern(self, pattern: str) -> int:
        return 0

    async def close(self):
        pass


# ============================================================
# 装饰器：自动缓存函数结果
# ============================================================


def cached(ttl: int = 300, key_prefix: str = ""):
    """函数结果自动缓存的装饰器

    用法:
        @cached(ttl=60, key_prefix="backtest")
        async def get_backtest_result(strategy_id: str):
            ...
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache = await get_cache()

            # 生成缓存 key
            key_parts = [key_prefix or func.__name__]
            key_parts.extend(str(a) for a in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            # 尝试缓存命中
            result = await cache.get(cache_key)
            if result is not None:
                return result

            # 未命中：执行原函数
            result = await func(*args, **kwargs)
            await cache.set(cache_key, result, ttl=ttl)
            return result

        return wrapper

    return decorator


# ============================================================
# 连接池健康检查
# ============================================================


def pool_stats() -> dict:
    """返回连接池当前状态"""
    global _pool
    if _pool is None:
        return {"available": False, "reason": "连接池未初始化"}
    try:
        return {
            "available": True,
            "max_connections": _pool.max_connections,
            "in_use": getattr(_pool, "_in_use_connections", 0),
            "available_connections": getattr(_pool, "_available_connections", 0),
        }
    except Exception as e:
        return {"available": False, "reason": str(e)}
