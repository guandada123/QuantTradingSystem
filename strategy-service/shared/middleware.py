"""Trace ID middleware"""

from contextvars import ContextVar
import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


def get_trace_headers() -> dict:
    tid = trace_id_var.get()
    return {"X-Request-ID": tid} if tid and tid != "-" else {}


class TraceIDMiddleware(BaseHTTPMiddleware):
    """为每个 HTTP 请求注入 Trace ID，用于全链路日志追踪"""

    async def dispatch(self, request: Request, call_next):
        tid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        token = trace_id_var.set(tid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = tid
            return response
        finally:
            trace_id_var.reset(token)


def setup_trace_logging():
    """注册 LogRecord 工厂，确保 request_id 字段始终存在（默认 '-'）"""
    _old_factory = logging.getLogRecordFactory()

    def _factory(*args, **kwargs):
        record = _old_factory(*args, **kwargs)
        if not hasattr(record, "request_id"):
            record.request_id = trace_id_var.get()
        return record

    logging.setLogRecordFactory(_factory)
    logger.info("Trace ID 日志注入已激活")
