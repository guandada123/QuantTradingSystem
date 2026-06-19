"""
RiskController 核心行为契约测试 v1.0

验证 RiskController 的独立方法行为契约：
1. TestBuildResultContract — 风控结果级别判定逻辑 (_build_result)
2. TestStopLossContract — 止损检查 (check_stop_loss)
3. TestTakeProfitContract — 止盈检查 (check_take_profit)
4. TestTradeRiskContract — 交易风险检查 (check_trade_risk)
5. TestPreTradeCheckContract — 交易前风控检查无DB (pre_trade_check)
6. TestResultFormatContract — 返回值格式一致性

不依赖任何外部服务，直接测试 services.risk_controller.RiskController 的纯逻辑方法。
"""

from datetime import datetime

import pytest

from services.risk_controller import RiskController


# =========================================================================
# 1. 风控结果级别判定合约
# =========================================================================


class TestBuildResultContract:
    """契约：_build_result 根据风险数量判定级别"""

    def test_zero_risks_low(self):
        """0 个风险 → LOW，允许交易"""
        rc = RiskController()
        result = rc._build_result([])
        assert result["risk_level"] == "LOW"
        assert result["allowed"] is True
        assert result["recommendation"] == "PASS"
        assert result["risks"] == []

    def test_one_risk_medium(self):
        """1 个风险 → MEDIUM，仍允许交易"""
        rc = RiskController()
        result = rc._build_result(["资金不足"])
        assert result["risk_level"] == "MEDIUM"
        assert result["allowed"] is True
        assert result["recommendation"] == "PASS"
        assert result["risks"] == ["资金不足"]

    def test_two_risks_high(self):
        """2 个风险 → HIGH，交易被禁止"""
        rc = RiskController()
        result = rc._build_result(["资金不足", "仓位超标"])
        assert result["risk_level"] == "HIGH"
        assert result["allowed"] is False
        assert result["recommendation"] == "BLOCK"
        assert len(result["risks"]) == 2

    def test_many_risks_high(self):
        """3+ 个风险仍为 HIGH"""
        rc = RiskController()
        result = rc._build_result(["a", "b", "c"])
        assert result["risk_level"] == "HIGH"
        assert result["allowed"] is False

    def test_empty_risks_preserves_list_type(self):
        """空风险列表返回空列表（非 None）"""
        rc = RiskController()
        result = rc._build_result([])
        assert isinstance(result["risks"], list)
        assert len(result["risks"]) == 0

    def test_result_has_timestamp(self):
        """结果包含 ISO 8601 格式时间戳"""
        rc = RiskController()
        result = rc._build_result([])
        assert "timestamp" in result
        # 验证 ISO 8601 格式
        datetime.fromisoformat(result["timestamp"])

    def test_result_structure_contract(self):
        """结果包含全部必需字段且类型正确"""
        rc = RiskController()
        result = rc._build_result([])
        assert set(result.keys()) == {"allowed", "risk_level", "risks", "recommendation", "timestamp"}
        assert isinstance(result["allowed"], bool)
        assert isinstance(result["risk_level"], str)
        assert isinstance(result["recommendation"], str)
        assert isinstance(result["timestamp"], str)


# =========================================================================
# 2. 止损检查合约
# =========================================================================


