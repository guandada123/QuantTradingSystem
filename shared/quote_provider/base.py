"""
行情数据提供者抽象基类
"""

import abc
from typing import Any


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
