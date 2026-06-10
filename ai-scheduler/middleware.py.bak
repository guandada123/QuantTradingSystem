"""
共享 Trace ID 中间件

跨服务请求链路追踪。
- 从 X-Request-ID / X-Trace-ID 请求头提取或生成 UUID
- 注入到日志记录 (request_id 字段)
- 添加到响应头
- 存储到 request.state.trace_id 供下游使用
"""
import uuid
import logging
import contextvars
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
