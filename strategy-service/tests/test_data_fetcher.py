"""
测试多源数据获取模块
Cover services/data_fetcher.py 中未覆盖的分支：

函数级:
  - _get_cache_ttl: settings 导入失败 (52-53)
  - fetch_kline_tencent: 缓存过期(115-119), HTTP重试(134-136), 成功解析(146-172)
  - fetch_kline_eastmoney: 内存缓存命中(197-198), 缓存过期(210-224), HTTP重试(243-244), 成功解析(250-277)

DataFetcher 类:
  - _get_data_service: callback 返回 None (305)
  - fetch_market_data: 东方财富成功(328), DataService 未配置(333-336), DataService 返回数据(339-347)
  - fetch_benchmark_data: AKShare 路径(371-403)
"""

import json
import sys as _sys
import time
import types
from unittest.mock import MagicMock, PropertyMock, call, mock_open, patch
import urllib.request

import pytest
from services.data_fetcher import (
    DataFetcher,
    _cache_dir,
    _get_cache_ttl,
    _mem_cache,
    _mem_cache_key,
    fetch_kline_eastmoney,
    fetch_kline_tencent,
)

# ============================================================
# 测试辅助
# ============================================================


def _make_http_response(data: dict) -> MagicMock:
    """创建模拟 HTTP 响应，正确支持上下文管理器协议

    MagicMock.__enter__() 默认返回新的 MagicMock 而非 self，
    导致 with urllib.request.urlopen(...) as resp 中 resp 不指向原 mock。
    此 helper 确保 __enter__ 返回 self，使 resp.read() 能正确获取预设值。
    """
    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode()
    resp.__enter__.return_value = resp
    return resp


@pytest.fixture(autouse=True)
def clear_mem_cache():
    """每个测试前清空模块级内存缓存，避免跨测试干扰"""
    _mem_cache.clear()
    yield
    _mem_cache.clear()


# ============================================================
# _get_cache_ttl
# ============================================================


class TestGetCacheTtl:
    """测试 _get_cache_ttl (lines 46-53)"""

    def test_settings_import_fails_returns_default(self):
        """settings 导入失败 → 返回默认 TTL (lines 52-53)"""
        # 将 core.config.settings 置为 None，使其属性访问触发 AttributeError
        import core.config

        with patch.object(core.config, "settings", new=None):
            with patch("services.data_fetcher.logger"):
                ttl = _get_cache_ttl()
        assert ttl == 86400  # _default_cache_ttl

    def test_settings_import_returns_configured(self):
        """正常导入返回 settings 中的值 (line 51)"""
        with patch("core.config.settings.CACHE_TTL_SECONDS", 7200):
            ttl = _get_cache_ttl()
        assert ttl == 7200


# ============================================================
# fetch_kline_tencent
# ============================================================


