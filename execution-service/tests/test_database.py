"""
数据库连接层测试 — models/database.py

测试策略：
- Engine 创建：模拟 sqlalchemy.create_engine，通过 importlib.reload() 触发模块级代码
- get_db() / get_db_session()：直接替换模块级的 SessionLocal 为 MagicMock
- 三种 URL 来源：环境变量 > settings.DATABASE_URL > 默认 SQLite 路径
- 连接池参数：pool_size, max_overflow, pool_pre_ping
- 异常路径：SessionLocal 异常、generator finally 清理
"""

import importlib
import os
from unittest.mock import MagicMock, patch

import pytest


class TestEngineCreation:
    """测试 engine 创建逻辑（模块级代码）"""

    @patch("sqlalchemy.create_engine")
    def test_default_fallback(self, mock_ce):
        """无 DATABASE_URL 环境变量时使用 settings / .env 值"""
        import models.database

        mock_ce.reset_mock()
        # conftest 会设置 DATABASE_URL=sqlite:///...，测试前先清理
        saved = os.environ.pop("DATABASE_URL", None)
        importlib.reload(models.database)
        if saved is not None:
            os.environ["DATABASE_URL"] = saved

        # .env 中 DATABASE_URL=postgresql://...，settings 会从 .env 读取
        mock_ce.assert_called_once_with(
            "postgresql://quant_user:quant_pass@127.0.0.1:15432/quant_trading",
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )

    @patch("sqlalchemy.create_engine")
    def test_env_var_override(self, mock_ce):
        """DATABASE_URL 环境变量优先于 settings"""
        saved = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/test"
        import models.database

        importlib.reload(models.database)
        if saved is not None:
            os.environ["DATABASE_URL"] = saved
        else:
            os.environ.pop("DATABASE_URL", None)

        mock_ce.assert_called_once_with(
            "postgresql://user:pass@localhost:5432/test",
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )

    @patch("sqlalchemy.create_engine")
    def test_settings_url_as_fallback(self, mock_ce):
        """无 env var 时 fallback 到 settings.DATABASE_URL"""
        import models.database

        mock_ce.reset_mock()

        original = models.database.settings.DATABASE_URL
        models.database.settings.DATABASE_URL = "mysql://user:pass@localhost/mydb"
        importlib.reload(models.database)
        models.database.settings.DATABASE_URL = original

        mock_ce.assert_called_once_with(
            "mysql://user:pass@localhost/mydb",
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )

    @patch("sqlalchemy.create_engine")
    def test_env_precedence_over_settings(self, mock_ce):
        """环境变量优先级高于 settings.DATABASE_URL"""
        saved = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://env:pass@localhost/envdb"
        import models.database

        mock_ce.reset_mock()
        original = models.database.settings.DATABASE_URL
        models.database.settings.DATABASE_URL = "mysql://cfg:pass@localhost/cfgdb"
        importlib.reload(models.database)
        if saved is not None:
            os.environ["DATABASE_URL"] = saved
        else:
            os.environ.pop("DATABASE_URL", None)
        models.database.settings.DATABASE_URL = original

        mock_ce.assert_called_once()
        url = mock_ce.call_args[0][0]
        assert "envdb" in url, "应使用环境变量值"
        assert "cfgdb" not in url, "不应使用 settings 值"

    @patch("sqlalchemy.create_engine")
    def test_pool_parameters(self, mock_ce):
        """连接池参数正确传递"""
        import models.database

        importlib.reload(models.database)

        kwargs = mock_ce.call_args[1]
        assert kwargs["pool_size"] == 5
        assert kwargs["max_overflow"] == 10
        assert kwargs["pool_pre_ping"] is True


class TestGetDb:
    """测试 get_db() 函数"""

    def test_returns_session(self):
        """get_db() 返回 Session 实例"""
        import models.database

        mock_session = MagicMock()
        models.database.SessionLocal = MagicMock(return_value=mock_session)

        session = models.database.get_db()
        assert session is mock_session

    def test_calls_session_local(self):
        """get_db() 正确调用 SessionLocal()"""
        import models.database

        mock_session = MagicMock()
        models.database.SessionLocal = MagicMock(return_value=mock_session)

        models.database.get_db()
        models.database.SessionLocal.assert_called_once_with()

    def test_session_local_exception_propagates(self):
        """SessionLocal() 抛异常时透传（异常发生在 try 块外）"""
        import models.database

        models.database.SessionLocal = MagicMock(
            side_effect=ValueError("connection failed")
        )

        with pytest.raises(ValueError, match="connection failed"):
            models.database.get_db()


class TestGetDbSession:
    """测试 get_db_session() generator"""

    def test_yields_session(self):
        """generator yield 一个 Session 实例"""
        import models.database

        mock_session = MagicMock()
        models.database.SessionLocal = MagicMock(return_value=mock_session)

        gen = models.database.get_db_session()
        session = next(gen)

        assert session is mock_session

    def test_calls_session_local(self):
        """generator 正确调用 SessionLocal()"""
        import models.database

        mock_session = MagicMock()
        models.database.SessionLocal = MagicMock(return_value=mock_session)

        gen = models.database.get_db_session()
        next(gen)

        models.database.SessionLocal.assert_called_once_with()

    def test_closes_on_generator_close(self):
        """gen.close() 触发 finally → session.close()"""
        import models.database

        mock_session = MagicMock()
        models.database.SessionLocal = MagicMock(return_value=mock_session)

        gen = models.database.get_db_session()
        next(gen)
        gen.close()

        mock_session.close.assert_called_once()

    def test_closes_on_exhaustion(self):
        """generator 耗尽（StopIteration）触发 finally → session.close()"""
        import models.database

        mock_session = MagicMock()
        models.database.SessionLocal = MagicMock(return_value=mock_session)

        gen = models.database.get_db_session()
        sessions = list(gen)

        assert len(sessions) == 1
        mock_session.close.assert_called_once()

    def test_closes_on_exception(self):
        """generator 内抛异常触发 finally → session.close()"""
        import models.database

        mock_session = MagicMock()
        models.database.SessionLocal = MagicMock(return_value=mock_session)

        gen = models.database.get_db_session()
        next(gen)

        with pytest.raises(RuntimeError, match="test error"):
            gen.throw(RuntimeError("test error"))

        mock_session.close.assert_called_once()

    def test_fastapi_dependency_pattern(self):
        """模拟 FastAPI Depends 使用模式：gen.close() 清理"""
        import models.database

        mock_session = MagicMock()
        models.database.SessionLocal = MagicMock(return_value=mock_session)

        # FastAPI 内部模式：next(gen) 获取 → gen.close() 释放
        gen = models.database.get_db_session()
        session = next(gen)
        assert session is mock_session

        gen.close()
        mock_session.close.assert_called_once()
