"""shared/middleware.py 单元测试 — Trace ID 中间件 + 响应脱敏"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from shared.middleware import (
    SENSITIVE_FIELD_NAMES,
    SENSITIVE_HEADERS,
    ResponseSanitizerMiddleware,
    TraceIDFilter,
    TraceIDMiddleware,
    get_trace_headers,
    sanitize_header_value,
    sanitize_headers,
    sanitize_response_value,
    setup_trace_logging,
    trace_id_var,
)

# ============================================================
#  sanitize_header_value / sanitize_headers 测试
# ============================================================


class TestSanitizeHeaderValue:
    """请求头脱敏测试"""

    def test_non_sensitive_header(self):
        assert sanitize_header_value("content-type", "application/json") == "application/json"

    def test_authorization_bearer(self):
        result = sanitize_header_value("authorization", "Bearer eyJhbGciOiJIUzI1NiJ9.token")
        assert "***" in result
        assert "eyJhbGciOiJIUzI1NiJ9.token" not in result

    def test_authorization_basic(self):
        result = sanitize_header_value("authorization", "Basic dXNlcjpwYXNz")
        assert "***" in result
        assert "dXNlcjpwYXNz" not in result

    def test_x_api_key(self):
        result = sanitize_header_value("x-api-key", "sk-abc123def456")
        assert "***" in result
        assert "sk-abc123def456" not in result

    def test_case_insensitive(self):
        result = sanitize_header_value("Authorization", "Bearer token123")
        assert "***" in result

    def test_empty_value(self):
        assert sanitize_header_value("authorization", "") == ""

    def test_cookie_header(self):
        result = sanitize_header_value("cookie", "session=abc123")
        assert "***" in result

    def test_set_cookie(self):
        result = sanitize_header_value("set-cookie", "token=secret")
        assert "***" in result


class TestSanitizeHeaders:
    """请求头字典脱敏测试"""

    def test_sanitize_headers_mixed(self):
        headers = {
            "authorization": "Bearer secret_token",
            "content-type": "application/json",
            "x-api-key": "sk-xxx",
        }
        result = sanitize_headers(headers)
        assert "***" in result["authorization"]
        assert result["content-type"] == "application/json"
        assert "***" in result["x-api-key"]

    def test_sanitize_headers_doesnt_modify_original(self):
        original = {"authorization": "Bearer secret"}
        result = sanitize_headers(original)
        assert original["authorization"] == "Bearer secret"
        assert result["authorization"] != original["authorization"]

    def test_sanitize_empty_headers(self):
        assert sanitize_headers({}) == {}

    def test_sensitive_headers_frozenset(self):
        assert isinstance(SENSITIVE_HEADERS, frozenset)
        assert "authorization" in SENSITIVE_HEADERS


# ============================================================
#  sanitize_response_value 测试
# ============================================================


class TestSanitizeResponseValue:
    """响应体脱敏递归测试"""

    def test_sensitive_field_name_redacted(self):
        result = sanitize_response_value("api_key", "sk-abc123")
        assert result == "***REDACTED***"

    def test_non_sensitive_field_untouched(self):
        result = sanitize_response_value("name", "John")
        assert result == "John"

    def test_nested_dict(self):
        data = {"user": {"name": "Alice", "api_key": "sk-secret"}, "status": "ok"}
        result = sanitize_response_value("", data)
        assert result["user"]["name"] == "Alice"
        assert result["user"]["api_key"] == "***REDACTED***"
        assert result["status"] == "ok"

    def test_list_of_dicts(self):
        data = [{"token": "eyJtoken"}, {"name": "public"}]
        result = sanitize_response_value("", data)
        assert result[0]["token"] == "***REDACTED***"
        assert result[1]["name"] == "public"

    def test_sensitive_value_pattern(self):
        result = sanitize_response_value("data", "sk-abc123def456")
        assert result == "***REDACTED***"

    def test_non_sensitive_value(self):
        result = sanitize_response_value("data", "hello world")
        assert result == "hello world"

    def test_numeric_value_untouched(self):
        result = sanitize_response_value("amount", 42)
        assert result == 42

    def test_bool_value_untouched(self):
        result = sanitize_response_value("active", True)
        assert result is True

    def test_none_value_untouched(self):
        result = sanitize_response_value("data", None)
        assert result is None

    def test_case_insensitive_field_match(self):
        """SENSITIVE_FIELD_NAMES 比较不区分大小写"""
        result = sanitize_response_value("API_KEY", "secret123")
        assert result == "***REDACTED***"

    def test_sensitive_field_names_frozenset(self):
        assert isinstance(SENSITIVE_FIELD_NAMES, frozenset)
        assert "api_key" in SENSITIVE_FIELD_NAMES


# ============================================================
#  TraceIDFilter 测试
# ============================================================


class TestTraceIDFilter:
    def test_filter_sets_request_id_from_context(self):
        trace_id_var.set("trace-abc")
        filter_ = TraceIDFilter()
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
        record.request_id = "-"
        filter_.filter(record)
        assert record.request_id == "trace-abc"
        trace_id_var.set("")

    def test_filter_keeps_default_when_no_trace(self):
        filter_ = TraceIDFilter()
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
        record.request_id = "-"
        filter_.filter(record)
        assert record.request_id == "-"

    def test_filter_returns_true(self):
        filter_ = TraceIDFilter()
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
        assert filter_.filter(record) is True


# ============================================================
#  get_trace_headers 测试
# ============================================================


class TestGetTraceHeaders:
    def test_returns_empty_when_no_trace(self):
        trace_id_var.set("")
        assert get_trace_headers() == {}

    def test_returns_trace_header(self):
        trace_id_var.set("trace-xyz")
        headers = get_trace_headers()
        assert headers == {"X-Request-ID": "trace-xyz"}
        trace_id_var.set("")


# ============================================================
#  setup_trace_logging 测试
# ============================================================


class TestSetupTraceLogging:
    def test_injects_request_id_field(self):
        setup_trace_logging()
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
        assert hasattr(record, "request_id")
        # cleanup
        logging.setLogRecordFactory(logging.getLogRecordFactory())

    def test_adds_trace_id_filter_to_root(self):
        root = logging.getLogger()
        # 移除之前添加的 TraceIDFilter（如有）
        root.filters = [f for f in root.filters if not isinstance(f, TraceIDFilter)]
        setup_trace_logging()
        has_filter = any(isinstance(f, TraceIDFilter) for f in root.filters)
        assert has_filter


# ============================================================
#  TraceIDMiddleware 集成测试
# ============================================================


def _make_trace_app():
    """创建带 TraceIDMiddleware 的测试应用"""
    app = Starlette()

    async def test_endpoint(request):
        return JSONResponse(
            {
                "trace_id": request.state.trace_id,
                "sanitized_headers": request.state.sanitized_headers.get("authorization", "N/A"),
            }
        )

    app.add_middleware(TraceIDMiddleware)
    app.add_route("/test", test_endpoint, methods=["GET"])
    return app


class TestTraceIDMiddleware:
    """TraceIDMiddleware 集成测试"""

    def test_generates_trace_id_when_missing(self):
        app = _make_trace_app()
        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        data = response.json()
        assert len(data["trace_id"]) > 0

    def test_uses_x_request_id_header(self):
        app = _make_trace_app()
        client = TestClient(app)
        response = client.get("/test", headers={"X-Request-ID": "req-001"})
        data = response.json()
        assert data["trace_id"] == "req-001"

    def test_uses_x_trace_id_header(self):
        app = _make_trace_app()
        client = TestClient(app)
        response = client.get("/test", headers={"X-Trace-ID": "trace-002"})
        data = response.json()
        assert data["trace_id"] == "trace-002"

    def test_response_contains_trace_id(self):
        app = _make_trace_app()
        client = TestClient(app)
        response = client.get("/test", headers={"X-Request-ID": "req-003"})
        assert response.headers.get("X-Request-ID") == "req-003"

    def test_sanitized_headers_in_state(self):
        app = _make_trace_app()
        client = TestClient(app)
        response = client.get("/test", headers={"Authorization": "Bearer secret_token"})
        data = response.json()
        assert "***" in data["sanitized_headers"]


# ============================================================
#  ResponseSanitizerMiddleware 集成测试
# ============================================================


class TestResponseSanitizerMiddleware:
    """ResponseSanitizerMiddleware 集成测试"""

    def test_sanitizes_api_key_in_response(self):
        app = Starlette()

        async def endpoint(request):
            return JSONResponse({"api_key": "sk-abc123", "name": "public"})

        app.add_middleware(ResponseSanitizerMiddleware)
        app.add_route("/data", endpoint, methods=["GET"])
        client = TestClient(app)
        response = client.get("/data")
        data = response.json()
        assert data["api_key"] == "***REDACTED***"
        assert data["name"] == "public"

    def test_passes_non_json_response(self):
        app = Starlette()

        async def endpoint(request):
            return Response(content="<html>ok</html>", media_type="text/html")

        app.add_middleware(ResponseSanitizerMiddleware)
        app.add_route("/html", endpoint, methods=["GET"])
        client = TestClient(app)
        response = client.get("/html")
        assert "***REDACTED***" not in response.text

    def test_nested_sanitization(self):
        app = Starlette()

        async def endpoint(request):
            return JSONResponse({"user": {"token": "eyJtoken", "profile": {"name": "Alice"}}})

        app.add_middleware(ResponseSanitizerMiddleware)
        app.add_route("/nested", endpoint, methods=["GET"])
        client = TestClient(app)
        response = client.get("/nested")
        data = response.json()
        assert data["user"]["token"] == "***REDACTED***"
        assert data["user"]["profile"]["name"] == "Alice"

    def test_extra_sensitive_fields(self):
        """custom_fields 参数传递额外敏感字段"""
        app = Starlette()

        async def endpoint(request):
            return JSONResponse({"my_custom_secret": "sensitive_data"})

        app.add_middleware(
            ResponseSanitizerMiddleware,
            extra_sensitive_fields={"my_custom_secret"},
        )
        app.add_route("/custom", endpoint, methods=["GET"])
        client = TestClient(app)
        response = client.get("/custom")
        data = response.json()
        assert data["my_custom_secret"] == "***REDACTED***"

    def test_empty_body_response(self):
        app = Starlette()

        async def endpoint(request):
            return Response(content="", status_code=204)

        app.add_middleware(ResponseSanitizerMiddleware)
        app.add_route("/empty", endpoint, methods=["GET"])
        client = TestClient(app)
        response = client.get("/empty")
        assert response.status_code == 204

    def test_list_response_sanitized(self):
        app = Starlette()

        async def endpoint(request):
            return JSONResponse([{"token": "eyJsecret"}, {"name": "public"}])

        app.add_middleware(ResponseSanitizerMiddleware)
        app.add_route("/list", endpoint, methods=["GET"])
        client = TestClient(app)
        response = client.get("/list")
        data = response.json()
        assert data[0]["token"] == "***REDACTED***"
        assert data[1]["name"] == "public"