class TestFetchKlineTencent:
    """测试 fetch_kline_tencent (lines 70-174)"""

    def test_mem_cache_hit(self):
        """内存缓存命中 → 直接返回缓存数据 (lines 86-89)"""
        key = _mem_cache_key("tx", "000001.SZ", "20260101", "20260619")
        expected = [{"trade_date": "2026-01-01"}]
        _mem_cache[key] = expected
        result = fetch_kline_tencent("000001.SZ", "2026-01-01", "2026-06-19")
        assert result == expected

    def test_file_cache_hit(self):
        """文件缓存命中（未过期）→ 从文件读取 (lines 105-113)"""
        expected = [{"trade_date": "2026-01-01"}]
        mock_json = json.dumps(expected)
        now = time.time()
        with (
            patch("services.data_fetcher.os.path.exists", return_value=True),
            patch("services.data_fetcher.os.path.getmtime", return_value=now - 100),  # 100秒前
            patch("services.data_fetcher._get_cache_ttl", return_value=86400),  # TTL=1天，未过期
            patch("builtins.open", mock_open(read_data=mock_json)),
        ):
            result = fetch_kline_tencent("000001.SZ", "2026-01-01", "2026-06-19")
        assert result == expected
        # 同时也预热了内存缓存
        key = _mem_cache_key("tx", "000001.SZ", "20260101", "20260619")
        assert _mem_cache.get(key) == expected

    def test_file_cache_expired(self):
        """文件缓存过期 → 继续 HTTP 请求 (lines 114-119)"""
        mock_json = json.dumps([{"trade_date": "2026-01-01"}])
        now = time.time()
        # 缓存过期，走 HTTP 路径，HTTP 也返回数据
        mock_response = _make_http_response(
            {
                "code": 0,
                "data": {"sz000001": {"qfqday": [["2026-01-01", 10, 10.5, 11, 9.5, 100000]]}},
            }
        )

        with (
            patch("services.data_fetcher.os.path.exists", return_value=True),
            patch("services.data_fetcher.os.path.getmtime", return_value=now - 90000),  # 很久之前
            patch("services.data_fetcher._get_cache_ttl", return_value=3600),  # TTL=1小时
            patch("builtins.open", mock_open(read_data=mock_json)),
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.json.dump"),
        ):
            result = fetch_kline_tencent("000001.SZ", "2026-01-01", "2026-06-19")
        assert len(result) == 1
        assert result[0]["trade_date"] == "2026-01-01"

    def test_file_cache_read_error(self):
        """文件缓存读取异常 → pass 继续 HTTP (lines 118-119)"""
        now = time.time()
        mock_response = _make_http_response(
            {
                "code": 0,
                "data": {"sz000001": {"qfqday": [["2026-01-01", 10, 10.5, 11, 9.5, 100000]]}},
            }
        )

        with (
            patch("services.data_fetcher.os.path.exists", return_value=True),
            patch("services.data_fetcher.os.path.getmtime", return_value=now - 100),
            patch("services.data_fetcher._get_cache_ttl", return_value=86400),
            patch("builtins.open", mock_open()) as mf,
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.json.dump"),
        ):
            # JSON 解码失败 → except pass
            mf.return_value.read.side_effect = json.JSONDecodeError("bad json", "", 0)
            result = fetch_kline_tencent("000001.SZ", "2026-01-01", "2026-06-19")
        assert len(result) == 1

    def test_http_retry_then_success(self):
        """HTTP 请求前两次失败，第三次成功 (lines 134-136)"""
        mock_response = _make_http_response(
            {
                "code": 0,
                "data": {"sz000001": {"qfqday": [["2026-01-01", 10, 10.5, 11, 9.5, 100000]]}},
            }
        )

        # urlopen 前2次抛异常，第3次成功
        urlopen_mock = MagicMock()
        urlopen_mock.side_effect = [
            OSError("timeout"),
            OSError("timeout"),
            mock_response,
        ]

        with (
            patch("urllib.request.urlopen", urlopen_mock) as uo,
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.json.dump"),
            patch("services.data_fetcher.time.sleep"),  # 避免真实等待
        ):
            result = fetch_kline_tencent("000001.SZ", "2026-01-01", "2026-06-19")

        assert len(result) == 1
        assert uo.call_count == 3

    def test_http_parse_kline_success_and_cache(self):
        """HTTP 成功获取 K线 + 解析 + 写入缓存 (lines 146-172)"""
        raw_rows = [
            ["2026-01-01", 10.0, 10.5, 11.0, 9.5, 100000, 0],
            ["2026-01-02", 10.5, 10.8, 11.2, 10.3, 120000, 0],
            ["2026-01-03", 10.8, 10.3, 11.0, 10.1, 90000, 0],
        ]
        mock_response = _make_http_response({"code": 0, "data": {"sz000001": {"qfqday": raw_rows}}})

        with (
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.json.dump") as mock_dump,
        ):
            result = fetch_kline_tencent("000001.SZ", "2026-01-01", "2026-06-19")

        assert len(result) == 3
        assert result[0]["trade_date"] == "2026-01-01"
        assert result[0]["open"] == 10.0
        assert result[0]["close"] == 10.5
        assert result[0]["vol"] == 100000
        # 文件缓存被写入
        mock_dump.assert_called_once()

    def test_parse_kline_row_error_skipped(self):
        """K线行解析失败 → 跳过该行 (lines 160-162)"""
        raw_rows = [
            ["2026-01-01", 10.0, 10.5, 11.0, 9.5, 100000],
            ["INVALID_ROW"],  # 这行会被跳过
            ["2026-01-03", 10.8, 10.3, 11.0, 10.1, 90000],
        ]
        mock_response = _make_http_response({"code": 0, "data": {"sz000001": {"qfqday": raw_rows}}})

        with (
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.json.dump"),
        ):
            result = fetch_kline_tencent("000001.SZ", "2026-01-01", "2026-06-19")
        assert len(result) == 2  # 跳过一行

    def test_empty_response_returns_empty_list(self):
        """API 返回空数据 → 返回 [] (line 174)"""
        mock_response = _make_http_response({"code": 0, "data": {}})

        with (
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.os.makedirs"),
        ):
            result = fetch_kline_tencent("000001.SZ", "2026-01-01", "2026-06-19")
        assert result == []


