"""MarketDataProvider 单元测试

改动前 services/market_data_provider.py 覆盖率为 0%（158 语句全未覆盖）。

隔离要求（磁盘缓存泄漏）：
  本类有**磁盘缓存**层（cache_dir/<key>.json，TTL 5 分钟）。若指向真实
  shared/claw_data/cache/，只要历史上真跑过一次，测试就会读到真实缓存、
  **完全绕过** mock，于是"通过了"但与改动的代码毫无关系。
  因此每个用例都把 provider.cache_dir 指向 tmp_path。

契约重点（与 advanced_risk_rules.R2 的接口）：
  `stock_drop_pct` / `sector_drop_pct` 必须是**带符号**涨跌幅（跌为负）。
  R2 曾用 abs() 判定，导致上涨 ≥7% 被判成"暴跌"。本文件用契约测试把
  "下跌→冻结 / 上涨→不冻结" 这条链路钉死。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.advanced_risk_rules import AdvancedRiskChecker, RuleSeverity
from services.market_data_provider import (
    CACHE_TTL_MINUTES,
    MarketDataProvider,
    get_market_data_for_symbol,
)

from shared.risk_config import RiskConfig

# ──────────────────── 工具 ────────────────────


def _resp(json_data=None, text: str = "", status_code: int = 200) -> MagicMock:
    """模拟 httpx.Response（.json() 是同步调用）"""
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.json.return_value = json_data
    return r


def _client_factory(*responses: MagicMock) -> MagicMock:
    """构造 httpx.AsyncClient 的替身工厂。

    AsyncClient 的用法是 `async with httpx.AsyncClient(...) as client:`，
    因此必须显式配置 __aenter__/__aexit__ —— 默认的 __aenter__ 会返回**另一个**
    MagicMock，导致代码里的 `client.get(...)` 落到未被配置的对象上
    （经典的异步上下文管理器陷阱）。

    get 用 side_effect 列表：调用次数多于预期会 StopIteration，
    从而暴露"多打了一次 HTTP"这类回归。
    """
    client = MagicMock()
    client.get = AsyncMock(side_effect=list(responses))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=client)


def _kline(close: float, *, spread: float = 1.0, volume: float = 1000.0) -> dict:
    return {
        "date": "2026-09-01",
        "open": close,
        "close": close,
        "high": close + spread,
        "low": close - spread,
        "volume": volume,
    }


def _klines(closes: list[float], *, spread: float = 1.0, volume: float = 1000.0) -> list[dict]:
    return [_kline(c, spread=spread, volume=volume) for c in closes]


def _tencent_year_of_quote(change_percent: float, price: float = 10.0) -> str:
    """构造腾讯 qt.gtimg.cn 的 `~` 分隔行情串（字段位与生产代码对齐）"""
    parts = ["0"] * 40
    parts[1] = "长电科技"
    parts[2] = "600584"
    parts[3] = f"{price:.2f}"
    parts[4] = "9.50"
    parts[5] = "9.60"
    parts[6] = "12345"
    parts[32] = f"{change_percent:.2f}"
    parts[33] = "10.60"
    parts[34] = "9.40"
    return "v_sh600584=" + "~".join(parts)


@pytest.fixture
def provider(tmp_path) -> MarketDataProvider:
    """缓存目录隔离到 tmp_path —— 否则真实缓存会让 mock 静默失效"""
    p = MarketDataProvider(use_mcp=False)
    p.cache_dir = tmp_path / "cache"
    return p


# ════════════════════ 磁盘缓存层 ════════════════════


class TestDiskCache:
    def test_set_then_get_round_trip(self, provider):
        provider._cache_set("market_data_sh600584", {"atr": 0.5})

        assert provider._cache_get("market_data_sh600584") == {"atr": 0.5}

    def test_missing_key_returns_none(self, provider):
        assert provider._cache_get("never_written") is None

    def test_expired_entry_returns_none(self, provider):
        """超过 TTL 的缓存必须失效"""
        provider.cache_dir.mkdir(parents=True, exist_ok=True)
        stale_ts = datetime.now() - timedelta(minutes=CACHE_TTL_MINUTES + 1)
        (provider.cache_dir / "old.json").write_text(
            json.dumps({"ts": stale_ts.isoformat(), "value": {"atr": 0.1}}), encoding="utf-8"
        )

        assert provider._cache_get("old") is None

    def test_fresh_entry_is_returned(self, provider):
        provider.cache_dir.mkdir(parents=True, exist_ok=True)
        (provider.cache_dir / "fresh.json").write_text(
            json.dumps({"ts": datetime.now().isoformat(), "value": {"atr": 0.9}}), encoding="utf-8"
        )

        assert provider._cache_get("fresh") == {"atr": 0.9}

    def test_corrupt_cache_file_returns_none(self, provider):
        """缓存文件损坏 → 当作未命中，不得抛异常打断风控链路"""
        provider.cache_dir.mkdir(parents=True, exist_ok=True)
        (provider.cache_dir / "broken.json").write_text("{不是 JSON", encoding="utf-8")

        assert provider._cache_get("broken") is None

    def test_cache_key_format(self, provider):
        assert provider._cache_key("sh600584", "market_data") == "market_data_sh600584"

    async def test_fetch_uses_cache_without_calling_sources(self, provider):
        """命中缓存时不得再打任何数据源（用会抛异常的替身证明它没被调用）"""
        cached = {"atr": 0.42, "stock_drop_pct": -0.03}
        provider._cache_set("market_data_sh600584", cached)
        provider._compute_atr = AsyncMock(side_effect=AssertionError("不该走 ATR 计算"))
        provider._fetch_today_quote = AsyncMock(side_effect=AssertionError("不该打行情接口"))
        provider._fetch_market_stats = AsyncMock(side_effect=AssertionError("不该打统计接口"))

        result = await provider.fetch_market_data("sh600584")

        assert result == cached


# ════════════════════ _compute_atr 数值正确性 ════════════════════


class TestComputeAtr:
    async def test_flat_series_exact_values(self, provider):
        """横盘序列：TR 恒为 2.0（high-low），可手工验算"""
        provider._fetch_kline = AsyncMock(return_value=_klines([10.0] * 30))

        result = await provider._compute_atr("sh600584")

        assert result is not None
        assert result["atr"] == 2.0
        assert result["ma20"] == 10.0
        assert result["high_20d"] == 11.0
        assert result["low_20d"] == 9.0
        assert result["avg_volume"] == 1000
        # 完全横盘：无涨无跌，中性 50.0（原实现会算出 99.0 → 被 R8 误判为过热）
        assert result["rsi"] == 50.0

    async def test_rising_series_rsi_is_100(self, provider):
        """单调上涨：14 个相邻价差全为正 → RSI = 100"""
        closes = [float(i) for i in range(1, 31)]
        provider._fetch_kline = AsyncMock(return_value=_klines(closes, spread=0.0))

        result = await provider._compute_atr("sh600584")

        assert result is not None
        assert result["atr"] == 1.0
        assert result["rsi"] == 100.0

    async def test_falling_series_rsi_is_zero(self, provider):
        """单调下跌：14 个相邻价差全为负 → RSI = 0"""
        closes = [float(i) for i in range(30, 0, -1)]
        provider._fetch_kline = AsyncMock(return_value=_klines(closes, spread=0.0))

        result = await provider._compute_atr("sh600584")

        assert result is not None
        assert result["rsi"] == 0.0

    async def test_rsi_uses_adjacent_days_not_distant_pairs(self, provider):
        """🐛 回归护栏：RSI 必须基于**相邻两日**收盘价差。

        原实现把切片内序号拿去索引完整列表，相当于拿「15 天前」当「昨天」：
        对单调序列会算出 gains=210（真实 14 日涨幅总和仅 14）。
        这里构造一个"前段大跌、后段小涨"的序列，两种算法结论相反：
          相邻日：末 14 个价差 = +1 ×13 → RSI ≈ 100（强势）
          错配对：末段与 15 天前的高位相比 → 亏损占优 → RSI 明显偏低
        """
        closes = [float(i) for i in range(30, 15, -1)] + [float(i) for i in range(16, 30)]
        provider._fetch_kline = AsyncMock(return_value=_klines(closes, spread=0.0))

        result = await provider._compute_atr("sh600584")

        assert result is not None
        assert result["rsi"] > 90.0, "RSI 仍在用跨 15 天的错配对计算"

    async def test_insufficient_history_returns_none(self, provider):
        """K 线不足一个 ATR 周期 → None"""
        provider._fetch_kline = AsyncMock(return_value=_klines([10.0] * 10))

        assert await provider._compute_atr("sh600584") is None

    async def test_exactly_period_klines_returns_none(self, provider):
        """边界：恰好 14 根 K 线 → TR 只有 13 个，仍不足 14 → None"""
        provider._fetch_kline = AsyncMock(return_value=_klines([10.0] * 14))

        assert await provider._compute_atr("sh600584") is None

    async def test_empty_klines_returns_none(self, provider):
        provider._fetch_kline = AsyncMock(return_value=[])

        assert await provider._compute_atr("sh600584") is None

    async def test_missing_numeric_fields_returns_none(self, provider):
        """K 线字段缺失/非数值 → 走 except 分支返回 None，不抛出"""
        provider._fetch_kline = AsyncMock(return_value=[{"close": "abc"} for _ in range(30)])

        assert await provider._compute_atr("sh600584") is None


# ════════════════════ _fetch_kline 解析 ════════════════════


class TestFetchKline:
    async def test_parses_qfqday(self, provider):
        payload = {
            "data": {
                "1600584": {
                    "qfqday": [
                        ["2026-09-01", "9.90", "10.00", "10.10", "9.80", "1000"],
                        ["2026-09-02", "10.00", "10.20", "10.30", "9.90", "1200"],
                    ]
                }
            }
        }
        factory = _client_factory(_resp(json_data=payload))

        with patch("httpx.AsyncClient", factory):
            rows = await provider._fetch_kline("sh600584", 2)

        assert len(rows) == 2
        assert rows[0] == {
            "date": "2026-09-01",
            "open": "9.90",
            "close": "10.00",
            "high": "10.10",
            "low": "9.80",
            "volume": "1000",
        }

    async def test_falls_back_to_day_key(self, provider):
        """qfqday 为空时回落到 day 字段"""
        payload = {
            "data": {"1600584": {"qfqday": [], "day": [["2026-09-01", "1", "2", "3", "4", "5"]]}}
        }
        factory = _client_factory(_resp(json_data=payload))

        with patch("httpx.AsyncClient", factory):
            rows = await provider._fetch_kline("sh600584", 1)

        assert len(rows) == 1
        assert rows[0]["close"] == "2"

    async def test_empty_when_symbol_absent(self, provider):
        factory = _client_factory(_resp(json_data={"data": {}}))

        with patch("httpx.AsyncClient", factory):
            assert await provider._fetch_kline("sh600584", 1) == []

    async def test_returns_empty_on_network_error(self, provider):
        client = MagicMock()
        client.get = AsyncMock(side_effect=RuntimeError("connection refused"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", MagicMock(return_value=client)):
            assert await provider._fetch_kline("sh600584", 1) == []


# ════════════════════ _fetch_today_quote 解析 ════════════════════


class TestFetchTodayQuote:
    async def test_parses_tencent_format(self, provider):
        factory = _client_factory(_resp(text=_tencent_year_of_quote(5.26, price=10.0)))

        with patch("httpx.AsyncClient", factory):
            quote = await provider._fetch_today_quote("sh600584")

        assert quote is not None
        assert quote["price"] == 10.0
        assert quote["prev_close"] == 9.5
        assert quote["change_percent"] == 5.26
        assert quote["high"] == 10.6
        assert quote["low"] == 9.4

    async def test_negative_change_percent_is_negative(self, provider):
        """符号约定：下跌必须是负数（R2 的全部前提）"""
        factory = _client_factory(_resp(text=_tencent_year_of_quote(-8.0)))

        with patch("httpx.AsyncClient", factory):
            quote = await provider._fetch_today_quote("sh600584")

        assert quote is not None
        assert quote["change_percent"] == -8.0

    async def test_returns_none_when_no_tilde(self, provider):
        factory = _client_factory(_resp(text="v_pv_none_match"))

        with patch("httpx.AsyncClient", factory):
            assert await provider._fetch_today_quote("sh600584") is None

    async def test_returns_none_when_too_few_fields(self, provider):
        factory = _client_factory(_resp(text="v_sh600584=" + "~".join(["0"] * 20)))

        with patch("httpx.AsyncClient", factory):
            assert await provider._fetch_today_quote("sh600584") is None

    async def test_returns_none_on_network_error(self, provider):
        client = MagicMock()
        client.get = AsyncMock(side_effect=RuntimeError("boom"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", MagicMock(return_value=client)):
            assert await provider._fetch_today_quote("sh600584") is None


# ════════════════════ _fetch_market_stats 解析 ════════════════════


def _index_text(change_percent: float) -> str:
    parts = ["0"] * 40
    parts[32] = f"{change_percent:.2f}"
    return "v_sh000001=" + "~".join(parts)


class TestFetchMarketStats:
    async def test_computes_limit_ratio(self, provider):
        eastmoney = {"data": {"diff": [{"f3": -9.95}, {"f3": -10.01}, {"f3": 10.0}, {"f3": 3.2}]}}
        factory = _client_factory(
            _resp(text=_index_text(-1.25)),
            _resp(json_data=eastmoney, status_code=200),
        )

        with patch("httpx.AsyncClient", factory):
            stats = await provider._fetch_market_stats()

        assert stats is not None
        assert stats["sector_drop_pct"] == pytest.approx(-0.0125)
        assert stats["total_limit_down"] == 2
        assert stats["total_limit_up"] == 1
        assert stats["limit_down_up_ratio"] == 2.0

    async def test_zero_limit_up_uses_denominator_floor(self, provider):
        """涨停 0 家时用 max(limit_up,1) 兜底，不能除零"""
        eastmoney = {"data": {"diff": [{"f3": -9.95}, {"f3": -10.0}, {"f3": -10.01}]}}
        factory = _client_factory(
            _resp(text=_index_text(-3.0)),
            _resp(json_data=eastmoney, status_code=200),
        )

        with patch("httpx.AsyncClient", factory):
            stats = await provider._fetch_market_stats()

        assert stats is not None
        assert stats["limit_down_up_ratio"] == 3.0

    async def test_non_200_returns_none(self, provider):
        """非 200 响应必须显式判定，不能拿空 body 当有效数据"""
        factory = _client_factory(
            _resp(text=_index_text(-1.0)),
            _resp(json_data={"data": {"diff": [{"f3": -10.0}]}}, status_code=500),
        )

        with patch("httpx.AsyncClient", factory):
            assert await provider._fetch_market_stats() is None

    async def test_empty_diff_returns_none(self, provider):
        factory = _client_factory(
            _resp(text=_index_text(-1.0)),
            _resp(json_data={"data": {"diff": []}}, status_code=200),
        )

        with patch("httpx.AsyncClient", factory):
            assert await provider._fetch_market_stats() is None


# ════════════════════ fetch_market_data 组装 ════════════════════


class TestFetchMarketData:
    async def test_assembles_all_sources(self, provider):
        provider._compute_atr = AsyncMock(
            return_value={
                "atr": 0.5,
                "avg_volume": 1000,
                "ma20": 10.0,
                "high_20d": 12.0,
                "low_20d": 8.0,
                "rsi": 55.0,
            }
        )
        provider._fetch_today_quote = AsyncMock(return_value={"price": 9.4, "change_percent": -6.0})
        provider._fetch_market_stats = AsyncMock(
            return_value={"sector_drop_pct": -0.02, "limit_down_up_ratio": 1.5}
        )

        result = await provider.fetch_market_data("sh600584")

        assert result["atr"] == 0.5
        assert result["ma20"] == 10.0
        assert result["rsi"] == 55.0
        assert result["current_price"] == 9.4
        assert result["stock_drop_pct"] == pytest.approx(-0.06)
        assert result["sector_drop_pct"] == -0.02
        assert result["limit_down_up_ratio"] == 1.5

    async def test_atr_failure_degrades_gracefully(self, provider):
        """ATR 拿不到时其余字段仍应产出（降级而非整体失败）"""
        provider._compute_atr = AsyncMock(return_value=None)
        provider._fetch_today_quote = AsyncMock(return_value={"price": 9.4, "change_percent": -6.0})
        provider._fetch_market_stats = AsyncMock(return_value=None)

        result = await provider.fetch_market_data("sh600584")

        assert "atr" not in result
        assert result["stock_drop_pct"] == pytest.approx(-0.06)

    async def test_quote_exception_does_not_kill_whole_pack(self, provider):
        provider._compute_atr = AsyncMock(return_value=None)
        provider._fetch_today_quote = AsyncMock(side_effect=RuntimeError("接口挂了"))
        provider._fetch_market_stats = AsyncMock(return_value={"sector_drop_pct": -0.03})

        result = await provider.fetch_market_data("sh600584")

        assert "stock_drop_pct" not in result
        assert result["sector_drop_pct"] == -0.03

    async def test_all_sources_failed_returns_empty_and_is_not_cached_usefully(self, provider):
        """全部数据源失败 → 返回 {}；且 {} 是 falsy，下次调用不会命中缓存"""
        provider._compute_atr = AsyncMock(return_value=None)
        provider._fetch_today_quote = AsyncMock(return_value=None)
        provider._fetch_market_stats = AsyncMock(return_value=None)

        assert await provider.fetch_market_data("sh600584") == {}
        # 缓存里确实写了空值，但 _cache_get 返回 {} 是 falsy → 不会被当成命中
        assert not provider._cache_get("market_data_sh600584")


# ════════════════════ 契约：provider → R2 ════════════════════


class TestR2ContractWithProvider:
    """provider 的符号约定与 R2 判定必须一致 —— 这是 abs() 误报的根源所在。"""

    @pytest.fixture
    def checker(self, tmp_path) -> AdvancedRiskChecker:
        return AdvancedRiskChecker(
            RiskConfig(advanced_rules_state_path=str(tmp_path / "state.json"))
        )

    def _market_data_for(self, change_percent: float) -> dict:
        """复刻 fetch_market_data 中 stock_drop_pct 的换算（change_percent / 100）"""
        return {"stock_drop_pct": change_percent / 100}

    def test_falling_stock_freezes(self, checker):
        result = checker._check_freeze_buy("sh600584", 9.2, self._market_data_for(-8.0))

        assert result is not None
        assert result.severity is RuleSeverity.CRITICAL

    def test_rising_stock_does_not_freeze(self, checker):
        """上涨 8%（腾讯 change_percent = +8.0）不得冻结"""
        assert checker._check_freeze_buy("sh600584", 10.8, self._market_data_for(8.0)) is None

    def test_limit_up_stock_does_not_freeze(self, checker):
        assert checker._check_freeze_buy("sh600584", 11.0, self._market_data_for(10.0)) is None


# ════════════════════ 便捷函数 ════════════════════


class TestConvenienceFunction:
    async def test_delegates_to_provider(self):
        expected = {"atr": 1.0}

        with patch.object(
            MarketDataProvider, "fetch_market_data", new=AsyncMock(return_value=expected)
        ):
            result = await get_market_data_for_symbol("sh600584")

        assert result == expected