class TestStopLossContract:
    """契约：check_stop_loss 正确判断止损触发条件"""

    def test_price_above_cost_not_triggered(self):
        """当前价高于成本价 → 不触发"""
        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=10.0, current_price=11.0)
        assert result["triggered"] is False
        assert result["action"] == "HOLD"

    def test_price_equal_cost_not_triggered(self):
        """当前价等于成本价 → 不触发"""
        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=10.0, current_price=10.0)
        assert result["triggered"] is False
        assert result["action"] == "HOLD"

    def test_slight_loss_below_threshold_not_triggered(self):
        """小幅亏损未达阈值 → 不触发（亏 7% < SL 8%）"""
        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=10.0, current_price=9.3)
        assert result["triggered"] is False

    def test_exact_threshold_not_triggered(self):
        """亏损恰好等于阈值 → 不触发（严格小于）
        注：由于浮点精度，(9.2-10)/10=-0.08000000000000007，使用可靠数值验证。
        """
        rc = RiskController(stop_loss_ratio=0.08)
        # loss_ratio ≈ (92.0 - 100.0) / 100.0 ≈ -0.08
        # -0.08（即 stop_loss_ratio）与 loss_ratio 即使浮点误差也接近
        # 用稍高一点的价格确保 loss_ratio 略高于 -0.08
        result = rc.check_stop_loss("000001.SZ", cost_price=100.0, current_price=92.01)
        # loss_ratio = -0.0799，-0.0799 < -0.08 → False
        assert result["triggered"] is False

    def test_loss_exceeds_threshold_triggered(self):
        """亏损超过阈值 → 触发止损"""
        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=10.0, current_price=9.0)
        assert result["triggered"] is True
        assert result["action"] == "STOP_LOSS"
        assert result["ts_code"] == "000001.SZ"
        assert abs(result["loss_ratio"] - 0.1) < 1e-6  # 亏 10%

    def test_triggered_result_format(self):
        """触发时返回完整信息（含 loss_ratio 和 message）"""
        rc = RiskController(stop_loss_ratio=0.05)
        result = rc.check_stop_loss("000001.SZ", cost_price=100.0, current_price=90.0)
        assert set(result.keys()) == {"triggered", "action", "ts_code", "loss_ratio", "message"}
        assert "止损" in result["message"]
        assert "5.0%" in result["message"]

    def test_not_triggered_result_format(self):
        """未触发时返回简洁信息（仅 triggered/action/ts_code）"""
        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=10.0, current_price=10.5)
        assert set(result.keys()) == {"triggered", "action", "ts_code"}
        assert result["action"] == "HOLD"

    def test_zero_cost_price(self):
        """成本价为 0 时返回 HOLD（避免除零）"""
        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=0, current_price=10.0)
        assert result["triggered"] is False
        assert result["action"] == "HOLD"

    def test_custom_stop_loss_ratio(self):
        """自定义止损比例生效"""
        rc = RiskController(stop_loss_ratio=0.15)
        # 亏 10% < SL 15% → 不触发
        result = rc.check_stop_loss("000001.SZ", cost_price=10.0, current_price=9.0)
        assert result["triggered"] is False

        # 亏 20% > SL 15% → 触发
        result = rc.check_stop_loss("000001.SZ", cost_price=10.0, current_price=8.0)
        assert result["triggered"] is True

    def test_extreme_negative_price_triggers(self):
        """极端异常价格（负数）依然按公式计算"""
        rc = RiskController(stop_loss_ratio=0.08)
        # loss_ratio = (-1 - 10) / 10 = -1.1 = -110%
        # -1.1 < -0.08 → True
        result = rc.check_stop_loss("000001.SZ", cost_price=10.0, current_price=-1.0)
        assert result["triggered"] is True

    @pytest.mark.parametrize("current,expected", [
        (10.0, False),    # 不亏
        (9.3, False),     # 亏 7% < 8%
        (9.21, False),    # 亏 7.9% < 8%
        (9.19, True),     # 亏 8.1% > 8%
        (8.0, True),      # 亏 20%
        (5.0, True),      # 亏 50%
    ])
    def test_stop_loss_boundaries(self, current, expected):
        """止损边界值参数化测试 (cost=10, SL=8%)"""
        rc = RiskController(stop_loss_ratio=0.08)
        result = rc.check_stop_loss("000001.SZ", cost_price=10.0, current_price=current)
        assert result["triggered"] is expected, (
            f"cost=10, current={current}: expected triggered={expected}, "
            f"loss_ratio={(current - 10) / 10}"
        )


# =========================================================================
# 3. 止盈检查合约
# =========================================================================


