"""Quote provider factory — legacy stub, now typed via QuoteProvider ABC"""

from typing import Any

from services.provider_interface import QuoteProvider


class QuoteProviderFactory:
    """行情数据源工厂（v4.0 兼容接口）。

    接受各数据源配置参数，get_provider() 返回对应 QuoteProvider 实例。
    当前为轻量存根（stub），完整实现可对接 tdx / tushare / akshare。
    """

    def __init__(
        self,
        default_source: str = "tencent",
        tdx: dict[str, Any] | None = None,
        tushare: dict[str, Any] | None = None,
        akshare: dict[str, Any] | None = None,
    ):
        # 兼容代码通过 _default_source 和 _config 访问
        self._default_source = default_source
        self.default_source = default_source
        self._config = {"tdx": tdx or {}, "tushare": tushare or {}, "akshare": akshare or {}}

    @property
    def default(self) -> QuoteProvider | None:
        """获取默认 provider（为兼容存根模式返回 None）"""
        return self.get_provider(self._default_source)

    def set_default_source(self, source: str):
        self._default_source = source
        self.default_source = source

    def get_provider(self, source: str | None = None) -> QuoteProvider | None:
        """获取指定数据源 provider（存根始终返回 None，表示数据源不可用）"""
        return

    def create(self, source: str | None = None, tushare_token: str | None = None) -> QuoteProvider | None:
        return None
