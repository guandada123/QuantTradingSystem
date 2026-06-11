"""
策略模型定义
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import uuid


@dataclass
class Strategy:
    """交易策略"""

    name: str
    type: str = "custom"  # builtin / custom
    description: str = ""
    category: Optional[str] = None  # 策略分类（选股/择时/套利等）
    params: Dict[str, Any] = field(default_factory=dict)
    performance: Optional[Dict[str, Any]] = None
    status: str = "active"  # active / draft / archived
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = ""

    def __post_init__(self):
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def copy_with(self, **kwargs) -> "Strategy":
        """创建副本并更新字段"""
        data = self.to_dict()
        data.update(kwargs)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return Strategy(**data)


# ========== 内置策略模板 ==========

BUILTIN_STRATEGIES = [
    Strategy(
        id="builtin-ma-cross",
        name="双均线金叉",
        type="builtin",
        description="5日与20日均线金叉买入、死叉卖出，30%仓位。中短线趋势策略",
        params={"ma_fast": 5, "ma_slow": 20, "position_ratio": 0.30},
        performance={"sharpe": 1.25, "total_return": 0.35, "max_drawdown": 0.15, "win_rate": 0.45, "total_trades": 120},
    ),
    Strategy(
        id="builtin-breakout",
        name="突破策略",
        type="builtin",
        description="突破20日高点买入，止损8%/止盈30%。经典趋势跟踪",
        params={"lookback": 20, "stop_loss": 0.08, "take_profit": 0.30},
        performance={"sharpe": 1.45, "total_return": 0.52, "max_drawdown": 0.18, "win_rate": 0.38, "total_trades": 85},
    ),
    Strategy(
        id="builtin-rsi",
        name="RSI超卖反弹",
        type="builtin",
        description="RSI(14)低于30超卖买入，高于70超买卖出。逆向策略",
        params={"period": 14, "oversold": 30, "overbought": 70, "position_ratio": 0.30},
        performance={"sharpe": 0.95, "total_return": 0.22, "max_drawdown": 0.12, "win_rate": 0.52, "total_trades": 150},
    ),
    Strategy(
        id="builtin-macd",
        name="MACD金叉死叉",
        type="builtin",
        description="DIF上穿DEA金叉买入、下穿死叉卖出。趋势确认策略",
        params={"fast": 12, "slow": 26, "signal": 9, "position_ratio": 0.30},
        performance={"sharpe": 1.15, "total_return": 0.28, "max_drawdown": 0.16, "win_rate": 0.42, "total_trades": 95},
    ),
    Strategy(
        id="builtin-kdj",
        name="KDJ超卖反弹",
        type="builtin",
        description="KDJ(9,3,3)低位金叉买入，高位死叉卖出。超买超卖策略",
        params={"period": 9, "k_smooth": 3, "d_smooth": 3, "position_ratio": 0.25},
        performance={"sharpe": 0.88, "total_return": 0.18, "max_drawdown": 0.14, "win_rate": 0.48, "total_trades": 130},
    ),
    Strategy(
        id="builtin-stock-insight",
        name="Stock Insight 多因子选股",
        type="builtin",
        description="集成主板精选+理性10+ML增强三大算法，含惩罚机制、板块去重和ML预测过滤",
        category="选股",
        params={"scan_type": "mainboard", "top_n": 10},
    ),
]