# ============================================================
# fetch_kline_eastmoney
# ============================================================


class TestFetchKlineEastmoney:
    """测试 fetch_kline_eastmoney (lines 188-279)"""

    def test_mem_cache_hit(self):
        """内存缓存命中 → 直接返回 (lines 197-198)"""
        key = _mem_cache_key("em", "000001.SZ", "20260101", "20260619")
        expected = [{"trade_date": "2026-01-01"}]
        _mem_cache[key] = expected
        result = fetch_kline_eastmoney("000001.SZ", "2026-01-01", "2026-06-19")
        assert result == expected

    def test_file_cache_expired(self):
        """文件缓存过期 → 继续 HTTP 请求 (lines 210-224)"""
        mock_json = json.dumps([{"trade_date": "2026-01-01"}])
        now = time.time()
        mock_response = _make_http_response(
            {
                "data": {
                    "klines": ["2026-01-01,10.0,10.5,11.0,9.5,100000,5000000"],
                }
            }
        )

        with (
            patch("services.data_fetcher.os.path.exists", return_value=True),
            patch("services.data_fetcher.os.path.getmtime", return_value=now - 90000),
            patch("services.data_fetcher._get_cache_ttl", return_value=3600),
            patch("builtins.open", mock_open(read_data=mock_json)),
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.json.dump"),
        ):
            result = fetch_kline_eastmoney("000001.SZ", "2026-01-01", "2026-06-19")
        assert len(result) == 1
        assert result[0]["trade_date"] == "2026-01-01"

    def test_http_retry_then_success(self):
        """HTTP 失败重试 (lines 243-247)"""
        mock_response = _make_http_response(
            {
                "data": {
                    "klines": ["2026-01-01,10.0,10.5,11.0,9.5,100000,5000000"],
                }
            }
        )

        urlopen_mock = MagicMock()
        urlopen_mock.side_effect = [OSError("timeout"), mock_response]

        with (
            patch("urllib.request.urlopen", urlopen_mock) as uo,
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.json.dump"),
            patch("services.data_fetcher.time.sleep"),
        ):
            result = fetch_kline_eastmoney("000001.SZ", "2026-01-01", "2026-06-19")
        assert len(result) == 1
        assert uo.call_count == 2

    def test_parse_klines_success_and_cache(self):
        """解析 K线成功 + 写入缓存 (lines 250-277)"""
        raw_klines = [
            "2026-01-01,10.0,10.5,11.0,9.5,100000,5000000",
            "2026-01-02,10.5,10.8,11.2,10.3,120000,6000000",
        ]
        mock_response = _make_http_response({"data": {"klines": raw_klines}})

        with (
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.json.dump") as mock_dump,
        ):
            result = fetch_kline_eastmoney("000001.SZ", "2026-01-01", "2026-06-19")

        assert len(result) == 2
        assert result[0]["trade_date"] == "2026-01-01"
        assert result[0]["open"] == 10.0
        assert result[0]["close"] == 10.5
        assert result[0]["vol"] == 100000
        assert result[0]["amount"] == 5000000.0
        mock_dump.assert_called_once()

    def test_parse_kline_row_error_skipped(self):
        """解析行失败 → 跳过 (lines 265-267)"""
        raw_klines = [
            "2026-01-01,10.0,10.5,11.0,9.5,100000,5000000",
            "BAD_LINE",
            "2026-01-03,10.8,10.3,11.0,10.1,90000,4500000",
        ]
        mock_response = _make_http_response({"data": {"klines": raw_klines}})

        with (
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.json.dump"),
        ):
            result = fetch_kline_eastmoney("000001.SZ", "2026-01-01", "2026-06-19")
        assert len(result) == 2

    def test_empty_response_returns_empty(self):
        """API 返回空数据 → 返回 [] (line 279)"""
        mock_response = _make_http_response({"data": {"klines": []}})

        with (
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.os.makedirs"),
        ):
            result = fetch_kline_eastmoney("000001.SZ", "2026-01-01", "2026-06-19")
        assert result == []