class TestTakeProfitContract:
    """契约：check_take_profit 正确判断止盈触发条件"""

    def test_price_below_cost_not_triggered(self):
        """当前价低于成本价 → 不触发"""
        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=10.0, current_price=9.0)
        assert result["triggered"] is False
        assert result["action"] == "HOLD"

    def test_price_equal_cost_not_triggered(self):
        """当前价等于成本价 → 不触发"""
        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=10.0, current_price=10.0)
        assert result["triggered"] is False

    def test_slight_profit_below_threshold_not_triggered(self):
        """小幅盈利未达阈值 → 不触发（盈 25% < TP 30%）"""
        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=10.0, current_price=12.5)
        assert result["triggered"] is False

    def test_exact_threshold_not_triggered(self):
        """盈利恰好等于阈值 → 不触发（严格大于）"""
        rc = RiskController(take_profit_ratio=0.30)
        # profit_ratio = (13 - 10) / 10 = 0.30
        # 0.30 > 0.30 → False
        result = rc.check_take_profit("000001.SZ", cost_price=10.0, current_price=13.0)
        assert result["triggered"] is False

    def test_profit_exceeds_threshold_triggered(self):
        """盈利超过阈值 → 触发止盈"""
        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=10.0, current_price=14.0)
        assert result["triggered"] is True
        assert result["action"] == "TAKE_PROFIT"
        assert result["ts_code"] == "000001.SZ"
        assert abs(result["profit_ratio"] - 0.4) < 1e-6  # 盈 40%

    def test_triggered_result_format(self):
        """触发时返回完整信息（含 profit_ratio 和 message）"""
        rc = RiskController(take_profit_ratio=0.20)
        result = rc.check_take_profit("000001.SZ", cost_price=100.0, current_price=130.0)
        assert set(result.keys()) == {"triggered", "action", "ts_code", "profit_ratio", "message"}
        assert "止盈" in result["message"]
        assert "20.0%" in result["message"]

    def test_not_triggered_result_format(self):
        """未触发时返回简洁信息（仅 triggered/action/ts_code）"""
        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=10.0, current_price=11.0)
        assert set(result.keys()) == {"triggered", "action", "ts_code"}
        assert result["action"] == "HOLD"

    def test_zero_cost_price(self):
        """成本价为 0 时返回 HOLD（避免除零）"""
        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=0, current_price=10.0)
        assert result["triggered"] is False
        assert result["action"] == "HOLD"

    def test_custom_take_profit_ratio(self):
        """自定义止盈比例生效"""
        rc = RiskController(take_profit_ratio=0.10)
        # 盈 5% < TP 10% → 不触发
        result = rc.check_take_profit("000001.SZ", cost_price=10.0, current_price=10.5)
        assert result["triggered"] is False

        # 盈 15% > TP 10% → 触发
        result = rc.check_take_profit("000001.SZ", cost_price=10.0, current_price=11.5)
        assert result["triggered"] is True

    @pytest.mark.parametrize("current,expected", [
        (10.0, False),     # 不盈
        (12.0, False),     # 盈 20% < 30%
        (13.0, False),     # 盈 30% == 30%（不大于）
        (13.01, True),     # 盈 30.1% > 30%
        (15.0, True),      # 盈 50%
        (20.0, True),      # 盈 100%
    ])
    def test_take_profit_boundaries(self, current, expected):
        """止盈边界值参数化测试 (cost=10, TP=30%)"""
        rc = RiskController(take_profit_ratio=0.30)
        result = rc.check_take_profit("000001.SZ", cost_price=10.0, current_price=current)
        assert result["triggered"] is expected, (
            f"cost=10, current={current}: expected triggered={expected}, "
            f"profit_ratio={(current - 10) / 10}"
        )


# =========================================================================
# 4. 交易风险检查合约
# =========================================================================


