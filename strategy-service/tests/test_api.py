"""
API集成测试（使用FastAPI TestClient）
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestAPIEndpoints:
    """核心API端点集成测试"""

    def test_root_endpoint(self):
        """根端点返回服务信息"""
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "QuantTradingSystem Strategy Service"
        assert data["version"] == "2.0.0"

    def test_health_endpoint(self):
        """健康检查"""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_ai_models_endpoint(self):
        """AI模型列表"""
        resp = client.get("/api/v1/ai/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]) >= 10  # 至少10个模型

    def test_backtest_strategies(self):
        """回测策略列表"""
        resp = client.get("/api/v1/backtest/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        strategies = [s["name"] for s in data["data"]]
        assert "ma-cross" in strategies
        assert "breakout" in strategies
        assert "rsi" in strategies

    def test_backtest_run_ma_cross(self):
        """回测：双均线策略（沙箱下Tushare不可用，验证接口存在）"""
        resp = client.post(
            "/api/v1/backtest/run?ts_code=600519.SH&strategy=ma-cross"
            "&start_date=20240101&end_date=20240601"
        )
        assert resp.status_code in [200, 400, 500]
        data = resp.json()
        # 沙箱环境下Tushare不可用, code可能为1(数据不足)或0(成功)
        assert "code" in data

    def test_backtest_run_breakout(self):
        """回测：突破策略"""
        resp = client.post(
            "/api/v1/backtest/run?ts_code=000001.SZ&strategy=breakout"
            "&start_date=20240101&end_date=20240601"
        )
        assert resp.status_code in [200, 400]
        data = resp.json()
        assert "code" in data

    def test_account_summary(self):
        """账户概要"""
        resp = client.get("/api/v1/account/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "total_assets" in data["data"]

    def test_account_positions(self):
        """持仓列表"""
        resp = client.get("/api/v1/account/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 3  # 模拟持仓至少3只

    def test_trades_list(self):
        """交易记录列表"""
        resp = client.get("/api/v1/trades?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 10

    def test_trades_filter_by_direction(self):
        """交易记录按方向筛选"""
        resp = client.get("/api/v1/trades?limit=5&direction=BUY")
        assert resp.status_code == 200
        data = resp.json()
        assert all(t["direction"] == "BUY" for t in data["data"])

    def test_trades_stats(self):
        """交易统计"""
        resp = client.get("/api/v1/trades/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "total_trades" in data["data"]
        assert "win_rate" in data["data"]

    def test_ai_scan_post(self):
        """AI选股扫描"""
        resp = client.post("/api/v1/ai/scan?strategy=all&top_n=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) <= 3

    def test_ai_review(self):
        """AI每日复盘"""
        resp = client.get("/api/v1/ai/review?date=2026-06-07")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "summary" in data["data"]

    def test_stock_index_realtime(self):
        """指数实时行情"""
        resp = client.get("/api/v1/stocks/index/realtime")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data

    def test_stock_realtime_quote(self):
        """个股实时行情"""
        resp = client.get("/api/v1/stocks/realtime/600519.SH")
        assert resp.status_code == 200
        data = resp.json()
        if data.get("code") == 0 or data.get("success"):
            assert "data" in data

    def test_websocket_endpoint_exists(self):
        """WebSocket路由存在（不连接）"""
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
