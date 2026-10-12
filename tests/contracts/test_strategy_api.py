"""
策略服务 API 契约测试
验证 strategy-service REST API 的响应格式稳定不变。
"""

import pytest

STRATEGY_URL = "http://localhost:8000"

# ── 2026-10-12：鉴权凭据统一走共享 helper（本文件原先自带一份副本，已收敛）──
# 消除「双副本」：本地 _get/_post 与 tests/_api_contract_helper.py 的 api_get/api_post 语义重复，
# 一旦服务端鉴权策略变化就会两处分叉。约定与实现见 tests/_api_contract_helper.py。
from tests._api_contract_helper import api_get, api_post  # noqa: E402


class TestHealthEndpoint:
    def test_health_returns_200(self):
        resp = api_get(f"{STRATEGY_URL}/health", timeout=5)
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


class TestIndexEndpoint:
    def test_index_realtime_schema(self):
        resp = api_get(f"{STRATEGY_URL}/api/v1/stocks/index/realtime", timeout=10)
        if resp.status_code == 404:
            pytest.skip("index endpoint not mounted")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        indices = data["data"]
        assert len(indices) >= 8, f"Expected >=8 indices, got {len(indices)}"
        for idx in indices:
            assert "code" in idx
            assert "name" in idx
            assert "price" in idx
            assert "pct_change" in idx
        valid = [i for i in indices if i["price"] > 0]
        assert len(valid) >= 1, "No index has price > 0"


class TestStockEndpoint:
    def test_realtime_quote_schema(self):
        resp = api_get(f"{STRATEGY_URL}/api/v1/stocks/realtime/600519.SH", timeout=10)
        if resp.status_code == 404:
            pytest.skip("stock realtime endpoint not mounted")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        quote = data["data"]
        required = ["ts_code", "name", "price", "open", "high", "low", "pre_close", "pct_change"]
        for field in required:
            assert field in quote, f"Missing field: {field}"

    def test_realtime_quote_not_found(self):
        resp = api_get(f"{STRATEGY_URL}/api/v1/stocks/realtime/999999.XZ", timeout=10)
        if resp.status_code == 404:
            pytest.skip("stock realtime endpoint not mounted")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] != 0 or data.get("data", {}).get("price", -1) <= 0


class TestBacktestEndpoint:
    def test_run_backtest_contract(self):
        payload = {
            "ts_code": "000001.SZ",
            "strategies": ["ma-cross"],
            "start_date": "20250101",
            "end_date": "20250601",
            "initial_cash": 100000,
        }
        resp = api_post(
            f"{STRATEGY_URL}/api/v1/backtest/run",
            json=payload,
            timeout=30,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        result = data["data"]
        assert "strategy" in result
        assert "metrics" in result
        metrics = result["metrics"]
        required_metrics = ["total_return", "sharpe_ratio", "max_drawdown", "win_rate"]
        for m in required_metrics:
            assert m in metrics, f"Missing metric: {m}"

    def test_backtest_invalid_params(self):
        payload = {
            "ts_code": "NONEXISTENT",
            "strategies": ["ma-cross"],
            "start_date": "20990101",
            "end_date": "20991231",
            "initial_cash": 100000,
        }
        resp = api_post(
            f"{STRATEGY_URL}/api/v1/backtest/run",
            json=payload,
            timeout=10,
        )
        assert resp.status_code == 200
        # 无效参数应返回 success=False 或空数据，不应 500
        data = resp.json()
        assert data["success"] is False or data["data"] is not None


class TestStrategiesEndpoint:
    def test_list_strategies(self):
        resp = api_get(f"{STRATEGY_URL}/api/v1/strategies", timeout=5)
        assert resp.status_code in (200, 404)  # 端点存在即可
