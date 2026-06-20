"""
DataService v4 单元测试

测试策略：
- 所有外部依赖（QuoteProvider 各子类）被 mock
- 内部 Repository 层通过 MockRepo + 真实 SQLite 双模式覆盖
- 降级链行为通过 mock provider 返回值控制

关键假设:
- conftest.py 已设置 DATABASE_URL=sqlite:///quant_trading.db
- 系统时间：2026-06（测试中日期固定）
"""

from datetime import datetime, timedelta
import sys
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

# ── conftest.py 已处理 sys.path，此处仅做防御性补入 ──
sys.path.insert(0, ".")


# =============================================================================
# Fixtures — Mock Provider
# =============================================================================


@pytest.fixture
def mock_factory():
    """Mock QuoteProviderFactory — 所有 provider 方法返回预设数据"""
    with patch("shared.quote_provider.QuoteProviderFactory") as mock_factory_cls:
        # 构造 mock factory 实例
        factory = MagicMock()
        mock_factory_cls.return_value = factory

        # mock default provider
        default = MagicMock()
        factory.default = default
        type(factory).default_source = PropertyMock(return_value="tushare")

        # mock get_provider — 返回 default 的副本
        factory.get_provider.return_value = default

        yield factory, default


@pytest.fixture
def mock_empty_provider():
    """Mock provider 所有方法返回空/None — 触发降级链"""
    with patch("shared.quote_provider.QuoteProviderFactory") as mock_factory_cls:
        factory = MagicMock()
        mock_factory_cls.return_value = factory

        empty = MagicMock()
        empty.get_realtime_quote.return_value = {}
        empty.get_batch_realtime.return_value = []
        empty.get_daily_kline.return_value = []
        empty.get_index_realtime.return_value = []
        empty.get_fundamental.return_value = {}

        factory.default = empty
        type(factory).default_source = PropertyMock(return_value="tushare")
        factory.get_provider.return_value = empty

        yield factory, empty


@pytest.fixture
def mock_quote_row():
    """标准行情返回行"""
    return {
        "ts_code": "000001.SZ",
        "name": "平安银行",
        "price": 12.50,
        "pct_change": 2.35,
        "volume": 50000000,
        "amount": 625000000.0,
        "high": 12.65,
        "low": 12.20,
        "open": 12.30,
        "close": 12.50,
        "pre_close": 12.22,
        "change": 0.28,
        "timestamp": "2026-06-18T10:30:00",
    }


@pytest.fixture
def mock_kline_rows():
    """5 条日线数据"""
    return [
        {
            "trade_date": "20260610",
            "open": 12.10,
            "high": 12.40,
            "low": 12.05,
            "close": 12.30,
            "pre_close": 12.20,
            "change": 0.10,
            "pct_chg": 0.82,
            "vol": 45000000,
            "amount": 5.4e8,
        },
        {
            "trade_date": "20260611",
            "open": 12.30,
            "high": 12.50,
            "low": 12.10,
            "close": 12.15,
            "pre_close": 12.30,
            "change": -0.15,
            "pct_chg": -1.22,
            "vol": 52000000,
            "amount": 6.3e8,
        },
        {
            "trade_date": "20260612",
            "open": 12.15,
            "high": 12.60,
            "low": 12.10,
            "close": 12.50,
            "pre_close": 12.15,
            "change": 0.35,
            "pct_chg": 2.88,
            "vol": 48000000,
            "amount": 5.9e8,
        },
        {
            "trade_date": "20260615",
            "open": 12.50,
            "high": 12.70,
            "low": 12.30,
            "close": 12.35,
            "pre_close": 12.50,
            "change": -0.15,
            "pct_chg": -1.20,
            "vol": 55000000,
            "amount": 6.8e8,
        },
        {
            "trade_date": "20260616",
            "open": 12.35,
            "high": 12.60,
            "low": 12.25,
            "close": 12.50,
            "pre_close": 12.35,
            "change": 0.15,
            "pct_chg": 1.21,
            "vol": 50000000,
            "amount": 6.2e8,
        },
    ]


@pytest.fixture
def mock_index_rows():
    """指数行情"""
    return [
        {"code": "000001", "name": "上证指数", "price": 3600.0, "pct_change": 0.35},
        {"code": "399001", "name": "深证成指", "price": 12000.0, "pct_change": -0.42},
        {"code": "399006", "name": "创业板指", "price": 2500.0, "pct_change": 1.12},
    ]


# =============================================================================
# Helper — 构造 DataService 实例（避免 tushare 初始化）
# =============================================================================


def make_ds(tushare_token=None, data_source=None):
    """构造 DataService（不再依赖 _init_tushare_pro mock）"""
    from services.data_service import DataService

    return DataService(tushare_token=tushare_token or "", data_source=data_source or "tushare")