class TestTradeRiskContract:
    """契约：check_trade_risk 根据账户信息和交易动作判定风险"""

    def test_buy_no_risk_low(self):
        """买入操作无风险 → LOW"""
        rc = RiskController(max_position_ratio=0.30, max_total_positions=5)
        account_info = {
            "total_assets": 100000,
            "total_positions": 2,
            "positions": {
                "000001.SZ": {"market_value": 10000},
            },
        }
        result = rc.check_trade_risk("000002.SZ", "BUY", 100, account_info)
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"
        assert result["risks"] == []
        assert result["recommendation"] == "PASS"

    def test_buy_position_ratio_exceeded_medium(self):
        """买入操作仓位比例超标 → MEDIUM"""
        rc = RiskController(max_position_ratio=0.20, max_total_positions=5)
        account_info = {
            "total_assets": 100000,
            "total_positions": 2,
            "positions": {
                "000001.SZ": {"market_value": 30000},  # 已占比 30%
            },
        }
        result = rc.check_trade_risk("000001.SZ", "BUY", 100, account_info)
        assert result["allowed"] is True
        assert result["risk_level"] == "MEDIUM"
        assert len(result["risks"]) == 1
        assert "仓位" in result["risks"][0]

    def test_buy_position_count_exceeded_medium(self):
        """买入新股票导致持仓数量超标 → MEDIUM"""
        rc = RiskController(max_position_ratio=0.30, max_total_positions=3)
        account_info = {
            "total_assets": 100000,
            "total_positions": 3,
            "positions": {
                "000001.SZ": {"market_value": 10000},
                "000002.SZ": {"market_value": 10000},
                "000003.SZ": {"market_value": 10000},
            },
        }
        result = rc.check_trade_risk("000004.SZ", "BUY", 100, account_info)
        assert result["allowed"] is True
        assert result["risk_level"] == "MEDIUM"
        assert len(result["risks"]) == 1
        assert "持仓数量" in result["risks"][0]

    def test_buy_ratio_only_single_risk(self):
        """已有持仓比例超标 → 1 个风险（仓位比例），持仓数量检查跳过已有股票"""
        rc = RiskController(max_position_ratio=0.10, max_total_positions=2)
        account_info = {
            "total_assets": 100000,
            "total_positions": 2,  # 已达上限
            "positions": {
                "000001.SZ": {"market_value": 50000},  # 占比 50% > 10%
            },
        }
        # 已有持仓的股票加仓 → 只触发比例检查，持仓数量检查跳过（因为股票已存在）
        result = rc.check_trade_risk("000001.SZ", "BUY", 100, account_info)
        assert result["risk_level"] == "MEDIUM"
        assert len(result["risks"]) == 1
        assert "仓位" in result["risks"][0]

    def test_buy_count_only_single_risk(self):
        """新股票达到持仓上限 → 1 个风险（持仓数量），仓位比例检查未触发"""
        rc = RiskController(max_position_ratio=0.30, max_total_positions=2)
        account_info = {
            "total_assets": 100000,
            "total_positions": 2,  # 已达上限
            "positions": {
                "000001.SZ": {"market_value": 10000},
                "000002.SZ": {"market_value": 10000},
            },
        }
        # 新股票（不在持仓中）→ 触发数量检查，但比例不超标
        result = rc.check_trade_risk("000003.SZ", "BUY", 100, account_info)
        assert result["risk_level"] == "MEDIUM"
        assert len(result["risks"]) == 1
        assert "持仓数量" in result["risks"][0]

    def test_highest_risk_level_not_reachable_in_current_code(self):
        """
        【合约备注】在 check_trade_risk 当前实现中，HIGH 级别不可达。
        因为比例检查（需股票已在持仓）和数量检查（需股票不在持仓）
        对同一 ts_code 是互斥的，无法同时触发两个风险。
        此为代码设计观察，非修复。
        """
        rc = RiskController(max_position_ratio=0.10, max_total_positions=2)
        account_info = {
            "total_assets": 100000,
            "total_positions": 2,
            "positions": {
                "000001.SZ": {"market_value": 50000},
            },
        }
        # 比例触发 → 1 risk（股票在持仓）
        r1 = rc.check_trade_risk("000001.SZ", "BUY", 100, account_info)
        assert len(r1["risks"]) == 1  # 比例风险
        # 数量触发 → 1 risk（新股票）
        r2 = rc.check_trade_risk("000003.SZ", "BUY", 100, account_info)
        assert len(r2["risks"]) == 1  # 数量风险
        # 但无法同时触发 2 个风险 → HIGH 不可达
        assert r1["risk_level"] != "HIGH"
        assert r2["risk_level"] != "HIGH"

    def test_sell_no_checks(self):
        """卖出操作不触发仓位/数量检查 → LOW"""
        rc = RiskController(max_position_ratio=0.30, max_total_positions=3)
        account_info = {
            "total_assets": 100000,
            "total_positions": 5,  # 超标但 SELL 不检查
            "positions": {},
        }
        result = rc.check_trade_risk("000001.SZ", "SELL", 100, account_info)
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"
        assert result["risks"] == []

    def test_existing_position_not_counted_as_new(self):
        """加仓已有持仓的股票不触发持仓数量警告"""
        rc = RiskController(max_position_ratio=0.30, max_total_positions=2)
        account_info = {
            "total_assets": 100000,
            "total_positions": 2,
            "positions": {
                "000001.SZ": {"market_value": 10000},
                "000002.SZ": {"market_value": 10000},
            },
        }
        # 加仓已有持仓的 000001.SZ
        result = rc.check_trade_risk("000001.SZ", "BUY", 100, account_info)
        assert result["risk_level"] == "LOW"

    def test_empty_account_info_graceful(self):
        """账户信息为空时降级处理"""
        rc = RiskController(max_position_ratio=0.30, max_total_positions=3)
        result = rc.check_trade_risk("000001.SZ", "BUY", 100, {})
        # total_assets=0 触发除零规避，应无风险或最多一个风险
        assert result["risk_level"] in ("LOW", "MEDIUM")
        assert isinstance(result["allowed"], bool)

    def test_zero_total_assets_no_division_error(self):
        """total_assets=0 时不触发除零错误"""
        rc = RiskController(max_position_ratio=0.30, max_total_positions=3)
        account_info = {
            "total_assets": 0,
            "total_positions": 0,
            "positions": {},
        }
        # 不会抛出 ZeroDivisionError
        result = rc.check_trade_risk("000001.SZ", "BUY", 100, account_info)
        assert isinstance(result["allowed"], bool)

    def test_inline_risk_logic_consistency(self):
        """check_trade_risk 的风险级别判定逻辑与 _build_result 一致"""
        rc = RiskController(max_position_ratio=0.10, max_total_positions=2)
        account_info = {
            "total_assets": 100000,
            "total_positions": 3,
            "positions": {
                "000001.SZ": {"market_value": 50000},
            },
        }
        trade_result = rc.check_trade_risk("000001.SZ", "BUY", 100, account_info)
        # 用 _build_result 验证判定一致性（当前代码会内联复制逻辑而非调用 _build_result）
        build_result = rc._build_result(trade_result["risks"])
        assert trade_result["risk_level"] == build_result["risk_level"]
        assert trade_result["allowed"] == build_result["allowed"]
        assert trade_result["recommendation"] == build_result["recommendation"]

    def test_result_has_timestamp(self):
        """结果包含 ISO 格式时间戳"""
        rc = RiskController()
        account_info = {"total_assets": 100000, "total_positions": 0, "positions": {}}
        result = rc.check_trade_risk("000001.SZ", "BUY", 100, account_info)
        assert "timestamp" in result
        datetime.fromisoformat(result["timestamp"])


