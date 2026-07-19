"""
高级风控规则引擎 — 试运行版（2026-07-15）
基于实盘操作回溯审计报告的优化规则。

模式：
  - 默认：只提醒不执行（ADVANCED_RULES_AUTO_EXECUTE=False）
  - 所有规则产出：RuleCheckResult + Feishu卡片推送
  - 状态持久化到 JSON 文件，支持跨重启

十一大规则：
  R1: 强制止损硬化（硬阈值 + ATR动态）
  R2: 暴跌日禁止抄底闸门
  R3: 卖飞-回马枪冷却
  R4: T+3强制决策矩阵
  R5: 双账户合并记账与入场价告警
  R6: 卖飞缓解保留仓策略
  R7: 单票仓位上限（≤15%）
  R8: 入场区间建议器
  R9: 盈亏比预演（<1.8:1标红）
 R10: 飞书日报审计自动化
 R11: 交易日志联动

Usage:
    from services.advanced_risk_rules import AdvancedRiskChecker
    checker = AdvancedRiskChecker(config)
    results = checker.run_all_checks(symbol, price, portfolio_data)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ──────────────────── 数据类 ────────────────────


class RuleSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class RuleAction(Enum):
    ALERT_ONLY = "alert_only"  # 仅推送提醒
    RECOMMEND_SELL = "recommend_sell"  # 建议减仓
    RECOMMEND_FREEZE = "recommend_freeze"  # 建议冻结买入
    RECOMMEND_REDUCE = "recommend_reduce"  # 建议减仓N%
    SUGGEST_POSITION = "suggest_position"  # 建议仓位大小
    SUGGEST_ENTRY = "suggest_entry"  # 建议入场价位
    MARK_FLAGGED = "mark_flagged"  # 标记为红色警告


@dataclass
class RuleCheckResult:
    rule_id: str
    rule_name: str
    severity: RuleSeverity
    action: RuleAction
    triggered: bool
    symbol: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PortfolioHolding:
    """简化持仓结构"""

    code: str
    name: str
    shares: int
    avg_cost: float
    current_price: float
    buy_date: str
    buy_prices: list[float] = field(default_factory=list)  # 多次买入价列表


# ──────────────────── 状态管理 ────────────────────


class RuleStateManager:
    """持久化规则状态（冷却期 / T+3 标记 / 历史交易记录）"""

    def __init__(self, state_path: str):
        self.state_path = state_path
        self.state = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                logger.warning(
                    f"Failed to load rule state from {self.state_path}, using empty state"
                )
        return self._default_state()

    def _default_state(self) -> dict:
        return {
            "freeze_list": {},  # {symbol: {"frozen_at": ISO, "thaw_condition": str}}
            "sell_history": {},  # {symbol: [{"date": str, "price": float}, ...]}
            "position_days": {},  # {symbol: {"first_buy": ISO, "days_held": int}}
            "rule_violations": [],  # 历史违规记录
            "last_updated": datetime.now().isoformat(),
        }

    def save(self):
        self.state["last_updated"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def is_frozen(self, symbol: str) -> bool:
        return symbol in self.state["freeze_list"]

    def freeze_buy(self, symbol: str, reason: str):
        self.state["freeze_list"][symbol] = {
            "frozen_at": datetime.now().isoformat(),
            "reason": reason,
        }
        self.save()

    def unfreeze_buy(self, symbol: str):
        self.state["freeze_list"].pop(symbol, None)
        self.save()

    def record_sell(self, symbol: str, price: float):
        if symbol not in self.state["sell_history"]:
            self.state["sell_history"][symbol] = []
        self.state["sell_history"][symbol].append(
            {
                "date": date.today().isoformat(),
                "price": price,
            }
        )
        self.save()

    def get_last_sell(self, symbol: str) -> dict | None:
        history = self.state["sell_history"].get(symbol, [])
        return history[-1] if history else None

    def record_buy(self, symbol: str, price: float):
        if symbol not in self.state["position_days"]:
            self.state["position_days"][symbol] = {
                "first_buy": date.today().isoformat(),
                "days_held": 1,
            }
        else:
            self.state["position_days"][symbol]["days_held"] += 1
        self.save()

    def get_position_days(self, symbol: str) -> int:
        return self.state["position_days"].get(symbol, {}).get("days_held", 0)

    def add_violation(self, rule_id: str, symbol: str, message: str):
        self.state["rule_violations"].append(
            {
                "rule_id": rule_id,
                "symbol": symbol,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            }
        )
        # 只保留最近 100 条
        if len(self.state["rule_violations"]) > 100:
            self.state["rule_violations"] = self.state["rule_violations"][-100:]
        self.save()


# ──────────────────── 主规则引擎 ────────────────────


class AdvancedRiskChecker:
    """高级风控规则检查器"""

    def __init__(self, risk_config, market_data_provider=None):
        """
        Args:
            risk_config: RiskConfig 实例
            market_data_provider: 可选，市场数据提供者（用于获取行情/ATR/涨跌停等）
        """
        self.config = risk_config
        self.market = market_data_provider
        self.state = RuleStateManager(risk_config.advanced_rules_state_path)
        self.auto_execute = risk_config.advanced_rules_auto_execute

    def run_all_checks(
        self,
        symbol: str,
        current_price: float,
        holding: PortfolioHolding | None = None,
        market_data: dict[str, Any] | None = None,
    ) -> list[RuleCheckResult]:
        """
        对指定标的运行所有高级规则。

        Args:
            symbol: 股票代码 (如 sh600584)
            current_price: 当前价格
            holding: 持仓数据（若已持仓）
            market_data: 市场数据（含 ATR/行业指数/涨跌停数等）

        Returns:
            List[RuleCheckResult] 按严重程度排序
        """
        results = []

        if not self.config.advanced_rules_enabled:
            return results

        # R1: 止损检查（仅对持仓生效）
        if holding and holding.shares > 0:
            result_r1 = self._check_stop_loss(symbol, current_price, holding, market_data)
            if result_r1:
                results.append(result_r1)

        # R2: 暴跌日冻结检查
        result_r2 = self._check_freeze_buy(symbol, current_price, market_data)
        if result_r2:
            results.append(result_r2)

        # R3: 卖飞冷却检查
        result_r3 = self._check_sell_cooldown(symbol)
        if result_r3:
            results.append(result_r3)

        # R4: T+3 决策检查（仅对持仓生效）
        if holding and holding.shares > 0:
            result_r4 = self._check_t3_decision(symbol, current_price, holding)
            if result_r4:
                results.append(result_r4)

        # R5: 双账户合并记账（需portfolio上下文）
        if holding and holding.shares > 0:
            result_r5 = self._check_dual_account(symbol, holding, market_data)
            if result_r5:
                results.append(result_r5)

        # R7: 单票仓位上限（需组合上下文）
        result_r7 = self._check_position_limit(symbol, holding)
        if result_r7:
            results.append(result_r7)

        # R8: 入场区间建议（仅未持仓时触发）
        if not holding or holding.shares == 0:
            result_r8 = self._suggest_entry_range(symbol, current_price, market_data)
            if result_r8:
                results.append(result_r8)

        # R9: 盈亏比预演（需目标价和止损价）
        result_r9 = self._check_risk_reward(symbol, current_price, holding, market_data)
        if result_r9:
            results.append(result_r9)

        # 按严重程度排序
        severity_order = {RuleSeverity.CRITICAL: 0, RuleSeverity.WARNING: 1, RuleSeverity.INFO: 2}
        results.sort(key=lambda r: severity_order.get(r.severity, 99))

        # 记录违规
        for r in results:
            if r.triggered and r.severity in (RuleSeverity.CRITICAL, RuleSeverity.WARNING):
                self.state.add_violation(r.rule_id, symbol, r.message)

        return results

    # ——— R1: 止损硬化 ———
    def _check_stop_loss(
        self,
        symbol: str,
        current_price: float,
        holding: PortfolioHolding,
        market_data: dict[str, Any] | None = None,
    ) -> RuleCheckResult | None:
        """双阈值止损：硬阈值(8%) 或 ATR动态阈值"""

        # Hard stop
        hard_stop_price = holding.avg_cost * (1 - self.config.stop_loss_hard_pct)
        hard_triggered = current_price <= hard_stop_price
        hard_pct = (current_price - holding.avg_cost) / holding.avg_cost

        # ATR stop
        atr = self._get_atr(symbol, market_data)
        atr_triggered = False
        atr_stop_price = None
        if atr and atr > 0:
            atr_stop_price = holding.avg_cost - self.config.stop_loss_atr_mult * atr
            atr_triggered = current_price <= atr_stop_price

        triggered = hard_triggered or atr_triggered

        if not triggered:
            return None

        # 确定触发原因
        reasons = []
        if hard_triggered:
            reasons.append(
                f"硬止损: {current_price:.2f} ≤ {hard_stop_price:.2f} (成本 {holding.avg_cost:.2f} × {1 - self.config.stop_loss_hard_pct:.0%})"
            )
        if atr_triggered and atr_stop_price:
            reasons.append(
                f"ATR止损: {current_price:.2f} ≤ {atr_stop_price:.2f} (ATR={atr:.2f} × {self.config.stop_loss_atr_mult})"
            )

        severity = RuleSeverity.CRITICAL if hard_triggered else RuleSeverity.WARNING
        action = RuleAction.RECOMMEND_SELL if self.auto_execute else RuleAction.ALERT_ONLY

        return RuleCheckResult(
            rule_id="R1_STOP_LOSS",
            rule_name="止损硬化",
            severity=severity,
            action=action,
            triggered=True,
            symbol=symbol,
            message=f"⚠️ {holding.name}({symbol}) 触发止损: {'; '.join(reasons)}",
            details={
                "current_price": current_price,
                "avg_cost": holding.avg_cost,
                "floating_pnl_pct": round(hard_pct * 100, 2),
                "hard_stop_price": round(hard_stop_price, 2),
                "atr_stop_price": round(atr_stop_price, 2) if atr_stop_price else None,
                "atr": round(atr, 2) if atr else None,
                "shares": holding.shares,
                "auto_execute": self.auto_execute,
            },
        )

    # ——— R2: 暴跌日冻结买入 ———
    def _check_freeze_buy(
        self,
        symbol: str,
        current_price: float,
        market_data: dict[str, Any] | None = None,
    ) -> RuleCheckResult | None:
        """检查是否触发暴跌日买入冻结"""

        # 先检查是否已被冻结
        if self.state.is_frozen(symbol):
            freeze_info = self.state.state["freeze_list"][symbol]
            return RuleCheckResult(
                rule_id="R2_FREEZE_BUY",
                rule_name="暴跌日买入冻结",
                severity=RuleSeverity.WARNING,
                action=RuleAction.RECOMMEND_FREEZE,
                triggered=True,
                symbol=symbol,
                message=f"🚫 {symbol} 处于买入冻结期 ({freeze_info['frozen_at']})，原因: {freeze_info['reason']}",
                details={"frozen_since": freeze_info["frozen_at"], "reason": freeze_info["reason"]},
            )

        if not market_data:
            return None

        # 检查暴跌条件
        stock_drop = market_data.get("stock_drop_pct", 0)
        sector_drop = market_data.get("sector_drop_pct", 0)
        limit_ratio = market_data.get("limit_down_up_ratio", 0)

        conditions_met = []
        if abs(stock_drop) >= self.config.freeze_buy_stock_drop:
            conditions_met.append(
                f"个股跌幅 {stock_drop:.1%} ≥ {self.config.freeze_buy_stock_drop:.0%}"
            )
        if abs(sector_drop) >= self.config.freeze_buy_sector_drop:
            conditions_met.append(
                f"行业跌幅 {sector_drop:.1%} ≥ {self.config.freeze_buy_sector_drop:.0%}"
            )
        if limit_ratio >= self.config.freeze_buy_limit_ratio:
            conditions_met.append(
                f"跌停/涨停比 {limit_ratio:.1f} ≥ {self.config.freeze_buy_limit_ratio}"
            )

        if not conditions_met:
            return None

        self.state.freeze_buy(symbol, f"暴跌日: {'; '.join(conditions_met)}")

        return RuleCheckResult(
            rule_id="R2_FREEZE_BUY",
            rule_name="暴跌日买入冻结",
            severity=RuleSeverity.CRITICAL,
            action=RuleAction.RECOMMEND_FREEZE,
            triggered=True,
            symbol=symbol,
            message=f"🚫 暴跌触发买入冻结: {'; '.join(conditions_met)}。解冻条件: 两连阳站上MA5 或 放量反包站上MA10",
            details={
                "stock_drop_pct": stock_drop,
                "sector_drop_pct": sector_drop,
                "limit_ratio": limit_ratio,
                "frozen_at": datetime.now().isoformat(),
            },
        )

    # ——— R3: 卖飞冷却 ———
    def _check_sell_cooldown(self, symbol: str) -> RuleCheckResult | None:
        """检查卖出冷却期是否未过"""

        last_sell = self.state.get_last_sell(symbol)
        if not last_sell:
            return None

        sell_date = datetime.strptime(last_sell["date"], "%Y-%m-%d").date()
        days_since_sell = (date.today() - sell_date).days

        # 默认冷却 10 个交易日（约 14 个自然日）
        cooldown = self.config.sell_cooldown_days

        # 检查是否卖出后 5 日内创新高（延长冷却）
        self._check_new_high_after_sell(symbol, last_sell)
        if (
            self.state.state["sell_history"].get(symbol)
            and len(self.state.state["sell_history"][symbol]) > 1
        ):
            cooldown = self.config.sell_cooldown_extended_days

        if days_since_sell < cooldown:
            return RuleCheckResult(
                rule_id="R3_SELL_COOLDOWN",
                rule_name="卖飞冷却期",
                severity=RuleSeverity.WARNING,
                action=RuleAction.RECOMMEND_FREEZE,
                triggered=True,
                symbol=symbol,
                message=f"⏳ {symbol} 卖出仅 {days_since_sell} 天，冷却期 {cooldown} 天未过，禁止再次买入",
                details={
                    "last_sell_date": last_sell["date"],
                    "last_sell_price": last_sell["price"],
                    "days_since_sell": days_since_sell,
                    "cooldown_days": cooldown,
                },
            )

        return None

    def _check_new_high_after_sell(self, symbol: str, last_sell: dict):
        """检查卖出后是否创新高（需外部数据）—— 当前为 stub"""
        # TODO: 接入行情数据后实现

    # ——— R4: T+3 决策矩阵 ———
    def _check_t3_decision(
        self,
        symbol: str,
        current_price: float,
        holding: PortfolioHolding,
    ) -> RuleCheckResult | None:
        """T+3 持仓满3天自动评估"""

        days_held = self.state.get_position_days(symbol)
        if days_held < 3:
            return None

        pnl_pct = (current_price - holding.avg_cost) / holding.avg_cost

        if pnl_pct >= self.config.t3_lock_profit_pct:
            severity = RuleSeverity.INFO
            action_pct = 0.30
            message = (
                f"💰 {holding.name}({symbol}) 持仓第 {days_held} 天，浮盈 {pnl_pct:.1%} ≥ "
                f"{self.config.t3_lock_profit_pct:.0%}，建议锁利卖出 30%（余仓追踪止盈=昨日低点/5EMA）"
            )
        elif pnl_pct <= -self.config.t3_reduce_light_pct:
            severity = RuleSeverity.CRITICAL
            action_pct = 0.50
            message = (
                f"🔴 {holding.name}({symbol}) 持仓第 {days_held} 天，浮亏 {pnl_pct:.1%} ≤ "
                f"-{self.config.t3_reduce_light_pct:.0%}，建议紧急减仓 50%"
            )
        elif pnl_pct <= -self.config.t3_reduce_early_pct:
            severity = RuleSeverity.WARNING
            action_pct = 0.30
            message = (
                f"🟡 {holding.name}({symbol}) 持仓第 {days_held} 天，浮亏 {pnl_pct:.1%}，"
                f"建议减仓 30%"
            )
        else:
            return None

        action = RuleAction.RECOMMEND_REDUCE if self.auto_execute else RuleAction.ALERT_ONLY

        return RuleCheckResult(
            rule_id="R4_T3_DECISION",
            rule_name="T+3 决策矩阵",
            severity=severity,
            action=action,
            triggered=True,
            symbol=symbol,
            message=message,
            details={
                "days_held": days_held,
                "pnl_pct": round(pnl_pct * 100, 2),
                "avg_cost": holding.avg_cost,
                "current_price": current_price,
                "recommend_sell_pct": round(action_pct * 100),
                "auto_execute": self.auto_execute,
            },
        )

    # ——— R5: 双账户合并记账 ———
    def _check_dual_account(
        self,
        symbol: str,
        holding: PortfolioHolding,
        market_data: dict[str, Any] | None = None,
    ) -> RuleCheckResult | None:
        """同一标的多次买入的加权成本与持有天数告警"""
        if not holding.buy_prices or len(holding.buy_prices) <= 1:
            return None

        # 检查是否有"高位接刀"：最新买入价显著高于最早买入价
        first_price = holding.buy_prices[0]
        last_price = holding.buy_prices[-1]
        premium_pct = (last_price - first_price) / first_price if first_price > 0 else 0

        if premium_pct > 0.10:  # 最新买入比最初买入贵10%以上
            return RuleCheckResult(
                rule_id="R5_DUAL_ACCOUNT",
                rule_name="高位接刀告警",
                severity=RuleSeverity.WARNING,
                action=RuleAction.MARK_FLAGGED,
                triggered=True,
                symbol=symbol,
                message=f"🔺 {holding.name}({symbol}) 多次买入价差 {premium_pct:.1%}（首买{first_price:.2f}→末买{last_price:.2f}），疑似高位接刀",
                details={
                    "first_buy_price": first_price,
                    "last_buy_price": last_price,
                    "premium_pct": round(premium_pct * 100, 2),
                    "buy_count": len(holding.buy_prices),
                    "avg_cost": holding.avg_cost,
                },
            )
        return None

    # ——— R6: 卖飞保留仓 ———
    def _check_sell_retention(
        self,
        symbol: str,
        holding: PortfolioHolding,
        position_value: float,
        total_asset: float,
    ) -> RuleCheckResult | None:
        """清仓时建议保留10-20%跟踪仓，采用2×ATR移动止盈"""
        if not holding or holding.shares <= 0:
            return None
        if position_value <= 0 or total_asset <= 0:
            return None

        retention_pct = 0.15  # 建议保留15%
        retention_shares = max(1, int(holding.shares * retention_pct / 100) * 100)

        return RuleCheckResult(
            rule_id="R6_SELL_RETENTION",
            rule_name="卖飞保留仓",
            severity=RuleSeverity.INFO,
            action=RuleAction.SUGGEST_POSITION,
            triggered=True,
            symbol=symbol,
            message=f"📌 若清仓{holding.name}，建议保留 {retention_shares} 股({retention_pct:.0%})作跟踪仓，2×ATR移动止盈防卖飞",
            details={
                "total_shares": holding.shares,
                "suggested_retention": retention_shares,
                "retention_pct": retention_pct,
                "position_value": position_value,
            },
        )

    # ——— R7: 单票仓位上限 ———
    def _check_position_limit(
        self,
        symbol: str,
        holding: PortfolioHolding | None = None,
        position_value: float = 0,
        total_asset: float = 0,
    ) -> RuleCheckResult | None:
        """单票仓位不得超过15%（高Beta行业≤10%）"""
        if not holding or holding.shares <= 0:
            return None
        if total_asset <= 0:
            return None

        ratio = position_value / total_asset
        limit = 0.15

        if ratio > limit:
            return RuleCheckResult(
                rule_id="R7_POSITION_LIMIT",
                rule_name="仓位上限告警",
                severity=RuleSeverity.WARNING,
                action=RuleAction.RECOMMEND_REDUCE,
                triggered=True,
                symbol=symbol,
                message=f"⚠️ {holding.name}({symbol}) 仓位 {ratio:.1%} 超过{limit:.0%}上限，建议减仓至{limit:.0%}以内",
                details={
                    "current_ratio": round(ratio * 100, 2),
                    "limit_ratio": round(limit * 100),
                    "position_value": position_value,
                    "total_asset": total_asset,
                },
            )
        # 近上限提醒
        if ratio > limit * 0.8:
            return RuleCheckResult(
                rule_id="R7_POSITION_LIMIT",
                rule_name="仓位近上限提醒",
                severity=RuleSeverity.INFO,
                action=RuleAction.ALERT_ONLY,
                triggered=True,
                symbol=symbol,
                message=f"ℹ️ {holding.name}({symbol}) 仓位 {ratio:.1%} 接近{limit:.0%}上限",
                details={"current_ratio": round(ratio * 100, 2), "limit_ratio": round(limit * 100)},
            )
        return None

    # ——— R8: 入场区间建议器 ———
    def _suggest_entry_range(
        self,
        symbol: str,
        current_price: float,
        market_data: dict[str, Any] | None = None,
    ) -> RuleCheckResult | None:
        """基于MA20偏离和20日价格分位数，给出分批买入建议"""
        if not market_data:
            return None

        ma20 = market_data.get("ma20")
        high_20 = market_data.get("high_20d")
        low_20 = market_data.get("low_20d")
        rsi = market_data.get("rsi")

        if not ma20 or not high_20 or not low_20:
            return None

        range_span = high_20 - low_20
        if range_span <= 0:
            return None

        percentile = (current_price - low_20) / range_span
        ma_deviation = (current_price - ma20) / ma20

        # 高位：不建议入场
        if rsi and rsi > 70:
            return RuleCheckResult(
                rule_id="R8_ENTRY_RANGE",
                rule_name="入场区间(过热)",
                severity=RuleSeverity.WARNING,
                action=RuleAction.SUGGEST_ENTRY,
                triggered=True,
                symbol=symbol,
                message=f"🔥 {symbol} RSI={rsi:.0f} >70 过热，暂缓买入。建议等待回调至MA20(¥{ma20:.2f})附近",
                details={"rsi": rsi, "ma20": ma20, "current_price": current_price},
            )

        # 中间区域：分批建议
        buy_zone_1 = round(ma20 * 0.97, 2)  # -3%
        buy_zone_2 = round(ma20 * 0.94, 2)  # -6%

        if percentile > 0.7:
            severity = RuleSeverity.INFO
            message = (
                f"📊 {symbol} 处于20日高位(分位{percentile:.0%})，"
                f"建议入场区: ¥{buy_zone_1}/¥{buy_zone_2}（MA20的-3%/-6%），"
                f"当前¥{current_price:.2f}，距MA20(¥{ma20:.2f})偏离{ma_deviation:.1%}"
            )
        elif percentile < 0.3:
            message = (
                f"📊 {symbol} 处于20日低位(分位{percentile:.0%})，"
                f"可考虑分批入场: ¥{current_price:.2f}"
            )
            severity = RuleSeverity.INFO
        else:
            return None

        return RuleCheckResult(
            rule_id="R8_ENTRY_RANGE",
            rule_name="入场区间建议",
            severity=severity,
            action=RuleAction.SUGGEST_ENTRY,
            triggered=True,
            symbol=symbol,
            message=message,
            details={
                "current_price": current_price,
                "ma20": ma20,
                "percentile": round(percentile * 100),
                "ma_deviation_pct": round(ma_deviation * 100, 2),
                "buy_zone_1": buy_zone_1,
                "buy_zone_2": buy_zone_2,
                "rsi": rsi,
            },
        )

    # ——— R9: 盈亏比预演 ———
    def _check_risk_reward(
        self,
        symbol: str,
        current_price: float,
        holding: PortfolioHolding | None = None,
        market_data: dict[str, Any] | None = None,
        target_price: float | None = None,
        stop_price: float | None = None,
    ) -> RuleCheckResult | None:
        """下单前校验盈亏比，<1.8:1 标红"""
        if not target_price or not stop_price:
            return None

        reward = target_price - current_price
        risk = current_price - stop_price
        if risk <= 0:
            return RuleCheckResult(
                rule_id="R9_RISK_REWARD",
                rule_name="盈亏比(无效)",
                severity=RuleSeverity.CRITICAL,
                action=RuleAction.MARK_FLAGGED,
                triggered=True,
                symbol=symbol,
                message=f"❌ {symbol} 止损价{stop_price:.2f}≥入场价{current_price:.2f}，盈亏比无效",
                details={"target_price": target_price, "stop_price": stop_price},
            )

        rr_ratio = reward / risk
        if rr_ratio < 1.8:
            return RuleCheckResult(
                rule_id="R9_RISK_REWARD",
                rule_name="盈亏比不足",
                severity=RuleSeverity.WARNING if rr_ratio >= 1.2 else RuleSeverity.CRITICAL,
                action=RuleAction.MARK_FLAGGED,
                triggered=True,
                symbol=symbol,
                message=f"🔴 {symbol} 盈亏比 {rr_ratio:.2f}:1 < 1.8:1，风险收益不佳。目标{target_price:.2f}/止损{stop_price:.2f}",
                details={
                    "rr_ratio": round(rr_ratio, 2),
                    "reward": round(reward, 2),
                    "risk": round(risk, 2),
                    "target_price": target_price,
                    "stop_price": stop_price,
                },
            )

        return RuleCheckResult(
            rule_id="R9_RISK_REWARD",
            rule_name="盈亏比达标",
            severity=RuleSeverity.INFO,
            action=RuleAction.ALERT_ONLY,
            triggered=True,
            symbol=symbol,
            message=f"✅ {symbol} 盈亏比 {rr_ratio:.2f}:1 ≥ 1.8:1 达标",
            details={
                "rr_ratio": round(rr_ratio, 2),
                "target_price": target_price,
                "stop_price": stop_price,
            },
        )

    # ——— 辅助方法 ———
    def _get_atr(self, symbol: str, market_data: dict[str, Any] | None = None) -> float | None:
        """获取 ATR(14)"""
        if market_data and "atr" in market_data:
            return market_data["atr"]
        return None

    def to_feishu_card(self, results: list[RuleCheckResult]) -> dict:
        """将检查结果转换为飞书交互式卡片"""
        if not results:
            return self._build_empty_card()

        critical_count = sum(1 for r in results if r.severity == RuleSeverity.CRITICAL)
        warning_count = sum(1 for r in results if r.severity == RuleSeverity.WARNING)

        header_color = "red" if critical_count > 0 else ("orange" if warning_count > 0 else "blue")
        header_title = (
            f"🔴 高级风控告警 ({critical_count}严重/{warning_count}警告)"
            if critical_count > 0
            else f"🟡 高级风控提醒 ({warning_count}项)"
        )

        elements = []
        for r in results:
            icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(r.severity.value, "⚪")
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"{icon} **[{r.rule_name}]** {r.message}\n"
                        f"─ 操作建议: {r.action.value} | 时间: {r.timestamp[:19]}",
                    },
                }
            )
            if r.details:
                detail_lines = "\n".join(
                    f"  • {k}: {v}" for k, v in r.details.items() if v is not None
                )
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": detail_lines}})

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": header_title},
                "template": header_color,
            },
            "elements": elements,
            "note": {
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"试运行模式 | 自动执行: {'ON' if self.auto_execute else 'OFF'} | {datetime.now().strftime('%m-%d %H:%M')}",
                    }
                ]
            },
        }
        return card

    def _build_empty_card(self) -> dict:
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "✅ 高级风控无异常"},
                "template": "green",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "所有高级风控规则检查通过，未触发任何告警。",
                    },
                }
            ],
        }


# ──────────────────── 集成示例 ────────────────────


def create_portfolio_holding_from_dict(data: dict) -> PortfolioHolding:
    """从字典创建 PortfolioHolding"""
    return PortfolioHolding(
        code=data.get("code", ""),
        name=data.get("name", ""),
        shares=data.get("shares", 0),
        avg_cost=data.get("avg_cost", 0.0),
        current_price=data.get("current_price", 0.0),
        buy_date=data.get("buy_date", ""),
        buy_prices=data.get("buy_prices", []),
    )
