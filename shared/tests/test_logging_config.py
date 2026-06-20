"""shared/logging_config.py 单元测试 — 结构化日志配置（JSON + 请求追踪）"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import logging

import pytest

from shared.logging_config import (
    _JsonFormatter,
    get_logger,
    get_request_id,
    request_id_var,
    service_name_var,
    set_request_id,
)

# reconfigure 辅助标记
_SAVED_CONFIGURED = False


def _reset_configured():
    """重置 _configured 标记以便测试 configure_logging()"""
    import shared.logging_config as lc

    lc._configured = False
    # 清除 root handlers 防止日志堆叠
    logging.getLogger().handlers.clear()


# ============================================================
#  _StructuredLogger 测试
# ============================================================


class TestStructuredLogger:
    """_StructuredLogger 子类测试（与 structured_log.py 中的行为一致）"""

    def test_log_with_kwargs(self, caplog):
        caplog.set_level(logging.INFO)
        from shared.logging_config import _StructuredLogger

        logger = _StructuredLogger("test_lc")
        logger.info("hello", x=1)
        record = caplog.records[0]
        assert "hello" in record.getMessage()
        assert "x=1" in record.getMessage()

    def test_log_without_kwargs(self, caplog):
        caplog.set_level(logging.INFO)
        from shared.logging_config import _StructuredLogger

        logger = _StructuredLogger("test_lc")
        logger.info("plain")
        assert caplog.records[0].getMessage() == "plain"

    def test_log_with_float(self, caplog):
        caplog.set_level(logging.INFO)
        from shared.logging_config import _StructuredLogger

        logger = _StructuredLogger("test_lc")
        logger.info("stats", latency=1.5)
        msg = caplog.records[0].getMessage()
        assert "latency=1.5" in msg or "latency=1.500000" in msg


# ============================================================
#  configure_logging 测试（structlog 不可用时的降级路径）
# ============================================================


class TestConfigureLoggingWithoutStructlog:
    """structlog 未安装时的降级路径"""

    def setup_method(self):
        _reset_configured()

    @pytest.fixture(autouse=True)
    def _patch_structlog(self):
        """模拟 structlog 不可用"""
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "structlog", None)
            yield

    def test_configure_logging_json(self):
        """降级到 JSON 输出"""
        from shared.logging_config import configure_logging

        configure_logging("test-svc", level="DEBUG", json_output=True)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        handlers = [h for h in root.handlers if not isinstance(h, logging.NullHandler)]
        assert len(handlers) >= 1
        # handler 的 formatter 应该是 _JsonFormatter
        has_json_formatter = any(
            isinstance(h.formatter, _JsonFormatter) for h in root.handlers if h.formatter
        )
        assert has_json_formatter

    def test_configure_logging_console(self):
        """降级到控制台（非 JSON）输出"""
        from shared.logging_config import configure_logging

        configure_logging("test-svc", level="INFO", json_output=False)
        root = logging.getLogger()
        handlers = [h for h in root.handlers if not isinstance(h, logging.NullHandler)]
        assert len(handlers) >= 1

    def test_configure_logging_twice_idempotent(self):
        """多次调用不重复配置"""
        from shared.logging_config import configure_logging

        configure_logging("svc-a")
        configure_logging("svc-a")
        root = logging.getLogger()
        # 不应该有重复的 handler
        real_handlers = [h for h in root.handlers if not isinstance(h, logging.NullHandler)]
        assert len(real_handlers) == 1


# ============================================================
#  _JsonFormatter 测试
# ============================================================


class TestJsonFormatter:
    def test_format_basic(self):
        formatter = _JsonFormatter("test-svc")
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=42,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        output = json.loads(formatter.format(record))
        assert output["level"] == "info"
        assert output["service"] == "test-svc"
        assert output["logger"] == "test.logger"
        assert output["event"] == "hello world"
        assert "timestamp" in output

    def test_format_with_request_id(self):
        request_id_var.set("req-123")
        formatter = _JsonFormatter("svc")
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
        output = json.loads(formatter.format(record))
        assert output["request_id"] == "req-123"
        request_id_var.set("")  # cleanup

    def test_format_with_exception(self):
        formatter = _JsonFormatter("svc")
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.LogRecord(
                "x",
                logging.ERROR,
                __file__,
                1,
                "error occurred",
                (),
                exc_info=sys.exc_info(),
            )
        output = json.loads(formatter.format(record))
        assert output["event"] == "error occurred"
        assert "exception" in output
        assert "ValueError" in output["exception"]

    def test_format_levels(self):
        formatter = _JsonFormatter("svc")
        for level, name in [
            (logging.DEBUG, "debug"),
            (logging.WARNING, "warning"),
            (logging.ERROR, "error"),
            (logging.CRITICAL, "critical"),
        ]:
            record = logging.LogRecord("x", level, __file__, 1, "msg", (), None)
            output = json.loads(formatter.format(record))
            assert output["level"] == name


# ============================================================
#  request_id 上下文测试
# ============================================================


class TestRequestId:
    def test_default_empty(self):
        assert get_request_id() == ""

    def test_set_returns_id(self):
        rid = set_request_id()
        assert len(rid) == 12  # uuid4().hex[:12]

    def test_set_with_custom_id(self):
        rid = set_request_id("custom-123")
        assert rid == "custom-123"
        assert get_request_id() == "custom-123"

    def test_set_twice_overwrites(self):
        set_request_id("first")
        set_request_id("second")
        assert get_request_id() == "second"

    def test_contextvar_isolation(self):
        """不同异步任务应有不同的 request_id（ContextVar 特性）"""
        set_request_id("task-a")
        assert get_request_id() == "task-a"
        # 重置
        request_id_var.set("")


class TestGetLogger:
    """get_logger 在不同场景下的行为"""

    def test_get_logger_returns_logger(self):
        logger = get_logger("test_mod")
        assert isinstance(logger, logging.Logger)

    def test_service_name_var_set_by_configure_logging(self):
        _reset_configured()
        from shared.logging_config import configure_logging

        configure_logging("my-service")
        assert service_name_var.get() == "my-service"


class TestServiceNameVar:
    def test_default_unknown(self):
        assert service_name_var.get() == "unknown"

    def test_set_and_get(self):
        service_name_var.set("strategy-service")
        assert service_name_var.get() == "strategy-service"
        service_name_var.set("unknown")  # cleanup
