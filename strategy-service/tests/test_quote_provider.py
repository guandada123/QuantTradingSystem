"""
QuoteProvider 单元测试 v1.0

测试策略：所有外部依赖（tushare、httpx、akshare）均被 mock。
macOS 沙箱中 numpy C 扩展签名不一致，预处理 mock 模块。
"""

import os
import sys

# ── 导入路径修复 ──────────────────────────────────────────────
# conftest.py 已统一处理 shared/ 目录解析。此文件的重复修复逻辑
# 在容器环境（/app/tests/../.. = /）中指向错误路径，导致导入失败。
# 保留 sys.path 和 shared.__path__ 的清理逻辑但不对抗 conftest。
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# ─────────────────────────────────────────────────────────────

from unittest.mock import MagicMock, patch

import pytest

from shared.quote_provider import (
    AKShareQuoteProvider,
    QuoteProvider,
    QuoteProviderFactory,
    TdxQuoteProvider,
    TushareQuoteProvider,
    get_quote_provider,
    set_data_source,
)

# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


def _make_mock_quote_row():
    """创建模拟的 DataFrame.iloc[0] 返回行"""
    return {
        "close": 1810.0,
        "open": 1800.0,
        "high": 1820.0,
        "low": 1790.0,
        "pre_close": 1790.0,
        "change": 20.0,
        "pct_chg": 1.12,
        "vol": 5000000,
        "amount": 9.05e9,
        "trade_date": "20260610",
    }


def _make_mock_index_row():
    """创建模拟的指数返回行"""
    return {
        "close": 3600.0,
        "pct_chg": 0.35,
        "trade_date": "20260610",
    }


@pytest.fixture
def tushare_provider():
    """直接构造，完全 mock，避免任何 C 扩展加载"""
    provider = TushareQuoteProvider.__new__(TushareQuoteProvider)
    provider._pro = MagicMock()
    provider._token = "fake_token"

    def make_daily_df(*args, **kwargs):
        df = MagicMock()
        df.empty = False
        iloc = MagicMock()
        iloc.__getitem__.return_value = _make_mock_quote_row()
        df.iloc = iloc
        return df

    def make_index_df(*args, **kwargs):
        df = MagicMock()
        df.empty = False
        iloc = MagicMock()
        iloc.__getitem__.return_value = _make_mock_index_row()
        df.iloc = iloc
        return df

    def make_basic_df(*args, **kwargs):
        df = MagicMock()
        df.empty = False
        iloc = MagicMock()
        iloc.__getitem__.return_value = {
            "ts_code": "600519.SH",
            "pe_ttm": 25.5,
            "pb": 6.2,
            "ps_ttm": 8.1,
            "total_mv": 2.27e12,
            "circ_mv": 2.27e12,
        }
        df.iloc = iloc
        return df

    def make_sort_df(*args, **kwargs):
        df = MagicMock()
        df.empty = False
        # sort_values returns self
        df.sort_values = MagicMock(return_value=df)
        df.tail = MagicMock(return_value=[{"trade_date": "20260610"}])
        # to_dict for compat
        df.to_dict = MagicMock(return_value=[{"trade_date": "20260610"}])
        return df

    provider._pro.daily.side_effect = make_daily_df
    provider._pro.index_daily.side_effect = make_index_df
    provider._pro.daily_basic.side_effect = make_basic_df
    return provider


@pytest.fixture
def tdx_provider():
    return TdxQuoteProvider(api_url="http://localhost:8300")


@pytest.fixture
def akshare_provider():
    return AKShareQuoteProvider()


# ──────────────────────────────────────────────
# Tests: QuoteProvider ABC
# ──────────────────────────────────────────────


class TestQuoteProviderABC:
    """抽象接口一致性测试"""

    def test_all_abstract_methods_defined(self):
        methods = [
            "get_realtime_quote",
            "get_batch_realtime",
            "get_index_realtime",
            "get_daily_kline",
            "get_fundamental",
        ]
        for m in methods:
            assert hasattr(QuoteProvider, m), f"Missing: {m}"
            assert getattr(QuoteProvider, m).__isabstractmethod__, f"{m} not abstract"

    def test_concrete_implementations_exist(self):
        assert issubclass(TushareQuoteProvider, QuoteProvider)
        assert issubclass(TdxQuoteProvider, QuoteProvider)
        assert issubclass(AKShareQuoteProvider, QuoteProvider)


