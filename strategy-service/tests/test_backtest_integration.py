"""
回测 API 集成测试 (#139) — 全链路 DB persistence 层

覆盖（mock persistence，不依赖真实数据库）：
- POST /run → backtest_id（持久化成功）
- POST /run → DB 不可用时降级，不阻塞回测
- GET /{id} → 返回正确的持久化内容（含 metrics/curves）
- GET /{id} → 不存在记录时返回 error
- GET / → 返回历史列表
- GET / → DB 降级时返回空列表
"""

from unittest.mock import MagicMock, patch
import uuid

from api.backtest_v2 import router
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

# 预导入 backtest_repo 模块，确保 @patch 在 CI 环境也能正确找到目标
import repositories.backtest_repo  # noqa: F401 — 确保 patch 目标模块已加载

# ============================================================
#  测试应用（与 test_backtest_api_v2.py 相同的 setup）
# ============================================================

app = FastAPI()
app.include_router(router, prefix="/api/v1/backtest")
client = TestClient(app)

# ============================================================
#  Mock 数据
# ============================================================

_MOCK_BT_ID = "550e8400-e29b-41d4-a716-446655440000"

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
    """创建模拟 BacktestResult（与 test_backtest_api_v2.py 一致）"""
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
    result.winning_trades = overrides.get("winning_trades", 10)
    result.losing_trades = overrides.get("losing_trades", 5)
    result.avg_hold_days = overrides.get("avg_hold_days", 5)
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


# get_backtest_result / get_backtest_history 的模拟返回值
# 模拟 _result_to_dict 输出的结构（含 backtest_details 供路由展开）
_MOCK_RESULT_DICT = {
    "backtest_id": _MOCK_BT_ID,
    "strategy_name": "ma-cross",
    "strategy_version": "2.0",
    "ts_code": "000333.SZ",
    "start_date": "2026-01-05",
    "end_date": "2026-01-07",
    "initial_cash": 100000.0,
    "final_value": 115600.0,
    "total_return": 0.156,
    "annual_return": 0.08,
    "sharpe_ratio": 1.25,
    "max_drawdown": -0.05,
    "win_rate": 0.65,
    "profit_loss_ratio": 2.1,
    "total_trades": 15,
    "winning_trades": 10,
    "losing_trades": 5,
    "avg_holding_days": 5.2,
    "created_at": "2026-06-15T12:00:00",
    "backtest_details": {
        "equity_curve": [
            {"date": "20260105", "nav": 1.0, "benchmark_nav": 1.0, "drawdown": 0.0},
        ],
        "benchmark_curve": [],
        "drawdown_curve": [],
        "monthly_returns": [],
        "trades": [],
        "alpha": 0.02,
        "beta": 0.9,
        "volatility": 0.15,
        "calmar_ratio": 1.6,
        "sortino_ratio": 1.8,
    },
}


# ============================================================
#  集成测试 — 回测执行 + DB 持久化全链路
# ============================================================


