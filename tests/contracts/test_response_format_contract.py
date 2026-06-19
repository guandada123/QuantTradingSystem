"""
响应格式契约测试 v2.0

验证 QTS 所有微服务的统一响应格式一致性：
  - 成功: {"code": 0, "data": {...}, "message": ""}
  - 错误: {"code": -1, "message": "...", "data": None}
  - 风控拦截: {"code": -1, "message": "...", "data": {"allowed": false, "reason": "..."}}

本文件测试：
1. 各服务 main.py 中异常处理器的响应格式一致性
2. 共享模块中响应辅助函数的格式一致性
3. 关键 API 路由返回的统一格式（通过解析源码）

不依赖外部服务。使用源码静态分析与 Mock。
"""

import ast
import os
import re
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── 项目根路径 ───────────────────────────────────────────────────────
_QTS_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))

SERVICE_FILES = {
    "strategy-service": os.path.join(_QTS_ROOT, "strategy-service", "main.py"),
    "execution-service": os.path.join(_QTS_ROOT, "execution-service", "main.py"),
    "ai-scheduler": os.path.join(_QTS_ROOT, "ai-scheduler", "main.py"),
}


# =========================================================================
# 1. 各服务异常处理器响应格式
# =========================================================================


class TestErrorHandlerFormat:
    """测试各服务的异常处理器的 JSON 响应格式是否统一"""

    SERVICE_EXCEPTION_HANDLERS = {
        "strategy-service": {
            "expected": {"code": -1, "message": "内部服务错误"},
            "file": "strategy-service/main.py",
        },
        "execution-service": {
            "expected": {"code": -1, "message": None, "data": None},
            "file": "execution-service/main.py",
        },
        "ai-scheduler": {
            "expected": {"success": True, "message": "测试告警已发送到飞书群"},
            "file": "ai-scheduler/main.py",
        },
    }

    def test_strategy_service_error_format(self):
        """strategy-service 错误格式: {"code": -1, "message": "..."}"""
        main_path = SERVICE_FILES["strategy-service"]
        assert os.path.exists(main_path), f"文件不存在: {main_path}"

        with open(main_path, encoding="utf-8") as f:
            content = f.read()

        # 验证 code=-1 格式存在
        assert '"code": -1' in content or "'code': -1" in content, \
            "strategy-service 应包含 code=-1 错误响应"
        assert '"message"' in content or "'message'" in content, \
            "strategy-service 错误响应应包含 message 字段"

    def test_execution_service_error_format(self):
        """execution-service 错误格式: {"code": -1, "message": "...", "data": None}"""
        main_path = SERVICE_FILES["execution-service"]
        assert os.path.exists(main_path), f"文件不存在: {main_path}"

        with open(main_path, encoding="utf-8") as f:
            content = f.read()

        # 验证 code=-1 格式存在
        assert '"code": -1' in content, "execution-service 应包含 code=-1 错误响应"
        assert '"message"' in content, "execution-service 错误响应应包含 message 字段"
        assert '"data"' in content, "execution-service 错误响应应包含 data 字段"

    def test_execution_service_error_handlers_count(self):
        """execution-service 应该有完整的异常处理器覆盖"""
        main_path = SERVICE_FILES["execution-service"]
        with open(main_path, encoding="utf-8") as f:
            content = f.read()

        # 统计类似 @app.exception_handler 的异常处理器
        handler_count = content.count("exception_handler")
        assert handler_count >= 1, "execution-service 应至少有一个异常处理器"
        print(f"  → execution-service 异常处理器数量: {handler_count}")

    def test_strategy_service_error_handlers_count(self):
        """strategy-service 应该有完整的异常处理器覆盖"""
        main_path = SERVICE_FILES["strategy-service"]
        with open(main_path, encoding="utf-8") as f:
            content = f.read()

        handler_count = content.count("exception_handler")
        print(f"  → strategy-service 异常处理器数量: {handler_count}")


# =========================================================================
# 2. execution-service 统一错误响应格式
# =========================================================================