# ──────────────────────────────────────────────
# Tests: TushareQuoteProvider
# ──────────────────────────────────────────────


class TestTushareQuoteProvider:
    def test_name(self, tushare_provider):
        assert tushare_provider.name() == "tushare"

    def test_get_realtime_quote(self, tushare_provider):
        result = tushare_provider.get_realtime_quote("600519.SH")
        assert result["ts_code"] == "600519.SH"
        assert result["price"] == 1810.0
        assert result["pct_change"] == 1.12
        assert result["source"] == "tushare"

    def test_get_realtime_quote_empty(self, tushare_provider):
        def empty_df(*a, **kw):
            df = MagicMock()
            df.empty = True
            return df

        tushare_provider._pro.daily.side_effect = empty_df
        result = tushare_provider.get_realtime_quote("999999.XS")
        assert result["price"] == 0.0

    def test_get_index_realtime(self, tushare_provider):
        results = tushare_provider.get_index_realtime(["000001.SH"])
        assert len(results) >= 1
        assert results[0]["code"] == "000001"
        assert results[0]["price"] == 3600.0

    def test_get_daily_kline(self, tushare_provider):
        def good_kline(*a, **kw):
            df = MagicMock()
            df.empty = False
            df.sort_values = MagicMock(return_value=df)
            df.tail = MagicMock(return_value=df)
            df.to_dict = MagicMock(return_value=[{"trade_date": "20260610", "close": 1810.0}])
            return df

        tushare_provider._pro.daily.side_effect = good_kline
        results = tushare_provider.get_daily_kline("600519.SH", limit=10)
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["close"] == 1810.0

    def test_get_fundamental(self, tushare_provider):
        result = tushare_provider.get_fundamental("600519.SH")
        assert result["pe_ttm"] == 25.5
        assert result["pb"] == 6.2

    def test_init_without_token(self):
        provider = TushareQuoteProvider()
        result = provider.get_realtime_quote("600519.SH")
        assert result["ts_code"] == "600519.SH"
        assert result["price"] == 0.0


# ──────────────────────────────────────────────
# Tests: TdxQuoteProvider
# ──────────────────────────────────────────────


