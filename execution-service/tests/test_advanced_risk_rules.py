"""AdvancedRiskChecker 单元测试

改动前 services/advanced_risk_rules.py 覆盖率为 0%（299 语句全未覆盖），
本文件针对 R1–R9 的边界语义建立护栏。

两条硬性隔离要求（否则测试会污染真实数据或静默失效）：
  1. **状态文件**：`AdvancedRiskChecker.__init__` 会读 `advanced_rules_state_path`，
     且 `run_all_checks` 内部 `add_violation` → `save()` 会**写盘**。
     所有用例必须把该路径指向 tmp_path，绝不触碰 repo 内的
     `shared/claw_data/advanced_rules_state.json`。
  2. **配置口径**：断言使用 `RiskConfig` 的真实默认值，不臆造数字；
     需要非默认值时才在用例内显式覆盖并注明原因。

边界口径（改动后统一）：止损「达到即触发」（含等号），与
`RiskController.check_stop_loss` 及 `RiskConfig.stop_loss_hard_pct` 文档一致。
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from services.advanced_risk_rules import (
    AdvancedRiskChecker,
    PortfolioHolding,
    RuleAction,
    RuleCheckResult,
    RuleSeverity,
    RuleStateManager,
    _cli,
    create_portfolio_holding_from_dict,
    extract_live_holdings,
    extract_total_asset,
)

from shared.risk_config import RiskConfig

# ──────────────────── 夹具 ────────────────────


@pytest.fixture
def config(tmp_path) -> RiskConfig:
    """真实默认配置 + 状态文件隔离到 tmp_path。

    RiskConfig 用 default_factory 读取环境变量，因此这里显式传参覆盖状态路径，
    避免直接依赖 `QTS_ADVANCED_RULES_STATE_PATH` 的全局状态。
    """
    return RiskConfig(advanced_rules_state_path=str(tmp_path / "advanced_rules_state.json"))


@pytest.fixture
def checker(config) -> AdvancedRiskChecker:
    return AdvancedRiskChecker(config)


@pytest.fixture
def holding() -> PortfolioHolding:
    """成本 10.00 / 现价 10.00 / 1000 股的常规持仓"""
    return PortfolioHolding(
        code="sh600584",
        name="长电科技",
        shares=1000,
        avg_cost=10.0,
        current_price=10.0,
        buy_date="2026-01-05",
    )


def _set_days_held(checker: AdvancedRiskChecker, symbol: str, days: int) -> None:
    """白盒：直接设定持仓天数（R4 的输入为状态而非持仓字段）"""
    checker.state.state["position_days"][symbol] = {
        "first_buy": "2026-01-01",
        "last_buy": "2026-01-05",
        "days_held": days,
    }


def _set_sell_history(checker: AdvancedRiskChecker, symbol: str, dates: list[str]) -> None:
    """白盒：直接设定卖出历史（record_sell 只能写当天，无法构造历史日期）"""
    checker.state.state["sell_history"][symbol] = [{"date": d, "price": 10.0} for d in dates]


def _days_ago(n: int) -> str:
    """N 个自然日前的日期字符串。

    必须用相对日期：硬编码绝对日期会随运行日漂移
    （写死 2026-01-01 在 2026-10 运行时其实是 282 天前，不是 15 天前）。
    """
    return (date.today() - timedelta(days=n)).isoformat()


# ════════════════════ R1 止损硬化 ════════════════════


class TestR1StopLoss:
    def test_hard_stop_exact_threshold_triggers(self, checker, holding):
        """恰好 -8.00% 触发（含等号）——与 RiskController 对齐后的权威口径"""
        holding.current_price = 10.0 * (1 - 0.08)
        result = checker._check_stop_loss("sh600584", 9.2, holding)

        assert result is not None
        assert result.severity is RuleSeverity.CRITICAL
        assert result.triggered is True
        assert result.details["hard_stop_price"] == 9.2

    def test_hard_stop_just_above_threshold_no_trigger(self, checker, holding):
        """略高于阈值（-7.99%）不触发"""
        assert checker._check_stop_loss("sh600584", 9.201, holding) is None

    def test_hard_stop_below_threshold_triggers(self, checker, holding):
        result = checker._check_stop_loss("sh600584", 9.0, holding)

        assert result is not None
        assert result.details["current_price"] == 9.0
        assert result.details["avg_cost"] == 10.0
        assert result.details["shares"] == 1000
        assert result.details["floating_pnl_pct"] == pytest.approx(-10.0)

    def test_atr_branch_only_is_warning(self, checker, holding):
        """ATR 止损独立触发（未触发硬止损）→ WARNING，不是 CRITICAL。

        ATR 位 = 10.00 - 1.8×0.2 = 9.64，高于硬止损位 9.20，
        因此现价 9.60 只命中 ATR 分支。
        """
        result = checker._check_stop_loss("sh600584", 9.6, holding, {"atr": 0.2})

        assert result is not None
        assert result.severity is RuleSeverity.WARNING
        assert result.details["atr_stop_price"] == pytest.approx(9.64)
        assert "ATR止损" in result.message

    def test_atr_branch_not_triggered(self, checker, holding):
        """低于 ATR 位一点（9.65 > 9.64）→ 两条分支都不触发"""
        assert checker._check_stop_loss("sh600584", 9.65, holding, {"atr": 0.2}) is None

    def test_both_branches_severity_is_critical(self, checker, holding):
        """两条同时触发 → CRITICAL（硬止损优先定级），且 reasons 同时列出"""
        result = checker._check_stop_loss("sh600584", 9.0, holding, {"atr": 0.2})

        assert result is not None
        assert result.severity is RuleSeverity.CRITICAL
        assert "硬止损" in result.message
        assert "ATR止损" in result.message

    def test_atr_missing_falls_back_to_hard_stop_only(self, checker, holding):
        """缺 ATR 时只按硬止损判定，不应崩溃；且 details.atr 为 None"""
        result = checker._check_stop_loss("sh600584", 9.0, holding, {})

        assert result is not None
        assert result.details["atr"] is None
        assert result.details["atr_stop_price"] is None

    def test_zero_avg_cost_does_not_crash(self, checker, holding):
        """零成本保护：avg_cost 缺失/为 0 时返回 None，而不是 ZeroDivisionError"""
        holding.avg_cost = 0.0

        assert checker._check_stop_loss("sh600584", 9.0, holding) is None

    def test_auto_execute_off_action_is_alert_only(self, checker, holding):
        """默认 advanced_rules_auto_execute=False → 只提醒不执行"""
        result = checker._check_stop_loss("sh600584", 9.0, holding)

        assert result is not None
        assert result.action is RuleAction.ALERT_ONLY

    def test_auto_execute_on_action_is_recommend_sell(self, tmp_path, holding):
        config = RiskConfig(
            advanced_rules_state_path=str(tmp_path / "s.json"),
            advanced_rules_auto_execute=True,
        )
        checker = AdvancedRiskChecker(config)

        result = checker._check_stop_loss("sh600584", 9.0, holding)

        assert result is not None
        assert result.action is RuleAction.RECOMMEND_SELL


# ════════════════════ R2 暴跌日冻结（符号约定） ════════════════════


class TestR2FreezeBuy:
    def test_missing_market_data_returns_none(self, checker):
        assert checker._check_freeze_buy("sh600584", 10.0, None) is None
        assert checker._check_freeze_buy("sh600584", 10.0, {}) is None

    def test_stock_drop_exact_threshold_freezes(self, checker):
        """个股恰好跌 7%（带符号 -0.07）触发冻结"""
        result = checker._check_freeze_buy("sh600584", 10.0, {"stock_drop_pct": -0.07})

        assert result is not None
        assert result.severity is RuleSeverity.CRITICAL
        assert "跌幅 7.0%" in result.message

    def test_stock_rise_does_not_freeze(self, checker):
        """🐛 回归护栏：个股**上涨**不得触发暴跌冻结。

        此前用 abs(stock_drop) >= 阈值，导致上涨 ≥7% 也被判为「暴跌」并 CRITICAL 冻结买入。
        """
        result = checker._check_freeze_buy("sh600584", 10.0, {"stock_drop_pct": 0.07})

        assert result is None, "上涨 7% 被误判为暴跌冻结（abs() 回归）"

    def test_stock_limit_up_does_not_freeze(self, checker):
        result = checker._check_freeze_buy("sh600584", 11.0, {"stock_drop_pct": 0.15})

        assert result is None

    def test_stock_drop_just_below_threshold_no_freeze(self, checker):
        assert checker._check_freeze_buy("sh600584", 10.0, {"stock_drop_pct": -0.069}) is None

    def test_sector_drop_boundary_and_rise(self, checker):
        """行业：恰好跌 5% 冻结；上涨 5% 不冻结。

        必须用不同标的：先跑的那个会把标的写入 freeze_list，
        第二个断言就会命中「已冻结」分支而不是暴跌判定分支。
        """
        assert checker._check_freeze_buy("sh000001", 10.0, {"sector_drop_pct": -0.05}) is not None
        assert checker._check_freeze_buy("sh000002", 10.0, {"sector_drop_pct": 0.05}) is None

    def test_limit_ratio_boundary(self, checker):
        """跌停/涨停比恰好 3.0 触发；2.9 不触发"""
        assert checker._check_freeze_buy("sh600000", 10.0, {"limit_down_up_ratio": 3.0}) is not None
        assert checker._check_freeze_buy("sh600001", 10.0, {"limit_down_up_ratio": 2.9}) is None

    def test_already_frozen_reports_warning_without_refreeze(self, checker):
        """已冻结时先返回 WARNING，且不重复写入 freeze_list"""
        checker.state.freeze_buy("sh600584", "暴跌日: 个股跌幅 7.0%")
        assert checker.state.is_frozen("sh600584")

        result = checker._check_freeze_buy("sh600584", 10.0, {"stock_drop_pct": -0.07})

        assert result is not None
        assert result.severity is RuleSeverity.WARNING
        assert "冻结期" in result.message
        assert len(checker.state.state["freeze_list"]) == 1

    def test_freeze_persists_to_state_file(self, config):
        """冻结写入状态文件（readback 校验，而不是只信内存）"""
        checker = AdvancedRiskChecker(config)
        checker._check_freeze_buy("sh600584", 10.0, {"stock_drop_pct": -0.08})

        with open(config.advanced_rules_state_path, encoding="utf-8") as f:
            persisted = json.load(f)

        assert "sh600584" in persisted["freeze_list"]

    def test_empty_market_data_does_not_clear_existing_freeze(self, checker):
        """传空 market_data（日报链路的现状）不得误解冻"""
        checker.state.freeze_buy("sh600584", "暴跌日")

        result = checker._check_freeze_buy("sh600584", 10.0, {})

        assert result is not None
        assert checker.state.is_frozen("sh600584")


# ════════════════════ R3 卖飞冷却 ════════════════════


class TestR3SellCooldown:
    def test_no_history_returns_none(self, checker):
        assert checker._check_sell_cooldown("sh600584") is None

    def test_sold_today_within_cooldown(self, checker):
        checker.state.record_sell("sh600584", 10.0)

        result = checker._check_sell_cooldown("sh600584")

        assert result is not None
        assert result.severity is RuleSeverity.WARNING
        assert result.details["cooldown_days"] == 10

    def test_sold_long_ago_clears_cooldown(self, checker):
        """15 天前卖出、且只卖过 1 次 → 10 天冷却已过"""
        _set_sell_history(checker, "sh600584", [_days_ago(15)])

        assert checker._check_sell_cooldown("sh600584") is None

    def test_second_sell_extends_cooldown_to_20(self, checker):
        """历史卖出 >1 次 → 冷却延长到 sell_cooldown_extended_days（20 天）。

        同样是 15 天前卖出：只卖 1 次不触发、卖过 2 次触发 —— 对照实验。
        """
        _set_sell_history(checker, "sh600584", [_days_ago(15)])
        assert checker._check_sell_cooldown("sh600584") is None

        _set_sell_history(checker, "sh600584", [_days_ago(40), _days_ago(15)])
        result = checker._check_sell_cooldown("sh600584")

        assert result is not None
        assert result.details["cooldown_days"] == 20

    def test_cooldown_boundary_exactly_ten_days(self, checker):
        """恰好 10 天 → 不触发（冷却 10 天，严格小于才拦）"""
        _set_sell_history(checker, "sh600584", [_days_ago(10)])

        assert checker._check_sell_cooldown("sh600584") is None

    def test_cooldown_boundary_nine_days(self, checker):
        _set_sell_history(checker, "sh600584", [_days_ago(9)])

        assert checker._check_sell_cooldown("sh600584") is not None


# ════════════════════ R4 T+3 决策矩阵 ════════════════════


class TestR4T3Decision:
    def test_fewer_than_three_days_returns_none(self, checker, holding):
        _set_days_held(checker, "sh600584", 2)

        assert checker._check_t3_decision("sh600584", 10.0, holding) is None

    def test_profit_locks_30_pct(self, checker, holding):
        _set_days_held(checker, "sh600584", 3)

        result = checker._check_t3_decision("sh600584", 10.5, holding)

        assert result is not None
        assert result.severity is RuleSeverity.INFO
        assert result.details["recommend_sell_pct"] == 30

    def test_light_loss_reduces_50_pct(self, checker, holding):
        """浮亏 ≥3% → CRITICAL，紧急减仓 50%"""
        _set_days_held(checker, "sh600584", 3)

        result = checker._check_t3_decision("sh600584", 9.7, holding)

        assert result is not None
        assert result.severity is RuleSeverity.CRITICAL
        assert result.details["recommend_sell_pct"] == 50

    def test_small_loss_reduces_30_pct(self, checker, holding):
        """浮亏 1%（<= t3_reduce_early_pct=0.0）→ WARNING 减仓 30%"""
        _set_days_held(checker, "sh600584", 3)

        result = checker._check_t3_decision("sh600584", 9.9, holding)

        assert result is not None
        assert result.severity is RuleSeverity.WARNING
        assert result.details["recommend_sell_pct"] == 30

    def test_breakeven_also_reduces_30_pct(self, checker, holding):
        """记录既有行为：t3_reduce_early_pct=0.0 → 平价（浮亏 0.0%）也建议减仓 30%。

        这是配置默认值的直接推论，属策略口径问题（是否过激进）而非代码 bug，
        故此处只固化现状，改动需先回测。
        """
        _set_days_held(checker, "sh600584", 3)

        result = checker._check_t3_decision("sh600584", 10.0, holding)

        assert result is not None
        assert result.severity is RuleSeverity.WARNING

    def test_small_profit_returns_none(self, checker, holding):
        """浮盈 1%（未达 5% 锁利线）→ 不触发"""
        _set_days_held(checker, "sh600584", 3)

        assert checker._check_t3_decision("sh600584", 10.1, holding) is None


class TestRecordBuyDayCounting:
    """🐛 days_held 计数语义：同一天多次买入（加仓）只能计 1 天。

    此前每次 record_buy 都 +1，加仓会让 R4「T+3」提前触发。
    """

    def test_same_day_multiple_buys_count_once(self, checker):
        checker.state.record_buy("sh600584", 10.0)
        checker.state.record_buy("sh600584", 10.1)
        checker.state.record_buy("sh600584", 10.2)

        assert checker.state.get_position_days("sh600584") == 1

    def test_first_buy_sets_both_dates(self, checker):
        checker.state.record_buy("sh600584", 10.0)

        entry = checker.state.state["position_days"]["sh600584"]
        assert entry["days_held"] == 1
        assert entry["first_buy"] == entry["last_buy"]

    def test_legacy_state_without_last_buy_migrates(self, tmp_path):
        """老状态文件无 last_buy 字段时，首次调用应递增一次并补齐字段（不崩溃）"""
        state_path = tmp_path / "legacy.json"
        state_path.write_text(
            json.dumps(
                {"position_days": {"sh600584": {"first_buy": "2026-01-01", "days_held": 2}}}
            ),
            encoding="utf-8",
        )
        manager = RuleStateManager(str(state_path))

        manager.record_buy("sh600584", 10.0)

        entry = manager.state["position_days"]["sh600584"]
        assert entry["days_held"] == 3
        assert entry["last_buy"]

    def test_corrupt_state_file_falls_back_to_default(self, tmp_path):
        """状态文件损坏 → 回落默认状态，而不是抛异常打断整条风控链路"""
        state_path = tmp_path / "broken.json"
        state_path.write_text("{ 这不是合法 JSON", encoding="utf-8")

        manager = RuleStateManager(str(state_path))

        assert manager.state["freeze_list"] == {}
        assert manager.get_position_days("sh600584") == 0


# ════════════════════ R5 高位接刀 ════════════════════


class TestR5DualAccount:
    def test_single_buy_price_returns_none(self, checker, holding):
        holding.buy_prices = [10.0]

        assert checker._check_dual_account("sh600584", holding) is None

    def test_premium_exactly_threshold_does_not_trigger(self, checker, holding):
        """价差恰好 10% 不触发（严格大于）"""
        holding.buy_prices = [10.0, 11.0]

        assert checker._check_dual_account("sh600584", holding) is None

    def test_premium_above_threshold_triggers(self, checker, holding):
        holding.buy_prices = [10.0, 11.5]

        result = checker._check_dual_account("sh600584", holding)

        assert result is not None
        assert result.severity is RuleSeverity.WARNING
        assert result.details["premium_pct"] == pytest.approx(15.0)
        assert result.details["buy_count"] == 2

    def test_config_threshold_takes_effect(self, tmp_path, holding):
        """配置项 dual_account_premium_threshold 生效（此前硬编码 0.10）"""
        config = RiskConfig(
            advanced_rules_state_path=str(tmp_path / "s.json"),
            dual_account_premium_threshold=0.05,
        )
        checker = AdvancedRiskChecker(config)
        holding.buy_prices = [10.0, 10.6]

        assert checker._check_dual_account("sh600584", holding) is not None


# ════════════════════ R6 卖飞保留仓（整手） ════════════════════


class TestR6SellRetention:
    def test_single_lot_cannot_be_retained(self, checker, holding):
        """🐛 回归护栏：100 股持仓按 15% 算出 15 股 → 不足 1 手，不给保留建议。

        此前用 max(1, ...) 会产出「保留 1 股」这一不可下单的数字。
        """
        holding.shares = 100

        result = checker._check_sell_retention("sh600584", holding, 1000.0, 10000.0)

        assert result is None

    def test_retention_is_whole_lot(self, checker, holding):
        """1000 股 × 15% = 150 → 向下取整到 1 手 = 100 股"""
        holding.shares = 1000

        result = checker._check_sell_retention("sh600584", holding, 10000.0, 50000.0)

        assert result is not None
        assert result.details["suggested_retention"] == 100
        assert result.details["suggested_retention"] % 100 == 0

    @pytest.mark.parametrize(
        ("shares", "expected"),
        [
            (600, None),  # 90 股 → 不足 1 手
            (700, 100),  # 105 → 100
            (2000, 300),  # 300 → 300
            (10000, 1500),  # 1500 → 1500
        ],
    )
    def test_retention_rounds_down_to_lot(self, checker, holding, shares, expected):
        holding.shares = shares

        result = checker._check_sell_retention("sh600584", holding, shares * 10.0, 100000.0)

        if expected is None:
            assert result is None
        else:
            assert result is not None
            assert result.details["suggested_retention"] == expected
            assert result.details["suggested_retention"] % 100 == 0

    def test_zero_position_value_returns_none(self, checker, holding):
        assert checker._check_sell_retention("sh600584", holding, 0.0, 50000.0) is None

    def test_zero_total_asset_returns_none(self, checker, holding):
        assert checker._check_sell_retention("sh600584", holding, 10000.0, 0.0) is None

    def test_message_no_longer_claims_trailing_take_profit(self, checker, holding):
        """文案不得再宣称「移动止盈」（实现是成本价锚定的固定止损）"""
        result = checker._check_sell_retention("sh600584", holding, 10000.0, 50000.0)

        assert result is not None
        assert "移动止盈" not in result.message
        assert "固定止损" in result.message

    def test_config_retention_pct_takes_effect(self, tmp_path, holding):
        config = RiskConfig(
            advanced_rules_state_path=str(tmp_path / "s.json"),
            sell_retention_pct=0.20,
        )
        checker = AdvancedRiskChecker(config)

        result = checker._check_sell_retention("sh600584", holding, 10000.0, 50000.0)

        assert result is not None
        assert result.details["suggested_retention"] == 200


# ════════════════════ R7 单票仓位上限 ════════════════════


class TestR7PositionLimit:
    def test_missing_total_asset_skips(self, checker, holding):
        """缺 total_asset → 跳过（不得拿 0 当分母）"""
        assert checker._check_position_limit("sh600584", holding, 10000.0, 0.0) is None

    def test_no_holding_returns_none(self, checker):
        assert checker._check_position_limit("sh600584", None, 10000.0, 100000.0) is None

    def test_ratio_below_warning_band_returns_none(self, checker, holding):
        """仓位 10%（< 15%×0.8=12%）→ 无告警"""
        assert checker._check_position_limit("sh600584", holding, 10000.0, 100000.0) is None

    def test_ratio_in_warning_band_is_info(self, checker, holding):
        """仓位 13%（>12% 且 ≤15%）→ INFO 近上限提醒"""
        result = checker._check_position_limit("sh600584", holding, 13000.0, 100000.0)

        assert result is not None
        assert result.severity is RuleSeverity.INFO
        assert "接近" in result.message

    def test_ratio_exactly_at_limit_is_info_not_warning(self, checker, holding):
        """恰好 15% 不算超限（严格大于），落入近上限 INFO"""
        result = checker._check_position_limit("sh600584", holding, 15000.0, 100000.0)

        assert result is not None
        assert result.severity is RuleSeverity.INFO

    def test_ratio_above_limit_is_warning(self, checker, holding):
        result = checker._check_position_limit("sh600584", holding, 16000.0, 100000.0)

        assert result is not None
        assert result.severity is RuleSeverity.WARNING
        assert result.action is RuleAction.RECOMMEND_REDUCE
        assert result.details["current_ratio"] == pytest.approx(16.0)

    def test_config_limit_takes_effect(self, tmp_path, holding):
        """配置项 max_single_position_ratio 生效（此前硬编码 0.15）"""
        config = RiskConfig(
            advanced_rules_state_path=str(tmp_path / "s.json"),
            max_single_position_ratio=0.10,
        )
        checker = AdvancedRiskChecker(config)

        result = checker._check_position_limit("sh600584", holding, 11000.0, 100000.0)

        assert result is not None
        assert result.severity is RuleSeverity.WARNING

    def test_run_all_checks_triggers_r7_when_context_passed(self, checker, holding):
        """🐛 回归护栏：传入 position_value/total_asset 后，
        run_all_checks 必须真的产出 R7（此前恒因 total_asset=0 提前返回）。
        """
        results = checker.run_all_checks(
            "sh600584",
            10.0,
            holding,
            {},
            position_value=20000.0,
            total_asset=100000.0,
        )

        assert any(r.rule_id == "R7_POSITION_LIMIT" for r in results)

    def test_run_all_checks_skips_r7_without_context(self, checker, holding):
        """不传组合上下文 → R7 不出现（跳过而非误报）"""
        results = checker.run_all_checks("sh600584", 10.0, holding, {})

        assert not any(r.rule_id == "R7_POSITION_LIMIT" for r in results)

    def test_position_value_derived_from_holding(self, checker, holding):
        """未显式传 position_value 时按 股数×现价 推算：1000×10=10000，占比 10% → 不告警"""
        results = checker.run_all_checks("sh600584", 10.0, holding, {}, total_asset=100000.0)

        assert not any(r.rule_id == "R7_POSITION_LIMIT" for r in results)


# ════════════════════ R8 入场区间建议 ════════════════════


class TestR8EntryRange:
    def test_missing_market_data_returns_none(self, checker):
        assert checker._suggest_entry_range("sh600584", 10.0, None) is None
        assert checker._suggest_entry_range("sh600584", 10.0, {}) is None

    def test_missing_price_series_returns_none(self, checker):
        assert checker._suggest_entry_range("sh600584", 10.0, {"ma20": 10.0}) is None

    def test_flat_range_returns_none(self, checker):
        """high == low → 分位无意义，返回 None（除零保护）"""
        market = {"ma20": 10.0, "high_20d": 10.0, "low_20d": 10.0}

        assert checker._suggest_entry_range("sh600584", 10.0, market) is None

    def test_overheated_rsi_warns(self, checker):
        market = {"ma20": 10.0, "high_20d": 12.0, "low_20d": 8.0, "rsi": 75.0}

        result = checker._suggest_entry_range("sh600584", 10.0, market)

        assert result is not None
        assert result.severity is RuleSeverity.WARNING
        assert "过热" in result.rule_name

    def test_low_percentile_suggests_entry(self, checker):
        market = {"ma20": 10.0, "high_20d": 12.0, "low_20d": 8.0, "rsi": 40.0}

        result = checker._suggest_entry_range("sh600584", 8.4, market)

        assert result is not None
        assert result.details["percentile"] == 10
        assert "低位" in result.message

    def test_middle_percentile_returns_none(self, checker):
        market = {"ma20": 10.0, "high_20d": 12.0, "low_20d": 8.0, "rsi": 50.0}

        assert checker._suggest_entry_range("sh600584", 10.0, market) is None

    def test_high_percentile_gives_buy_zones(self, checker):
        market = {"ma20": 10.0, "high_20d": 12.0, "low_20d": 8.0, "rsi": 60.0}

        result = checker._suggest_entry_range("sh600584", 11.5, market)

        assert result is not None
        assert result.details["buy_zone_1"] == 9.7
        assert result.details["buy_zone_2"] == 9.4


# ════════════════════ R9 盈亏比预演 ════════════════════


class TestR9RiskReward:
    def test_missing_target_or_stop_returns_none(self, checker):
        assert checker._check_risk_reward("sh600584", 10.0) is None
        assert checker._check_risk_reward("sh600584", 10.0, None, None, 11.0) is None
        assert checker._check_risk_reward("sh600584", 10.0, None, None, None, 9.5) is None

    def test_invalid_stop_above_entry_is_critical(self, checker):
        result = checker._check_risk_reward("sh600584", 10.0, None, None, 11.0, 10.0)

        assert result is not None
        assert result.severity is RuleSeverity.CRITICAL
        assert "无效" in result.rule_name

    def test_ratio_below_1_2_is_critical(self, checker):
        """盈亏比 1.0:1 → CRITICAL"""
        result = checker._check_risk_reward("sh600584", 10.0, None, None, 10.5, 9.5)

        assert result is not None
        assert result.severity is RuleSeverity.CRITICAL
        assert result.details["rr_ratio"] == pytest.approx(1.0)

    def test_ratio_between_1_2_and_1_8_is_warning(self, checker):
        """盈亏比 1.6:1 → WARNING"""
        result = checker._check_risk_reward("sh600584", 10.0, None, None, 10.8, 9.5)

        assert result is not None
        assert result.severity is RuleSeverity.WARNING
        assert result.details["rr_ratio"] == pytest.approx(1.6)

    def test_ratio_at_threshold_is_info(self, checker):
        """恰好 1.8:1 达标（严格小于才判不足）"""
        result = checker._check_risk_reward("sh600584", 10.0, None, None, 11.8, 9.0)

        assert result is not None
        assert result.severity is RuleSeverity.INFO
        assert "达标" in result.rule_name

    def test_config_threshold_takes_effect(self, tmp_path):
        """配置项 min_risk_reward_ratio 生效（此前硬编码 1.8）"""
        config = RiskConfig(
            advanced_rules_state_path=str(tmp_path / "s.json"),
            min_risk_reward_ratio=2.5,
        )
        checker = AdvancedRiskChecker(config)

        result = checker._check_risk_reward("sh600584", 10.0, None, None, 12.0, 9.0)

        assert result is not None
        # rr = 2.0 < 2.5 → 不足
        assert "达标" not in result.rule_name


# ════════════════════ run_all_checks 编排 ════════════════════


class TestRunAllChecks:
    def test_disabled_returns_empty(self, tmp_path, holding):
        config = RiskConfig(
            advanced_rules_state_path=str(tmp_path / "s.json"),
            advanced_rules_enabled=False,
        )
        checker = AdvancedRiskChecker(config)

        assert checker.run_all_checks("sh600584", 10.0, holding, {}) == []

    def test_results_sorted_by_severity(self, checker, holding):
        """CRITICAL 排在 WARNING 前，WARNING 排在 INFO 前"""
        checker.state.freeze_buy("sh600584", "暴跌日")
        results = checker.run_all_checks(
            "sh600584",
            9.0,
            holding,
            {"atr": 0.2, "stock_drop_pct": -0.08, "limit_down_up_ratio": 5.0},
            position_value=10000.0,
            total_asset=100000.0,
        )

        order = {RuleSeverity.CRITICAL: 0, RuleSeverity.WARNING: 1, RuleSeverity.INFO: 2}
        severities = [order[r.severity] for r in results]
        assert severities == sorted(severities)
        assert len(results) > 1

    def test_violations_recorded_to_state_file(self, config, holding):
        """CRITICAL/WARNING 结果写入 rule_violations 并落盘（readback）"""
        checker = AdvancedRiskChecker(config)

        checker.run_all_checks("sh600584", 9.0, holding, {})

        with open(config.advanced_rules_state_path, encoding="utf-8") as f:
            persisted = json.load(f)

        rule_ids = {v["rule_id"] for v in persisted["rule_violations"]}
        assert "R1_STOP_LOSS" in rule_ids

    def test_violations_capped_at_100(self, checker, holding):
        for i in range(105):
            checker.state.add_violation("R1_STOP_LOSS", f"stock{i}", "x")

        assert len(checker.state.state["rule_violations"]) == 100

    def test_no_holding_skips_position_rules(self, checker):
        """未持仓时 R1/R4/R5 不参与，R2 仍可触发"""
        results = checker.run_all_checks("sh600584", 10.0, None, {"stock_drop_pct": -0.08})

        rule_ids = {r.rule_id for r in results}
        assert "R2_FREEZE_BUY" in rule_ids
        assert "R1_STOP_LOSS" not in rule_ids


# ════════════════════ 飞书卡片 ════════════════════


class TestFeishuCard:
    def test_empty_results_green_card(self, checker):
        card = checker.to_feishu_card([])

        assert card["header"]["template"] == "green"
        assert "无异常" in card["header"]["title"]["content"]

    def test_critical_makes_card_red(self, checker, holding):
        results = checker.run_all_checks("sh600584", 9.0, holding, {})

        card = checker.to_feishu_card(results)

        assert card["header"]["template"] == "red"
        assert "严重" in card["header"]["title"]["content"]

    def test_warning_makes_card_orange(self, checker):
        result = RuleCheckResult(
            rule_id="R3_SELL_COOLDOWN",
            rule_name="卖飞冷却期",
            severity=RuleSeverity.WARNING,
            action=RuleAction.RECOMMEND_FREEZE,
            triggered=True,
            symbol="sh600584",
            message="冷却中",
        )

        card = checker.to_feishu_card([result])

        assert card["header"]["template"] == "orange"

    def test_details_rendered_but_none_filtered(self, checker, holding):
        results = checker.run_all_checks("sh600584", 9.0, holding, {})

        card = checker.to_feishu_card(results)

        contents = [
            el["text"]["content"]
            for el in card["elements"]
            if el.get("tag") == "div" and el.get("text", {}).get("tag") == "lark_md"
        ]
        assert any("current_price" in c for c in contents)
        assert not any("atr_stop_price: None" in c for c in contents)


# ════════════════════ extract_total_asset ════════════════════


class TestExtractTotalAsset:
    def test_live_total_assets(self):
        assert extract_total_asset({"live": {"total_assets": 50000}}, "live") == 50000.0

    def test_live_total_from_summary(self):
        """国金权威源把总资产放在顶层 summary.total_assets（不是 live.total_assets）。"""
        assert extract_total_asset({"summary": {"total_assets": 47949.72}}, "live") == 47949.72

    def test_live_total_assets_precedence_over_summary(self):
        """两者都在时以 live.total_assets 为准（显式 live 结构优先）。"""
        doc = {"live": {"total_assets": 100}, "summary": {"total_assets": 200}}
        assert extract_total_asset(doc, "live") == 100.0

    def test_sim_flat_config(self):
        assert extract_total_asset({"config": {"initial_capital": 50000}}, "sim") == 50000.0

    def test_sim_wrapped_config(self):
        assert (
            extract_total_asset({"sim": {"config": {"initial_capital": 30000}}}, "sim") == 30000.0
        )

    def test_missing_field_returns_zero(self):
        """缺字段 → 0.0（调用方据此跳过 R7，而不是拿 0 当分母）"""
        assert extract_total_asset({}, "live") == 0.0
        assert extract_total_asset({}, "sim") == 0.0

    def test_none_value_returns_zero(self):
        assert extract_total_asset({"live": {"total_assets": None}}, "live") == 0.0

    def test_garbage_value_returns_zero(self):
        assert extract_total_asset({"config": {"initial_capital": "abc"}}, "sim") == 0.0

    def test_non_dict_input_returns_zero(self):
        assert extract_total_asset(None, "live") == 0.0


# ════════════════════ extract_live_holdings ════════════════════


class TestExtractLiveHoldings:
    """实盘持仓提取（单一真源）—— 历史事故：脚本从模拟盘文件取 live.holdings 恒空。"""

    def test_top_level_holdings(self):
        doc = {"broker": "国金证券", "holdings": [{"code": "600584"}]}
        assert extract_live_holdings(doc) == [{"code": "600584"}]

    def test_legacy_live_wrapper(self):
        assert extract_live_holdings({"live": {"holdings": [{"code": "600036"}]}}) == [
            {"code": "600036"}
        ]

    def test_missing_returns_empty(self):
        assert extract_live_holdings({}) == []
        assert extract_live_holdings(None) == []
        # 顶层 holdings 存在但不是 list（脏数据）→ 不炸、回退 live 分支
        assert extract_live_holdings({"holdings": "oops", "live": {"holdings": [1]}}) == [1]


class TestCreatePortfolioHoldingBuyDate:
    """买入日兼容：模拟盘用 buy_date，国金实盘权威源用 bought_date。"""

    def test_bought_date_maps_to_buy_date(self):
        h = create_portfolio_holding_from_dict({"code": "600584", "bought_date": "2026-07-15"})
        assert h.buy_date == "2026-07-15"

    def test_buy_date_takes_precedence(self):
        h = create_portfolio_holding_from_dict(
            {"buy_date": "2026-01-01", "bought_date": "2026-07-15"}
        )
        assert h.buy_date == "2026-01-01"


# ════════════════════ CLI 人工解冻入口 ════════════════════


class TestUnfreezeCli:
    """unfreeze_buy 此前零调用方 → R2 冻结永久生效。此 CLI 是它的真实入口。"""

    @pytest.fixture(autouse=True)
    def _isolate_state(self, monkeypatch, tmp_path):
        state_path = tmp_path / "cli_state.json"
        monkeypatch.setenv("QTS_ADVANCED_RULES_STATE_PATH", str(state_path))
        return state_path

    def test_list_frozen_when_empty(self, capsys):
        assert _cli(["--list-frozen"]) == 0
        assert "当前无冻结标的" in capsys.readouterr().out

    def test_list_frozen_shows_symbol(self, capsys, _isolate_state):
        RuleStateManager(str(_isolate_state)).freeze_buy("sh600584", "暴跌日: 个股跌幅 7.0%")

        assert _cli(["--list-frozen"]) == 0
        out = capsys.readouterr().out
        assert "sh600584" in out
        assert "暴跌日" in out

    def test_unfreeze_not_frozen_is_noop(self, capsys):
        assert _cli(["--unfreeze", "sh600584"]) == 0
        assert "未处于冻结状态" in capsys.readouterr().out

    def test_unfreeze_removes_freeze(self, capsys, _isolate_state):
        RuleStateManager(str(_isolate_state)).freeze_buy("sh600584", "暴跌日")

        assert _cli(["--unfreeze", "sh600584"]) == 0
        assert "已解除" in capsys.readouterr().out
        assert not RuleStateManager(str(_isolate_state)).is_frozen("sh600584")

    def test_requires_one_action(self):
        with pytest.raises(SystemExit):
            _cli([])


# ════════════════════ 工厂函数 ════════════════════


class TestCreateHoldingFromDict:
    def test_maps_all_fields(self):
        holding = create_portfolio_holding_from_dict(
            {
                "code": "600584",
                "name": "长电科技",
                "shares": 500,
                "avg_cost": 30.5,
                "current_price": 24.0,
                "buy_date": "2026-03-01",
                "buy_prices": [30.0, 31.0],
            }
        )

        assert holding.code == "600584"
        assert holding.shares == 500
        assert holding.buy_prices == [30.0, 31.0]

    def test_defaults_for_missing_keys(self):
        holding = create_portfolio_holding_from_dict({})

        assert holding.shares == 0
        assert holding.avg_cost == 0.0
        assert holding.buy_prices == []