# =============================================================================
# 基本构造
# =============================================================================


class TestDataServiceInit:
    """初始化测试"""

    def test_basic_init(self):
        """构造 DataService 实例不报错"""
        ds = make_ds()
        assert ds is not None
        assert ds._factory is not None

    def test_init_with_source(self):
        """指定数据源构造"""
        ds = make_ds(data_source="tdx")
        assert ds is not None

    def test_set_data_source(self):
        """动态切换数据源"""
        ds = make_ds()
        ds._factory = MagicMock()
        ds.set_data_source("akshare")
        ds._factory.set_default_source.assert_called_once_with("akshare")


# =============================================================================
# Provider 代理方法
# =============================================================================


class TestProviderProxies:
    """直接代理到 default provider 的方法"""

    def test_get_stock_realtime_quote_success(self, mock_factory, mock_quote_row):
        """正常获取单只股票行情"""
        factory, default = mock_factory
        default.get_realtime_quote.return_value = mock_quote_row

        ds = make_ds()
        ds._factory = factory

        result = ds.get_stock_realtime_quote("000001.SZ")
        default.get_realtime_quote.assert_called_once_with("000001.SZ")
        assert result["price"] == 12.50
        assert result["ts_code"] == "000001.SZ"

    def test_get_stock_realtime_quote_failure(self, mock_factory):
        """Provider 失败 → 返回空行情兜底"""
        factory, default = mock_factory
        default.get_realtime_quote.side_effect = Exception("API timeout")

        ds = make_ds()
        ds._factory = factory

        result = ds.get_stock_realtime_quote("000001.SZ")
        assert result["price"] == 0  # empty quote
        assert result["ts_code"] == "000001.SZ"

    def test_get_stock_batch_realtime_success(self, mock_factory, mock_quote_row):
        """批量获取行情"""
        factory, default = mock_factory
        codes = ["000001.SZ", "000858.SZ"]
        default.get_batch_realtime.return_value = [
            mock_quote_row,
            {**mock_quote_row, "ts_code": "000858.SZ"},
        ]

        ds = make_ds()
        ds._factory = factory

        result = ds.get_stock_batch_realtime(codes)
        assert len(result) == 2

    def test_get_stock_batch_realtime_failure(self, mock_factory):
        """批量获取行情失败 → 空行情列表"""
        factory, default = mock_factory
        default.get_batch_realtime.side_effect = Exception("timeout")

        ds = make_ds()
        ds._factory = factory

        result = ds.get_stock_batch_realtime(["000001.SZ"])
        assert len(result) == 1
        assert result[0]["price"] == 0

    def test_get_stock_fundamental_success(self, mock_factory):
        """获取基本面数据"""
        factory, default = mock_factory
        default.get_fundamental.return_value = {
            "ts_code": "000001.SZ",
            "pe_ttm": 8.5,
            "pb": 1.2,
            "total_mv": 2.5e11,
            "circ_mv": 2.0e11,
        }

        ds = make_ds()
        ds._factory = factory

        result = ds.get_stock_fundamental("000001.SZ")
        assert result["pe_ttm"] == 8.5


# =============================================================================
# 降级链方法
# =============================================================================


