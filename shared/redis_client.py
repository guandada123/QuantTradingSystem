"""
Redis 客户端工厂 — 支持 Sentinel 高可用和单实例双模式

功能：
- Sentinel 模式：通过 REDIS_SENTINEL_HOSTS 环境变量启用
- 单实例模式：通过标准 redis:// URL 连接（向后兼容）
- 自动降级：redis 模块未安装时返回 None，不阻塞主流程

用法：
    from shared.redis_client import get_redis_client

    # 自动判断模式（优先 Sentinel）
    client = get_redis_client("redis://localhost:6379/0")
    if client:
        client.lpush("key", "value")

    # 或显式指定 Sentinel
    client = get_redis_client(
        redis_url="redis://localhost:6379/0",
        sentinel_hosts="sentinel1:26379,sentinel2:26379",
        sentinel_service_name="mymaster",
    )
"""

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 环境变量名称常量
ENV_SENTINEL_HOSTS = "REDIS_SENTINEL_HOSTS"
ENV_SENTINEL_SERVICE_NAME = "REDIS_SENTINEL_SERVICE_NAME"
ENV_SENTINEL_SOCKET_TIMEOUT = "REDIS_SENTINEL_SOCKET_TIMEOUT"

# 默认值
DEFAULT_SENTINEL_SERVICE_NAME = "mymaster"
DEFAULT_SENTINEL_SOCKET_TIMEOUT = 0.1


def get_redis_client(
    redis_url: str = "redis://localhost:6379/0",
    sentinel_hosts: Optional[str] = None,
    sentinel_service_name: str = DEFAULT_SENTINEL_SERVICE_NAME,
    sentinel_socket_timeout: float = DEFAULT_SENTINEL_SOCKET_TIMEOUT,
) -> Optional[Any]:
    """
    创建 Redis 客户端，支持 Sentinel 高可用和单实例双模式。

    Sentinel 模式优先于单实例模式：
    1. sentinel_hosts 参数非空 → 使用 Sentinel
    2. REDIS_SENTINEL_HOSTS 环境变量非空 → 使用 Sentinel
    3. 以上均未设置 → 使用 redis:// URL 单实例连接

    Args:
        redis_url: 标准 Redis URL（Sentinel 未启用时的 fallback）
        sentinel_hosts: Sentinel 节点列表 "host1:26379,host2:26379"
        sentinel_service_name: Sentinel 监控的服务名
        sentinel_socket_timeout: Socket 超时（秒）

    Returns:
        Redis 客户端实例，或 None（redis 不可用或连接失败时）
        返回的客户端兼容 lpush/lrange/expire/ping 等操作。
    """
    # 可选导入 redis
    try:
        import redis as redis_mod  # noqa: F401
    except ImportError:
        logger.warning("redis 模块未安装，Redis 功能不可用")
        return None

    # 确定 Sentinel 是否启用（参数 > 环境变量 > 禁用）
    hosts = sentinel_hosts or os.environ.get(ENV_SENTINEL_HOSTS, "")

    if hosts:
        return _create_sentinel_client(hosts, sentinel_service_name, sentinel_socket_timeout)

    # 标准单实例模式
    try:
        client = redis_mod.from_url(redis_url)
        logger.debug("Redis 客户端创建成功（单实例模式）")
        return client
    except Exception as e:
        logger.warning(f"Redis 连接失败（单实例模式）: {e}")
        return None


def _create_sentinel_client(
    hosts: str,
    service_name: str = DEFAULT_SENTINEL_SERVICE_NAME,
    socket_timeout: float = DEFAULT_SENTINEL_SOCKET_TIMEOUT,
) -> Optional[Any]:
    """
    创建 Redis Sentinel 客户端。

    Args:
        hosts: 逗号分隔的 host:port 列表（如 "host1:26379,host2:26379"）
        service_name: Sentinel 监控的服务名
        socket_timeout: Socket 超时（秒）

    Returns:
        Redis master 客户端，或 None
    """
    try:
        from redis.sentinel import Sentinel
    except ImportError:
        logger.warning("redis.sentinel 模块不可用（redis 版本过低），Redis 功能不可用")
        return None

    # 解析节点列表
    sentinel_list = []
    for host_port in hosts.split(","):
        host_port = host_port.strip()
        if not host_port:
            continue
        if ":" in host_port:
            host, port_str = host_port.split(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                logger.warning(f"Sentinel 节点格式错误 '{host_port}'，已跳过")
                continue
        else:
            host = host_port
            port = 26379
        sentinel_list.append((host, port))

    if not sentinel_list:
        logger.error("未配置有效的 Redis Sentinel 节点")
        return None

    # 连接 Sentinel 并获取 master
    try:
        sentinel = Sentinel(sentinel_list, socket_timeout=socket_timeout)
        master = sentinel.master_for(service_name, socket_timeout=socket_timeout)
        # 验证连接
        master.ping()
        logger.info(
            f"Redis Sentinel 就绪（{len(sentinel_list)} 节点, "
            f"service={service_name}）"
        )
        return master
    except Exception as e:
        logger.warning(f"Redis Sentinel 连接失败: {e}")
        return None


__all__ = ["get_redis_client", "ENV_SENTINEL_HOSTS", "ENV_SENTINEL_SERVICE_NAME"]