# ============================================================
# DataFetcher 类
# ============================================================


class TestDataFetcherGetDataService:
    """测试 DataFetcher._get_data_service (lines 301-305)"""

    def test_callback_none_returns_none(self):
        """无回调 → 返回 None (line 305)"""
        fetcher = DataFetcher(config=MagicMock())
        assert fetcher._get_data_service() is None

    def test_callback_returns_service(self):
        """有回调 → 返回回调结果 (line 304)"""
        mock_ds = MagicMock()
        fetcher = DataFetcher(config=MagicMock(), get_data_service=lambda: mock_ds)
        assert fetcher._get_data_service() is mock_ds


class TestDataFetcherFetchMarketData:
    """测试 DataFetcher.fetch_market_data (lines 309-350)"""

    def test_eastmoney_success(self):
        """腾讯空 + 东方财富成功 → 返回东方财富数据 (line 328)"""
        fetcher = DataFetcher(config=MagicMock())
        em_data = [{"trade_date": "2026-01-01"}]
        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch("services.data_fetcher.fetch_kline_eastmoney", return_value=em_data),
        ):
            result = fetcher.fetch_market_data("000001.SZ", "2026-01-01", "2026-06-19")
        assert result == em_data

    def test_dataservice_not_configured(self):
        """所有公开源失败 + DataService 未配置 → 返回 [] (lines 333-336)"""
        fetcher = DataFetcher(config=MagicMock())
        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch("services.data_fetcher.fetch_kline_eastmoney", return_value=[]),
            patch.object(fetcher, "_get_data_service", return_value=None),
        ):
            result = fetcher.fetch_market_data("000001.SZ", "2026-01-01", "2026-06-19")
        assert result == []

    def test_dataservice_returns_data_with_date_conversion(self):
        """DataService 返回数据 + trade_date 需格式化 (lines 339-345)"""
        fetcher = DataFetcher(config=MagicMock())
        mock_ds = MagicMock()
        from datetime import date

        mock_ds.get_stock_daily_quote.return_value = [
            {"trade_date": date(2026, 1, 1), "open": 10.0, "close": 10.5},
        ]
        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch("services.data_fetcher.fetch_kline_eastmoney", return_value=[]),
            patch.object(fetcher, "_get_data_service", return_value=mock_ds),
        ):
            result = fetcher.fetch_market_data("000001.SZ", "2026-01-01", "2026-06-19")
        assert len(result) == 1
        assert result[0]["trade_date"] == "20260101"

    def test_dataservice_returns_empty(self):
        """DataService 返回空数据 → 返回 [] (lines 346-347)"""
        fetcher = DataFetcher(config=MagicMock())
        mock_ds = MagicMock()
        mock_ds.get_stock_daily_quote.return_value = []
        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch("services.data_fetcher.fetch_kline_eastmoney", return_value=[]),
            patch.object(fetcher, "_get_data_service", return_value=mock_ds),
        ):
            result = fetcher.fetch_market_data("000001.SZ", "2026-01-01", "2026-06-19")
        assert result == []

    def test_dataservice_exception(self):
        """DataService 抛异常 → 返回 [] (lines 348-350)"""
        fetcher = DataFetcher(config=MagicMock())
        mock_ds = MagicMock()
        mock_ds.get_stock_daily_quote.side_effect = RuntimeError("挂了")
        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch("services.data_fetcher.fetch_kline_eastmoney", return_value=[]),
            patch.object(fetcher, "_get_data_service", return_value=mock_ds),
        ):
            result = fetcher.fetch_market_data("000001.SZ", "2026-01-01", "2026-06-19")
        assert result == []


