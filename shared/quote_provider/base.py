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
    """数据源系统性错误（限频 / 网络不通）：调用方应对该数据源做冷却，而非继续重试

    2026-09-01 run#58：语义从「仅限频」扩大到「限频 + 网络不通」——
    两者对降级链的处理完全一样（换个标的、重试一次都不会好）。
    保留原名以免破坏已有 import 与测试。
    """


def is_rate_limit_error(err: Exception) -> bool:
    msg = str(err).lower()
    return any(marker in msg for marker in RATE_LIMIT_MARKERS)


# 网络/连通性错误特征（2026-09-01 run#58 引入）
# 与限频同属「系统性错误」：换个标的、重试一次都不会好，只该冷却整个 (源, 方法)。
# 与之相对的是业务性错误（代码无效、停牌无数据）—— 换标的就会成功，不该冷却。
#
# 实证背景：akshare（东方财富 push2）在本机网络环境不可达，24h 被调用 48 次、
# 成功 0 次，每次重试 3 轮耗时 20.4s ≈ 16.4 分钟/天。而 provider 把该异常
# 吞掉并返回空结果，降级链看到的是「有结果但没数据」，既不报错也不熔断，
# 于是一个 100% 失败的源被每 30 分钟忠实重试一次。
CONNECTION_ERROR_MARKERS = (
    "connection aborted",
    "remote end closed",
    "connection refused",
    "connection reset",
    "name or service not known",
    "temporary failure in name resolution",
    "max retries exceeded",
    "timed out",
    "timeout",
    "network is unreachable",
)


def is_systemic_error(err: Exception) -> bool:
    """是否为系统性错误（限频 / 网络不通）—— 重试与换标的都无意义。

    provider 判断依据：系统性错误应当**上抛**给降级链（触发冷却），
    而不是吞掉返回空结果；业务性错误才返回空，让降级链换个源继续试。
    """
    msg = str(err).lower()
    return is_rate_limit_error(err) or any(marker in msg for marker in CONNECTION_ERROR_MARKERS)


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
