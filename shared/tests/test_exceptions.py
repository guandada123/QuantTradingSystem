"""shared/exceptions.py 单元测试 — 统一异常层次结构"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from shared.exceptions import (
    AIServiceException,
    AlertException,
    ConfigException,
    ConfigMissingError,
    DatabaseConnectionError,
    DataSourceError,
    DataSourceException,
    DataSourceParseError,
    DataSourceTimeout,
    DataSourceUnavailable,
    EntityConflictError,
    EntityNotFoundError,
    ExecutionException,
    QTSBaseException,
    RepositoryException,
    SchedulerConflictError,
    SchedulerException,
    StrategyConflictError,
    StrategyException,
    StrategyExecutionError,
    StrategyNotFoundError,
    StrategyValidationError,
    WebSocketException,
)


class TestQTSBaseException:
    """基类异常：构造函数、字段、to_dict()"""

    def test_construct_with_only_message(self):
        exc = QTSBaseException("test error")
        assert exc.message == "test error"
        assert exc.code is None
        assert exc.detail == {}
        assert exc.cause is None

    def test_construct_with_code_and_detail(self):
        exc = QTSBaseException("error", code=400, detail={"field": "value"})
        assert exc.message == "error"
        assert exc.code == 400
        assert exc.detail == {"field": "value"}

    def test_construct_with_cause(self):
        cause = ValueError("root cause")
        exc = QTSBaseException("wrapped", cause=cause)
        assert exc.cause is cause

    def test_str_contains_message(self):
        exc = QTSBaseException("something broke")
        assert str(exc) == "something broke"

    def test_to_dict_minimal(self):
        exc = QTSBaseException("minimal")
        d = exc.to_dict()
        assert d == {"error_type": "QTSBaseException", "message": "minimal"}

    def test_to_dict_with_code(self):
        exc = QTSBaseException("with code", code=503)
        d = exc.to_dict()
        assert d["code"] == 503

    def test_to_dict_with_detail(self):
        exc = QTSBaseException("with detail", detail={"reason": "timeout"})
        d = exc.to_dict()
        assert d["detail"] == {"reason": "timeout"}

    def test_to_dict_code_none_omitted(self):
        """code 为 None 时 to_dict 中不包含 code"""
        exc = QTSBaseException("no code")
        d = exc.to_dict()
        assert "code" not in d

    def test_to_dict_empty_detail_omitted(self):
        """detail 为空时 to_dict 中不包含 detail"""
        exc = QTSBaseException("no detail")
        d = exc.to_dict()
        assert "detail" not in d

    def test_int_code(self):
        exc = QTSBaseException("int code", code=500)
        assert exc.code == 500

    def test_str_code(self):
        exc = QTSBaseException("str code", code="ERR_001")
        assert exc.code == "ERR_001"


class TestDataSourceExceptions:
    def test_data_source_exception(self):
        exc = DataSourceException("API error", source="tencent", code=503)
        assert isinstance(exc, QTSBaseException)
        assert exc.message == "API error"

    def test_data_source_timeout(self):
        exc = DataSourceTimeout("timeout after 5s")
        assert isinstance(exc, DataSourceException)

    def test_data_source_unavailable(self):
        exc = DataSourceUnavailable("service down")
        assert isinstance(exc, DataSourceException)

    def test_data_source_parse_error(self):
        exc = DataSourceParseError("bad format")
        assert isinstance(exc, DataSourceException)


class TestRepositoryExceptions:
    def test_repository_exception(self):
        exc = RepositoryException("db error")
        assert isinstance(exc, QTSBaseException)

    def test_entity_not_found(self):
        exc = EntityNotFoundError("stock 000001 not found")
        assert isinstance(exc, RepositoryException)

    def test_entity_conflict(self):
        exc = EntityConflictError("duplicate key")
        assert isinstance(exc, RepositoryException)

    def test_database_connection_error(self):
        exc = DatabaseConnectionError("connection refused")
        assert isinstance(exc, RepositoryException)


class TestStrategyExceptions:
    def test_strategy_exception(self):
        exc = StrategyException("strategy crashed")
        assert isinstance(exc, QTSBaseException)

    def test_strategy_not_found(self):
        exc = StrategyNotFoundError("strategy id=42 not found")
        assert isinstance(exc, StrategyException)

    def test_strategy_validation_error(self):
        exc = StrategyValidationError("invalid param")
        assert isinstance(exc, StrategyException)

    def test_strategy_conflict(self):
        exc = StrategyConflictError("duplicate id")
        assert isinstance(exc, StrategyException)

    def test_strategy_execution_error(self):
        exc = StrategyExecutionError("exec failed")
        assert isinstance(exc, StrategyException)


class TestSchedulerExceptions:
    def test_scheduler_exception(self):
        exc = SchedulerException("scheduler error")
        assert isinstance(exc, QTSBaseException)

    def test_scheduler_conflict(self):
        exc = SchedulerConflictError("task conflict")
        assert isinstance(exc, SchedulerException)


class TestConfigExceptions:
    def test_config_exception(self):
        exc = ConfigException("config missing")
        assert isinstance(exc, QTSBaseException)

    def test_config_missing(self):
        exc = ConfigMissingError("REDIS_URL not set")
        assert isinstance(exc, ConfigException)


class TestOtherExceptionSubclasses:
    def test_execution_exception(self):
        exc = ExecutionException("order failed")
        assert isinstance(exc, QTSBaseException)

    def test_ai_service_exception(self):
        exc = AIServiceException("LLM call failed")
        assert isinstance(exc, QTSBaseException)

    def test_web_socket_exception(self):
        exc = WebSocketException("connection lost")
        assert isinstance(exc, QTSBaseException)

    def test_alert_exception(self):
        exc = AlertException("push failed")
        assert isinstance(exc, QTSBaseException)


class TestBackwardCompatibilityAlias:
    def test_data_source_error_is_data_source_exception(self):
        assert DataSourceError is not DataSourceException
        assert issubclass(DataSourceError, DataSourceException)

    def test_data_source_error_instantiation(self):
        exc = DataSourceError("legacy error", code=500)
        assert isinstance(exc, DataSourceException)
        assert isinstance(exc, QTSBaseException)
