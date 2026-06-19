"""
策略市场 API 路由测试

覆盖：
- GET  /api/v1/strategies/              — 策略列表
- GET  /api/v1/strategies/ranking       — 排行榜
- GET  /api/v1/strategies/{id}          — 策略详情
- POST /api/v1/strategies/              — 创建策略
- POST /api/v1/strategies/compare       — 对比回测
- PUT  /api/v1/strategies/{id}          — 更新策略
- DELETE /api/v1/strategies/{id}        — 删除策略
- POST /api/v1/strategies/{id}/backtest — 回测指定策略
- 404 / 400 / 500 错误处理
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from api.strategies import router
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

# ============================================================
#  测试应用
# ============================================================

app = FastAPI()
app.include_router(router, prefix="/api/v1/strategies")
client = TestClient(app)


# ============================================================
#  Mock 数据
# ============================================================

_MOCK_STRATEGIES = [
    {
        "id": "ma-cross",
        "name": "双均线金叉",
        "type": "builtin",
        "description": "短期均线上穿长期均线时买入",
        "status": "active",
        "params": {"ma_fast": 5, "ma_slow": 20},
    },
    {
        "id": "breakout",
        "name": "突破策略",
        "type": "builtin",
        "description": "价格突破近期高点时买入",
        "status": "active",
        "params": {"lookback": 20},
    },
    {
        "id": "rsi",
        "name": "RSI 超买超卖",
        "type": "builtin",
        "description": "RSI 低于30超买，高于70超卖",
        "status": "active",
        "params": {"period": 14, "oversold": 30, "overbought": 70},
    },
]

_MOCK_RANKING = sorted(_MOCK_STRATEGIES, key=lambda s: s["id"])  # 模拟排序


# ============================================================
#  GET /api/v1/strategies/
# ============================================================


class TestListStrategies:
    """策略列表"""

    @patch("services.strategy_market.strategy_market")
    def test_list_without_filter(self, mock_market):
        """不加过滤时返回所有策略"""
        mock_market.list_strategies.return_value = _MOCK_STRATEGIES

        resp = client.get("/api/v1/strategies/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 3
        assert data["total"] == 3

    @patch("services.strategy_market.strategy_market")
    def test_list_with_type_filter(self, mock_market):
        """按类型过滤"""
        builtin = [s for s in _MOCK_STRATEGIES if s["type"] == "builtin"]
        mock_market.list_strategies.return_value = builtin

        resp = client.get("/api/v1/strategies/?type=builtin")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 3

        mock_market.list_strategies.assert_called_with(type_filter="builtin", status="active")

    @patch("services.strategy_market.strategy_market")
    def test_list_with_status_filter(self, mock_market):
        """按状态过滤"""
        mock_market.list_strategies.return_value = []

        resp = client.get("/api/v1/strategies/?status=draft")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        mock_market.list_strategies.assert_called_with(type_filter=None, status="draft")


# ============================================================
#  GET /api/v1/strategies/ranking
# ============================================================


class TestStrategyRanking:
    """策略排行榜"""

    @patch("services.strategy_market.strategy_market")
    def test_ranking_default_metric(self, mock_market):
        """默认按 sharpe 排序"""
        mock_market.get_ranking.return_value = _MOCK_RANKING

        resp = client.get("/api/v1/strategies/ranking")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert len(resp.json()["data"]) == 3

    @patch("services.strategy_market.strategy_market")
    def test_ranking_custom_metric(self, mock_market):
        """自定义排序指标"""
        mock_market.get_ranking.return_value = []

        resp = client.get("/api/v1/strategies/ranking?metric=total_return")
        assert resp.status_code == 200
        mock_market.get_ranking.assert_called_with(metric="total_return")


# ============================================================
#  GET /api/v1/strategies/{strategy_id}
# ============================================================


class TestGetStrategy:
    """策略详情"""

    @patch("services.strategy_market.strategy_market")
    def test_get_existing(self, mock_market):
        """获取已存在的策略"""
        mock_market.get_strategy.return_value = _MOCK_STRATEGIES[0]

        resp = client.get("/api/v1/strategies/ma-cross")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["id"] == "ma-cross"
        assert data["name"] == "双均线金叉"

    @patch("services.strategy_market.strategy_market")
    def test_get_not_found(self, mock_market):
        """不存在的策略 → 404"""
        mock_market.get_strategy.return_value = None

        resp = client.get("/api/v1/strategies/non-existent")
        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    @patch("services.strategy_market.strategy_market")
    def test_get_invalid_id(self, mock_market):
        """空 ID → 由 FastAPI 路由匹配处理"""
        mock_market.get_strategy.return_value = None

        resp = client.get("/api/v1/strategies/")
        # 会匹配到 list_strategies 而非 get_strategy
        assert resp.status_code == 200


# ============================================================
#  POST /api/v1/strategies/
# ============================================================


class TestCreateStrategy:
    """创建策略"""

    @patch("services.strategy_market.strategy_market")
    def test_create_success(self, mock_market):
        """成功创建"""
        new_strategy = {
            "id": "custom-001",
            "name": "自定义策略",
            "type": "custom",
            "description": "我的自定义策略",
            "status": "active",
            "params": {"ma_fast": 10, "ma_slow": 30},
        }
        mock_market.create_strategy.return_value = new_strategy

        resp = client.post(
            "/api/v1/strategies/",
            json={
                "name": "自定义策略",
                "description": "我的自定义策略",
                "params": {"ma_fast": 10, "ma_slow": 30},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["data"]["id"] == "custom-001"

    @patch("services.strategy_market.strategy_market")
    def test_create_missing_name(self, mock_market):
        """缺少 name → Pydantic 校验失败 → 422"""
        resp = client.post(
            "/api/v1/strategies/",
            json={"params": {}},
        )
        assert resp.status_code == 422

    @patch("services.strategy_market.strategy_market")
    def test_create_service_error(self, mock_market):
        """服务层异常 → 400"""
        mock_market.create_strategy.side_effect = ValueError("策略名称已存在")

        resp = client.post(
            "/api/v1/strategies/",
            json={"name": "重复策略"},
        )
        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]


# ============================================================
#  POST /api/v1/strategies/compare
# ============================================================


class TestCompareStrategies:
    """多策略对比"""

    @patch("services.strategy_market.strategy_market")
    def test_compare_success(self, mock_market):
        """对比成功"""
        mock_market.compare_strategies.return_value = {
            "strategies": [
                {"id": "ma-cross", "sharpe": 1.2, "total_return": 0.15},
                {"id": "breakout", "sharpe": 0.9, "total_return": 0.10},
            ],
            "ts_code": "000001",
        }

        resp = client.post(
            "/api/v1/strategies/compare",
            json={"strategy_ids": ["ma-cross", "breakout"], "ts_code": "000001"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert len(resp.json()["data"]["strategies"]) == 2

    @patch("services.strategy_market.strategy_market")
    def test_compare_empty_ids(self, mock_market):
        """空 ID 列表 → 传给服务层处理（当前不做 min_length 校验）"""
        mock_market.compare_strategies.return_value = {"strategies": [], "ts_code": "000001"}

        resp = client.post(
            "/api/v1/strategies/compare",
            json={"strategy_ids": [], "ts_code": "000001"},
        )
        assert resp.status_code == 200
        mock_market.compare_strategies.assert_called_with([], "000001")

    @patch("services.strategy_market.strategy_market")
    def test_compare_service_error(self, mock_market):
        """服务层异常 → 500"""
        mock_market.compare_strategies.side_effect = Exception("对比服务不可用")

        resp = client.post(
            "/api/v1/strategies/compare",
            json={"strategy_ids": ["ma-cross", "breakout"]},
        )
        assert resp.status_code == 500


# ============================================================
#  PUT /api/v1/strategies/{strategy_id}
# ============================================================


class TestUpdateStrategy:
    """更新策略"""

    @patch("services.strategy_market.strategy_market")
    def test_update_success(self, mock_market):
        """成功更新"""
        mock_market.update_strategy.return_value = {
            "id": "custom-001",
            "name": "新名称",
            "description": "更新后的描述",
            "status": "active",
        }

        resp = client.put(
            "/api/v1/strategies/custom-001",
            json={"name": "新名称", "description": "更新后的描述"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["data"]["name"] == "新名称"

    @patch("services.strategy_market.strategy_market")
    def test_update_not_found(self, mock_market):
        """不存在的策略 → 404"""
        mock_market.update_strategy.return_value = None

        resp = client.put(
            "/api/v1/strategies/non-existent",
            json={"name": "新名称"},
        )
        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]


# ============================================================
#  DELETE /api/v1/strategies/{strategy_id}
# ============================================================


class TestDeleteStrategy:
    """删除策略"""

    @patch("services.strategy_market.strategy_market")
    def test_delete_success(self, mock_market):
        """成功删除"""
        mock_market.delete_strategy.return_value = True

        resp = client.delete("/api/v1/strategies/custom-001")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "已删除" in resp.json()["message"]

    @patch("services.strategy_market.strategy_market")
    def test_delete_not_found(self, mock_market):
        """不存在的策略 → 404"""
        mock_market.delete_strategy.return_value = False

        resp = client.delete("/api/v1/strategies/non-existent")
        assert resp.status_code == 404

    @patch("services.strategy_market.strategy_market")
    def test_delete_builtin_forbidden(self, mock_market):
        """内置策略不可删除 → 403"""
        mock_market.delete_strategy.side_effect = ValueError("内置策略不可删除")

        resp = client.delete("/api/v1/strategies/ma-cross")
        assert resp.status_code == 403
        assert "不可删除" in resp.json()["detail"]


# ============================================================
#  POST /api/v1/strategies/{strategy_id}/backtest
# ============================================================


class TestBacktestStrategy:
    """回测指定策略"""

    @patch("services.strategy_market.strategy_market")
    def test_backtest_success(self, mock_market):
        """回测成功"""
        mock_market.backtest_strategy.return_value = {
            "strategy_id": "ma-cross",
            "ts_code": "000001",
            "sharpe": 1.25,
            "total_return": 0.156,
            "total_trades": 15,
        }

        resp = client.post("/api/v1/strategies/ma-cross/backtest?ts_code=000001")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["data"]["sharpe"] == 1.25

    @patch("services.strategy_market.strategy_market")
    def test_backtest_default_ts_code(self, mock_market):
        """默认 ts_code=000001"""
        mock_market.backtest_strategy.return_value = {}

        resp = client.post("/api/v1/strategies/ma-cross/backtest")
        assert resp.status_code == 200
        mock_market.backtest_strategy.assert_called_with("ma-cross", "000001")

    @patch("services.strategy_market.strategy_market")
    def test_backtest_strategy_not_found(self, mock_market):
        """策略不存在 → 404"""
        mock_market.backtest_strategy.side_effect = ValueError("策略不存在")

        resp = client.post("/api/v1/strategies/non-existent/backtest")
        assert resp.status_code == 404

    @patch("services.strategy_market.strategy_market")
    def test_backtest_service_error(self, mock_market):
        """执行异常 → 500"""
        mock_market.backtest_strategy.side_effect = Exception("数据获取失败")

        resp = client.post("/api/v1/strategies/ma-cross/backtest")
        assert resp.status_code == 500