# =========================================================================
# 5. 无DB交易前风控检查合约
# =========================================================================


class TestPreTradeCheckContract:
    """契约：pre_trade_check 在无 DB 时不执行风控，直接 PASS"""

    def test_no_db_returns_pass(self):
        """db=None 时所有检查直接 PASS"""
        rc = RiskController(db=None)
        result = rc.pre_trade_check("000001.SZ", "BUY", 100, 12.5)
        assert result["allowed"] is True
        assert result["risk_level"] == "LOW"
        assert result["risks"] == []
        assert result["recommendation"] == "PASS"

    def test_no_db_result_format(self):
        """db=None 的结果包含全部必需字段"""
        rc = RiskController(db=None)
        result = rc.pre_trade_check("000001.SZ", "BUY", 100, 12.5)
        assert set(result.keys()) == {"allowed", "risk_level", "risks", "recommendation", "timestamp"}

    def test_no_db_sell_also_passes(self):
        """db=None 时卖出操作也 PASS"""
        rc = RiskController(db=None)
        result = rc.pre_trade_check("000001.SZ", "SELL", 100, 12.5)
        assert result["allowed"] is True


# =========================================================================
# 6. 返回值格式一致性合约
# =========================================================================


class TestInitContract:
    """契约：新实例参数正确存储"""

    def test_default_parameters_stored(self):
        """默认参数正确存储"""
        rc = RiskController()
        assert rc.max_position_ratio == 0.30
        assert rc.max_total_positions == 3
        assert rc.stop_loss_ratio == 0.08
        assert rc.take_profit_ratio == 0.30
        assert rc.max_daily_loss == 0.05

    def test_custom_parameters_stored(self):
        """自定义参数正确存储"""
        rc = RiskController(
            max_position_ratio=0.50,
            max_total_positions=10,
            stop_loss_ratio=0.10,
            take_profit_ratio=0.50,
            max_daily_loss=0.10,
        )
        assert rc.max_position_ratio == 0.50
        assert rc.max_total_positions == 10
        assert rc.stop_loss_ratio == 0.10
        assert rc.take_profit_ratio == 0.50
        assert rc.max_daily_loss == 0.10

    def test_db_defaults_to_none(self):
        """db 默认为 None"""
        rc = RiskController()
        assert rc.db is None

    def test_account_id_default(self):
        """默认 account_id 为字符串"""
        rc = RiskController()
        assert rc.account_id is not None
        assert isinstance(rc.account_id, str)