class TestFallbackChain:
    """多数据源自动降级行为"""

    def test_get_index_realtime_success(self, mock_factory, mock_index_rows):
        """正常获取指数行情"""
        factory, default = mock_factory
        default.get_index_realtime.return_value = mock_index_rows

        ds = make_ds()
        ds._factory = factory

        result = ds.get_index_realtime_quote()
        assert len(result) == 3
        assert result[0]["price"] == 3600.0

    def test_get_index_realtime_fallback_to_tencent(self, mock_factory):
        """Primary 失败 → 降级到腾讯财经"""
        factory, default = mock_factory
        default.get_index_realtime.side_effect = Exception("provider down")
        # get_provider 也要失败，迫使走到 _fetch_index_via_tencent
        factory.get_provider.return_value = None

        ds = make_ds()
        ds._factory = factory

        # mock _fetch_index_via_tencent 返回模拟数据
        with patch.object(
            type(ds),
            "_fetch_index_via_tencent",
            return_value=[
                {"code": "000001", "name": "上证指数", "price": 3600.0, "pct_change": 0.35}
            ],
        ):
            result = ds.get_index_realtime_quote()
            assert len(result) == 1
            assert result[0]["price"] == 3600.0

    def test_get_index_realtime_all_fail(self, mock_factory):
        """所有数据源均失败 → 零值兜底"""
        factory, default = mock_factory
        default.get_index_realtime.side_effect = Exception("fail")
        factory.get_provider.return_value = None

        ds = make_ds()
        ds._factory = factory

        with patch.object(type(ds), "_fetch_index_via_tencent", return_value=[]):
            result = ds.get_index_realtime_quote()
        # 8 个指数，全部零值
        assert len(result) == 8
        assert all(r["price"] == 0.0 for r in result)

    def test_get_stock_daily_quote_success(self, mock_factory, mock_kline_rows):
        """获取日线行情"""
        factory, default = mock_factory
        default.get_daily_kline.return_value = mock_kline_rows

        ds = make_ds()
        ds._factory = factory

        result = ds.get_stock_daily_quote("000001.SZ")
        assert len(result) == 5

    def test_get_stock_daily_quote_db_first(self, mock_factory, mock_kline_rows):
        """优先从 DB 读取（mock DB 返回数据，provider 不应被调用）"""
        factory, default = mock_factory

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo

            # DB 返回有效数据
            db_rows = [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "2026-06-10",
                    "open": 12.10,
                    "close": 12.30,
                    "high": 12.40,
                    "low": 12.05,
                    "pre_close": 12.20,
                    "change": 0.10,
                    "pct_chg": 0.82,
                    "vol": 45000000,
                    "amount": 5.4e8,
                }
            ]
            mock_repo.select_daily_quote.return_value = db_rows

            result = ds.get_stock_daily_quote("000001.SZ", "20260601", "20260630")

            mock_repo.select_daily_quote.assert_called_once()
            default.get_daily_kline.assert_not_called()  # DB 命中，不走 provider

    def test_get_stock_daily_quote_db_fallback(self, mock_factory, mock_kline_rows):
        """DB 无数据 → 降级到 provider"""
        factory, default = mock_factory
        default.get_daily_kline.return_value = mock_kline_rows

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.select_daily_quote.return_value = None  # DB 无数据

            result = ds.get_stock_daily_quote("000001.SZ", "20260601", "20260630")
            assert len(result) == 5  # fallback 成功

    def test_get_stock_daily_quote_all_fail(self, mock_factory):
        """所有源均失败 → 空列表"""
        factory, default = mock_factory
        default.get_daily_kline.return_value = []
        factory.get_provider.return_value = default  # single source

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.select_daily_quote.return_value = None

            result = ds.get_stock_daily_quote("000001.SZ", "20260601", "20260630")
            assert result == []


# =============================================================================
# 股票池操作
# =============================================================================


class TestStockPool:
    """股票池查询"""

    def test_get_stock_pool_from_db(self, mock_factory):
        """从 DB stock_pool 表读取"""
        ds = make_ds()
        ds._factory = mock_factory[0]

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.select_stock_pool.return_value = [
                {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "market": "主板"},
                {"ts_code": "000858.SZ", "name": "五粮液", "industry": "白酒", "market": "主板"},
            ]

            result = ds.get_stock_pool()
            assert len(result) == 2

    def test_get_stock_pool_with_industry_filter(self, mock_factory):
        """按行业过滤股票池"""
        ds = make_ds()
        ds._factory = mock_factory[0]

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.select_stock_pool.return_value = [
                {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "market": "主板"},
                {"ts_code": "000858.SZ", "name": "五粮液", "industry": "白酒", "market": "主板"},
            ]

            result = ds.get_stock_pool(industry="白酒")
            assert len(result) == 1
            assert result[0]["ts_code"] == "000858.SZ"

    def test_get_stock_pool_db_empty(self, mock_factory):
        """DB 为空 → 返回空（无降级数据源）"""
        ds = make_ds()
        ds._factory = mock_factory[0]

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.select_stock_pool.return_value = []

            result = ds.get_stock_pool()
            assert result == []


# =============================================================================
# 数据同步 (sync_daily_data)
# =============================================================================


class TestSyncDailyData:
    """数据同步流程"""

    def test_sync_with_explicit_symbols(self, mock_factory, mock_kline_rows):
        """显式指定标的列表"""
        factory, default = mock_factory
        default.get_daily_kline.return_value = mock_kline_rows

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.upsert_daily_quote.return_value = 5

            result = ds.sync_daily_data(symbols=["000001.SZ"], days=5)
            assert result["synced"] == 1
            assert result["failed"] == 0

    def test_sync_empty_symbols(self, mock_factory):
        """无标的 → 空结果"""
        ds = make_ds()
        ds._factory = mock_factory[0]

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = []

            result = ds.sync_daily_data(symbols=None, days=5)
            assert result["synced"] == 0
            assert result["failed"] == 0

    def test_sync_partial_failure(self, mock_factory, mock_kline_rows):
        """部分标的同步失败 — 继续处理后续"""
        factory, default = mock_factory
        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo

            # 第一个 symbol 的 get_stock_daily_quote 抛出异常
            original_get = ds.get_stock_daily_quote

            def side_effect(ts_code, *args, **kwargs):
                if ts_code == "000001.SZ":
                    return mock_kline_rows
                raise Exception("API error")

            ds.get_stock_daily_quote = MagicMock(side_effect=side_effect)

            result = ds.sync_daily_data(symbols=["000001.SZ", "000858.SZ"], days=5)
            # 第一个成功 upsert，第二个获取数据失败
            assert result["synced"] == 1
            assert result["failed"] == 1
            assert len(result["errors"]) == 1


