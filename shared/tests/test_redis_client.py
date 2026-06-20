"""shared/redis_client.py 单元测试 — Redis 客户端工厂"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unittest.mock import MagicMock, patch

import pytest

# ── redis 模块不存在 ─────────────────────────────────────
# 运行环境可能未安装 redis → 用 sys.modules mock 模拟双路径
# 在所有测试前清理避免污染
import shared.redis_client as rc

# ============================================================
#  get_redis_client — redis 模块未安装
# ============================================================


class TestGetRedisClientRedisNotInstalled:
    """redis 模块不可用时 get_redis_client 返回 None"""

    def test_returns_none_when_redis_missing(self):
        result = rc.get_redis_client()
        assert result is None

    def test_returns_none_with_url(self):
        result = rc.get_redis_client(redis_url="redis://localhost:6379/0")
        assert result is None

    def test_returns_none_with_sentinel(self):
        result = rc.get_redis_client(
            redis_url="redis://localhost:6379/0",
            sentinel_hosts="host1:26379,host2:26379",
        )
        assert result is None


# ============================================================
#  _create_sentinel_client — 通过 sys.modules mock 测试
# ============================================================


class _MockRedis:
    """模拟 redis.Redis 客户端"""

    def ping(self):
        return True

    def from_url(self, url, **kwargs):
        return self


class TestCreateSentinelClient:
    """通过 mock redis 模块测试 Sentinel 路径"""

    def _make_fake_redis_pkg(self):
        """创建 fake redis 包层次"""
        import collections.abc

        # 创建嵌套结构
        class FakeRedis:
            pass

        # 模拟 redis.Redis
        fake_redis_cls = MagicMock()
        fake_redis_instance = _MockRedis()
        fake_redis_from_url = MagicMock(return_value=fake_redis_instance)
        fake_redis_cls.from_url = fake_redis_from_url
        FakeRedis.Redis = fake_redis_cls

        # 模拟 redis.sentinel.Sentinel
        fake_sentinel_instance = MagicMock()
        fake_master = _MockRedis()
        fake_sentinel_instance.master_for.return_value = fake_master
        fake_sentinel_instance.master_for = MagicMock(return_value=fake_master)
        # 或者用 callable
        FakeSentinel = MagicMock(return_value=fake_sentinel_instance)
        FakeRedis.sentinel = MagicMock()
        FakeRedis.sentinel.Sentinel = FakeSentinel

        return FakeRedis

    def test_create_sentinel_basic(self):
        fake_redis = self._make_fake_redis_pkg()
        with patch.dict(
            "sys.modules", {"redis": fake_redis, "redis.sentinel": fake_redis.sentinel}
        ):
            # 重新加载模块以获得新的 import
            import importlib

            importlib.reload(rc)
            from shared.redis_client import _create_sentinel_client

            master = _create_sentinel_client("host1:26379,host2:26379")
            assert master is not None
            # 恢复 reload
            importlib.reload(rc)

    @patch("shared.redis_client._create_sentinel_client")
    def test_get_client_with_sentinel_hosts(self, mock_create):
        """sentinel_hosts 参数传入时调用 _create_sentinel_client"""
        fake_master = MagicMock()
        mock_create.return_value = fake_master
        result = rc.get_redis_client(
            redis_url="redis://localhost:6379/0",
            sentinel_hosts="host1:26379,host2:26379",
        )
        mock_create.assert_called_once()
        assert result is fake_master

    @patch("shared.redis_client._create_sentinel_client")
    def test_get_client_with_sentinel_hosts_empty_string_fallback(self, mock_create):
        """sentinel_hosts 为空字符串时走单实例路径"""
        result = rc.get_redis_client(redis_url="redis://localhost:6379/0", sentinel_hosts="")
        mock_create.assert_not_called()
        # redis 模块不可用，返回 None
        assert result is None


# ============================================================
#  _create_sentinel_client — 节点解析测试
# ============================================================


class TestSentinelNodeParsing:
    """直接测试 _create_sentinel_client 的节点解析逻辑"""

    def test_single_node(self):
        with patch("shared.redis_client.Sentinel") as mock_sentinel_cls:
            mock_master = MagicMock()
            mock_master.ping.return_value = True
            mock_sentinel = MagicMock()
            mock_sentinel.master_for.return_value = mock_master
            mock_sentinel_cls.return_value = mock_sentinel

            from shared.redis_client import _create_sentinel_client

            result = _create_sentinel_client("host1:26379")
            mock_sentinel_cls.assert_called_once_with([("host1", 26379)], socket_timeout=0.1)
            assert result is mock_master

    def test_multiple_nodes(self):
        with patch("shared.redis_client.Sentinel") as mock_sentinel_cls:
            mock_master = MagicMock()
            mock_master.ping.return_value = True
            mock_sentinel = MagicMock()
            mock_sentinel.master_for.return_value = mock_master
            mock_sentinel_cls.return_value = mock_sentinel

            from shared.redis_client import _create_sentinel_client

            result = _create_sentinel_client("host1:26379,host2:26380,host3:26381")
            mock_sentinel_cls.assert_called_once_with(
                [("host1", 26379), ("host2", 26380), ("host3", 26381)],
                socket_timeout=0.1,
            )
            assert result is mock_master

    def test_node_without_port_uses_default(self):
        with patch("shared.redis_client.Sentinel") as mock_sentinel_cls:
            mock_master = MagicMock()
            mock_master.ping.return_value = True
            mock_sentinel = MagicMock()
            mock_sentinel.master_for.return_value = mock_master
            mock_sentinel_cls.return_value = mock_sentinel

            from shared.redis_client import _create_sentinel_client

            result = _create_sentinel_client("host1")  # no port → 26379
            mock_sentinel_cls.assert_called_once_with([("host1", 26379)], socket_timeout=0.1)
            assert result is mock_master

    def test_custom_service_name(self):
        with patch("shared.redis_client.Sentinel") as mock_sentinel_cls:
            mock_master = MagicMock()
            mock_master.ping.return_value = True
            mock_sentinel = MagicMock()
            mock_sentinel.master_for.return_value = mock_master
            mock_sentinel_cls.return_value = mock_sentinel

            from shared.redis_client import _create_sentinel_client

            result = _create_sentinel_client(
                "host1:26379", service_name="custom_master", socket_timeout=0.5
            )
            mock_sentinel.master_for.assert_called_once_with("custom_master", socket_timeout=0.5)
            assert result is mock_master

    def test_invalid_port_skipped(self):
        with patch("shared.redis_client.Sentinel") as mock_sentinel_cls:
            mock_master = MagicMock()
            mock_master.ping.return_value = True
            mock_sentinel = MagicMock()
            mock_sentinel.master_for.return_value = mock_master
            mock_sentinel_cls.return_value = mock_sentinel

            from shared.redis_client import _create_sentinel_client

            result = _create_sentinel_client("host1:abc,host2:26379")
            # host1:abc 应该被跳过
            mock_sentinel_cls.assert_called_once_with([("host2", 26379)], socket_timeout=0.1)
            assert result is mock_master

    def test_empty_node_list(self):
        with patch("shared.redis_client.Sentinel") as mock_sentinel_cls:
            from shared.redis_client import _create_sentinel_client

            result = _create_sentinel_client("")
            mock_sentinel_cls.assert_not_called()
            assert result is None


# ============================================================
#  ENV 常量测试
# ============================================================


class TestEnvConstants:
    def test_env_sentinel_hosts(self):
        assert rc.ENV_SENTINEL_HOSTS == "REDIS_SENTINEL_HOSTS"

    def test_env_sentinel_service_name(self):
        assert rc.ENV_SENTINEL_SERVICE_NAME == "REDIS_SENTINEL_SERVICE_NAME"

    def test_default_sentinel_service_name(self):
        assert rc.DEFAULT_SENTINEL_SERVICE_NAME == "mymaster"

    def test_default_sentinel_socket_timeout(self):
        assert rc.DEFAULT_SENTINEL_SOCKET_TIMEOUT == 0.1


# ============================================================
#  __all__ 导出测试
# ============================================================


class TestModuleExports:
    def test_all_contains_expected(self):
        assert "get_redis_client" in rc.__all__
        assert "ENV_SENTINEL_HOSTS" in rc.__all__
        assert "ENV_SENTINEL_SERVICE_NAME" in rc.__all__