class TestTdxQuoteProvider:
    def test_name(self, tdx_provider):
        assert tdx_provider.name() == "tdx"

    def test_normalize_code(self, tdx_provider):
        assert tdx_provider._normalize_code("600519") == "600519.SH"
        assert tdx_provider._normalize_code("000001") == "000001.SZ"
        assert tdx_provider._normalize_code("300001") == "300001.SZ"
        assert tdx_provider._normalize_code("000001.SZ") == "000001.SZ"
        assert tdx_provider._normalize_code("899050") == "899050.BJ"

    @patch("shared.quote_provider.TdxQuoteProvider._call_mcp")
    def test_get_realtime_quote(self, mock_call, tdx_provider):
        mock_call.return_value = [
            {
                "code": "000001",
                "name": "Ping An Bank",
                "price": 12.5,
                "open": 12.4,
                "high": 12.6,
                "low": 12.3,
                "pre_close": 12.4,
                "change": 0.1,
                "pct_change": 0.81,
                "volume": 50000000,
                "amount": 6.25e8,
            }
        ]
        result = tdx_provider.get_realtime_quote("000001.SZ")
        assert result["price"] == 12.5
        assert result["pct_change"] == 0.81
        assert result["source"] == "tdx"

    @patch("shared.quote_provider.TdxQuoteProvider._call_mcp")
    def test_get_realtime_quote_fallback_empty(self, mock_call, tdx_provider):
        mock_call.return_value = None
        result = tdx_provider.get_realtime_quote("000001.SZ")
        assert result["price"] == 0.0

    @patch("shared.quote_provider.TdxQuoteProvider._call_mcp")
    def test_get_index_realtime(self, mock_call, tdx_provider):
        mock_call.return_value = [
            {
                "code": "000001.SH",
                "name": "SSE Composite",
                "price": 3600.0,
                "pct_change": 0.35,
            }
        ]
        results = tdx_provider.get_index_realtime(["000001.SH"])
        assert len(results) == 1
        assert results[0]["price"] == 3600.0

    @patch("shared.quote_provider.TdxQuoteProvider._call_mcp")
    def test_get_daily_kline_dict(self, mock_call, tdx_provider):
        mock_call.return_value = [
            {
                "date": "20260610",
                "open": 1800.0,
                "high": 1820.0,
                "low": 1790.0,
                "close": 1810.0,
                "volume": 5000000,
                "amount": 9.05e9,
            }
        ]
        results = tdx_provider.get_daily_kline("600519.SH", limit=10)
        assert len(results) == 1
        assert results[0]["close"] == 1810.0

    @patch("shared.quote_provider.TdxQuoteProvider._call_mcp")
    def test_get_daily_kline_list(self, mock_call, tdx_provider):
        mock_call.return_value = [
            [20260610, 1800.0, 1820.0, 1790.0, 1810.0, 5000000, 9.05e9],
        ]
        results = tdx_provider.get_daily_kline("600519.SH", limit=10)
        assert len(results) == 1
        assert results[0]["close"] == 1810.0

    @patch("shared.quote_provider.TdxQuoteProvider._call_mcp")
    def test_get_fundamental(self, mock_call, tdx_provider):
        mock_call.return_value = {
            "pe_ttm": 25.5,
            "pb": 6.2,
            "total_mv": 2.27e12,
            "circ_mv": 2.27e12,
        }
        result = tdx_provider.get_fundamental("600519.SH")
        assert result["pe_ttm"] == 25.5

    def test_init_without_config(self):
        provider = TdxQuoteProvider()
        result = provider.get_realtime_quote("000001.SZ")
        assert result["price"] == 0.0

    @patch("httpx.post")
    def test_http_api_success(self, mock_post, tdx_provider):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"code": "000001", "price": 12.5, "pct_change": 0.81}]
        }
        mock_post.return_value = mock_resp
        result = tdx_provider._call_mcp("get_quotes", {"codes": ["000001"]})
        assert result is not None
        assert result[0]["price"] == 12.5

    @patch("httpx.post")
    def test_http_api_fallback(self, mock_post, tdx_provider):
        mock_post.side_effect = Exception("connection refused")
        result = tdx_provider._call_mcp("get_quotes", {"codes": ["000001"]})
        assert result is None


# ──────────────────────────────────────────────
# Tests: AKShareQuoteProvider
# ──────────────────────────────────────────────


