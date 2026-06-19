"""
QTS 统一结构化日志配置 — JSON 格式 + 请求追踪

Usage:
    # 在每个微服务的 main.py 中初始化
    from shared.logging_config import configure_logging, get_logger

    configure_logging("strategy-service")
    logger = get_logger(__name__)
    logger.info("service_started", port=8000, version="1.0.0")

    # 输出示例:
    # {"timestamp":"2026-06-12T22:45:00+08:00","level":"info","service":"strategy-service",
    #  "event":"service_started","port":8000,"version":"1.0.0"}

注意: 需安装 structlog>=24.0。如环境中不存在 structlog，自动降级为标准 JSON logging。
"""

from contextvars import ContextVar
import json
import logging
import sys
import time
from typing import Any
import uuid

# 请求 ID 上下文变量（跨异步任务传递）
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
service_name_var: ContextVar[str] = ContextVar("service_name", default="unknown")

_configured = False


class _StructuredLogger(logging.Logger):
    """Python 3.13 兼容的 Logger 子类。

    标准 Logger._log() 从 3.13 起拒绝额外的 **kwargs 参数。
    本子类自动将额外 kwargs 格式化为结构化字符串后拼接到 msg 中。
    """

    def _log(
        self,
        level: int,
        msg: object,
        args: tuple[object, ...] = (),
        exc_info: Any = None,
        extra: dict[str, Any] | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        **kwargs: Any,
    ) -> None:
        if kwargs:
            extra_str = "  " + "  ".join(
                f"{k}={v}" if isinstance(v, int | str | float) else f"{k}={v!r}"
                for k, v in kwargs.items()
            )
            msg = f"{msg}{extra_str}"
        super()._log(level, msg, args, exc_info, extra, stack_info, stacklevel + 1)


def configure_logging(
    service_name: str,
    level: str = "INFO",
    json_output: bool = True,
):
    """
    初始化结构化日志。

    Args:
        service_name: 服务名称（strategy-service / execution-service / ai-scheduler）
        level: 日志级别
        json_output: 是否输出 JSON 格式（生产环境 True，开发环境可设为 False）
    """
    global _configured
    if _configured:
        return
    _configured = True

    service_name_var.set(service_name)

    try:
        import structlog

        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="iso"),
                _add_service_context,
                _add_request_id,
                structlog.processors.JSONRenderer(ensure_ascii=False)
                if json_output
                else structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, level.upper(), logging.INFO)
            ),
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    except ImportError:
        # structlog 不可用 — 降级为标准 JSON logging
        logging.setLoggerClass(_StructuredLogger)
        handler = logging.StreamHandler(sys.stdout)
        if json_output:
            handler.setFormatter(_JsonFormatter(service_name))
        else:
            handler.setFormatter(
                logging.Formatter(
                    f"%(asctime)s [{service_name}] %(levelname)s %(name)s: %(message)s"
                )
            )
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str):
    """
    获取结构化 logger。

    优先返回 structlog BoundLogger，不可用时返回标准 logging.Logger。
    """
    try:
        import structlog

        return structlog.get_logger(name)
    except ImportError:
        return logging.getLogger(name)


def set_request_id(rid: str | None = None) -> str:
    """设置当前请求 ID（通常在中间件中调用）。"""
    if rid is None:
        rid = uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    """获取当前请求 ID。"""
    return request_id_var.get("")


# ═══════════════════════════════════════
# 内部处理器
# ═══════════════════════════════════════


def _add_service_context(logger, method_name, event_dict):
    """添加服务名上下文。"""
    event_dict["service"] = service_name_var.get("unknown")
    return event_dict


def _add_request_id(logger, method_name, event_dict):
    """添加请求 ID（如有）。"""
    rid = request_id_var.get("")
    if rid:
        event_dict["request_id"] = rid
    return event_dict


class _JsonFormatter(logging.Formatter):
    """标准 logging 的 JSON 格式化器（structlog 不可用时的降级方案）。"""

    def __init__(self, service_name: str):
        super().__init__()
        self._service = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "service": self._service,
            "logger": record.name,
            "event": record.getMessage(),
        }
        rid = request_id_var.get("")
        if rid:
            log_entry["request_id"] = rid
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)