# =============================================================================
# scan_market / review / helper
# =============================================================================


class TestMarketScan:
    """全市场扫描"""

    def test_scan_market_with_symbols(self, mock_factory, mock_quote_row):
        """正常扫描 — 从 stock_pool 获取标的"""
        factory, default = mock_factory
        default.get_batch_realtime.return_value = [
            {**mock_quote_row, "ts_code": "000001.SZ", "pct_change": 2.5},
            {**mock_quote_row, "ts_code": "000858.SZ", "pct_change": -1.2},
        ]

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = ["000001.SZ", "000858.SZ"]

            result = ds.scan_market(top_n=20)
            assert len(result) >= 1
            # pct_change > 0 的股票标记为 BUY
            buy_items = [r for r in result if r["signal"] == "BUY"]
            assert len(buy_items) >= 1

    def test_scan_market_empty_symbols(self, mock_factory):
        """无标的 → 空结果"""
        factory, default = mock_factory

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = []

            result = ds.scan_market(top_n=20)
            assert result == []


class TestReview:
    """每日复盘"""

    def test_generate_review_success(self, mock_factory, mock_index_rows):
        """正常生成复盘数据"""
        factory, default = mock_factory
        default.get_index_realtime.return_value = mock_index_rows

        ds = make_ds()
        ds._factory = factory

        result = ds.generate_review("2026-06-18")
        assert result["date"] == "2026-06-18"
        assert result["summary"]["sh_close"] == 3600.0
        assert result["summary"]["sh_pct"] == pytest.approx(0.0035)  # 0.35/100

    def test_generate_review_failure(self, mock_empty_provider):
        """指数获取失败 → 零值兜底"""
        ds = make_ds()
        ds._factory = mock_empty_provider[0]

        # mock 掉腾讯财经兜底，模拟全部失败
        with patch.object(type(ds), "_fetch_index_via_tencent", return_value=[]):
            result = ds.generate_review("2026-06-18")
            assert result["date"] == "2026-06-18"
            assert result["summary"]["sh_close"] == 0.0  # 零值兜底
            assert result["summary"]["sh_pct"] == 0.0


class TestDeprecatedApi:
    """废弃 API 兼容性"""

    def test_deprecated_pro_property(self, mock_factory):
        """访问 deprecation pro 属性 → 记录 warning 不崩溃"""
        ds = make_ds()
        # pro 是 @property 但返回 None，仅记录 warning
        assert ds.pro is None


class TestReviewException:
    """复盘异常路径"""

    def test_generate_review_raises_exception_caught(self, mock_factory):
        """get_index_realtime_quote 抛异常 → except 捕获返回 {}"""
        factory, default = mock_factory

        ds = make_ds()
        ds._factory = factory

        # 让降级链全部抛异常
        default.get_index_realtime.side_effect = RuntimeError("provider crash")
        with patch.object(
            type(ds), "_fetch_index_via_tencent", side_effect=ConnectionError("tencent down")
        ):
            result = ds.generate_review("2026-06-18")
            assert result == {}  # except 分支返回空 dict


class TestHelpers:
    """辅助方法"""

    def test_get_name_known(self):
        """已知股票代码 → 返回中文名"""
        ds = make_ds()
        assert ds._get_name("600519.SH") == "贵州茅台"

    def test_get_name_unknown(self):
        """未知代码 → 返回代码本身"""
        ds = make_ds()
        assert ds._get_name("999999.XX") == "999999.XX"

    def test_empty_quote_format(self, mock_factory):
        """空行情兜底格式"""
        ds = make_ds()
        ds._factory = mock_factory[0]
        result = ds._empty_quote("000001.SZ")
        assert result["ts_code"] == "000001.SZ"
        assert result["price"] == 0
        assert "timestamp" in result


# =============================================================================
# _call_provider_with_fallback 直接测试
# =============================================================================