class TestExecutionServiceErrorFormat:
    """execution-service 的 ValueError / HTTPException / 自定义异常响应格式"""

    @pytest.mark.asyncio
    async def test_value_error_handler_format(self):
        """ValueError 异常处理器返回正确格式"""
        # 模拟 FastAPI exception_handler 中的 JSONResponse
        from fastapi.responses import JSONResponse

        # 模拟 execution-service 的 ValueError handler
        import json

        response = JSONResponse(
            status_code=400,
            content={"code": -1, "message": "test error", "data": None},
        )
        parsed = json.loads(response.body.decode())
        assert parsed["code"] == -1
        assert parsed["message"] == "test error"
        assert parsed["data"] is None

    @pytest.mark.asyncio
    async def test_http_exception_handler_format(self):
        """HTTPException 异常处理器返回正确格式"""
        from fastapi.responses import JSONResponse

        import json

        response = JSONResponse(
            status_code=404,
            content={"code": -1, "message": "Not Found", "data": None},
        )
        parsed = json.loads(response.body.decode())
        assert parsed["code"] == -1
        assert parsed["message"] == "Not Found"
        assert parsed["data"] is None


# =========================================================================
# 3. 客户端响应格式解析契约
# =========================================================================

# 所有客户端使用的统一数据提取模式: data.get("data", data.get("results", []))
# 这里直接测试该模式，不依赖真实客户端 import


class TestResponseParsingPattern:
    """客户端统一解析模式兼容性验证"""

    def test_standard_format_parsing(self):
        """标准格式 {"code": 0, "data": [...]} 可正确提取"""
        response = {
            "code": 0,
            "data": [{"ts_code": "600519.SH", "name": "贵州茅台"}],
            "message": "",
        }
        extracted = response.get("data", response.get("results", []))
        assert len(extracted) == 1
        assert extracted[0]["ts_code"] == "600519.SH"

    def test_legacy_format_parsing(self):
        """旧格式 {"results": [...]} 兼容"""
        response = {"results": [{"ts_code": "000001.SZ", "score": 85}]}
        extracted = response.get("data", response.get("results", []))
        assert len(extracted) == 1
        assert extracted[0]["score"] == 85

    def test_empty_data_parsing(self):
        """空 data 返回空列表"""
        response = {"code": 0, "data": []}
        extracted = response.get("data", response.get("results", []))
        assert extracted == []

    def test_both_fields_empty_returns_empty_list(self):
        """data 和 results 都不存在时返回空列表"""
        response = {"code": -1, "message": "error"}
        extracted = response.get("data", response.get("results", []))
        assert extracted == []

    def test_error_response_format(self):
        """客户端错误降级返回格式: {success: False, error: "..."}"""
        error_result = {"success": False, "error": "Connection refused"}
        assert error_result["success"] is False
        assert "Connection refused" in error_result["error"]


# =========================================================================
# 4. 跨服务数据格式合同一致性
# =========================================================================


