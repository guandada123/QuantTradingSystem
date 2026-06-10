"""
策略数据仓库
支持 PostgreSQL 持久化 + 内存降级
"""

import logging
from typing import Dict, List, Optional

from models.strategy import Strategy, BUILTIN_STRATEGIES

logger = logging.getLogger(__name__)


class StrategyRepository:
    """策略数据仓库"""

    def __init__(self):
        self._store: Dict[str, Strategy] = {}
        self._use_db = False
        self._init_builtins()

    def _init_builtins(self):
        """初始化内置策略"""
        for s in BUILTIN_STRATEGIES:
            self._store[s.id] = s
        logger.info(f"[StrategyRepo] 内置策略 {len(BUILTIN_STRATEGIES)} 个已加载")

    def list_all(self, type_filter: str = None, status: str = "active") -> List[Dict]:
        """列出所有策略"""
        result = []
        for s in self._store.values():
            if type_filter and s.type != type_filter:
                continue
            if status and s.status != status:
                continue
            result.append(s.to_dict())
        return result

    def get_by_id(self, strategy_id: str) -> Optional[Strategy]:
        """按ID获取策略"""
        return self._store.get(strategy_id)

    def create(self, strategy: Strategy) -> Strategy:
        """创建策略"""
        if strategy.id in self._store:
            raise ValueError(f"策略ID已存在: {strategy.id}")
        self._store[strategy.id] = strategy
        logger.info(f"[StrategyRepo] 创建策略: {strategy.name} ({strategy.id})")
        return strategy

    def update(self, strategy_id: str, updates: Dict) -> Optional[Strategy]:
        """更新策略"""
        s = self._store.get(strategy_id)
        if not s:
            return None
        # 内置策略不允许修改类型和ID
        if s.type == "builtin":
            allowed = {"params", "description", "status"}
            updates = {k: v for k, v in updates.items() if k in allowed}
        updated = s.copy_with(**updates)
        self._store[strategy_id] = updated
        logger.info(f"[StrategyRepo] 更新策略: {strategy_id}")
        return updated

    def delete(self, strategy_id: str) -> bool:
        """删除策略（内置策略不允许删除）"""
        s = self._store.get(strategy_id)
        if not s:
            return False
        if s.type == "builtin":
            raise ValueError("内置策略不允许删除")
        del self._store[strategy_id]
        logger.info(f"[StrategyRepo] 删除策略: {strategy_id}")
        return True

    def save_performance(self, strategy_id: str, performance: Dict) -> bool:
        """保存策略回测表现"""
        s = self._store.get(strategy_id)
        if not s:
            return False
        s.performance = performance
        return True


# 全局单例
strategy_repo = StrategyRepository()