class TestFallbackCore:
    """_call_provider_with_fallback 降级链核心逻辑"""

    FAKE_SOURCES = ["tushare", "akshare"]

    @pytest.fixture
    def mock_factory_for_fallback(self):
        with patch("shared.quote_provider.QuoteProviderFactory") as mock_factory_cls:
            factory = MagicMock()
            mock_factory_cls.return_value = factory

            # 模拟 get_provider 根据 source 返回不同 provider
            provider_a = MagicMock()
            provider_a.get_data.return_value = ["result_a"]
            provider_b = MagicMock()
            provider_b.get_data.return_value = ["result_b"]

            def get_provider_side_effect(source):
                mapping = {"first": provider_a, "second": provider_b}
                return mapping.get(source)

            factory.get_provider.side_effect = get_provider_side_effect
            type(factory).default_source = PropertyMock(return_value="first")
            yield factory, provider_a, provider_b

    def _patch_fallback_sources(self):
        """临时替换 FALLBACK_SOURCES 以控制降级链顺序

        注意: data_service.py 使用 from services.data_models import FALLBACK_SOURCES
        """
        return patch(
            "services.data_service.FALLBACK_SOURCES",
            ["first", "second"],
        )

    def test_fallback_first_source_success(self):
        """首源成功 → 直接返回结果，不调用后续源"""
        with self._patch_fallback_sources():
            with patch("shared.quote_provider.QuoteProviderFactory") as mock_factory_cls:
                factory = MagicMock()
                mock_factory_cls.return_value = factory

                provider = MagicMock()
                provider.get_data.return_value = ["success"]
                factory.get_provider.return_value = provider
                type(factory).default_source = PropertyMock(return_value="first")

                ds = make_ds()
                ds._factory = factory

                result = ds._call_provider_with_fallback(
                    lambda p: p.get_data,
                    lambda r: len(r) > 0,
                    "arg1",
                    kwarg1="val1",
                )
                assert result == ["success"]
                provider.get_data.assert_called_once_with("arg1", kwarg1="val1")

    def test_fallback_first_fail_second_success(self):
        """首源失败/无效 → 降级到次源"""
        with self._patch_fallback_sources():
            with patch("shared.quote_provider.QuoteProviderFactory") as mock_factory_cls:
                factory = MagicMock()
                mock_factory_cls.return_value = factory

                provider_a = MagicMock()
                provider_a.get_data.return_value = []  # 无效结果（空列表）
                provider_b = MagicMock()
                provider_b.get_data.return_value = ["fallback_ok"]

                def get_provider_side(source):
                    return {"first": provider_a, "second": provider_b}.get(source)

                factory.get_provider.side_effect = get_provider_side
                type(factory).default_source = PropertyMock(return_value="first")

                ds = make_ds()
                ds._factory = factory

                result = ds._call_provider_with_fallback(
                    lambda p: p.get_data,
                    lambda r: len(r) > 0,
                )
                assert result == ["fallback_ok"]
                provider_b.get_data.assert_called_once()

    def test_fallback_all_sources_fail(self):
        """全部失败 → 返回 None"""
        with self._patch_fallback_sources():
            with patch("shared.quote_provider.QuoteProviderFactory") as mock_factory_cls:
                factory = MagicMock()
                mock_factory_cls.return_value = factory

                provider = MagicMock()
                provider.get_data.return_value = []
                factory.get_provider.return_value = provider
                type(factory).default_source = PropertyMock(return_value="first")

                ds = make_ds()
                ds._factory = factory

                result = ds._call_provider_with_fallback(
                    lambda p: p.get_data,
                    lambda r: len(r) > 0,
                )
                assert result is None

    def test_fallback_validator_rejects(self):
        """validator 返回 False → 继续降级，不返回"""
        with self._patch_fallback_sources():
            with patch("shared.quote_provider.QuoteProviderFactory") as mock_factory_cls:
                factory = MagicMock()
                mock_factory_cls.return_value = factory

                provider_a = MagicMock()
                provider_a.get_data.return_value = ["some_data"]
                provider_b = MagicMock()
                provider_b.get_data.return_value = ["valid_data"]

                def get_provider_side(source):
                    return {"first": provider_a, "second": provider_b}.get(source)

                factory.get_provider.side_effect = get_provider_side
                type(factory).default_source = PropertyMock(return_value="first")

                ds = make_ds()
                ds._factory = factory

                # validator 首源返回 False → 必须降级
                call_count = 0

                def picky_validator(r):
                    nonlocal call_count
                    call_count += 1
                    return call_count > 1  # 第一次 False，第二次 True

                result = ds._call_provider_with_fallback(
                    lambda p: p.get_data,
                    picky_validator,
                )
                assert result == ["valid_data"]

    def test_fallback_provider_none_skipped(self):
        """get_provider 返回 None → 跳过该源"""
        with self._patch_fallback_sources():
            with patch("shared.quote_provider.QuoteProviderFactory") as mock_factory_cls:
                factory = MagicMock()
                mock_factory_cls.return_value = factory

                # 首源返回 None（provider 不可用），次源成功
                provider_b = MagicMock()
                provider_b.get_data.return_value = ["ok"]

                def get_provider_side(source):
                    if source == "first":
                        return None  # 跳过
                    return provider_b

                factory.get_provider.side_effect = get_provider_side
                type(factory).default_source = PropertyMock(return_value="first")

                ds = make_ds()
                ds._factory = factory

                result = ds._call_provider_with_fallback(
                    lambda p: p.get_data,
                    lambda r: len(r) > 0,
                )
                assert result == ["ok"]

    def test_fallback_provider_exception_continue(self):
        """provider 方法抛出异常 → 记录 warning 并继续降级"""
        with self._patch_fallback_sources():
            with patch("shared.quote_provider.QuoteProviderFactory") as mock_factory_cls:
                factory = MagicMock()
                mock_factory_cls.return_value = factory

                provider_a = MagicMock()
                provider_a.get_data.side_effect = Exception("connection refused")
                provider_b = MagicMock()
                provider_b.get_data.return_value = ["recovered"]

                def get_provider_side(source):
                    return {"first": provider_a, "second": provider_b}.get(source)

                factory.get_provider.side_effect = get_provider_side
                type(factory).default_source = PropertyMock(return_value="first")

                ds = make_ds()
                ds._factory = factory

                result = ds._call_provider_with_fallback(
                    lambda p: p.get_data,
                    lambda r: len(r) > 0,
                )
                assert result == ["recovered"]