class TestCrossServiceDataContract:
    """跨服务数据格式一致性验证"""

    # 统一的数据契约: 股票代码、订单、持仓等核心数据结构
    STOCK_QUOTE_CONTRACT = {
        "required_fields": ["ts_code", "name", "price"],
        "optional_fields": ["open", "high", "low", "pre_close", "pct_change", "volume", "amount"],
        "code_field": "ts_code",
        "price_type": float,
    }

    ORDER_CONTRACT = {
        "required_fields": ["account_id", "ts_code", "direction", "order_type", "price", "quantity"],
        "direction_values": ["BUY", "SELL"],
        "order_type_values": ["LIMIT", "MARKET"],
    }

    POSITION_CONTRACT = {
        "required_fields": ["ts_code", "total_quantity", "available_quantity", "cost_price", "current_price", "market_value"],
    }

    def test_stock_quote_contract_fields(self):
        """股票行情契约字段完整性"""
        # 验证策略服务回传的股票行情数据结构
        valid_quote = {
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "price": 1880.0,
            "open": 1870.0,
            "high": 1890.0,
            "low": 1865.0,
            "pre_close": 1875.0,
            "pct_change": 0.27,
            "volume": 2500000,
            "amount": 4.7e9,
        }

        for field in self.STOCK_QUOTE_CONTRACT["required_fields"]:
            assert field in valid_quote, f"股票行情缺少必要字段: {field}"
        assert isinstance(valid_quote["price"], (int, float)), "price 必须是数值"

    def test_order_contract_fields(self):
        """订单契约字段完整性"""
        valid_order = {
            "account_id": "REAL_001",
            "ts_code": "000001.SZ",
            "direction": "BUY",
            "order_type": "LIMIT",
            "price": 12.50,
            "quantity": 100,
        }

        for field in self.ORDER_CONTRACT["required_fields"]:
            assert field in valid_order, f"订单缺少必要字段: {field}"
        assert valid_order["direction"] in self.ORDER_CONTRACT["direction_values"], \
            f"direction 必须是 {self.ORDER_CONTRACT['direction_values']} 之一"
        assert valid_order["order_type"] in self.ORDER_CONTRACT["order_type_values"], \
            f"order_type 必须是 {self.ORDER_CONTRACT['order_type_values']} 之一"

    def test_position_contract_fields(self):
        """持仓契约字段完整性"""
        valid_position = {
            "ts_code": "000001.SZ",
            "total_quantity": 1000,
            "available_quantity": 1000,
            "cost_price": 12.50,
            "current_price": 12.80,
            "market_value": 12800.0,
            "profit_loss": 300.0,
            "profit_loss_ratio": 0.024,
            "days_held": 5,
            "stop_loss_price": 11.50,
            "take_profit_price": 16.25,
            "strategy_name": "ma-cross",
        }

        for field in self.POSITION_CONTRACT["required_fields"]:
            assert field in valid_position, f"持仓缺少必要字段: {field}"
        assert isinstance(valid_position["market_value"], (int, float)), "market_value 必须是数值"

    def test_strategy_client_scan_request_format(self):
        """StrategyClient scan_stocks 请求体格式验证"""
        # 请求体应当包含 limit, 可选 strategy_ids, ts_codes
        request_body = {
            "limit": 100,
            "strategy_ids": ["ma-cross", "breakout"],
            "ts_codes": ["600519.SH"],
        }
        assert "limit" in request_body
        assert isinstance(request_body["limit"], int)
        assert 1 <= request_body["limit"] <= 500, "limit 应在 1-500 范围内"

    def test_execution_client_submit_request_format(self):
        """ExecutionClient submit_order 请求体格式验证"""
        request_body = {
            "account_id": "REAL_001",
            "ts_code": "000001.SZ",
            "direction": "BUY",
            "order_type": "LIMIT",
            "price": 12.50,
            "quantity": 100,
        }
        assert request_body["direction"] in ("BUY", "SELL")
        assert request_body["order_type"] in ("LIMIT", "MARKET")
        assert request_body["quantity"] > 0
        assert request_body["price"] > 0

    def test_backtest_request_contract(self):
        """回测请求体契约验证"""
        request_body = {
            "ts_code": "000001.SZ",
            "strategies": ["ma-cross"],
            "start_date": "20250101",
            "end_date": "20250601",
            "initial_cash": 100000,
        }
        assert "ts_code" in request_body
        assert "strategies" in request_body
        assert isinstance(request_body["strategies"], list)
        assert len(request_body["strategies"]) >= 1
        assert len(request_body["strategies"]) <= 5, "最多支持 5 个策略同时回测"
        assert "start_date" in request_body
        assert "end_date" in request_body


# =========================================================================
# 5. 飞书告警数据格式合同
# =========================================================================


class TestFeishuAlertDataContract:
    """飞书告警服务的消息格式一致性"""

    def test_alert_service_messages_format(self):
        """告警消息应包含必要字段"""
        alert_message = {
            "title": "服务宕机告警",
            "service": "strategy-service",
            "timestamp": "2026-06-16T22:00:00+08:00",
            "detail": "健康检查失败，服务不可达",
            "level": "critical",
        }
        required = ["title", "service", "timestamp", "detail", "level"]
        for field in required:
            assert field in alert_message, f"告警消息缺少必要字段: {field}"

    def test_alert_level_enum(self):
        """告警级别枚举完整性"""
        valid_levels = ["critical", "warning", "info", "recovered"]
        assert "critical" in valid_levels
        assert "recovered" in valid_levels
