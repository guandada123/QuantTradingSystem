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
from unittest.mock import MagicMock, mock_open, patch

import pytest
from services.data_fetcher import (
    _TENCENT_HOSTS,
    DataFetcher,
    _cache_dir,
    _fetch_kline_from_db,
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


# ============================================================
# 2026-09-03 回归：本地库优先 + 双 host 轮转 + 新鲜度守卫
# 背景：腾讯 fqkline 对单 IP 有 WAF 频控（约 2000 次请求后稳定 501），
#       全市场 4579 只串行取数必然跑不完。改本地 daily_quote 优先。
# ============================================================


class TestLocalDbFirst:
    """本地库 daily_quote 优先（data_fetcher._fetch_kline_from_db）"""

    _LOCAL = [
        {
            "trade_date": "2026-09-02",
            "open": 11.92,
            "high": 11.99,
            "low": 11.85,
            "close": 11.91,
            "vol": 892247,
            "amount": 1.06e9,
        }
    ]

    def test_local_db_hit_skips_network(self):
        """本地库有数据 → 直接返回，完全不发起 HTTP 请求"""
        with (
            patch("services.data_fetcher._fetch_kline_from_db", return_value=self._LOCAL),
            patch("urllib.request.urlopen") as mock_urlopen,
        ):
            result = fetch_kline_tencent("000001.SZ", "2026-06-01", "2026-09-03")

        mock_urlopen.assert_not_called()
        assert result == self._LOCAL

    def test_local_db_hit_populates_mem_cache(self):
        """本地库命中后写入内存缓存，同参数二次调用不再查库"""
        with patch(
            "services.data_fetcher._fetch_kline_from_db", return_value=self._LOCAL
        ) as mock_db:
            fetch_kline_tencent("000001.SZ", "2026-06-01", "2026-09-03")
            fetch_kline_tencent("000001.SZ", "2026-06-01", "2026-09-03")

        assert mock_db.call_count == 1

    def test_local_db_empty_falls_back_to_network(self):
        """本地库无数据 → 回落到网络源（腾讯 → 东财）

        注意：必须显式屏蔽磁盘缓存（os.path.exists → False）。
        磁盘缓存目录里有真实历史文件（如 tx_000001_20260601_20260903.json），
        不屏蔽的话会直接命中磁盘返回 67 条真数据，urlopen 的 mock 根本不会被调用，
        测试会假通过/假失败——取决于跑测试前有没有人手工取过同一区间。
        """
        mock_response = _make_http_response(
            {
                "code": 0,
                "data": {
                    "sz000001": {"qfqday": [["2026-09-02", 11.92, 11.91, 11.99, 11.85, 892247]]}
                },
            }
        )
        with (
            patch("services.data_fetcher._fetch_kline_from_db", return_value=[]),
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.json.dump"),
        ):
            result = fetch_kline_tencent("000001.SZ", "2026-06-01", "2026-09-03")

        assert len(result) == 1
        assert result[0]["close"] == 11.91

    def test_mem_cache_checked_before_local_db(self):
        """顺序守卫：内存缓存必须排在查库之前

        2026-09-03 实犯：初版把本地库查询放在内存缓存前面，同参数二次调用仍打 DB。
        11 策略 × 1200+ 只股票下同参数会被反复命中，顺序错 = DB QPS 放大量级。
        """
        with patch(
            "services.data_fetcher._fetch_kline_from_db", return_value=self._LOCAL
        ) as mock_db:
            fetch_kline_tencent("000001.SZ", "2026-06-01", "2026-09-03")
            first = mock_db.call_count
            fetch_kline_tencent("000001.SZ", "2026-06-01", "2026-09-03")

        assert first == 1
        assert mock_db.call_count == 1  # 第二次走内存缓存，不再查库

    def test_freshness_guard_skips_stale_db(self):
        """本地库过旧（max(trade_date) 距今 >5 天）→ 放弃本地源"""
        with patch("services.data_fetcher._local_db_fresh", return_value=False):
            result = _fetch_kline_from_db("000001.SZ", "20260601", "20260903")

        assert result == []


class TestTencentHostRotation:
    """双 host 轮转：web.ifzq 被 WAF 封(501)时自动切 ifzq"""

    def test_rotates_host_when_business_code_nonzero(self):
        """HTTP 200 但业务码非 0（WAF 拦截特征）→ 视同失败，切下一个 host"""
        mock_response = _make_http_response({"code": 1, "msg": "blocked"})
        with (
            patch("services.data_fetcher._fetch_kline_from_db", return_value=[]),
            patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen,
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.time.sleep"),
        ):
            result = fetch_kline_tencent("000001.SZ", "2026-06-01", "2026-09-03")

        assert result == []
        assert mock_urlopen.call_count == 3  # 3 次尝试，逐个轮转 host

    def test_rotates_host_on_http_exception(self):
        """HTTP 异常（如 WAF 501）→ 同样轮转，最终失败返回 []"""
        with (
            patch("services.data_fetcher._fetch_kline_from_db", return_value=[]),
            patch(
                "urllib.request.urlopen",
                side_effect=Exception("HTTP Error 501"),
            ) as mock_urlopen,
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.time.sleep"),
        ):
            result = fetch_kline_tencent("000001.SZ", "2026-06-01", "2026-09-03")

        assert result == []
        assert mock_urlopen.call_count == 3
        # 三次尝试分别落到两个 host 上（0→host0, 1→host1, 2→host0）
        hosts_tried = [c.args[0].full_url for c in mock_urlopen.call_args_list]
        assert len(set(hosts_tried)) == 2

    def test_stops_at_first_successful_host(self):
        """首个 host 即成功 → 不再尝试后续 host"""
        mock_response = _make_http_response(
            {
                "code": 0,
                "data": {
                    "sz000001": {"qfqday": [["2026-09-02", 11.92, 11.91, 11.99, 11.85, 892247]]}
                },
            }
        )
        with (
            patch("services.data_fetcher._fetch_kline_from_db", return_value=[]),
            patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen,
            patch("services.data_fetcher.os.makedirs"),
            patch("services.data_fetcher.os.path.exists", return_value=False),
            patch("services.data_fetcher.json.dump"),
        ):
            result = fetch_kline_tencent("000001.SZ", "2026-06-01", "2026-09-03")

        assert len(result) == 1
        assert mock_urlopen.call_count == 1

    def test_hosts_both_configured(self):
        """两个域名都配置在轮转列表里，任一被封都能自愈"""
        assert len(_TENCENT_HOSTS) == 2
        assert any("ifzq.gtimg.cn" in h for h in _TENCENT_HOSTS)


# ============================================================
# _local_db_fresh：截断写入不得被判为"新鲜"（2026-09-04 加）
#
# 事故：daily_quote 灌库被超时杀掉时只写进 44/5044 只，但 MAX(trade_date) 仍返回
# 那个残缺日 → 本函数判"可用(本地优先)" → 回测静默跑在 3 天前的数据上，连错 3 天。
# 修复：改用「行数 >= 1000 的最后一个交易日」判新鲜，并识别截断态。
#
# ⚠️ 关键取舍（别在重构时改坏）：截断态**必须继续返回 True**（留在本地库），
# 不能退回网络 —— 上层会为池中每只股票逐个发请求，1232 只立刻触发腾讯 WAF 频控，
# 即 09-03 那次 14min+ 雪崩。残缺数据仍优于打爆网络，但必须打 WARNING 暴露出来。
# ============================================================


class TestLocalDbFreshnessTruncation:
    @staticmethod
    def _mock_db(max_date, last_complete):
        """按顺序返回两条查询的结果：MAX(trade_date) → 最后完整交易日"""
        cm = MagicMock()
        db = MagicMock()
        queue = [max_date, last_complete]

        def execute(stmt, *a, **kw):
            resp = MagicMock()
            resp.scalar.return_value = queue.pop(0) if queue else None
            return resp

        db.execute.side_effect = execute
        cm.__enter__.return_value = db
        return cm

    def setup_method(self):
        import services.data_fetcher as df

        df._DB_FRESHNESS.update(checked_at=0.0, ok=None)  # 清进程内缓存

    @staticmethod
    def _today_iso():
        from datetime import date

        return date.today().isoformat()

    @staticmethod
    def _days_ago(n: int) -> str:
        """距今 n 天的 ISO 日期。

        ⚠️ 2026-09-25 修复测试腐烂：本类原用**写死的 2026-09-03/09-04**。
        `_local_db_fresh()` 的判据是 `effective >= today - 5 天` → 写死的日期
        在 09-09 之后必然判「过旧」，于是两个用例从**当天绿**变成**日历一到就红**，
        与代码无关（代码没改）。**写死日期的测试就是一条会腐烂的声明**：
        它不再验证"新鲜/截断"这件事，只在验证"今天离写测试那天有多远"。
        → 全部改成相对今天；判据本身（5 天阈值）由 stale 用例单独钉住。
        """
        from datetime import date, timedelta

        return (date.today() - timedelta(days=n)).isoformat()

    def test_healthy_db_reports_fresh_without_warning(self):
        """完整日 == MAX 日 → 新鲜，不打告警"""

        import services.data_fetcher as df

        d = self._days_ago(1)
        with (
            patch(
                "models.database.get_db_session",
                return_value=self._mock_db(d, d),
            ),
            patch.object(df.logger, "warning") as w,
        ):
            ok = df._local_db_fresh()
        assert ok is True
        assert w.call_count == 0

    def test_truncated_day_still_uses_local_but_warns(self):
        """核心回归：MAX 指向残缺日 → 仍留本地（不引雪崩），但必须告警"""
        import services.data_fetcher as df

        with (
            patch(
                "models.database.get_db_session",
                return_value=self._mock_db(self._days_ago(1), self._days_ago(3)),
            ),
            patch.object(df.logger, "warning") as w,
        ):
            ok = df._local_db_fresh()

        assert ok is True, "截断态必须继续用本地库，退回网络会触发 WAF 频控雪崩"
        assert w.call_count == 1
        assert "截断" in w.call_args[0][0]

    def test_genuinely_stale_complete_day_goes_network(self):
        """完整截止日距今 >5 天 → 判过旧，走网络"""
        from datetime import date, timedelta

        import services.data_fetcher as df

        old = (date.today() - timedelta(days=30)).isoformat()
        with patch("models.database.get_db_session", return_value=self._mock_db(old, old)):
            ok = df._local_db_fresh()
        assert ok is False

    def test_no_complete_day_falls_back_to_max(self):
        """一个完整交易日都没有 → 退回 MAX，行为与修复前一致"""
        import services.data_fetcher as df

        with patch(
            "models.database.get_db_session", return_value=self._mock_db(self._today_iso(), None)
        ):
            ok = df._local_db_fresh()
        assert ok is True

    def test_empty_table_goes_network(self):
        """空表 → 走网络"""
        import services.data_fetcher as df

        with patch("models.database.get_db_session", return_value=self._mock_db(None, None)):
            ok = df._local_db_fresh()
        assert ok is False

    def test_db_error_goes_network(self):
        """查库异常 → 走网络，不阻断主流程"""
        import services.data_fetcher as df

        cm = MagicMock()
        cm.__enter__.side_effect = RuntimeError("connection lost")
        with patch("models.database.get_db_session", return_value=cm):
            ok = df._local_db_fresh()
        assert ok is False
