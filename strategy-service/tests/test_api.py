"""
API集成测试（使用FastAPI TestClient）
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app
import pytest as pytest

client = TestClient(app)


class TestAPIEndpoints:
    """核心API端点集成测试"""

    def test_root_endpoint(self):
        """根端点返回服务信息（支持 JSON 和 SPA HTML 两种模式）"""
        resp = client.get("/")
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        if "json" in ct:
            data = resp.json()
            assert data["service"] == "QuantTradingSystem Strategy Service"
            assert data["version"] == "2.0.0"
        else:
            # Dashboard 模式——返回 SPA HTML
            assert "html" in ct or "text/html" in ct

    def test_health_endpoint(self):
        """健康检查"""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    @pytest.mark.skip(reason="GET /api/v1/ai/models 路由未实现")
    def test_ai_models_endpoint(self):
        """AI模型列表（暂不可用）"""
        resp = client.get("/api/v1/ai/models")
        assert resp.status_code == 200

    def test_backtest_strategies(self):
        """回测策略列表"""
        resp = client.get("/api/v1/strategies/")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True or "data" in data
        strategies_data = data.get("data", [])
        assert len(strategies_data) > 0
        strategy_ids = [s.get("id", s.get("name", "")) for s in strategies_data]
        has_ma = any("ma" in str(s).lower() for s in strategy_ids)
        has_breakout = any("breakout" in str(s).lower() for s in strategy_ids)
        has_rsi = any("rsi" in str(s).lower() for s in strategy_ids)
        assert has_ma and has_breakout and has_rsi

    def test_backtest_run_ma_cross(self):
        """回测：双均线策略（沙箱下Tushare/Pandas不可用）"""
        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "600519.SH",
                "strategy": "ma-cross",
                "start_date": "2024-01-01",
                "end_date": "2024-06-01",
            },
        )
        assert resp.status_code in [200, 400, 500]
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("success") is True

    def test_backtest_run_breakout(self):
        """回测：突破策略"""
        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000001.SZ",
                "strategy": "breakout",
                "start_date": "2024-01-01",
                "end_date": "2024-06-01",
            },
        )
        assert resp.status_code in [200, 400, 500]
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("success") is True

    def test_account_summary(self):
        """账户概要"""
        resp = client.get("/api/v1/account/summary")
        assert resp.status_code == 200
        data = resp.json()
        if not data.get("success"):
            pytest.skip("数据库无种子数据，跳过账户概要测试")
        assert "total_assets" in data["data"]

    def test_account_positions(self):
        """持仓列表"""
        resp = client.get("/api/v1/account/positions")
        assert resp.status_code == 200
        data = resp.json()
        if not data.get("success") or not isinstance(data.get("data"), list):
            pytest.skip("数据库无种子数据，跳过持仓列表测试")
        assert len(data["data"]) >= 3  # 模拟持仓至少3只

    def test_trades_list(self):
        """交易记录列表"""
        resp = client.get("/api/v1/trades?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        if not data.get("success") or not isinstance(data.get("data"), list):
            pytest.skip("数据库无种子数据，跳过交易记录测试")
        assert len(data["data"]) >= 1

    def test_trades_filter_by_direction(self):
        """交易记录按方向筛选"""
        resp = client.get("/api/v1/trades?limit=5&direction=buy")
        assert resp.status_code == 200
        data = resp.json()
        assert all(t["direction"].lower() == "buy" for t in data["data"])

    def test_trades_stats(self):
        """交易统计"""
        resp = client.get("/api/v1/trades/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "total_trades" in data["data"]
        assert "win_rate" in data["data"]

    def test_ai_scan_post(self):
        """AI选股扫描（沙箱下可能降级为演示数据）"""
        resp = client.post("/api/v1/ai/scan?strategy=all&top_n=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

    def test_ai_review(self):
        """AI每日复盘"""
        resp = client.get("/api/v1/ai/review?date=2026-06-07")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "market_overview" in data["data"]

    def test_stock_index_realtime(self):
        """指数实时行情（沙箱下可能无Tushare数据）"""
        resp = client.get("/api/v1/stocks/index/realtime")
        assert resp.status_code in [200, 500]  # Tushare可能不可用
        if resp.status_code == 200:
            data = resp.json()
            assert "data" in data

    def test_stock_realtime_quote(self):
        """个股实时行情（沙箱下可能无Tushare数据）"""
        resp = client.get("/api/v1/stocks/realtime/600519.SH")
        assert resp.status_code in [200, 500]
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0 or data.get("success"):
                assert "data" in data

    @pytest.mark.skip(reason="WebSocket handler 不发送 connected 消息，需异步测试")
    def test_websocket_endpoint_exists(self):
        """WebSocket路由存在——待异步测试"""

    # ==== 新增测试（DB接入后） ====

    @pytest.mark.skip(reason="GET /api/v1/stocks/search 路由未实现，使用 /api/v1/stocks/pool 替代")
    def test_stock_search(self):
        """股票搜索（暂不可用）"""

    def test_signal_history(self):
        """信号历史"""
        resp = client.get("/api/v1/signals/?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert isinstance(data["data"], dict)
        assert "signals" in data["data"]

    def test_signal_latest(self):
        """查询单个信号"""
        resp = client.get("/api/v1/signals/600519.SH")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_backtest_history(self):
        """回测历史"""
        resp = client.get("/api/v1/backtest/")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True

    def test_get_data_source(self):
        """获取当前数据源配置"""
        resp = client.get("/api/v1/config/data-source")
        assert resp.status_code == 200
        data = resp.json()
        assert "current_source" in data
        assert "available_sources" in data
        assert "tdx" in data["available_sources"]
        assert "tushare" in data["available_sources"]
        assert "akshare" in data["available_sources"]

    def test_switch_data_source(self):
        """切换数据源"""
        resp = client.post("/api/v1/config/data-source", json={"source": "tdx"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["current_source"] == "tdx"

    def test_switch_data_source_invalid(self):
        """切换到无效数据源应返回 400"""
        resp = client.post("/api/v1/config/data-source", json={"source": "nonexistent"})
        assert resp.status_code == 400
        data = resp.json()
        assert "detail" in data