class TestAKShareQuoteProvider:
    @pytest.fixture(autouse=True)
    def _mock_modules(self):
        """每个测试前 mock numpy/pandas/akshare，测试后自动恢复。

        避免模块级 mock 污染整个 pytest 会话中的其他测试文件
        （TypeError: isinstance() arg 2 must be a type）。
        """
        self._mock_ak = MagicMock()
        patcher = patch.dict(
            "sys.modules",
            {"numpy": MagicMock(), "pandas": MagicMock(), "akshare": self._mock_ak},
            clear=False,
        )
        patcher.start()
        yield
        patcher.stop()

    def test_name(self, akshare_provider):
        assert akshare_provider.name() == "akshare"

    def test_get_realtime_quote(self, akshare_provider):
        """AKShare 实时行情获取"""
        row_data = {
            "代码": "600519",
            "名称": "Moutai",
            "最新价": 1810.0,
            "今开": 1800.0,
            "最高": 1820.0,
            "最低": 1790.0,
            "昨收": 1790.0,
            "涨跌额": 20.0,
            "涨跌幅": 1.12,
            "成交量": 5000000,
            "成交额": 9.05e9,
        }
        mock_row = MagicMock()
        mock_row.get = lambda k, d=0: row_data.get(k, d)

        # 使用普通对象替代 MagicMock 的 __getitem__
        filtered_row_mock = MagicMock()
        filtered_row_mock.get = mock_row.get
        filtered_row_mock.empty = False

        # iloc[0] -> mock_row
        class FakeIloc:
            def __getitem__(self, idx):
                return mock_row

        filtered_row_mock.iloc = FakeIloc()

        # df['代码'] -> filtered_row_mock
        class FakeDF:
            def __getitem__(self, key):
                return filtered_row_mock

        mock_main_df = FakeDF()

        self._mock_ak.stock_zh_a_spot_em.return_value = mock_main_df

        result = akshare_provider.get_realtime_quote("600519.SH")
        assert result["price"] == 1810.0
        assert result["pct_change"] == 1.12
        assert result["source"] == "akshare"

    def test_get_realtime_quote_no_data(self, akshare_provider):
        self._mock_ak.stock_zh_a_spot_em.return_value = __import__("unittest").mock.MagicMock()
        self._mock_ak.stock_zh_a_spot_em.return_value.empty = True
        mock_result = akshare_provider.get_realtime_quote("999999.XS")
        assert mock_result["price"] == 0.0

    def test_get_index_realtime(self, akshare_provider):
        mock_df = MagicMock()
        mock_df.empty = False
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda k: {
            "代码": "000001",
            "名称": "SSE",
            "最新价": 3600.0,
            "涨跌幅": 0.35,
        }.get(k, 0)
        mock_df.iloc = MagicMock()
        mock_df.iloc.__getitem__.return_value = mock_row
        self._mock_ak.stock_zh_index_spot_em.return_value = mock_df

        results = akshare_provider.get_index_realtime(["000001.SH"])
        assert len(results) >= 1
        assert results[0]["code"] == "000001"


# ──────────────────────────────────────────────
# Tests: QuoteProviderFactory
# ──────────────────────────────────────────────


class TestQuoteProviderFactory:
    def test_default_provider(self):
        factory = QuoteProviderFactory(default_source="tushare")
        provider = factory.default
        assert provider.name() == "tushare"
        assert isinstance(provider, TushareQuoteProvider)

    def test_get_provider_by_name(self):
        factory = QuoteProviderFactory()
        tdx = factory.get_provider("tdx")
        assert isinstance(tdx, TdxQuoteProvider)
        assert factory.get_provider("tushare").name() == "tushare"
        assert factory.get_provider("akshare").name() == "akshare"

    def test_get_provider_caches_instance(self):
        factory = QuoteProviderFactory()
        p1 = factory.get_provider("tushare")
        p2 = factory.get_provider("tushare")
        assert p1 is p2

    def test_set_default_source(self):
        factory = QuoteProviderFactory(default_source="tushare")
        assert factory._default_source == "tushare"
        factory.set_default_source("tdx")
        assert factory._default_source == "tdx"
        assert factory.default.name() == "tdx"

    def test_set_default_source_invalid(self):
        factory = QuoteProviderFactory()
        factory.set_default_source("nonexistent")
        assert factory._default_source in ("tushare",)

    def test_register_custom(self):
        factory = QuoteProviderFactory()

        class MockProvider(QuoteProvider):
            def get_realtime_quote(self, ts_code):
                return {}

            def get_batch_realtime(self, codes):
                return []

            def get_index_realtime(self, codes=None):
                return []

            def get_daily_kline(self, code, **kw):
                return []

            def get_fundamental(self, code):
                return {}

            def name(self):
                return "mock"

        factory.register("mock", MockProvider)
        assert isinstance(factory.get_provider("mock"), MockProvider)

    def test_unknown_source_fallback(self):
        factory = QuoteProviderFactory(default_source="unknown")
        assert factory.get_provider("tushare") is not None


# ──────────────────────────────────────────────
# Tests: Global Functions
# ──────────────────────────────────────────────


class TestGlobalFunctions:
    def teardown_method(self):
        from shared.quote_provider import factory as _qp_factory

        _qp_factory._factory = None

    @patch.dict(os.environ, {"QTS_DATA_SOURCE": "tushare"})
    def test_get_quote_provider_default(self):
        from shared.quote_provider import factory as _qp_factory

        _qp_factory._factory = None
        assert get_quote_provider() is not None

    def test_set_data_source(self):
        set_data_source("tdx")
        assert get_quote_provider() is not None
