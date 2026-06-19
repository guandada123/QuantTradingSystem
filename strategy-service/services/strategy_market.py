"""
策略市场业务逻辑
"""

import logging
from typing import Any

from models.strategy import Strategy
from repositories.strategy_repo import strategy_repo

logger = logging.getLogger(__name__)


class StrategyMarketService:
    """策略市场服务"""

    def list_strategies(self, type_filter: str = None, status: str = "active") -> list[dict]:
        """列出策略"""
        return strategy_repo.list_all(type_filter=type_filter, status=status)

    def get_strategy(self, strategy_id: str) -> dict | None:
        """获取策略详情"""
        s = strategy_repo.get_by_id(strategy_id)
        return s.to_dict() if s else None

    def create_strategy(self, name: str, params: dict, description: str = "") -> dict:
        """创建自定义策略"""
        s = Strategy(name=name, type="custom", params=params, description=description)
        strategy_repo.create(s)
        return s.to_dict()

    def update_strategy(self, strategy_id: str, updates: dict) -> dict | None:
        """更新策略"""
        s = strategy_repo.update(strategy_id, updates)
        return s.to_dict() if s else None

    def delete_strategy(self, strategy_id: str) -> bool:
        """删除策略"""
        return strategy_repo.delete(strategy_id)

    def backtest_strategy(
        self, strategy_id: str, ts_code: str = "000001", data: list[dict] = None
    ) -> dict[str, Any]:
        """对指定策略回测（只使用真实行情数据；不再生成模拟数据）"""
        s = strategy_repo.get_by_id(strategy_id)
        if not s:
            raise ValueError(f"策略不存在: {strategy_id}")

        # 映射策略ID到回测策略名称
        strategy_map = {
            "builtin-ma-cross": "ma-cross",
            "builtin-breakout": "breakout",
            "builtin-rsi": "rsi",
            "builtin-macd": "macd",
            "builtin-kdj": "kdj",
            "builtin-stock-insight": "ma-cross",
        }
        strat_name = strategy_map.get(strategy_id, "ma-cross")

        # 标准化股票代码，兼容前端传 000001 / 600519
        if "." not in ts_code:
            ts_code = f"{ts_code}.SH" if ts_code.startswith("6") else f"{ts_code}.SZ"

        try:
            from datetime import date, timedelta

            from services.backtest_engine_v2 import BacktestConfig, EnhancedBacktestEngine

            end_date = date.today().strftime("%Y%m%d")
            start_date = (date.today() - timedelta(days=365)).strftime("%Y%m%d")
            config = BacktestConfig(
                ts_codes=[ts_code],
                strategies=[strat_name],
                start_date=start_date,
                end_date=end_date,
                initial_cash=100000,
            )
            engine = EnhancedBacktestEngine(config)
            result = engine.run(data={ts_code: data} if data else None)
            perf = {
                "sharpe": round(result.sharpe_ratio, 2),
                "total_return": round(result.total_return, 3),
                "max_drawdown": round(result.max_drawdown, 3),
                "win_rate": round(result.win_rate, 2),
                "total_trades": result.total_trades,
                "data_source": "tencent",
            }
            strategy_repo.save_performance(strategy_id, perf)
            return {
                "strategy": s.to_dict(),
                "backtest": perf,
                "daily_values": result.equity_curve[-30:],
            }
        except Exception as e:
            logger.error(f"回测失败: {e}")
            return {"strategy": s.to_dict(), "backtest": {"error": str(e)}}

    def compare_strategies(
        self, strategy_ids: list[str], ts_code: str = "000001", data: list[dict] = None
    ) -> list[dict]:
        """多策略对比回测"""
        results = []
        for sid in strategy_ids:
            try:
                r = self.backtest_strategy(sid, ts_code, data)
                results.append(r)
            except Exception as e:
                results.append({"strategy": {"id": sid}, "backtest": {"error": str(e)}})
        return results

    def get_ranking(self, metric: str = "sharpe") -> list[dict]:
        """策略排行榜"""
        strategies = strategy_repo.list_all()
        ranked = []
        for s in strategies:
            perf = s.get("performance") or {}
            score = perf.get(metric, 0)
            ranked.append(
                {
                    "id": s["id"],
                    "name": s["name"],
                    "type": s["type"],
                    "score": score,
                    "performance": perf,
                }
            )
        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked


# 全局单例
strategy_market = StrategyMarketService()


async def run_ai_scan(params: dict) -> list[dict]:
    """
    AI 选股扫描：对预设股票池运行多策略回测，按综合评分返回排名。
    """
    from datetime import date, timedelta

    from services.backtest_engine_v2 import EnhancedBacktestEngine

    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=90)).isoformat()

    # 从参数或默认股票池获取扫描列表
    pool = params.get("pool") or [
        "000001.SZ",
        "000333.SZ",
        "600519.SH",
        "600036.SH",
        "000858.SZ",
        "002415.SZ",
        "601318.SH",
        "600900.SH",
    ]
    strategies = params.get("strategies") or ["ma-cross", "macd", "breakout"]

    results = []
    engine = EnhancedBacktestEngine()

    for ts_code in pool[:10]:  # 最多10支，防超时
        try:
            best_sharpe = -99
            best_return = 0
            best_strategy = strategies[0]
            for strat in strategies:
                try:
                    res = engine.run(
                        ts_code=ts_code,
                        strategy=strat,
                        start_date=start_date,
                        end_date=end_date,
                        initial_cash=100000,
                    )
                    m = res.get("metrics", {})
                    sharpe = m.get("sharpe", -99) or -99
                    if sharpe > best_sharpe:
                        best_sharpe = sharpe
                        best_return = m.get("total_return", 0) or 0
                        best_strategy = strat
                except Exception as e:
                    logger.warning("strategy eval failed for %s: %s", ts_code, e)
                    continue

            score = round(max(0, min(100, (best_sharpe + 2) * 20)), 1)
            results.append(
                {
                    "ts_code": ts_code,
                    "name": ts_code,
                    "best_strategy": best_strategy,
                    "sharpe": round(best_sharpe, 3),
                    "return_pct": round(best_return * 100, 2),
                    "score": score,
                    "signal": "BUY"
                    if best_return > 0 and best_sharpe > 0.5
                    else "HOLD"
                    if best_return > -0.05
                    else "SELL",
                }
            )
        except Exception as e:
            logger.debug(f"[AIScân] {ts_code} 扫描失败: {e}")
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    return results
