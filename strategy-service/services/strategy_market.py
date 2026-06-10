"""
策略市场业务逻辑
"""
import logging
from typing import Dict, Any, List, Optional
from dataclasses import asdict

from models.strategy import Strategy, BUILTIN_STRATEGIES
from repositories.strategy_repo import strategy_repo

logger = logging.getLogger(__name__)


class StrategyMarketService:
    """策略市场服务"""

    def list_strategies(self, type_filter: str = None, status: str = "active") -> List[Dict]:
        """列出策略"""
        return strategy_repo.list_all(type_filter=type_filter, status=status)

    def get_strategy(self, strategy_id: str) -> Optional[Dict]:
        """获取策略详情"""
        s = strategy_repo.get_by_id(strategy_id)
        return s.to_dict() if s else None

    def create_strategy(self, name: str, params: Dict, description: str = "") -> Dict:
        """创建自定义策略"""
        s = Strategy(name=name, type="custom", params=params, description=description)
        strategy_repo.create(s)
        return s.to_dict()

    def update_strategy(self, strategy_id: str, updates: Dict) -> Optional[Dict]:
        """更新策略"""
        s = strategy_repo.update(strategy_id, updates)
        return s.to_dict() if s else None

    def delete_strategy(self, strategy_id: str) -> bool:
        """删除策略"""
        return strategy_repo.delete(strategy_id)

    def backtest_strategy(self, strategy_id: str, ts_code: str = "000001",
                          data: List[Dict] = None) -> Dict[str, Any]:
        """对指定策略回测（使用模拟数据或自检）"""
        s = strategy_repo.get_by_id(strategy_id)
        if not s:
            raise ValueError(f"策略不存在: {strategy_id}")

        if not data:
            # 使用模拟数据进行快速回测
            import random
            random.seed(hash(strategy_id) % 10000)
            days = 252
            base_price = 50.0
            noise = 0.015
            closes = []
            price = base_price
            for _ in range(days):
                price *= (1 + random.gauss(0.0003, noise))
                closes.append(max(price, 10.0))

            from services.backtest_service import BacktestService, SimpleBacktestEngine
            bs = BacktestService()
            engine = bs.engine

            # 映射策略ID到回测策略名称
            strategy_map = {
                "builtin-ma-cross": "ma-cross",
                "builtin-breakout": "breakout",
                "builtin-rsi": "rsi",
                "builtin-macd": "macd",
                "builtin-kdj": "kdj",
            }
            strat_name = strategy_map.get(strategy_id, "ma-cross")

            data = [{"close": c, "date": f"2025-{i//21+1:02d}-{i%21+1:02d}"} for i, c in enumerate(closes)]

        try:
            from services.backtest_service import BacktestService
            bs = BacktestService()
            result = bs.run_backtest(ts_code, "ma-cross", data, params=s.params)
            perf = {
                "sharpe": round(result.sharpe_ratio, 2),
                "total_return": round(result.total_return, 3),
                "max_drawdown": round(result.max_drawdown, 3),
                "win_rate": round(result.win_rate, 2),
                "total_trades": result.total_trades,
            }
            # 保存回测结果
            strategy_repo.save_performance(strategy_id, perf)
            return {"strategy": s.to_dict(), "backtest": perf, "daily_values": result.daily_values[-30:]}
        except Exception as e:
            logger.error(f"回测失败: {e}")
            return {"strategy": s.to_dict(), "backtest": {"error": str(e)}}

    def compare_strategies(self, strategy_ids: List[str], ts_code: str = "000001",
                           data: List[Dict] = None) -> List[Dict]:
        """多策略对比回测"""
        results = []
        for sid in strategy_ids:
            try:
                r = self.backtest_strategy(sid, ts_code, data)
                results.append(r)
            except Exception as e:
                results.append({"strategy": {"id": sid}, "backtest": {"error": str(e)}})
        return results

    def get_ranking(self, metric: str = "sharpe") -> List[Dict]:
        """策略排行榜"""
        strategies = strategy_repo.list_all()
        ranked = []
        for s in strategies:
            perf = s.get("performance") or {}
            score = perf.get(metric, 0)
            ranked.append({
                "id": s["id"], "name": s["name"], "type": s["type"],
                "score": score, "performance": perf
            })
        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked


# 全局单例
strategy_market = StrategyMarketService()