class TestDataFetcherFetchBenchmark:
    """测试 DataFetcher.fetch_benchmark_data (lines 352-403)"""

    def test_tencent_success(self):
        """腾讯成功获取基准数据 (lines 365-368)"""
        config = MagicMock()
        config.benchmark = "000300.SH"
        fetcher = DataFetcher(config=config)
        tencent_data = [{"trade_date": "2026-01-01"}]
        with patch("services.data_fetcher.fetch_kline_tencent", return_value=tencent_data):
            result = fetcher.fetch_benchmark_data("2026-01-01", "2026-06-19")
        assert result == tencent_data

    def test_akshare_success(self):
        """腾讯失败 → AKShare 成功 (lines 371-396)"""
        import pandas as pd

        config = MagicMock()
        config.benchmark = "000300.SH"
        fetcher = DataFetcher(config=config)

        mock_df = pd.DataFrame(
            {
                "date": ["2026-01-01", "2026-01-02"],
                "open": [3800.0, 3810.0],
                "high": [3820.0, 3830.0],
                "low": [3790.0, 3800.0],
                "close": [3810.0, 3820.0],
                "volume": [1000000, 1200000],
                "amount": [50000000, 60000000],
            }
        )

        # 注入 mock akshare，让 import akshare as ak 能找到
        mock_ak = types.ModuleType("akshare")
        mock_ak.stock_zh_index_daily = MagicMock(return_value=mock_df)

        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch.dict("sys.modules", {"akshare": mock_ak}),
        ):
            # 使用 YYYYMMDD 格式的日期，与内部 trade_date 格式一致
            result = fetcher.fetch_benchmark_data("20260101", "20260102")
        assert len(result) >= 1
        assert result[0]["trade_date"] == "20260101"

    def test_akshare_not_installed(self):
        """akshare 未安装 → ImportError 被 catch (lines 397-398)"""
        config = MagicMock()
        config.benchmark = "000300.SH"
        fetcher = DataFetcher(config=config)

        # 从 sys.modules 中移除 akshare（若有），触发 import akshare 失败
        saved = _sys.modules.pop("akshare", None)
        try:
            with patch("services.data_fetcher.fetch_kline_tencent", return_value=[]):
                result = fetcher.fetch_benchmark_data("2026-01-01", "2026-06-19")
            assert result == []
        finally:
            if saved is not None:
                _sys.modules["akshare"] = saved

    def test_akshare_exception(self):
        """AKShare 抛异常被 catch (lines 399-400)"""
        config = MagicMock()
        config.benchmark = "000300.SH"
        fetcher = DataFetcher(config=config)

        mock_ak = types.ModuleType("akshare")
        mock_ak.stock_zh_index_daily = MagicMock(side_effect=ValueError("API 调用失败"))

        with (
            patch("services.data_fetcher.fetch_kline_tencent", return_value=[]),
            patch.dict("sys.modules", {"akshare": mock_ak}),
        ):
            result = fetcher.fetch_benchmark_data("2026-01-01", "2026-06-19")
        assert result == []

    def test_all_sources_fail(self):
        """所有源都失败 → 返回 [] (lines 402-403)"""
        config = MagicMock()
        config.benchmark = "000300.SH"
        fetcher = DataFetcher(config=config)

        saved = _sys.modules.pop("akshare", None)
        try:
            with patch("services.data_fetcher.fetch_kline_tencent", return_value=[]):
                result = fetcher.fetch_benchmark_data("2026-01-01", "2026-06-19")
            assert result == []
        finally:
            if saved is not None:
                _sys.modules["akshare"] = saved


class TestCacheDir:
    """测试 _cache_dir"""

    def test_creates_dir_and_returns_path(self):
        """创建并返回缓存目录路径"""
        with patch("services.data_fetcher.os.makedirs") as mock_mkdir:
            path = _cache_dir()
        assert ".cache" in path
        mock_mkdir.assert_called_once()