# =============================================================================
# _fetch_index_via_tencent 直接测试
# =============================================================================


class TestTencentFallback:
    """腾讯财经 HTTP 兜底路径"""

    def test_tencent_parse_success(self):
        """正常解析腾讯财经返回的行情数据"""
        # 格式: v_s_sh000001="1~上证指数~999999~3600.50~3605.00~0.35~..."
        #        fields[3] = 价格, fields[5] = 涨跌幅
        mock_raw = (
            'v_s_sh000001="1~上证指数~999999~3600.50~3605.00~0.35~'
            '3600.50~3610.00~3590.00~500000~1800000000";\n'
            'v_s_sz399001="1~深证成指~999999~12000.30~12050.00~-0.42~'
            '12000.30~12100.00~11980.00~800000~9600000000";\n'
        )

        ds = make_ds()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = mock_raw.encode("gbk")
            mock_urlopen.return_value = mock_response

            result = ds._fetch_index_via_tencent(
                {
                    "000001.SH": "上证指数",
                    "399001.SZ": "深证成指",
                }
            )

        assert len(result) == 2
        assert result[0]["code"] == "000001"
        assert result[0]["name"] == "上证指数"
        assert result[0]["price"] == 3600.50
        assert result[0]["pct_change"] == 0.35
        assert result[1]["price"] == 12000.30
        assert result[1]["pct_change"] == -0.42

    def test_tencent_field_too_few(self):
        """腾讯返回字段不足6个 → 零值兜底"""
        mock_raw = 'v_s_sh000001="1~上证指数~0~3600.50";\n'

        ds = make_ds()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = mock_raw.encode("gbk")
            mock_urlopen.return_value = mock_response

            result = ds._fetch_index_via_tencent({"000001.SH": "上证指数"})
        assert len(result) == 1
        assert result[0]["code"] == "000001"
        assert result[0]["price"] == 0.0
        assert result[0]["pct_change"] == 0.0

    def test_tencent_parse_exception(self):
        """单个指数解析时异常 → 该指数零值兜底，继续处理后续"""
        # 上证 price 字段非数字 → float() 抛异常，零值兜底；深证正常
        mock_raw = (
            'v_s_sh000001="1~上证指数~999999~NOT_A_NUMBER~'
            '0~0~0~0~0~0~0~0~0~0~0~0~0~0";\n'
            'v_s_sz399001="1~深证成指~999999~12000.30~12050.00~-0.42~'
            '12000.30~12100.00~11980.00~800000~9600000000";\n'
        )

        ds = make_ds()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = mock_raw.encode("gbk")
            mock_urlopen.return_value = mock_response

            result = ds._fetch_index_via_tencent(
                {
                    "000001.SH": "上证指数",
                    "399001.SZ": "深证成指",
                }
            )
        # 上证解析异常时返回零值，深证正常
        assert len(result) == 2
        assert result[0]["price"] == 0.0
        assert result[1]["price"] == 12000.30

    def test_tencent_http_error(self):
        """HTTP 请求失败 → 返回空列表"""
        ds = make_ds()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("connection timeout")

            result = ds._fetch_index_via_tencent({"000001.SH": "上证指数"})
        assert result == []


# =============================================================================
# _db_select_daily_quote / _fetch_symbols / _do_db_upsert
# =============================================================================


