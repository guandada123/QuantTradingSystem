"""
risk_controller.py 单元测试 — 目标覆盖率达 85%+

测试策略：
1. CircuitBreaker — 纯逻辑 + patch datetime
2. _build_result — 纯函数
3. check_stop_loss / check_take_profit — 纯计算
4. check_trade_risk — 旧接口兼容，纯字典参数
5. pre_trade_check — mock SQLAlchemy Session + feishu_alert
6. monitor_positions — mock DB + feishu_alert + PositionManager + settings
7. log_risk_event / get_risk_events — mock DB 写入和查询
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

# ─── Mock 工具（移植自 test_api_risk.py，避免跨文件依赖） ──────


class MockRow:
    """模拟 SQLAlchemy 行对象"""

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def values(self):
        return self._data.values()


class MockResult:
    """模拟查询结果"""

    def __init__(self, rows=None, row=None, rowcount=0):
        self._rows = rows or []
        self._row = row
        self.rowcount = rowcount

    def mappings(self):
        return self

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


def make_mock_db(account_data=None, position_data=None, events_data=None):
    """创建风控测试专用 Mock DB"""
    db = MagicMock()

    default_account = MockRow(
        {
            "total_assets": 1000000.0,
            "available_cash": 500000.0,
            "market_value": 200000.0,
            "day_profit_loss": None,
        }
    )

    def execute_side_effect(stmt, params=None):
        sql = str(stmt.text) if hasattr(stmt, "text") else str(stmt)

        # 账户查询（含 day_profit_loss）
        if "FROM accounts" in sql:
            if account_data:
                return MockResult(row=MockRow(account_data))
            return MockResult(row=default_account)

        # 单只持仓查询（WHERE ts_code — 检查 WHERE ts_code 避免 SELECT 子句误匹配）
        if "FROM positions" in sql and "WHERE ts_code" in sql:
            req_tc = params.get("tc") if params else None
            if position_data and req_tc == position_data.get("ts_code"):
                return MockResult(row=MockRow(position_data))
            return MockResult(row=None)

        # 批量持仓查询
        if "FROM positions" in sql:
            if position_data:
                return MockResult(rows=[MockRow(position_data)])
            return MockResult(rows=[])

        # 风险事件查询
        if "FROM risk_events" in sql:
            if events_data:
                return MockResult(rows=[MockRow(e) for e in events_data])
            return MockResult(rows=[])

        # 写操作
        if "INSERT" in sql or "UPDATE" in sql or "DELETE" in sql:
            return MockResult(rowcount=1)

        return MockResult()

    db.execute.side_effect = execute_side_effect
    db.commit = MagicMock()
    db.close = MagicMock()
    return db


# ─── 默认数据 ────────────────────────────────────────────────────

DEFAULT_ACCOUNT = {
    "total_assets": 1000000.0,
    "available_cash": 500000.0,
    "market_value": 200000.0,
    "day_profit_loss": None,
}

DEFAULT_POSITION = {
    "ts_code": "000001.SZ",
    "total_quantity": 1000,
    "available_quantity": 1000,
    "market_value": 13500.0,
    "cost_price": 12.0,
    "current_price": 13.5,
}


# ====================================================================
#  CircuitBreaker 纯逻辑测试
# ====================================================================


class TestCircuitBreaker:
    """CircuitBreaker — 连续止损熔断器（需 mock datetime）"""

    # ── record_loss / record_profit ────────────────────────────

    # ── record_loss / record_profit ────────────────────────────

    def test_record_loss_below_threshold(self):
        """连续亏损未达阈值：不触发熔断，计数递增"""
        from services.risk_controller import CircuitBreaker

        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb.record_loss()
        assert cb._consecutive_losses == 1
        assert cb._is_open is False
        assert cb.is_allowed() is True

    def test_record_loss_hits_threshold(self):
        """连续亏损达到阈值：触发熔断，记录 opened_at"""
        from services.risk_controller import CircuitBreaker

        with patch("services.risk_controller.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 18, 10, 0, 0)
            cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
            cb.record_loss()
            cb.record_loss()
            cb.record_loss()
            assert cb._is_open is True
            assert cb._opened_at == datetime(2026, 6, 18, 10, 0, 0)
            assert cb.is_allowed() is False

    def test_record_profit_resets_counter(self):
        """盈利一笔重置连续亏损计数"""
        from services.risk_controller import CircuitBreaker

        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb.record_loss()
        cb.record_loss()
        cb.record_profit()
        assert cb._consecutive_losses == 0
        assert cb.is_allowed() is True

    # ── is_allowed ────────────────────────────────────────────

    def test_is_allowed_not_open(self):
        """未熔断：允许交易"""
        from services.risk_controller import CircuitBreaker

        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        assert cb.is_allowed() is True

    def test_is_allowed_opened_at_none(self):
        """熔断但 opened_at=None 时安全返回 True（防御 None 解包）"""
        from services.risk_controller import CircuitBreaker

        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb._is_open = True
        cb._opened_at = None
        assert cb.is_allowed() is True

    def test_is_allowed_cooldown_active(self):
        """熔断中且冷却尚未到期：禁止交易"""
        from services.risk_controller import CircuitBreaker

        with patch("services.risk_controller.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 18, 10, 0, 0)
            cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
            cb.record_loss()
            cb.record_loss()
            cb.record_loss()
            # 只过了 10 分钟
            mock_dt.now.return_value = datetime(2026, 6, 18, 10, 10, 0)
            assert cb.is_allowed() is False

    def test_is_allowed_cooldown_expired(self):
        """冷却期到期：自动恢复交易，重置计数器"""
        from services.risk_controller import CircuitBreaker

        with patch("services.risk_controller.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 18, 10, 0, 0)
            cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
            cb.record_loss()
            cb.record_loss()
            cb.record_loss()
            assert cb._is_open is True

            # 过了 35 分钟 → 冷却到期
            mock_dt.now.return_value = datetime(2026, 6, 18, 10, 35, 0)
            assert cb.is_allowed() is True
            assert cb._is_open is False
            assert cb._consecutive_losses == 0

    # ── reset ────────────────────────────────────────────────

    def test_reset(self):
        """手动重置：清除所有状态"""
        from services.risk_controller import CircuitBreaker

        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb._is_open = True
        cb._consecutive_losses = 5
        cb._opened_at = datetime(2026, 6, 18, 10, 0, 0)
        cb.reset()
        assert cb._is_open is False
        assert cb._consecutive_losses == 0
        assert cb._opened_at is None

    # ── status ───────────────────────────────────────────────

    def test_status_not_open(self):
        """未熔断时 status 显示冷却剩余为 0"""
        from services.risk_controller import CircuitBreaker

        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        s = cb.status
        assert s["is_open"] is False
        assert s["consecutive_losses"] == 0
        assert s["opened_at"] is None
        assert s["cooldown_remaining_minutes"] == 0

    def test_status_open_full_cooldown(self):
        """刚触发熔断：冷却剩余为完整 cooldown_minutes"""
        from services.risk_controller import CircuitBreaker

        with patch("services.risk_controller.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 18, 10, 0, 0)
            cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
            cb._is_open = True
            cb._opened_at = datetime(2026, 6, 18, 10, 0, 0)
            s = cb.status
            assert s["is_open"] is True
            assert s["cooldown_remaining_minutes"] == 30.0

    def test_status_cooldown_partial(self):
        """冷却进行中：剩余时间递减"""
        from services.risk_controller import CircuitBreaker

        with patch("services.risk_controller.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 18, 10, 15, 0)
            cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
            cb._is_open = True
            cb._opened_at = datetime(2026, 6, 18, 10, 0, 0)
            s = cb.status
            assert s["cooldown_remaining_minutes"] == 15.0

    def test_status_no_opened_at_returns_zero_remaining(self):
        """熔断中但 opened_at=None：冷却剩余返回 0（防御）"""
        from services.risk_controller import CircuitBreaker

        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb._is_open = True
        cb._opened_at = None
        s = cb.status
        assert s["cooldown_remaining_minutes"] == 0


# ====================================================================
#  RiskController — 纯函数测试
# ====================================================================


class TestRiskControllerBuildResult:
    """_build_result — 纯逻辑"""

    def test_no_risks(self):
        from services.risk_controller import RiskController

        rc = RiskController()
        result = rc._build_result([])
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"
        assert result["risks"] == []
        assert result["recommendation"] == "PASS"
        assert "timestamp" in result

    def test_single_risk(self):
        from services.risk_controller import RiskController

        rc = RiskController()
        result = rc._build_result(["资金不足"])
        assert result["allowed"] is True
        assert result["risk_level"] == "MEDIUM"
        assert result["risks"] == ["资金不足"]
        assert result["recommendation"] == "PASS"

    def test_multiple_risks(self):
        from services.risk_controller import RiskController

        rc = RiskController()
        result = rc._build_result(["资金不足", "仓位超标"])
        assert result["allowed"] is False
        assert result["risk_level"] == "HIGH"
        assert result["risks"] == ["资金不足", "仓位超标"]
        assert result["recommendation"] == "BLOCK"


class TestRiskControllerCheckStopLoss:
    """check_stop_loss — 纯计算"""

    def test_triggered(self):
        from services.risk_controller import RiskController

        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=10.0, current_price=9.0)
        assert result["triggered"] is True
        assert result["action"] == "STOP_LOSS"
        assert result["ts_code"] == "000001.SZ"
        assert result["loss_ratio"] == pytest.approx(0.1)

    def test_not_triggered(self):
        from services.risk_controller import RiskController

        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=10.0, current_price=9.5)
        assert result["triggered"] is False
        assert result["action"] == "HOLD"

    def test_cost_price_zero_no_trigger(self):
        """cost_price=0 时不会触发止损（除零保护）"""
        from services.risk_controller import RiskController

        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=0, current_price=9.0)
        assert result["triggered"] is False

    def test_exact_threshold_no_trigger(self):
        """精确等于止损阈值不触发（不等号 <）"""
        from services.risk_controller import RiskController

        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=100.0, current_price=92.0)
        assert result["triggered"] is False

    def test_barely_above_threshold(self):
        """略高于阈值（-7.99%）不触发"""
        from services.risk_controller import RiskController

        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=100.0, current_price=92.01)
        assert result["triggered"] is False


class TestRiskControllerCheckTakeProfit:
    """check_take_profit — 纯计算"""

    def test_triggered(self):
        from services.risk_controller import RiskController

        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=10.0, current_price=14.0)
        assert result["triggered"] is True
        assert result["action"] == "TAKE_PROFIT"
        assert result["ts_code"] == "000001.SZ"
        assert result["profit_ratio"] == pytest.approx(0.4)

    def test_not_triggered(self):
        from services.risk_controller import RiskController

        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=10.0, current_price=12.0)
        assert result["triggered"] is False
        assert result["action"] == "HOLD"

    def test_cost_price_zero_no_trigger(self):
        from services.risk_controller import RiskController

        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=0, current_price=14.0)
        assert result["triggered"] is False

    def test_exact_threshold_no_trigger(self):
        from services.risk_controller import RiskController

        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=100.0, current_price=130.0)
        assert result["triggered"] is False

    def test_barely_above_threshold_triggers(self):
        from services.risk_controller import RiskController

        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=100.0, current_price=130.01)
        assert result["triggered"] is True


# ====================================================================
#  RiskController — check_trade_risk（兼容旧接口）
# ====================================================================


class TestRiskControllerCheckTradeRisk:
    """check_trade_risk — 纯字典参数，仅 datetime.now() 用于 timestamp"""

    def test_buy_pass(self):
        from services.risk_controller import RiskController

        rc = RiskController(max_position_ratio=0.30, max_total_positions=3)
        account_info = {
            "total_assets": 100000,
            "positions": {"000001.SZ": {"market_value": 10000}},
            "total_positions": 1,
        }
        result = rc.check_trade_risk("000001.SZ", "BUY", 100, account_info)
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"

    def test_buy_position_ratio_exceeded(self):
        from services.risk_controller import RiskController

        rc = RiskController(max_position_ratio=0.30)
        account_info = {
            "total_assets": 100000,
            "positions": {"000001.SZ": {"market_value": 50000}},
            "total_positions": 1,
        }
        result = rc.check_trade_risk("000001.SZ", "BUY", 100, account_info)
        assert result["allowed"] is True  # 1 个风险 → MEDIUM
        assert result["risk_level"] == "MEDIUM"
        assert len(result["risks"]) == 1

    def test_buy_new_stock_position_limit_exceeded(self):
        """买入新股票时持仓数量超标 → MEDIUM"""
        from services.risk_controller import RiskController

        rc = RiskController(max_position_ratio=0.30, max_total_positions=2)
        account_info = {
            "total_assets": 100000,
            "positions": {
                "000001.SZ": {"market_value": 20000},
                "000002.SZ": {"market_value": 20000},
            },
            "total_positions": 2,
        }
        result = rc.check_trade_risk("000003.SH", "BUY", 100, account_info)
        assert result["allowed"] is True  # 1 个风险 → MEDIUM
        assert result["risk_level"] == "MEDIUM"
        assert len(result["risks"]) == 1

    def test_not_buy_skip_checks(self):
        """非 BUY 操作跳过检查"""
        from services.risk_controller import RiskController

        rc = RiskController(max_position_ratio=0.30)
        account_info = {"total_assets": 100000, "positions": {}, "total_positions": 0}
        result = rc.check_trade_risk("000001.SZ", "SELL", 100, account_info)
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"

    def test_empty_account_info(self):
        from services.risk_controller import RiskController

        rc = RiskController(max_position_ratio=0.30, max_total_positions=3)
        account_info = {"total_assets": 0, "positions": {}, "total_positions": 0}
        result = rc.check_trade_risk("000001.SZ", "BUY", 100, account_info)
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"

    def test_existing_position_not_counted(self):
        """已有持仓的股票不重复计入持仓数量限制"""
        from services.risk_controller import RiskController

        rc = RiskController(max_position_ratio=0.30, max_total_positions=1)
        account_info = {
            "total_assets": 100000,
            "positions": {"000001.SZ": {"market_value": 10000}},
            "total_positions": 1,
        }
        result = rc.check_trade_risk("000001.SZ", "BUY", 100, account_info)
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"  # 已有持仓不占新位置


# ====================================================================
#  RiskController — pre_trade_check（需 mock DB + feishu_alert）
# ====================================================================


class TestRiskControllerPreTradeCheck:
    """pre_trade_check — mock SQLAlchemy + 可选 feishu_alert"""

    def test_no_db(self):
        """db=None 时直接返回 PASS"""
        from services.risk_controller import RiskController

        rc = RiskController(db=None)
        result = rc.pre_trade_check("000001.SZ", "BUY", 100, 12.5)
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"

    def test_account_not_found(self):
        """账户不存在时返回 MEDIUM 风险"""
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.fetchone.return_value = None
        from services.risk_controller import RiskController

        rc = RiskController(db=mock_db)
        result = rc.pre_trade_check("000001.SZ", "BUY", 100, 12.5)
        assert result["allowed"] is True
        assert result["risk_level"] == "MEDIUM"
        assert any("不存在" in r for r in result["risks"])

    def test_buy_success(self):
        """买入 — 所有检查通过"""
        db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=None)
        from services.risk_controller import RiskController

        rc = RiskController(db=db)
        result = rc.pre_trade_check("000001.SZ", "BUY", 100, 12.5)
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"

    def test_buy_insufficient_funds(self):
        """买入 — 资金不足"""
        account_data = dict(DEFAULT_ACCOUNT, available_cash=500)
        db = make_mock_db(account_data=account_data, position_data=None)
        from services.risk_controller import RiskController

        rc = RiskController(db=db)
        result = rc.pre_trade_check("000001.SZ", "BUY", 1000, 12.5)
        assert result["allowed"] is True
        assert result["risk_level"] == "MEDIUM"
        assert any("资金不足" in r for r in result["risks"])

    def test_buy_position_ratio_exceeded(self):
        """买入 — 仓位比例超标（已有持仓 + 新买入超限）"""
        account_data = dict(DEFAULT_ACCOUNT, total_assets=100000, available_cash=50000)
        position_data = {
            "ts_code": "000001.SZ",
            "total_quantity": 500,
            "available_quantity": 500,
            "market_value": 6000.0,
            "cost_price": 12.0,
            "current_price": 12.0,
        }
        db = make_mock_db(account_data=account_data, position_data=position_data)
        from services.risk_controller import RiskController

        rc = RiskController(db=db, max_position_ratio=0.30)
        # 已有 6000, 买入 5000*10=50000 → 总额=56000/100000=56% > 30%
        result = rc.pre_trade_check("000001.SZ", "BUY", 5000, 10.0)
        assert result["allowed"] is True
        assert result["risk_level"] == "MEDIUM"
        assert any("仓位" in r for r in result["risks"])

    def test_buy_position_limit_exceeded(self):
        """买入 — 持仓数量超标"""
        account_data = dict(DEFAULT_ACCOUNT, total_assets=1000000, available_cash=500000)
        # 已有 3 个持仓
        mock_db = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()

        called = [0]

        def execute_side(stmt, params=None):
            sql = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
            called[0] += 1
            if "FROM accounts" in sql:
                return MockResult(row=MockRow(account_data))
            if "FROM positions" in sql and "WHERE" in sql:
                return MockResult(row=None)  # 新股票，无对应持仓
            if "FROM positions" in sql:
                # 返回 3 只持仓
                return MockResult(
                    rows=[
                        MockRow(
                            {
                                "ts_code": "600519.SH",
                                "total_quantity": 100,
                                "market_value": 180000,
                                "cost_price": 1800,
                                "current_price": 1800,
                            }
                        ),
                        MockRow(
                            {
                                "ts_code": "000001.SZ",
                                "total_quantity": 500,
                                "market_value": 6750,
                                "cost_price": 12,
                                "current_price": 13.5,
                            }
                        ),
                        MockRow(
                            {
                                "ts_code": "601318.SH",
                                "total_quantity": 200,
                                "market_value": 90000,
                                "cost_price": 45,
                                "current_price": 45,
                            }
                        ),
                    ]
                )
            if "INSERT" in sql or "UPDATE" in sql or "DELETE" in sql:
                return MockResult(rowcount=1)
            return MockResult()

        mock_db.execute.side_effect = execute_side

        from services.risk_controller import RiskController

        rc = RiskController(db=mock_db, max_total_positions=3)
        # 新股票 300001.SZ 不在现有持仓中 → 超过 max_total_positions=3
        result = rc.pre_trade_check("300001.SZ", "BUY", 100, 30.0)
        assert result["allowed"] is True
        assert result["risk_level"] == "MEDIUM"
        assert any("持仓数量" in r for r in result["risks"])

    def test_sell_insufficient_position(self):
        """卖出 — 持仓不足"""
        account_data = dict(DEFAULT_ACCOUNT, available_cash=500000)
        position_data = {
            "ts_code": "000001.SZ",
            "total_quantity": 1000,
            "available_quantity": 100,
            "market_value": 13500,
            "cost_price": 12,
            "current_price": 13.5,
        }
        db = make_mock_db(account_data=account_data, position_data=position_data)
        from services.risk_controller import RiskController

        rc = RiskController(db=db)
        # 请求卖出 500 股，但 available_quantity=100
        result = rc.pre_trade_check("000001.SZ", "SELL", 500, 13.5)
        assert result["allowed"] is True
        assert result["risk_level"] == "MEDIUM"
        assert any("持仓不足" in r for r in result["risks"])

    def test_sell_position_not_found(self):
        """卖出 — 股票无持仓记录"""
        db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=None)
        from services.risk_controller import RiskController

        rc = RiskController(db=db)
        result = rc.pre_trade_check("999999.SZ", "SELL", 100, 10.0)
        assert result["allowed"] is True
        assert result["risk_level"] == "MEDIUM"
        assert any("持仓不足" in r for r in result["risks"])

    def test_daily_loss_exceeded(self):
        """当日亏损超标"""
        account_data = dict(DEFAULT_ACCOUNT, day_profit_loss=-100000.0)  # 10%亏损
        db = make_mock_db(account_data=account_data, position_data=None)
        from services.risk_controller import RiskController

        rc = RiskController(db=db, max_daily_loss=0.05)
        result = rc.pre_trade_check("000001.SZ", "BUY", 100, 12.5)
        assert result["allowed"] is True
        assert result["risk_level"] == "MEDIUM"
        assert any("亏损" in r for r in result["risks"])

    def test_daily_loss_within_limit(self):
        """当日亏损在范围内"""
        account_data = dict(DEFAULT_ACCOUNT, day_profit_loss=-10000.0)  # 1%亏损 < 5%
        db = make_mock_db(account_data=account_data, position_data=None)
        from services.risk_controller import RiskController

        rc = RiskController(db=db, max_daily_loss=0.05)
        result = rc.pre_trade_check("000001.SZ", "BUY", 100, 12.5)
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"

    def test_buy_two_risks_blocked(self):
        """两个及以上风险 → HIGH → BLOCK，触发风控告警"""
        account_data = dict(
            DEFAULT_ACCOUNT, total_assets=100000, available_cash=500, day_profit_loss=-100000.0
        )
        position_data = {
            "ts_code": "000001.SZ",
            "total_quantity": 500,
            "available_quantity": 500,
            "market_value": 6000.0,
            "cost_price": 12.0,
            "current_price": 12.0,
        }
        db = make_mock_db(account_data=account_data, position_data=position_data)

        mock_feishu = MagicMock()
        mock_feishu.get_alert_service.return_value.send_risk_triggered.return_value = None

        from services.risk_controller import RiskController

        with patch.dict("sys.modules", {"services.feishu_alert": mock_feishu}):
            rc = RiskController(db=db, max_position_ratio=0.30, max_daily_loss=0.05)
            result = rc.pre_trade_check("000001.SZ", "BUY", 5000, 10.0)
            assert result["allowed"] is False
            assert result["risk_level"] == "HIGH"
            assert len(result["risks"]) >= 2

    def test_feishu_alert_exception_handled(self):
        """飞书告警异常不冒泡"""
        account_data = dict(
            DEFAULT_ACCOUNT, total_assets=100000, available_cash=500, day_profit_loss=-100000.0
        )
        position_data = {
            "ts_code": "000001.SZ",
            "total_quantity": 500,
            "available_quantity": 500,
            "market_value": 6000.0,
            "cost_price": 12.0,
            "current_price": 12.0,
        }
        db = make_mock_db(account_data=account_data, position_data=position_data)

        mock_feishu = MagicMock()
        mock_feishu.get_alert_service.side_effect = RuntimeError("feishu down")

        from services.risk_controller import RiskController

        with patch.dict("sys.modules", {"services.feishu_alert": mock_feishu}):
            rc = RiskController(db=db, max_position_ratio=0.30, max_daily_loss=0.05)
            # 即使飞书告警抛出异常，pre_trade_check 仍应正常返回结果
            result = rc.pre_trade_check("000001.SZ", "BUY", 5000, 10.0)
            assert result["allowed"] is False
            assert result["risk_level"] == "HIGH"


# ====================================================================
#  RiskController — log_risk_event / get_risk_events
# ====================================================================


class TestRiskControllerLogAndGetEvents:
    """log_risk_event / get_risk_events — DB 写入和查询"""

    def test_log_no_db(self):
        """无 DB 时只打日志不报错"""
        from services.risk_controller import RiskController

        rc = RiskController(db=None)
        rc.log_risk_event("STOP_LOSS", "HIGH", ts_code="000001.SZ", description="止损触发")
        # 不应抛出异常

    def test_log_with_db(self):
        """有 DB 时写入 risk_events 表并 commit"""
        db = make_mock_db()
        from services.risk_controller import RiskController

        rc = RiskController(db=db)
        rc.log_risk_event(
            "STOP_LOSS",
            "HIGH",
            ts_code="000001.SZ",
            description="止损触发",
            threshold_value=0.08,
            actual_value=0.1,
            action_taken="AUTO_CLOSE",
        )
        assert db.commit.called

    def test_get_events_no_db(self):
        """无 DB 时返回空列表"""
        from services.risk_controller import RiskController

        rc = RiskController(db=None)
        assert rc.get_risk_events() == []

    def test_get_events_with_db(self):
        """有 DB 时返回查询结果"""
        events_data = [
            {
                "event_type": "STOP_LOSS",
                "severity": "HIGH",
                "ts_code": "000001.SZ",
                "description": "止损触发",
                "action_taken": "AUTO_CLOSE",
                "threshold_value": 0.08,
                "actual_value": 0.1,
                "is_resolved": False,
                "created_at": "2026-06-18T10:00:00",
            },
        ]
        db = make_mock_db(events_data=events_data)
        from services.risk_controller import RiskController

        rc = RiskController(db=db)
        result = rc.get_risk_events(limit=10)
        assert len(result) == 1
        assert result[0]["event_type"] == "STOP_LOSS"
        assert result[0]["severity"] == "HIGH"


# ====================================================================
#  RiskController — monitor_positions（复杂 mock 链）
# ====================================================================


class TestRiskControllerMonitorPositions:
    """monitor_positions — mock DB + feishu_alert + PositionManager + settings"""

    def test_no_db(self):
        """db=None 时返回空结果 dict"""
        from services.risk_controller import RiskController

        rc = RiskController(db=None)
        result = rc.monitor_positions()
        assert result == {"alerts": [], "executed": [], "total_alerts": 0, "total_executed": 0}

    def test_no_positions(self):
        """无持仓时直接返回"""
        db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=None)
        from services.risk_controller import RiskController

        rc = RiskController(db=db)
        result = rc.monitor_positions()
        assert result["total_alerts"] == 0

    def test_stop_loss_triggered_no_auto_execute(self):
        """止损触发但 AUTO_EXECUTE_STOP_LOSS=False：只报警不自动平仓"""
        settings_patch = patch("services.risk_controller.settings")
        feishu_patch = patch.dict("sys.modules", {"services.feishu_alert": MagicMock()})

        with settings_patch as mock_settings, feishu_patch:
            mock_settings.AUTO_EXECUTE_STOP_LOSS = False
            mock_settings.AUTO_EXECUTE_TAKE_PROFIT = False

            # 建一个亏损的持仓（成本10，现价8.5 → -15% > 8% 止损）
            pos = {
                "ts_code": "000001.SZ",
                "total_quantity": 1000,
                "available_quantity": 1000,
                "market_value": 8500,
                "cost_price": 10.0,
                "current_price": 8.5,
            }
            db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=pos)
            from services.risk_controller import RiskController

            rc = RiskController(db=db)
            result = rc.monitor_positions()
            assert result["total_alerts"] == 1
            assert result["total_executed"] == 0
            assert result["alerts"][0]["action"] == "STOP_LOSS"

    def test_stop_loss_triggered_with_auto_execute(self):
        """止损触发 + AUTO_EXECUTE_STOP_LOSS=True：自动平仓"""
        settings_patch = patch("services.risk_controller.settings")
        feishu_patch = patch.dict("sys.modules", {"services.feishu_alert": MagicMock()})

        with settings_patch as mock_settings, feishu_patch:
            mock_settings.AUTO_EXECUTE_STOP_LOSS = True
            mock_settings.AUTO_EXECUTE_TAKE_PROFIT = False

            pos = {
                "ts_code": "000001.SZ",
                "total_quantity": 1000,
                "available_quantity": 1000,
                "market_value": 8500,
                "cost_price": 10.0,
                "current_price": 8.5,
            }
            db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=pos)

            # 模拟 close_position 成功（懒导入，patch 源模块而非导入方）
            position_manager_patch = patch(
                "services.position_manager.PositionManager",
                **{
                    "return_value.close_position.return_value": {
                        "success": True,
                        "profit_loss": -1500.0,
                    }
                },
            )

            with position_manager_patch:
                from services.risk_controller import RiskController

                rc = RiskController(db=db)
                result = rc.monitor_positions()
                assert result["total_alerts"] == 1
                assert result["total_executed"] == 1
                assert result["executed"][0]["action"] == "STOP_LOSS_EXECUTED"

    def test_stop_loss_auto_execute_fails(self):
        """止损自动平仓失败时记录错误但不抛异常"""
        settings_patch = patch("services.risk_controller.settings")
        feishu_patch = patch.dict("sys.modules", {"services.feishu_alert": MagicMock()})

        with settings_patch as mock_settings, feishu_patch:
            mock_settings.AUTO_EXECUTE_STOP_LOSS = True
            mock_settings.AUTO_EXECUTE_TAKE_PROFIT = False

            pos = {
                "ts_code": "000001.SZ",
                "total_quantity": 1000,
                "available_quantity": 1000,
                "market_value": 8500,
                "cost_price": 10.0,
                "current_price": 8.5,
            }
            db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=pos)

            # close_position 返回失败
            position_manager_patch = patch(
                "services.position_manager.PositionManager",
                **{
                    "return_value.close_position.return_value": {
                        "success": False,
                        "error": "order rejected",
                    }
                },
            )

            with position_manager_patch:
                from services.risk_controller import RiskController

                rc = RiskController(db=db)
                result = rc.monitor_positions()
                assert result["total_alerts"] == 1
                assert result["total_executed"] == 0  # 执行失败

    def test_stop_loss_auto_execute_raises_exception(self):
        """止损自动平仓抛出异常时被捕获"""
        settings_patch = patch("services.risk_controller.settings")
        feishu_patch = patch.dict("sys.modules", {"services.feishu_alert": MagicMock()})

        with settings_patch as mock_settings, feishu_patch:
            mock_settings.AUTO_EXECUTE_STOP_LOSS = True
            mock_settings.AUTO_EXECUTE_TAKE_PROFIT = False

            pos = {
                "ts_code": "000001.SZ",
                "total_quantity": 1000,
                "available_quantity": 1000,
                "market_value": 8500,
                "cost_price": 10.0,
                "current_price": 8.5,
            }
            db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=pos)

            position_manager_patch = patch(
                "services.position_manager.PositionManager",
                **{"return_value.close_position.side_effect": RuntimeError("API timeout")},
            )

            with position_manager_patch:
                from services.risk_controller import RiskController

                rc = RiskController(db=db)
                result = rc.monitor_positions()
                assert result["total_alerts"] == 1
                assert result["total_executed"] == 0

    def test_take_profit_triggered_with_auto_execute(self):
        """止盈触发 + AUTO_EXECUTE_TAKE_PROFIT=True：自动平仓"""
        settings_patch = patch("services.risk_controller.settings")
        feishu_patch = patch.dict("sys.modules", {"services.feishu_alert": MagicMock()})

        with settings_patch as mock_settings, feishu_patch:
            mock_settings.AUTO_EXECUTE_STOP_LOSS = False
            mock_settings.AUTO_EXECUTE_TAKE_PROFIT = True

            # 盈利持仓（成本10，现价14 → +40% > 30% 止盈）
            pos = {
                "ts_code": "000001.SZ",
                "total_quantity": 1000,
                "available_quantity": 1000,
                "market_value": 14000,
                "cost_price": 10.0,
                "current_price": 14.0,
            }
            db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=pos)

            position_manager_patch = patch(
                "services.position_manager.PositionManager",
                **{
                    "return_value.close_position.return_value": {
                        "success": True,
                        "profit_loss": 4000.0,
                    }
                },
            )

            with position_manager_patch:
                from services.risk_controller import RiskController

                rc = RiskController(db=db)
                result = rc.monitor_positions()
                assert result["total_alerts"] == 1
                assert result["total_executed"] == 1
                assert result["executed"][0]["action"] == "TAKE_PROFIT_EXECUTED"

    def test_take_profit_no_auto_execute(self):
        """止盈触发但 AUTO_EXECUTE_TAKE_PROFIT=False：只报警"""
        settings_patch = patch("services.risk_controller.settings")
        feishu_patch = patch.dict("sys.modules", {"services.feishu_alert": MagicMock()})

        with settings_patch as mock_settings, feishu_patch:
            mock_settings.AUTO_EXECUTE_STOP_LOSS = False
            mock_settings.AUTO_EXECUTE_TAKE_PROFIT = False

            pos = {
                "ts_code": "000001.SZ",
                "total_quantity": 1000,
                "available_quantity": 1000,
                "market_value": 14000,
                "cost_price": 10.0,
                "current_price": 14.0,
            }
            db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=pos)

            from services.risk_controller import RiskController

            rc = RiskController(db=db)
            result = rc.monitor_positions()
            assert result["total_alerts"] == 1
            assert result["total_executed"] == 0

    def test_stop_loss_feishu_alert_exception(self):
        """止损飞书告警异常被捕获"""
        settings_patch = patch("services.risk_controller.settings")
        feishu_patch = patch.dict(
            "sys.modules",
            {
                "services.feishu_alert": MagicMock(
                    get_alert_service=MagicMock(side_effect=Exception("feishu alert error"))
                )
            },
        )

        with settings_patch as mock_settings, feishu_patch:
            mock_settings.AUTO_EXECUTE_STOP_LOSS = False

            pos = {
                "ts_code": "000001.SZ",
                "total_quantity": 1000,
                "available_quantity": 1000,
                "market_value": 8500,
                "cost_price": 10.0,
                "current_price": 8.5,
            }
            db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=pos)

            from services.risk_controller import RiskController

            rc = RiskController(db=db)
            # 飞书告警异常不应该阻止止损检查的结果
            result = rc.monitor_positions()
            assert result["total_alerts"] == 1

    def test_no_alerts_for_normal_position(self):
        """正常持仓不触发任何告警"""
        settings_patch = patch("services.risk_controller.settings")
        feishu_patch = patch.dict("sys.modules", {"services.feishu_alert": MagicMock()})

        with settings_patch, feishu_patch:
            # 正常持仓（成本10，现价11：+10% < 30% 止盈，-9.1% > -8% 不触发止损）
            pos = {
                "ts_code": "000001.SZ",
                "total_quantity": 1000,
                "available_quantity": 1000,
                "market_value": 11000,
                "cost_price": 10.0,
                "current_price": 11.0,
            }
            db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=pos)

            from services.risk_controller import RiskController

            rc = RiskController(db=db)
            result = rc.monitor_positions()
            assert result["total_alerts"] == 0

    def test_current_price_none_falls_back_to_cost(self):
        """current_price=None 时回退到 cost_price，不触发告警"""
        settings_patch = patch("services.risk_controller.settings")
        feishu_patch = patch.dict("sys.modules", {"services.feishu_alert": MagicMock()})

        with settings_patch, feishu_patch:
            pos = {
                "ts_code": "000001.SZ",
                "total_quantity": 1000,
                "available_quantity": 1000,
                "market_value": None,
                "cost_price": 10.0,
                "current_price": None,
            }
            db = make_mock_db(account_data=DEFAULT_ACCOUNT, position_data=pos)

            from services.risk_controller import RiskController

            rc = RiskController(db=db)
            # current_price=None → 回退到 cost_price=10，波动=0，不触发
            result = rc.monitor_positions()
            assert result["total_alerts"] == 0
