"""
交易执行模块
处理交易成本模型（滑点、佣金、印花税）和交易限制（T+1、涨跌停）。
由 EnhancedBacktestEngine 委托调用。

职责范围：
- 滑点模型：买入加滑点 / 卖出减滑点
- 佣金计算：双向收取，最低 5 元
- 印花税：仅卖出收取千 1
- T+1 限制：当日买入不能当日卖出
- 涨跌停限制：涨停不能买入，跌停不能卖出

解耦目标：将 Engine 类中 ~70 行交易成本/限制逻辑迁出，
提升可测试性和关注点分离。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ============================================================
# TradeExecutor — 交易成本模型 + 限制检查
# ============================================================


class TradeExecutor:
    """交易执行器

    封装回测中的交易成本计算和交易限制检查，
    由 EnhancedBacktestEngine 创建并委托调用。
    纯计算逻辑，不持有引擎状态（除 config 外）。
    """

    def __init__(self, config):
        """初始化交易执行器

        Args:
            config: BacktestConfig 实例（为打破循环依赖不做类型注解）
        """
        self.config = config

    # ----------------------------------------------------------
    # 交易成本模型
    # ----------------------------------------------------------

    def apply_slippage(self, price: float, direction: str) -> float:
        """计算滑点后的成交价

        买入时加滑点（成交价更高），卖出时减滑点（成交价更低）。

        Args:
            price: 原始价格
            direction: 交易方向 "BUY" 或 "SELL"

        Returns:
            滑点调整后的价格
        """
        if direction == "BUY":
            result: float = price * (1 + self.config.slippage)
            return result
        result: float = price * (1 - self.config.slippage)
        return result

    def calc_commission(self, amount: float) -> float:
        """计算佣金（双向收取，最低5元）

        Args:
            amount: 交易金额

        Returns:
            佣金金额
        """
        commission: float = amount * self.config.commission_rate
        return max(commission, 5.0)

    def calc_tax(self, amount: float, direction: str) -> float:
        """计算印花税（仅卖出收取）

        Args:
            amount: 交易金额
            direction: 交易方向

        Returns:
            印花税金额
        """
        if direction == "SELL":
            tax: float = amount * self.config.stamp_tax
            return tax
        return 0.0

    # ----------------------------------------------------------
    # T+1 与涨跌停限制
    # ----------------------------------------------------------

    def check_t1(self, ts_code: str, trade_date: str, buy_date_map: dict[str, str]) -> bool:
        """检查T+1限制：当日买入的股票不能当日卖出

        Args:
            ts_code: 股票代码
            trade_date: 当前交易日
            buy_date_map: 引擎的 buy_date_map（{ts_code: last_buy_date}）

        Returns:
            True 表示可以卖出，False 表示受T+1限制不能卖出
        """
        if not self.config.enable_t1:
            return True
        buy_date = buy_date_map.get(ts_code)
        if buy_date and buy_date == trade_date:
            return False
        return True

    def check_limit(self, close: float, prev_close: float) -> tuple[bool, bool]:
        """检查涨跌停限制

        主板涨跌停 ±10%（ST 为 ±5%，此处简化按主板处理）。
        - 当日涨停（close >= prev_close * 1.098）：不能买入
        - 当日跌停（close <= prev_close * 0.902）：不能卖出

        Args:
            close: 当日收盘价
            prev_close: 前一日收盘价

        Returns:
            (can_buy, can_sell) 元组
        """
        if not self.config.enable_limit or prev_close <= 0:
            return True, True

        can_buy = close < prev_close * 1.098
        can_sell = close > prev_close * 0.902
        return can_buy, can_sell
