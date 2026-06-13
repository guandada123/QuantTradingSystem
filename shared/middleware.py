"""
共享 Trace ID 中间件

跨服务请求链路追踪。
- 从 X-Request-ID / X-Trace-ID 请求头提取或生成 UUID
- 注入到日志记录 (request_id 字段)
- 添加到响应头
- 存储到 request.state.trace_id 供下游使用
"""

import contextvars
import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# ContextVar 用于在异步上下文中传递 trace_id（兼容 asyncio）
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")

# 保存原始的 LogRecord 工厂
_original_factory = logging.getLogRecordFactory()


def _record_factory(*args, **kwargs):
    """自定义 LogRecord 工厂：为所有日志记录添加默认 request_id 字段"""
    record = _original_factory(*args, **kwargs)
    if not hasattr(record, "request_id"):
        record.request_id = "-"
    return record


def _inject_request_id():
    """激活 request_id 字段注入：为所有 LogRecord 添加默认 request_id = '-'"""
    logging.setLogRecordFactory(_record_factory)


class TraceIDFilter(logging.Filter):
    """日志过滤器：从 ContextVar 读取 trace_id 并更新 LogRecord"""

    def filter(self, record: logging.LogRecord) -> bool:
        tid = trace_id_var.get()
        if tid:
            record.request_id = tid
        return True


class TraceIDMiddleware(BaseHTTPMiddleware):
    """ASGI 中间件：为每个请求设置 trace_id，并传播到下游服务"""

    async def dispatch(self, request: Request, call_next):
        # 优先从请求头获取（支持跨服务链路追踪），否则生成新 UUID
        trace_id = (
            request.headers.get("X-Request-ID")
            or request.headers.get("X-Trace-ID")
            or str(uuid.uuid4())
        )

        # 设置到 ContextVar（供日志过滤器使用）
        token = trace_id_var.set(trace_id)
        # 附加到 request.state（供业务代码使用）
        request.state.trace_id = trace_id

        response = await call_next(request)

        # 添加到响应头（下游服务可提取）
        response.headers["X-Request-ID"] = trace_id

        # 清理 ContextVar
        trace_id_var.reset(token)

        return response


def get_trace_headers() -> dict:
    """
    获取当前请求的 trace_id 作为 HTTP 请求头，用于跨服务传播。

    在服务间 HTTP 调用时，将此方法返回的 headers 合并到请求中：
        headers = get_trace_headers()
        async with httpx.AsyncClient(headers=headers) as client:
            await client.get(url)

    Returns:
        dict: {"X-Request-ID": trace_id} 如果有活跃的 trace，否则 {}
    """
    tid = trace_id_var.get()
    if tid:
        return {"X-Request-ID": tid}
    return {}


def setup_trace_logging():
    """
    初始化 trace ID 日志支持。应在 logging.basicConfig() 之后调用一次。
    - 注册 LogRecord 工厂，确保 request_id 字段始终存在（默认 "-"）
    - 为 root logger 添加过滤器，在有请求上下文时更新 request_id
    """
    _inject_request_id()
    root = logging.getLogger()
    if not any(isinstance(f, TraceIDFilter) for f in root.filters):
        root.addFilter(TraceIDFilter())


# ============================================================
#  Structured Logging (structlog)
# ============================================================


def setup_structured_logging(
    service_name: str = "qts",
    log_level: str = "INFO",
    json_output: bool = True,
) -> None:
    """初始化结构化日志 — JSON 格式 + 上下文绑定。

    在此之后的所有 `logging.getLogger(__name__)` 调用都会自动获得：
    - service: 服务名称
    - trace_id: 请求链路追踪 ID（通过 TraceIDMiddleware 注入）
    - JSON 格式输出（生产环境）或彩色控制台输出（开发环境）

    Args:
        service_name: 服务名称，如 "strategy-service"
        log_level: 日志级别，默认 INFO
        json_output: 是否输出 JSON（生产环境 True，开发环境可以 False）
    """
    try:
        import structlog
    except ImportError:
        logger = logging.getLogger(__name__)
        logger.warning(
            "structlog not installed — falling back to standard logging. "
            "Install with: pip install structlog python-json-logger"
        )
        return

    # 确定处理器
    if json_output:
        processors = structlog.stdlib.ProcessorFormatter.wrap_for_formatter
        renderer = structlog.processors.JSONRenderer()
    else:
        processors = structlog.dev.ConsoleRenderer(colors=True)

    # 共享处理器链
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=shared_processors + [processors, renderer]
        if json_output
        else shared_processors + [renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 绑定服务名到全局上下文
    structlog.contextvars.bind_contextvars(service=service_name)

    # 设置日志级别
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 确保 root logger 有处理器（避免 "No handlers could be found"）
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=renderer,
                foreign_pre_chain=shared_processors,
            )
        )
        root.addHandler(handler)

    logger = structlog.get_logger(__name__)
    logger.info(
        "structured_logging_initialized",
        service=service_name,
        output="json" if json_output else "console",
    )