class TestBacktestIntegration:
    """全链路集成测试 — mock persistence 层验证执行→持久化→读取完整流"""

    # ----------------------------------------------------------
    #  POST /run — DB 持久化
    # ----------------------------------------------------------

    @patch("api.backtest_v2._persistence.save", return_value=None)
    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_persistence_graceful_degrade(self, mock_engine_cls, mock_save):
        """DB 不可用时，回测仍成功但 data 中无 backtest_id"""
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()

        resp = client.post(
            "/api/v1/backtest/run",
            json={"ts_code": "000333.SZ", "start_date": "2026-01-05", "end_date": "2026-01-07"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        # DB 不可用时不写 backtest_id，但回测结果正常返回
        assert "backtest_id" not in data["data"]
        assert data["data"]["metrics"]["total_return"] == 0.156

    @patch("api.backtest_v2._persistence.save", return_value=_MOCK_BT_ID)
    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_run_persists_and_returns_backtest_id(self, mock_engine_cls, mock_save):
        """POST /run → 持久化成功 → backtest_id 出现在 response"""
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()

        resp = client.post(
            "/api/v1/backtest/run",
            json={"ts_code": "000333.SZ", "start_date": "2026-01-05", "end_date": "2026-01-07"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["backtest_id"] == _MOCK_BT_ID

        # 验证 _persistence.save 被调用，且传入了正确的策略数据
        mock_save.assert_called_once()
        save_args = mock_save.call_args[0]
        assert len(save_args) >= 6
        assert save_args[0] == "ma-cross"  # strategy
        assert save_args[1] == "000333.SZ"  # ts_code
        assert save_args[3] == "20260107"  # end_date
        assert save_args[4] == 100000.0  # initial_cash

    # ----------------------------------------------------------
    #  GET /{backtest_id} — 查询详情
    # ----------------------------------------------------------

    @patch("repositories.backtest_repo.get_backtest_result_with_details")
    @patch("api.backtest_v2._persistence.save")
    @patch("api.backtest_v2.EnhancedBacktestEngine")
    def test_get_detail_returns_persisted_data(
        self,
        mock_engine_cls,
        mock_save,
        mock_get_detail,
    ):
        """POST /run → GET /{id} 返回正确展开的详情（含 metrics/curves）"""
        # 持久化 mock — 返回 known backtest_id
        mock_engine_cls.fetch_kline_tencent.return_value = _MOCK_KLINE
        instance = mock_engine_cls.return_value
        instance.run.return_value = _make_mock_result()
        mock_save.return_value = _MOCK_BT_ID

        # GET 详情 mock — 返回 DB 中的完整记录
        mock_get_detail.return_value = _MOCK_RESULT_DICT

        # POST /run 拿到 backtest_id
        resp = client.post(
            "/api/v1/backtest/run",
            json={"ts_code": "000333.SZ", "start_date": "2026-01-05", "end_date": "2026-01-07"},
        )
        bt_id = resp.json()["data"]["backtest_id"]

        # GET /{id} 验证展开后的内容
        resp = client.get(f"/api/v1/backtest/{bt_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["success"] is True

        d = detail["data"]
        assert d["backtest_id"] == _MOCK_BT_ID
        assert d["strategy_name"] == "ma-cross"
        assert d["ts_code"] == "000333.SZ"
        assert d["initial_cash"] == 100000.0

        # metrics 展开
        assert "metrics" in d
        assert d["metrics"]["total_return"] == 0.156
        assert d["metrics"]["sharpe"] == 1.25
        assert d["metrics"]["max_drawdown"] == -0.05
        assert d["metrics"]["trade_count"] == 15

        # curves 展开
        assert "equity_curve" in d
        assert "trades" in d
        assert "benchmark_curve" in d
        assert len(d["equity_curve"]) > 0
        assert d["equity_curve"][0]["nav"] == 1.0
        assert d["equity_curve"][0]["date"] == "20260105"

    @patch("repositories.backtest_repo.get_backtest_result_with_details")
    def test_get_detail_not_found(self, mock_get_detail):
        """GET /{id} 不存在的记录 → success=False + 错误提示"""
        mock_get_detail.return_value = None

        resp = client.get(f"/api/v1/backtest/{_MOCK_BT_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "不存在" in data["error"]

    # ----------------------------------------------------------
    #  GET / — 历史列表
    # ----------------------------------------------------------

    @patch("repositories.backtest_repo.get_backtest_history")
    def test_list_with_persisted_data(self, mock_get_history):
        """GET / → 返回正确的历史列表"""
        mock_get_history.return_value = [
            {**_MOCK_RESULT_DICT, "backtest_id": _MOCK_BT_ID},
            {**_MOCK_RESULT_DICT, "backtest_id": str(uuid.uuid4()), "strategy_name": "breakout"},
        ]

        resp = client.get("/api/v1/backtest/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["total"] == 2
        assert data["data"]["backtests"][0]["backtest_id"] == _MOCK_BT_ID
        assert data["data"]["backtests"][1]["strategy_name"] == "breakout"

    @patch("repositories.backtest_repo.get_backtest_history")
    def test_list_empty_when_no_data(self, mock_get_history):
        """GET / → 无数据 → 空列表"""
        mock_get_history.return_value = []

        resp = client.get("/api/v1/backtest/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["backtests"] == []
        assert data["data"]["total"] == 0

    @patch("repositories.backtest_repo.get_backtest_history", side_effect=Exception("DB断连"))
    def test_list_graceful_degrade_on_db_error(self, mock_get_history):
        """GET / → DB 异常 → 不报错，返回空列表"""
        resp = client.get("/api/v1/backtest/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["backtests"] == []
        assert data["data"]["total"] == 0

    # ----------------------------------------------------------
    #  GET /{backtest_id} — DB 降级
    # ----------------------------------------------------------

    @patch("api.backtest_v2.get_db_session", side_effect=Exception("DB断连"))
    def test_get_detail_graceful_degrade_on_db_error(self, mock_db_session):
        """GET /{id} → DB 异常 → success=False + 通用错误提示
        （通过 patch get_db_session 而非 repo 函数，避免 CI 上局部 import 的 mock 失效问题）
        """
        resp = client.get(f"/api/v1/backtest/{_MOCK_BT_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "失败" in data["error"]
