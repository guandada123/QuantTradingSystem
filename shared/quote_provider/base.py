"""
行情数据提供者抽象基类
"""

import abc
from typing import Any

# 数据源限频（2026-09-01 引入）
# 限频是「可恢复的系统性错误」，与「无数据」语义不同。
# 此前 provider 一律吞异常返回空结果，降级链无法区分两者，
# 导致批量任务对已超限的数据源重复发起数千次无效调用。
RATE_LIMIT_MARKERS = ("频率超限", "rate limit", "too many requests", "每分钟")


class RateLimitError(RuntimeError):
    """数据源限频错误：调用方应对该数据源做冷却，而非继续重试"""


def is_rate_limit_error(err: Exception) -> bool:
    msg = str(err).lower()
    return any(marker in msg for marker in RATE_LIMIT_MARKERS)


class QuoteProvider(abc.ABC):
    """行情数据提供者抽象接口"""

    @abc.abstractmethod
    def get_realtime_quote(self, ts_code: str) -> dict[str, Any]:
        """获取单只股票实时行情"""
        ...

    @abc.abstractmethod
    def get_batch_realtime(self, ts_codes: list[str]) -> list[dict[str, Any]]:
        """批量获取多只股票实时行情"""
        ...

    @abc.abstractmethod
    def get_index_realtime(self, index_codes: list[str] = None) -> list[dict[str, Any]]:
        """获取核心指数行情"""
        ...

    @abc.abstractmethod
    def get_daily_kline(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取日K线数据"""
        ...

    @abc.abstractmethod
    def get_fundamental(self, ts_code: str) -> dict[str, Any]:
        """获取基本面数据（PE/PB/市值等）"""
        ...

    def name(self) -> str:
        """返回数据源名称"""
        return self.__class__.__name__
