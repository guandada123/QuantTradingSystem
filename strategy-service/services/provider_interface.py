"""
数据源统一抽象接口层
定义所有行情数据提供者（Tushare, Akshare, 腾讯HTTP, TDX等）必须实现的接口，
确保各数据源可互换、可测试、可自动降级。

用法:
    class TencentProvider(QuoteProvider):
        def get_realtime_quote(self, ts_code): ...
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from shared.structured_log import get_logger

logger = get_logger(__name__)


class QuoteProvider(ABC):
    """行情数据提供者抽象基类

    所有数据源 provider 必须实现此接口，确保调用方可统一使用，
    无需关心底层是 Tushare / Akshare / 腾讯HTTP 还是 TDX。
    """

    @abstractmethod
    def get_realtime_quote(self, ts_code: str) -> dict[str, Any]:
        """获取单只股票实时行情

        Args:
            ts_code: 股票代码，如 "000001.SZ"

        Returns:
            dict 包含 ts_code, name, price, pct_change, timestamp 等字段，
            失败返回空 dict
        """
        ...

    @abstractmethod
    def get_batch_realtime(self, ts_codes: list[str]) -> list[dict[str, Any]]:
        """批量获取多只股票实时行情

        Args:
            ts_codes: 股票代码列表

        Returns:
            list[dict]，每个 dict 包含单只股票行情字段
        """
        ...

    @abstractmethod
    def get_daily_kline(
        self, ts_code: str, start_date: str, end_date: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """获取日K线数据

        Args:
            ts_code: 股票代码
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            limit: 最大返回条数

        Returns:
            list[dict]，每项含 open/high/low/close/volume/amount 等字段
        """
        ...

    @abstractmethod
    def get_index_realtime(self, index_codes: list[str]) -> list[dict[str, Any]]:
        """获取指数实时行情

        Args:
            index_codes: 指数代码列表，如 ["000001.SH", "399001.SZ"]

        Returns:
            list[dict]，每项含 code, name, price, pct_change 等字段
        """
        ...

    @abstractmethod
    def get_fundamental(self, ts_code: str) -> dict[str, Any]:
        """获取个股基本面数据

        Args:
            ts_code: 股票代码

        Returns:
            dict 含 pe_ttm, pb, ps_ttm, total_mv, circ_mv 等字段，
            失败返回空 dict
        """
        ...


class FallbackChain:
    """降级链执行器：按优先级依次调用 provider，首个成功即返回

    用法:
        result = FallbackChain(providers).execute(
            method_getter=lambda p: p.get_realtime_quote,
            validator=lambda r: r.get("price", 0) > 0,
            "000001.SZ"
        )
    """

    def __init__(self, providers: list[tuple[str, QuoteProvider]]):
        """

        Args:
            providers: list of (source_name, provider_instance)
        """
        self._providers = providers

    def execute(self, method_getter, validator, *args, **kwargs) -> Any | None:
        """按顺序调用各 provider 直至成功

        Args:
            method_getter: provider → callable 的函数
            validator: (result) → bool，判断结果是否有效
            *args, **kwargs: 传递给 provider 方法的参数

        Returns:
            有效的 provider 返回结果，或 None（全部失败）
        """
        tried = set()
        for source_name, provider in self._providers:
            if source_name in tried:
                continue
            tried.add(source_name)
            try:
                method = method_getter(provider)
                result = method(*args, **kwargs)
                if result and validator(result):
                    return result
            except Exception as e:
                logger.warning("FallbackChain: %s 调用失败", source_name, error=str(e))
        return None