class TestDbLayer:
    """数据库层辅助方法"""

    def test_db_select_daily_quote_success(self):
        """_db_select_daily_quote 正常返回值"""
        ds = make_ds()
        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.select_daily_quote.return_value = [
                {"ts_code": "000001.SZ", "trade_date": "2026-06-10", "close": 12.5}
            ]

            result = ds._db_select_daily_quote("000001.SZ", "20260601", "20260630")
            assert result is not None
            assert result[0]["ts_code"] == "000001.SZ"
            mock_repo.select_daily_quote.assert_called_once_with(
                "000001.SZ", "2026-06-01", "2026-06-30"
            )

    def test_db_select_daily_quote_exception(self):
        """_db_select_daily_quote 异常 → 返回 None（触发降级）"""
        ds = make_ds()
        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.select_daily_quote.side_effect = Exception("DB connection error")

            result = ds._db_select_daily_quote("000001.SZ", "20260601", "20260630")
            assert result is None

    def test_fetch_symbols_from_pool(self):
        """_fetch_symbols_from_pool 从股票池获取标的"""
        ds = make_ds()
        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = ["000001.SZ", "000858.SZ", "600519.SH"]

            result = ds._fetch_symbols_from_pool()
            assert result == ["000001.SZ", "000858.SZ", "600519.SH"]

    def test_fetch_symbols_from_pool_empty(self):
        """_fetch_symbols_from_pool 空列表"""
        ds = make_ds()
        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = []

            result = ds._fetch_symbols_from_pool()
            assert result == []

    def test_do_db_upsert(self):
        """_do_db_upsert 正确传递参数"""
        ds = make_ds()
        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo

            test_rows = [{"trade_date": "20260610", "close": 12.5}]
            ds._do_db_upsert("000001.SZ", test_rows)
            mock_repo.upsert_daily_quote.assert_called_once_with("000001.SZ", test_rows)


# =============================================================================
# get_stock_fundamental 异常路径
# =============================================================================


class TestFundamentalFailure:
    """基本面数据异常路径"""

    def test_get_stock_fundamental_failure(self):
        """provider 抛出异常 → 返回空字典"""
        with patch("shared.quote_provider.QuoteProviderFactory") as mock_factory_cls:
            factory = MagicMock()
            mock_factory_cls.return_value = factory
            default = MagicMock()
            default.get_fundamental.side_effect = Exception("API rate limit")
            factory.default = default
            type(factory).default_source = PropertyMock(return_value="tushare")

            ds = make_ds()
            ds._factory = factory

            result = ds.get_stock_fundamental("000001.SZ")
            assert result == {}

    def test_get_stock_fundamental_empty(self):
        """provider 返回空字典 → 透传空字典"""
        with patch("shared.quote_provider.QuoteProviderFactory") as mock_factory_cls:
            factory = MagicMock()
            mock_factory_cls.return_value = factory
            default = MagicMock()
            default.get_fundamental.return_value = {}
            factory.default = default
            type(factory).default_source = PropertyMock(return_value="tushare")

            ds = make_ds()
            ds._factory = factory

            result = ds.get_stock_fundamental("000001.SZ")
            assert result == {}


# =============================================================================
# sync_daily_data 补充场景
# =============================================================================


class TestSyncDailyDataExtended:
    """sync_daily_data 补充测试场景"""

    def test_sync_from_pool_auto(self, mock_factory, mock_kline_rows):
        """symbols=None → 自动从 pool 获取标的"""
        factory, default = mock_factory
        default.get_daily_kline.return_value = mock_kline_rows

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = ["000001.SZ", "000858.SZ"]
            mock_repo.select_daily_quote.return_value = None  # 跳过 DB，走 provider
            mock_repo.upsert_daily_quote.return_value = 5

            result = ds.sync_daily_data(symbols=None, days=30)
            assert result["synced"] == 2
            assert result["failed"] == 0

    def test_sync_empty_data_no_upsert(self, mock_factory):
        """某标的获取数据为空 → failed 计数"""
        factory, default = mock_factory
        default.get_daily_kline.return_value = []

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = ["000001.SZ"]
            mock_repo.select_daily_quote.return_value = None  # 跳过 DB

            result = ds.sync_daily_data(symbols=None, days=30)
            assert result["synced"] == 0
            assert result["failed"] == 1  # 无数据 → failed
            assert len(result["errors"]) == 0

    def test_sync_exception_during_fetch(self, mock_factory):
        """获取数据时 provider 内部异常 → 所有源失败 → 空数据 → failed 计数"""
        factory, default = mock_factory
        default.get_daily_kline.side_effect = Exception("API timeout after 30s")

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = ["000001.SZ"]
            mock_repo.select_daily_quote.return_value = None  # 跳过 DB

            result = ds.sync_daily_data(symbols=None, days=30)
            assert result["synced"] == 0
            assert result["failed"] == 1  # provider 异常被内部捕获，返回空数据
            # 注意: provider 异常在 get_stock_daily_quote 内部被捕获，
            # 不传播到 sync_daily_data 的 except 块，因此 errors 为空


