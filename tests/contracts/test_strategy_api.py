"""
策略服务 API 契约测试
验证 strategy-service REST API 的响应格式稳定不变。
"""

import pytest
import requests

STRATEGY_URL = "http://localhost:8000"

# ── 2026-10-12：服务端已启用鉴权（JWT + X-API-Key），裸 GET 会 401 ──
# 这 21 个契约用例因此长期"假红"。约定：**凭据从环境给**（不写进代码），
# 拿不到凭据时**带明确原因跳过**（skip ≠ 通过，也不会伪装成失败）。
#   export QTS_JWT=<访问令牌>   或   export QTS_API_KEY=<服务间密钥>
import os

_AUTH_HEADERS: dict[str, str] = {}
_jwt = os.environ.get("QTS_JWT", "").strip()
_key = (os.environ.get("QTS_API_KEY") or os.environ.get("API_KEYS", "").split(",")[0]).strip()
if _jwt:
    _AUTH_HEADERS["Authorization"] = f"Bearer {_jwt}"
elif _key:
    _AUTH_HEADERS["X-API-Key"] = _key


def _get(url: str, timeout: int = 10):
    """带凭据的 GET；**401 且未配置凭据** → 跳过（附原因），而不是假红。"""
    resp = requests.get(url, headers=_AUTH_HEADERS, timeout=timeout)
    if resp.status_code == 401 and not _AUTH_HEADERS:
        pytest.skip(
            "需要凭据：服务端鉴权已启用。设 QTS_JWT 或 QTS_API_KEY 后重跑"
            "（有凭据时 401 仍会判失败，不会掩盖真问题）"
        )
    return resp


def _post(url: str, *, json: dict | None = None, timeout: int = 15):
    """POST 版：与 _get 同一约定（无凭据遇 401 → 跳过并说明）。"""
    resp = requests.post(url, json=json, headers=_AUTH_HEADERS, timeout=timeout)
    if resp.status_code == 401 and not _AUTH_HEADERS:
        pytest.skip("需要凭据：服务端鉴权已启用。设 QTS_JWT 或 QTS_API_KEY 后重跑")
    return resp


class TestHealthEndpoint:
    def test_health_returns_200(self):
        resp = _get(f"{STRATEGY_URL}/health", timeout=5)
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


class TestIndexEndpoint:
    def test_index_realtime_schema(self):
        resp = _get(f"{STRATEGY_URL}/api/v1/stocks/index/realtime", timeout=10)
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
        resp = _get(f"{STRATEGY_URL}/api/v1/stocks/realtime/600519.SH", timeout=10)
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
        resp = _get(f"{STRATEGY_URL}/api/v1/stocks/realtime/999999.XZ", timeout=10)
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
        resp = _post(
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
        resp = _post(
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
        resp = _get(f"{STRATEGY_URL}/api/v1/strategies", timeout=5)
        assert resp.status_code in (200, 404)  # 端点存在即可