class TestResultFormatContract:
    """契约：所有风控方法的返回值格式保持一致"""

    @pytest.fixture
    def rc(self):
        return RiskController(
            max_position_ratio=0.30,
            max_total_positions=5,
            stop_loss_ratio=0.08,
            take_profit_ratio=0.30,
        )

    def test_all_return_dict(self, rc):
        """所有方法的返回值均为 dict"""
        assert isinstance(rc._build_result([]), dict)
        assert isinstance(rc.check_stop_loss("test", 10, 9), dict)
        assert isinstance(rc.check_take_profit("test", 10, 11), dict)
        assert isinstance(
            rc.check_trade_risk(
                "test", "BUY", 100, {"total_assets": 100000, "total_positions": 0, "positions": {}}
            ),
            dict,
        )
        assert isinstance(rc.pre_trade_check("test", "BUY", 100, 10), dict)

    def test_risk_methods_have_ts_code(self, rc):
        """止损/止盈方法包含 ts_code"""
        sl = rc.check_stop_loss("000001.SZ", 10, 9)
        assert sl["ts_code"] == "000001.SZ"
        tp = rc.check_take_profit("000001.SZ", 10, 11)
        assert tp["ts_code"] == "000001.SZ"

    def test_all_have_triggered_field(self, rc):
        """止损/止盈结果含 triggered 字段"""
        sl = rc.check_stop_loss("test", 10, 9)
        assert "triggered" in sl
        tp = rc.check_take_profit("test", 10, 11)
        assert "triggered" in tp

    def test_all_bool_triggered(self, rc):
        """triggered 字段为布尔值"""
        sl = rc.check_stop_loss("test", 10, 9)
        assert isinstance(sl["triggered"], bool)
        tp = rc.check_take_profit("test", 10, 11)
        assert isinstance(tp["triggered"], bool)
