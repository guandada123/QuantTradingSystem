"""
backtest_v2 API 路由测试

覆盖：
- POST /api/v1/backtest/run — 单策略 / 多策略回测
- GET /api/v1/backtest/ — 回测列表
- GET /api/v1/backtest/status — 服务状态
- POST /api/v1/backtest/walk-forward — Walk-Forward 分析
- 输入验证（缺失参数、JSON 格式错误）
- 异步超时保护（#138）
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from api.backtest_v2 import router
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

# ============================================================
#  测试应用
# ============================================================

app = FastAPI()
app.include_router(router, prefix="/api/v1/backtest")
client = TestClient(app)


# ============================================================
#  Mock 数据
# ============================================================

_MOCK_KLINE = [
    {
        "trade_date": "20260105",
        "open": 100.0,
        "close": 101.0,
        "high": 102.0,
        "low": 99.0,
        "vol": 1000000,
        "amount": 100000000.0,
    },
    {
        "trade_date": "20260106",
        "open": 101.0,
        "close": 102.5,
        "high": 103.0,
        "low": 100.5,
        "vol": 1200000,
        "amount": 122000000.0,
    },
    {
        "trade_date": "20260107",
        "open": 102.5,
        "close": 101.8,
        "high": 104.0,
        "low": 101.0,
        "vol": 900000,
        "amount": 92000000.0,
    },
]


def _make_mock_result(**overrides) -> MagicMock:
    """创建模拟 BacktestResult"""
    result = MagicMock()
    result.total_return = overrides.get("total_return", 0.156)
    result.annual_return = overrides.get("annual_return", 0.08)
    result.sharpe_ratio = overrides.get("sharpe_ratio", 1.25)
    result.max_drawdown = overrides.get("max_drawdown", -0.05)
    result.win_rate = overrides.get("win_rate", 0.65)
    result.profit_factor = overrides.get("profit_factor", 2.1)
    result.volatility = overrides.get("volatility", 0.15)
    result.alpha = overrides.get("alpha", 0.02)
    result.beta = overrides.get("beta", 0.9)
    result.calmar_ratio = overrides.get("calmar_ratio", 1.6)
    result.sortino_ratio = overrides.get("sortino_ratio", 1.8)
    result.total_trades = overrides.get("total_trades", 15)
    result.equity_curve = overrides.get(
        "equity_curve",
        [
            {"date": "20260105", "nav": 1.0, "benchmark_nav": 1.0, "drawdown": 0.0},
            {"date": "20260106", "nav": 1.015, "benchmark_nav": 1.005, "drawdown": -0.005},
            {"date": "20260107", "nav": 1.025, "benchmark_nav": 1.012, "drawdown": -0.008},
        ],
    )
    result.monthly_returns = overrides.get("monthly_returns", [])
    result.trades = overrides.get("trades", [])
    return result


# ============================================================
#  POST /api/v1/backtest/run
# ============================================================


class TestRunBacktest:
    """单策略回测"""

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_single_strategy_default(self, mock_engine_cls):
        """默认参数单策略回测 → 200 + 完整 data 结构"""
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()
        # mock 两个静态方法都返回有效数据
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE
        mock_engine_cls.fetch_kline_eastmoney.return_value = None

        resp = client.post(
            "/api/v1/backtest/run",
            json={"ts_code": "000333.SZ", "start_date": "2026-01-05", "end_date": "2026-01-07"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        result = data["data"]
        assert result["strategy"] == "ma-cross"
        assert result["metrics"]["total_return"] == 0.156
        assert result["metrics"]["sharpe"] == 1.25
        assert result["metrics"]["win_rate"] == 0.65
        assert result["metrics"]["trade_count"] == 15
        assert len(result["equity_curve"]) == 3
        assert len(result["trades"]) == 0
        assert result["data_source"] == "tencent"

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_single_strategy_ma_cross(self, mock_engine_cls):
        """指定 ma-cross 策略"""
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "strategy": "ma-cross",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["strategy"] == "ma-cross"

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_single_strategy_breakout(self, mock_engine_cls):
        """指定 breakout 策略"""
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "strategy": "breakout",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["strategy"] == "breakout"

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_multi_strategy(self, mock_engine_cls):
        """多策略回测 → 返回 comparison"""
        instance = mock_engine_cls.return_value
        instance.run.side_effect = [
            _make_mock_result(strategy_name="ma-cross"),
            _make_mock_result(strategy_name="breakout"),
        ]
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "strategies": ["ma-cross", "breakout"],
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "data" in data
        assert "comparison" in data
        assert len(data["comparison"]) == 2

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_custom_params(self, mock_engine_cls):
        """自定义资金和费率参数"""
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "strategy": "ma-cross",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
                "initial_cash": 500000,
                "params": {"slippage": 0.002, "commission_rate": 0.0005},
            },
        )

        assert resp.status_code == 200
        # 验证 BacktestConfig 传入了正确参数
        call_args = mock_engine_cls.call_args
        config = call_args[0][0]
        assert config.initial_cash == 500000.0
        assert config.slippage == 0.002
        assert config.commission_rate == 0.0005

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_uses_cash_fallback(self, mock_engine_cls):
        """兼容 'cash' 字段作为资金参数"""
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "cash": 200000,
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )
        assert resp.status_code == 200
        config = mock_engine_cls.call_args[0][0]
        assert config.initial_cash == 200000.0

    def test_missing_ts_code(self):
        """缺少 ts_code → success=False"""
        resp = client.post(
            "/api/v1/backtest/run",
            json={"start_date": "2026-01-05", "end_date": "2026-01-07"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "ts_code" in resp.json()["error"]

    def test_missing_dates(self):
        """缺少日期 → success=False"""
        resp = client.post(
            "/api/v1/backtest/run",
            json={"ts_code": "000333.SZ"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "日期" in resp.json()["error"]

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_no_strategies_fallback_to_default(self, mock_engine_cls):
        """无 strategy 字段时自动 fallback 到 ma-cross"""
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["strategy"] == "ma-cross"

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_empty_strategies_fallback(self, mock_engine_cls):
        """strategies 为空列表时 fallback 到 strategy 字段"""
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "strategy": "breakout",
                "strategies": [],
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["strategy"] == "breakout"

    def test_invalid_json(self):
        """非 JSON 请求体 → 200 + error（API 层 try/except 处理）"""
        resp = client.post(
            "/api/v1/backtest/run",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_engine_execution_failure(self, mock_engine_cls):
        """引擎内部异常 → success=False"""
        instance = mock_engine_cls.return_value
        instance.run.side_effect = Exception("数据获取失败")
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "失败" in resp.json()["error"]

    def test_invalid_date_value(self):
        """无效日期值（如13月）→ validate_dates 捕获 → success=False"""
        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "start_date": "2026-13-01",
                "end_date": "2026-01-07",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "日期" in resp.json()["error"]

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_data_source_fallback_to_eastmoney(self, mock_engine_cls):
        """腾讯数据为空 → 自动降级到东财"""
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()
        mock_engine_cls.fetch_kline_tencent.return_value = None
        mock_engine_cls.fetch_kline_eastmoney.return_value = _MOCK_KLINE

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_normalize_skips_empty_trade_date(self, mock_engine_cls):
        """K线数据中 trade_date 为空 → _normalize 跳过该行"""
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()
        mock_engine_cls.fetch_kline_tencent.return_value = [
            {
                "trade_date": "",
                "open": 100.0,
                "close": 101.0,
                "high": 102.0,
                "low": 99.0,
                "vol": 1000000,
                "amount": 100000000.0,
            },
            {
                "trade_date": "20260106",
                "open": 101.0,
                "close": 102.5,
                "high": 103.0,
                "low": 100.5,
                "vol": 1200000,
                "amount": 122000000.0,
            },
        ]
        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_backtest_without_equity_curve(self, mock_engine_cls):
        """equity_curve 为空时走 else 分支计算 final_value"""
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result(equity_curve=[])
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_trades_conversion(self, mock_engine_cls):
        """回测结果包含交易记录 → 正确转换为前端格式"""
        instance = mock_engine_cls.return_value
        mock_trade = MagicMock()
        mock_trade.date = "20260106"
        mock_trade.ts_code = "000333.SZ"
        mock_trade.direction = "BUY"
        mock_trade.price = 101.5
        mock_trade.amount = 1000
        mock_trade.shares = 100
        mock_trade.trade_type = "open"
        mock_trade.commission = 1.0

        cur = [
            {"date": "20260105", "nav": 1.0, "benchmark_nav": 1.0, "drawdown": 0.0},
            {"date": "20260106", "nav": 1.015, "benchmark_nav": 1.005, "drawdown": -0.005},
            {"date": "20260107", "nav": 1.025, "benchmark_nav": 1.012, "drawdown": -0.008},
        ]
        instance.run.return_value = _make_mock_result(equity_curve=cur, trades=[mock_trade])
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["trades"]) == 1
        assert data["trades"][0]["date"] == "20260106"
        assert data["trades"][0]["direction"] == "买入"


# ============================================================
#  GET /api/v1/backtest/
# ============================================================


class TestListBacktest:
    """回测列表"""

    @patch("repositories.backtest_repo.get_backtest_history", return_value=[])
    def test_list_results(self, mock_get_history):
        """GET / → 空列表（mock DB 避免被其他测试污染）"""
        resp = client.get("/api/v1/backtest/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["backtests"] == []
        assert data["data"]["total"] == 0

    @patch("repositories.backtest_repo.get_backtest_history")
    def test_list_results_with_strategy_filter(self, mock_get_history):
        """GET /?strategy=xxx → 按策略名称过滤（SQL 层过滤）"""
        _all = [
            {
                "backtest_id": "1",
                "strategy_name": "ma-cross",
                "ts_code": "000333.SZ",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
                "total_return": 0.15,
                "sharpe_ratio": 1.2,
                "max_drawdown": -0.05,
                "total_trades": 10,
                "created_at": "2026-06-15T12:00:00",
            },
            {
                "backtest_id": "2",
                "strategy_name": "breakout",
                "ts_code": "000001.SZ",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
                "total_return": 0.08,
                "sharpe_ratio": 0.9,
                "max_drawdown": -0.03,
                "total_trades": 5,
                "created_at": "2026-06-15T12:00:00",
            },
        ]

        def _mock_history(db, limit=20, strategy_name=None):
            if strategy_name:
                return [r for r in _all if r["strategy_name"] == strategy_name]
            return _all

        mock_get_history.side_effect = _mock_history

        resp = client.get("/api/v1/backtest/?strategy=ma-cross")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]["backtests"]) == 1
        assert data["data"]["backtests"][0]["strategy_name"] == "ma-cross"
        assert data["data"]["total"] == 1


# ============================================================
#  GET /api/v1/backtest/status
# ============================================================


class TestBacktestStatus:
    """服务状态"""

    def test_status_available(self):
        """服务状态正常"""
        resp = client.get("/api/v1/backtest/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["status"] == "available"
        assert data["data"]["engine"] == "enhanced_v2"


# ============================================================
#  POST /api/v1/backtest/walk-forward
# ============================================================


class TestWalkForward:
    """Walk-Forward 分析"""

    _MOCK_WF_RESULT = {
        "windows": [
            {
                "train_start": "20250105",
                "train_end": "20250630",
                "test_start": "20250701",
                "test_end": "20250815",
                "best_params": {"ma_fast": 10, "ma_slow": 30},
                "train_sharpe": 1.35,
                "test_sharpe": 0.95,
                "train_return": 0.12,
                "test_return": 0.08,
                "test_max_dd": -0.03,
            },
            {
                "train_start": "20250816",
                "train_end": "20260115",
                "test_start": "20260116",
                "test_end": "20260228",
                "best_params": {"ma_fast": 5, "ma_slow": 20},
                "train_sharpe": 1.25,
                "test_sharpe": 0.88,
                "train_return": 0.10,
                "test_return": 0.06,
                "test_max_dd": -0.04,
            },
        ],
        "overall_test_return": 0.14,
        "overfit_ratio": 0.72,
    }

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_walk_forward_success(self, mock_engine_cls):
        """基本 Walk-Forward 分析"""
        instance = mock_engine_cls.return_value
        instance.walk_forward.return_value = self._MOCK_WF_RESULT

        resp = client.post(
            "/api/v1/backtest/walk-forward",
            json={
                "ts_code": "000333.SZ",
                "strategy": "ma-cross",
                "start_date": "2025-01-05",
                "end_date": "2026-02-28",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        wf_data = data["data"]
        assert wf_data["strategy"] == "ma-cross"
        assert wf_data["num_windows"] == 2
        assert len(wf_data["windows"]) == 2
        assert wf_data["overall_test_return"] == 0.14
        assert wf_data["overfit_ratio"] == 0.72
        assert wf_data["data_source"] == "tencent"

        # 验证 windows 内容
        w0 = wf_data["windows"][0]
        assert w0["window"] == "W1"
        assert w0["train_sharpe"] == 1.35
        assert w0["test_sharpe"] == 0.95
        assert w0["best_params"] == {"ma_fast": 10, "ma_slow": 30}

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_walk_forward_custom_params(self, mock_engine_cls):
        """带自定义窗口参数"""
        instance = mock_engine_cls.return_value
        instance.walk_forward.return_value = self._MOCK_WF_RESULT

        resp = client.post(
            "/api/v1/backtest/walk-forward",
            json={
                "ts_code": "000333.SZ",
                "strategy": "ma-cross",
                "start_date": "2025-01-05",
                "end_date": "2026-02-28",
                "train_days": 126,
                "test_days": 42,
                "step_days": 42,
            },
        )

        assert resp.status_code == 200
        # 验证 walk_forward 参数
        instance.walk_forward.assert_called_once()
        call_kwargs = instance.walk_forward.call_args.kwargs
        assert call_kwargs["train_days"] == 126
        assert call_kwargs["test_days"] == 42
        assert call_kwargs["step_days"] == 42

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_walk_forward_error_response(self, mock_engine_cls):
        """引擎返回 error → success=False"""
        instance = mock_engine_cls.return_value
        instance.walk_forward.return_value = {"error": "无数据", "windows": []}

        resp = client.post(
            "/api/v1/backtest/walk-forward",
            json={
                "ts_code": "000333.SZ",
                "start_date": "2025-01-05",
                "end_date": "2026-02-28",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "error" in data

    def test_walk_forward_missing_ts_code(self):
        """缺少股票代码 → success=False"""
        resp = client.post(
            "/api/v1/backtest/walk-forward",
            json={"start_date": "2025-01-05", "end_date": "2026-02-28"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_walk_forward_missing_dates(self):
        """缺少日期 → success=False"""
        resp = client.post(
            "/api/v1/backtest/walk-forward",
            json={"ts_code": "000333.SZ"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_walk_forward_invalid_json(self):
        """非法 JSON → 200 + JSON解析错误"""
        resp = client.post(
            "/api/v1/backtest/walk-forward",
            content=b"bad json input",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "JSON" in resp.json()["error"]

    def test_walk_forward_invalid_date(self):
        """无效日期值 → validate_dates 捕获 → success=False"""
        resp = client.post(
            "/api/v1/backtest/walk-forward",
            json={
                "ts_code": "000333.SZ",
                "strategy": "ma-cross",
                "start_date": "2025-13-01",
                "end_date": "2026-02-28",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "日期" in resp.json()["error"]

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_walk_forward_generic_exception(self, mock_engine_cls):
        """引擎异常（非超时）→ 通用错误提示"""
        instance = mock_engine_cls.return_value
        instance.walk_forward.side_effect = RuntimeError("内部错误")

        resp = client.post(
            "/api/v1/backtest/walk-forward",
            json={
                "ts_code": "000333.SZ",
                "strategy": "ma-cross",
                "start_date": "2025-01-05",
                "end_date": "2026-02-28",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "失败" in data["error"]


# ============================================================
#  异步超时保护 (#138)
# ============================================================


class TestAsyncTimeout:
    """超时保护 — 同步调用被 run_in_executor + wait_for 安全包装"""

    @patch("api.backtest_v2.fetch_kline_tencent")
    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_fetch_timeout_propagates_as_error(self, mock_engine_cls, mock_fetch):
        """数据获取超时 → 被 try/except 捕获，返回 success=False"""
        mock_fetch.side_effect = TimeoutError("模拟超时")

        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ts_code": "000333.SZ",
                "start_date": "2026-01-05",
                "end_date": "2026-01-07",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["success"] is False

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_walk_forward_timeout_detection(self, mock_engine_cls):
        """Walk-Forward 超时 → 明确提示超时信息"""
        instance = mock_engine_cls.return_value
        instance.walk_forward.side_effect = TimeoutError("模拟WF超时")

        resp = client.post(
            "/api/v1/backtest/walk-forward",
            json={
                "ts_code": "000333.SZ",
                "strategy": "ma-cross",
                "start_date": "2025-01-05",
                "end_date": "2026-02-28",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "超时" in data["error"]


# ============================================================
#  GET /api/v1/backtest/walk-forward/param-grids  (P2-ARCH-05)
# ============================================================


class TestParamGrids:
    """Walk-Forward 参数网格端点"""

    def test_list_all_param_grids(self):
        """列出所有策略的默认参数网格"""
        resp = client.get("/api/v1/backtest/walk-forward/param-grids")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        grids = data["data"]
        assert "ma-cross" in grids
        assert "breakout" in grids
        assert "rsi" in grids
        assert "macd" in grids
        assert "kdj" in grids
        # 验证 ma-cross 网格结构
        assert grids["ma-cross"]["ma_fast"] == [5, 10, 15, 20]
        assert grids["ma-cross"]["ma_slow"] == [20, 30, 40, 60]
        # 验证 breakout 网格
        assert grids["breakout"]["lookback"] == [10, 15, 20, 30, 40]

    def test_param_grids_filter_by_strategy(self):
        """按策略名筛选参数网格"""
        resp = client.get("/api/v1/backtest/walk-forward/param-grids?strategy=ma-cross")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        grids = data["data"]
        assert "ma-cross" in grids
        assert "breakout" not in grids
        assert grids["ma-cross"]["ma_fast"] == [5, 10, 15, 20]

    def test_param_grids_invalid_strategy(self):
        """策略不存在 → success=False"""
        resp = client.get("/api/v1/backtest/walk-forward/param-grids?strategy=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "未知策略" in data["error"]

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_walk_forward_with_custom_param_grid(self, mock_engine_cls):
        """Walk-Forward 传入自定义参数网格"""
        mock_result = {
            "windows": [
                {
                    "train_start": "20250105",
                    "train_end": "20250630",
                    "test_start": "20250701",
                    "test_end": "20250815",
                    "best_params": {"ma_fast": 5, "ma_slow": 20},
                    "train_sharpe": 1.2,
                    "test_sharpe": 0.9,
                    "train_return": 0.10,
                    "test_return": 0.07,
                    "test_max_dd": -0.02,
                },
            ],
            "overall_test_return": 0.07,
            "overfit_ratio": 0.75,
        }
        instance = mock_engine_cls.return_value
        instance.walk_forward.return_value = mock_result

        custom_grid = {"ma_fast": [3, 5, 8], "ma_slow": [15, 25, 35]}
        resp = client.post(
            "/api/v1/backtest/walk-forward",
            json={
                "ts_code": "000333.SZ",
                "strategy": "ma-cross",
                "start_date": "2025-01-05",
                "end_date": "2026-02-28",
                "param_grid": custom_grid,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        # 验证 param_grid 传递到 engine.walk_forward
        instance.walk_forward.assert_called_once()
        call_kwargs = instance.walk_forward.call_args.kwargs
        assert call_kwargs["param_grid"] == custom_grid

    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_walk_forward_without_param_grid_uses_default(self, mock_engine_cls):
        """不传 param_grid → walk_forward 得到 None（引擎内部用默认）"""
        mock_result = {
            "windows": [
                {
                    "train_start": "20250105",
                    "train_end": "20250630",
                    "test_start": "20250701",
                    "test_end": "20250815",
                    "best_params": {},
                    "train_sharpe": 0,
                    "test_sharpe": 0,
                    "train_return": 0,
                    "test_return": 0,
                    "test_max_dd": 0,
                }
            ],
            "overall_test_return": 0.0,
            "overfit_ratio": 0.0,
        }
        instance = mock_engine_cls.return_value
        instance.walk_forward.return_value = mock_result

        resp = client.post(
            "/api/v1/backtest/walk-forward",
            json={
                "ts_code": "000333.SZ",
                "strategy": "ma-cross",
                "start_date": "2025-01-05",
                "end_date": "2026-02-28",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        # 不传 param_grid 时，param_grid=None
        instance.walk_forward.assert_called_once()
        call_kwargs = instance.walk_forward.call_args.kwargs
        assert call_kwargs["param_grid"] is None
