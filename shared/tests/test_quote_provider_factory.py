"""shared/quote_provider/factory.py 单元测试 — 工厂 + 全局实例管理"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unittest.mock import MagicMock, patch

import pytest

from shared.quote_provider.base import QuoteProvider
from shared.quote_provider.factory import (
    QuoteProviderFactory,
    get_quote_provider,
    set_data_source,
)

# ============================================================
#  QuoteProviderFactory 基础测试
# ============================================================


class TestQuoteProviderFactoryBasics:
    """工厂构造、默认值和属性"""

    def test_default_source_is_tushare(self):
        factory = QuoteProviderFactory()
        assert factory._default_source == "tushare"

    def test_custom_default_source(self):
        factory = QuoteProviderFactory(default_source="tdx")
        assert factory._default_source == "tdx"

    def test_registry_contains_three_sources(self):
        assert "tushare" in QuoteProviderFactory.REGISTRY
        assert "tdx" in QuoteProviderFactory.REGISTRY
        assert "akshare" in QuoteProviderFactory.REGISTRY

    def test_instances_empty_on_init(self):
        factory = QuoteProviderFactory()
        assert factory._instances == {}

    def test_default_property_calls_get_provider(self):
        factory = QuoteProviderFactory()
        with patch.object(factory, "get_provider", return_value="mock") as mock_get:
            result = factory.default
            mock_get.assert_called_once()
            assert result == "mock"


# ============================================================
#  get_provider 测试
# ============================================================


class TestGetProvider:
    """获取/延迟初始化提供者"""

    def test_get_provider_creates_instance(self):
        factory = QuoteProviderFactory(default_source="tushare")
        # 用 mock 替换 cls 构造
        with patch("shared.quote_provider.factory.TushareQuoteProvider") as MockTushare:
            mock_instance = MagicMock(spec=QuoteProvider)
            MockTushare.return_value = mock_instance
            provider = factory.get_provider("tushare")
            assert provider is mock_instance
            MockTushare.assert_called_once_with()

    def test_get_provider_caches_instance(self):
        factory = QuoteProviderFactory(default_source="tushare")
        with patch("shared.quote_provider.factory.TushareQuoteProvider") as MockTushare:
            mock_instance = MagicMock(spec=QuoteProvider)
            MockTushare.return_value = mock_instance

            p1 = factory.get_provider("tushare")
            p2 = factory.get_provider("tushare")
            assert p1 is p2
            MockTushare.assert_called_once()  # 只创建一次

    def test_get_provider_without_source_uses_default(self):
        factory = QuoteProviderFactory(default_source="tdx")
        with patch("shared.quote_provider.factory.TdxQuoteProvider") as MockTdx:
            mock_instance = MagicMock(spec=QuoteProvider)
            MockTdx.return_value = mock_instance
            provider = factory.get_provider()
            assert provider is mock_instance

    def test_get_provider_unknown_source_falls_back_to_tushare(self):
        factory = QuoteProviderFactory(default_source="tushare")
        with patch("shared.quote_provider.factory.TushareQuoteProvider") as MockTushare:
            mock_instance = MagicMock(spec=QuoteProvider)
            MockTushare.return_value = mock_instance
            provider = factory.get_provider("unknown_source")
            assert provider is mock_instance

    def test_get_provider_different_sources_different_instances(self):
        factory = QuoteProviderFactory()
        with (
            patch("shared.quote_provider.factory.TushareQuoteProvider") as MockTushare,
            patch("shared.quote_provider.factory.TdxQuoteProvider") as MockTdx,
        ):
            mock_tushare = MagicMock(spec=QuoteProvider)
            mock_tdx = MagicMock(spec=QuoteProvider)
            MockTushare.return_value = mock_tushare
            MockTdx.return_value = mock_tdx

            p1 = factory.get_provider("tushare")
            p2 = factory.get_provider("tdx")
            assert p1 is not p2
            assert p1 is mock_tushare
            assert p2 is mock_tdx


# ============================================================
#  set_default_source 测试
# ============================================================


class TestSetDefaultSource:
    def test_set_default_source_valid(self):
        factory = QuoteProviderFactory(default_source="tushare")
        factory.set_default_source("tdx")
        assert factory._default_source == "tdx"

    def test_set_default_source_unknown_ignored(self):
        factory = QuoteProviderFactory(default_source="tushare")
        factory.set_default_source("nonexistent")
        # 应该忽略，保留原值
        assert factory._default_source == "tushare"

    def test_default_changes_after_set(self):
        factory = QuoteProviderFactory(default_source="tushare")
        factory.set_default_source("akshare")
        with patch("shared.quote_provider.factory.AKShareQuoteProvider") as MockAkshare:
            mock_instance = MagicMock(spec=QuoteProvider)
            MockAkshare.return_value = mock_instance
            provider = factory.get_provider()
            assert provider is mock_instance


# ============================================================
#  register 测试
# ============================================================


class TestRegister:
    def test_register_custom_provider(self):
        """动态注册自定义提供者"""
        MockProvider = MagicMock(spec=QuoteProvider)
        QuoteProviderFactory.register("custom_source", MockProvider)
        assert "custom_source" in QuoteProviderFactory.REGISTRY
        assert QuoteProviderFactory.REGISTRY["custom_source"] is MockProvider

    def test_register_overrides_existing(self):
        """注册同名源可覆盖"""
        MockProvider = MagicMock(spec=QuoteProvider)
        QuoteProviderFactory.register("tushare", MockProvider)
        assert QuoteProviderFactory.REGISTRY["tushare"] is MockProvider
        # 恢复
        from shared.quote_provider.tushare import TushareQuoteProvider

        QuoteProviderFactory.REGISTRY["tushare"] = TushareQuoteProvider


# ============================================================
#  全局工厂实例测试
# ============================================================


class TestGlobalFactory:
    """get_quote_provider / set_data_source 全局函数"""

    def setup_method(self):
        # 清理全局 _factory 状态
        import shared.quote_provider.factory as qpf

        qpf._factory = None

    def test_get_quote_provider_lazy_init(self):
        provider = get_quote_provider("tushare")
        # 返回 cached 实例
        provider2 = get_quote_provider("tushare")
        assert provider is provider2

    def test_set_data_source_creates_factory(self):
        set_data_source("tdx")
        import shared.quote_provider.factory as qpf

        assert qpf._factory is not None
        assert qpf._factory._default_source == "tdx"

    def test_set_data_source_changes_existing(self):
        set_data_source("tushare")
        set_data_source("akshare")
        import shared.quote_provider.factory as qpf

        assert qpf._factory._default_source == "akshare"

    def test_get_quote_provider_nonexistent_returns_tushare(self):
        """未知源返回 tushare 回退"""
        provider = get_quote_provider("nonexistent")
        from shared.quote_provider.tushare import TushareQuoteProvider

        assert isinstance(provider, TushareQuoteProvider)