# =============================================================================
# get_stock_daily_quote — DB 异常降级链路
# =============================================================================


class TestDailyQuoteDbException:
    """DB 层异常后降级到 provider"""

    def test_db_exception_triggers_provider(self, mock_factory, mock_kline_rows):
        """DB 查询抛异常 → 降级到 provider"""
        factory, default = mock_factory
        default.get_daily_kline.return_value = mock_kline_rows

        ds = make_ds()
        ds._factory = factory

        with patch.object(ds, "_db_select_daily_quote") as mock_db:
            mock_db.return_value = None  # DB 无数据

            result = ds.get_stock_daily_quote("000001.SZ", "20260601", "20260630")
            assert len(result) == 5
            default.get_daily_kline.assert_called_once()


# =============================================================================
# scan_market 降级路径 & strategy_filter
# =============================================================================


class TestMarketScanExtended:
    """scan_market 补充测试"""

    def test_scan_market_with_strategy_filter(self, mock_factory, mock_quote_row):
        """strategy_filter 传递给候选结果"""
        factory, default = mock_factory
        default.get_batch_realtime.return_value = [
            {**mock_quote_row, "ts_code": "000001.SZ", "pct_change": 2.5},
        ]

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = ["000001.SZ"]

            result = ds.scan_market(top_n=20, strategy_filter="momentum")
            assert result[0]["strategy_name"] == "momentum"

    def test_scan_market_strategy_all_default(self, mock_factory, mock_quote_row):
        """strategy_filter='all' → 使用默认策略名 multi-factor"""
        factory, default = mock_factory
        default.get_batch_realtime.return_value = [
            {**mock_quote_row, "ts_code": "000001.SZ", "pct_change": 2.5},
        ]

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = ["000001.SZ"]

            result = ds.scan_market(top_n=20, strategy_filter="all")
            assert result[0]["strategy_name"] == "multi-factor"

    def test_scan_market_batch_empty(self, mock_factory):
        """batch_realtime 返回空 → 空结果"""
        factory, default = mock_factory
        default.get_batch_realtime.return_value = []

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = ["000001.SZ"]

            result = ds.scan_market(top_n=20)
            assert result == []

    def test_scan_market_top_n_truncation(self, mock_factory, mock_quote_row):
        """top_n 参数正确截断结果"""
        factory, default = mock_factory
        rows = []
        for i in range(10):
            r = {**mock_quote_row, "ts_code": f"000{i:03d}.SZ", "pct_change": float(i)}
            rows.append(r)
        default.get_batch_realtime.return_value = rows

        ds = make_ds()
        ds._factory = factory

        with patch("repositories.daily_quote_repo.DailyQuoteRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.fetch_symbols.return_value = [f"000{i:03d}.SZ" for i in range(10)]

            result = ds.scan_market(top_n=3)
            assert len(result) == 3


# =============================================================================
# generate_review 降级路径
# =============================================================================


class TestReviewExtended:
    """每日复盘补充测试"""

    def test_generate_review_partial_index(self, mock_factory):
        """只返回部分指数数据 → 缺失字段零值兜底"""
        factory, default = mock_factory
        default.get_index_realtime.return_value = [
            {"code": "000001", "name": "上证指数", "price": 3600.0, "pct_change": 0.35},
        ]

        ds = make_ds()
        ds._factory = factory

        result = ds.generate_review("2026-06-18")
        assert result["date"] == "2026-06-18"
        assert result["summary"]["sh_close"] == 3600.0
        assert result["summary"]["sz_close"] == 0.0  # 缺少深证数据 → 零值兜底

    def test_generate_review_all_zero(self, mock_factory):
        """所有指数返回零值 → 结构完整的零值报告"""
        factory, default = mock_factory
        default.get_index_realtime.side_effect = Exception("downstream down")
        factory.get_provider.return_value = None

        ds = make_ds()
        ds._factory = factory

        with patch.object(type(ds), "_fetch_index_via_tencent", return_value=[]):
            result = ds.generate_review("2026-06-18")
            # get_index_realtime_quote 捕获异常并返回8个零值指数
            # generate_review 构造完整报告
            assert result["date"] == "2026-06-18"
            assert result["summary"]["sh_close"] == 0.0
            assert result["summary"]["sh_pct"] == 0.0
            assert result["summary"]["sz_close"] == 0.0
