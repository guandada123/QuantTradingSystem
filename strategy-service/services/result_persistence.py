"""
回测结果持久化服务 — 封装 BacktestResult 的 DB 写入逻辑
将 _save_bt_result_db 的 7 参数大函数重构为 ResultPersistence 类
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ResultPersistence:
    """回测结果持久化服务

    职责：将 EnhancedBacktestEngine.run() 返回的 BacktestResult 写入数据库，
    封装 DB 连接管理、指标计算和异常处理。
    """

    def __init__(self):
        self._imported = False
        self._get_db_session = None
        self._save_backtest_result = None

    def _ensure_imports(self) -> bool:
        """惰性导入 DB 模块，返回模块是否可用"""
        if self._imported:
            return True
        try:
            from models.database import get_db_session
            from repositories.backtest_repo import save_backtest_result

            self._get_db_session = get_db_session
            self._save_backtest_result = save_backtest_result
            self._imported = True
            return True
        except ImportError:
            logger.warning("DB 模块不可用，跳过回测结果持久化")
            return False

    def compute_final_value(self, result, initial_cash: float, total_return: float) -> float:
        """从净值曲线或收益率计算最终资产值"""
        if result.equity_curve:
            last_point = result.equity_curve[-1]
            return float(last_point.get("value", 0)) or initial_cash * (1 + total_return)
        return initial_cash * (1 + total_return)

    def build_db_record(
        self,
        strategy: str,
        ts_code: str,
        start_date: str,
        end_date: str,
        initial_cash: float,
        result,
        result_dict: dict,
    ) -> dict:
        """构建写入 DB 的结果记录字典"""
        metrics = result_dict["metrics"]
        total_return = metrics["total_return"]
        final_value = self.compute_final_value(result, initial_cash, total_return)

        return {
            "strategy_name": strategy,
            "strategy_version": "2.0",
            "ts_code": ts_code,
            "start_date": datetime.strptime(start_date, "%Y%m%d").date(),
            "end_date": datetime.strptime(end_date, "%Y%m%d").date(),
            "initial_cash": initial_cash,
            "final_value": round(final_value, 2),
            "total_return": total_return,
            "annual_return": metrics["annual_return"],
            "sharpe_ratio": metrics["sharpe_ratio"],
            "max_drawdown": metrics["max_drawdown"],
            "win_rate": metrics["win_rate"],
            "profit_loss_ratio": metrics["profit_loss_ratio"],
            "total_trades": metrics["total_trades"],
            "winning_trades": getattr(result, "winning_trades", 0),
            "losing_trades": getattr(result, "losing_trades", 0),
            "avg_holding_days": round(getattr(result, "avg_hold_days", 0), 2),
            "backtest_details": {
                "equity_curve": result_dict.get("equity_curve", []),
                "benchmark_curve": result_dict.get("benchmark_curve", []),
                "drawdown_curve": result_dict.get("drawdown_curve", []),
                "monthly_returns": result_dict.get("monthly_returns", []),
                "trades": result_dict.get("trades", []),
                "alpha": metrics.get("alpha"),
                "beta": metrics.get("beta"),
                "volatility": metrics.get("volatility"),
                "calmar_ratio": metrics.get("calmar_ratio"),
                "sortino_ratio": metrics.get("sortino_ratio"),
            },
        }

    def save(
        self,
        strategy: str,
        ts_code: str,
        start_date: str,
        end_date: str,
        initial_cash: float,
        result,
        result_dict: dict,
    ) -> str | None:
        """将回测结果写入数据库，返回 backtest_id 或 None

        Args:
            strategy: 策略名称
            ts_code: 股票代码
            start_date: YYYYMMDD
            end_date: YYYYMMDD
            initial_cash: 初始资金
            result: BacktestResult dataclass 实例
            result_dict: 前端返回的 dict（含 curves/trades）

        Returns:
            backtest_id (str) 或 None（DB 不可用时）
        """
        if not self._ensure_imports():
            return None

        db_record = self.build_db_record(
            strategy, ts_code, start_date, end_date, initial_cash, result, result_dict
        )

        try:
            with self._get_db_session() as db:
                saved = self._save_backtest_result(db, db_record)
                bid = saved.get("backtest_id", "")
                logger.info(f"回测结果已持久化: {strategy}/{ts_code} → backtest_id={bid}")
                return bid
        except Exception as e:
            logger.warning(f"回测结果持久化失败 (非致命): {e}")
            return None


# 全局单例（兼容旧调用方式）
_persistence = ResultPersistence()


def save_backtest_result(
    strategy: str,
    ts_code: str,
    start_date: str,
    end_date: str,
    initial_cash: float,
    result,
    result_dict: dict,
) -> str | None:
    """兼容旧 API：委托给 ResultPersistence 单例"""
    return _persistence.save(strategy, ts_code, start_date, end_date, initial_cash, result, result_dict)
