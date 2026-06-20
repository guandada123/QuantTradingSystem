"""shared/structured_log.py 单元测试 — 结构化日志包装"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import logging

import pytest

from shared.structured_log import (
    LogHelper,
    StructuredLogger,
    _format_extra,
    get_logger,
)


class TestFormatExtra:
    """_format_extra() 格式化测试"""

    def test_empty_dict(self):
        assert _format_extra({}) == ""

    def test_float_value(self):
        result = _format_extra({"latency": 1.23456})
        assert "latency=1.235" in result

    def test_int_value(self):
        result = _format_extra({"count": 42})
        assert "count=42" in result

    def test_str_value(self):
        result = _format_extra({"source": "tencent"})
        assert "source=tencent" in result

    def test_mixed_types(self):
        result = _format_extra({"latency": 1.5, "code": 200, "source": "api"})
        assert "latency=1.500" in result
        assert "code=200" in result
        assert "source=api" in result

    def test_other_types_repr(self):
        """dict/list 等复杂类型用 repr"""
        result = _format_extra({"data": {"key": "val"}})
        assert "data={'key': 'val'}" in result

    def test_multiple_items_separated(self):
        result = _format_extra({"a": 1, "b": "test"})
        # 两个 空格 分隔
        assert "  " in result


class TestStructuredLogger:
    """StructuredLogger 子类测试"""

    def test_logger_is_logger_subclass(self):
        assert issubclass(StructuredLogger, logging.Logger)

    def test_log_with_kwargs(self, caplog):
        caplog.set_level(logging.INFO)
        logger = StructuredLogger("test_slog")
        logger.info("hello", extra_field="value", count=42)
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert "hello" in record.getMessage()
        assert "extra_field=value" in record.getMessage()
        assert "count=42" in record.getMessage()

    def test_log_without_kwargs(self, caplog):
        caplog.set_level(logging.INFO)
        logger = StructuredLogger("test_slog")
        logger.info("plain message")
        assert len(caplog.records) == 1
        assert "plain message" in caplog.records[0].getMessage()

    def test_log_levels(self, caplog):
        caplog.set_level(logging.DEBUG)
        logger = StructuredLogger("test_slog")
        logger.debug("debug msg", d=1)
        logger.info("info msg", i=2)
        logger.warning("warn msg", w=3)
        logger.error("error msg", e=4)
        logger.critical("critical msg", c=5)
        assert len(caplog.records) == 5

    def test_log_with_exception(self, caplog):
        caplog.set_level(logging.ERROR)
        logger = StructuredLogger("test_slog")
        try:
            raise ValueError("test error")
        except ValueError:
            logger.exception("caught error", code=500)
        assert len(caplog.records) == 1
        assert "caught error" in caplog.records[0].getMessage()
        assert "code=500" in caplog.records[0].getMessage()


class TestLogHelper:
    """LogHelper 静态方法测试"""

    def test_summary(self, caplog):
        caplog.set_level(logging.INFO)
        logger = logging.getLogger("test_helper")
        LogHelper.summary(logger, logging.INFO, "task done", duration=1.2, result="ok")
        assert len(caplog.records) == 1
        msg = caplog.records[0].getMessage()
        assert "task done" in msg
        assert "duration=1.200" in msg

    def test_info_shortcut(self, caplog):
        caplog.set_level(logging.INFO)
        logger = logging.getLogger("test_helper")
        LogHelper.info(logger, "info msg", x=1)
        assert caplog.records[0].levelno == logging.INFO

    def test_warn_shortcut(self, caplog):
        caplog.set_level(logging.WARNING)
        logger = logging.getLogger("test_helper")
        LogHelper.warn(logger, "warn msg", y=2)
        assert caplog.records[0].levelno == logging.WARNING

    def test_error_shortcut(self, caplog):
        caplog.set_level(logging.ERROR)
        logger = logging.getLogger("test_helper")
        LogHelper.error(logger, "error msg", z=3)
        assert caplog.records[0].levelno == logging.ERROR

    def test_debug_shortcut(self, caplog):
        caplog.set_level(logging.DEBUG)
        logger = logging.getLogger("test_helper")
        LogHelper.debug(logger, "debug msg", w=4)
        assert caplog.records[0].levelno == logging.DEBUG

    def test_summary_no_kwargs(self, caplog):
        caplog.set_level(logging.INFO)
        logger = logging.getLogger("test_helper")
        LogHelper.summary(logger, logging.INFO, "plain message")
        assert caplog.records[0].getMessage() == "plain message"

    def test_summary_empty_extra_str(self, caplog):
        """kwargs 的 extra_str 为空时原样输出"""
        caplog.set_level(logging.INFO)
        logger = logging.getLogger("test_helper")
        LogHelper.summary(logger, logging.INFO, "test")
        assert caplog.records[0].getMessage() == "test"


class TestGetLogger:
    """get_logger 工厂函数测试"""

    def test_returns_logger_instance(self):
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_returns_structured_logger(self):
        logger = get_logger("test_structured")
        assert isinstance(logger, StructuredLogger)

    def test_sets_root_logger_class(self):
        get_logger("class_test")
        assert logging.getLoggerClass() is StructuredLogger

    def test_same_name_returns_same_logger(self):
        logger1 = get_logger("shared_name")
        logger2 = get_logger("shared_name")
        assert logger1 is logger2

    def test_different_names_different_loggers(self):
        logger1 = get_logger("module_a")
        logger2 = get_logger("module_b")
        assert logger1 is not logger2
