"""TushareQuoteProvider 取数保护回归测试

覆盖 2026-10-23 加固的三处行为：
1. 估值取最新行不依赖接口默认排序（接口若改降序/乱序仍正确）
2. 窗口为空时回退全历史（长期停牌标的不退化）
3. 触达单次 6000 行上限时留告警，以及日线 limit 截断告警

使用真实 pandas DataFrame 而非 MagicMock，确保排序与行数逻辑被真正执行。
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from shared.quote_provider import tushare as tushare_module
from shared.quote_provider.tushare import TUSHARE_SINGLE_REQUEST_LIMIT, TushareQuoteProvider

FIELDS = ["ts_code", "pe_ttm", "pb", "ps_ttm", "total_mv", "circ_mv", "trade_date"]


class FakePro:
    """最小可用的 Tushare Pro 替身：记录调用并按队列返回数据"""

    def __init__(
        self, basic_frames: list[pd.DataFrame], daily_frames: list[pd.DataFrame] | None = None
    ):
        self._basic_frames = list(basic_frames)
        self._daily_frames = list(daily_frames or [])
        self.basic_calls: list[dict] = []
        self.daily_calls: list[dict] = []

    def daily_basic(self, **kwargs) -> pd.DataFrame:
        self.basic_calls.append(kwargs)
        if self._basic_frames:
            return self._basic_frames.pop(0)
        return pd.DataFrame(columns=FIELDS)

    def daily(self, **kwargs) -> pd.DataFrame:
        self.daily_calls.append(kwargs)
        if self._daily_frames:
            return self._daily_frames.pop(0)
        return pd.DataFrame(columns=["ts_code", "trade_date", "close"])


def make_frame(dates: list[str], pe: float = 10.0) -> pd.DataFrame:
    """按给定日期顺序构造 daily_basic 返回体（顺序即接口返回顺序）"""
    return pd.DataFrame(
        [
            {
                "ts_code": "600519.SH",
                "pe_ttm": pe + idx,
                "pb": 6.2,
                "ps_ttm": 8.1,
                "total_mv": 2.27e12,
                "circ_mv": 2.27e12,
                "trade_date": d,
            }
            for idx, d in enumerate(dates)
        ],
        columns=FIELDS,
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个用例前后清空估值缓存，避免跨用例污染"""
    TushareQuoteProvider.clear_fundamental_cache()
    yield
    TushareQuoteProvider.clear_fundamental_cache()


@pytest.fixture
def provider() -> TushareQuoteProvider:
    p = TushareQuoteProvider()
    assert p._pro is None
    return p


def attach(provider: TushareQuoteProvider, fake: FakePro) -> None:
    provider._pro = fake


class TestFundamentalLatestRow:
    def test_ascending_frame_picks_latest(self, provider):
        fake = FakePro([make_frame(["20261020", "20261021", "20261022"])])
        attach(provider, fake)

        result = provider.get_fundamental("600519.SH")

        assert result["pe_ttm"] == 12.0
        assert fake.basic_calls[0].get("start_date") is not None

    def test_descending_frame_still_picks_latest(self, provider):
        """接口改为降序返回时，仍必须取到最新一天（原实现 iloc[0] 会取到最新，但无契约）"""
        fake = FakePro([make_frame(["20261022", "20261021", "20261020"])])
        attach(provider, fake)

        result = provider.get_fundamental("600519.SH")

        assert result["pe_ttm"] == 10.0

    def test_window_empty_falls_back_to_full_history(self, provider):
        """长期停牌：窗口内无数据，回退全历史取停牌前最后一次估值"""
        fake = FakePro(
            [
                pd.DataFrame(columns=FIELDS),
                make_frame(["20240102", "20240103"]),
            ]
        )
        attach(provider, fake)

        result = provider.get_fundamental("600519.SH")

        assert result["pe_ttm"] == 11.0
        assert len(fake.basic_calls) == 2
        assert fake.basic_calls[1].get("start_date") is None

    def test_both_empty_returns_empty_dict(self, provider):
        fake = FakePro([pd.DataFrame(columns=FIELDS), pd.DataFrame(columns=FIELDS)])
        attach(provider, fake)

        assert provider.get_fundamental("600519.SH") == {}

    def test_truncation_logs_warning(self, provider, caplog):
        """回退全历史且行数触达 6000 上限时必须留痕，不能静默"""
        full = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "pe_ttm": 8.0,
                    "pb": 1.2,
                    "ps_ttm": 2.0,
                    "total_mv": 2.0e11,
                    "circ_mv": 2.0e11,
                    "trade_date": f"20{idx:06d}",
                }
                for idx in range(TUSHARE_SINGLE_REQUEST_LIMIT)
            ],
            columns=FIELDS,
        )
        fake = FakePro([pd.DataFrame(columns=FIELDS), full])
        attach(provider, fake)

        with caplog.at_level(logging.WARNING):
            provider.get_fundamental("000001.SZ")

        assert any("单次返回上限" in rec.message for rec in caplog.records)

    def test_missing_pe_keeps_other_fields(self, provider):
        """亏损股 pe_ttm 为空时不得丢弃整条记录。

        2026-10-22 实测 1632/5570 只（29%）PE 为空，旧实现 float(None) 抛错后整条返回 {}，
        连有效的 PB/PS/市值都拿不到。
        """
        frame = pd.DataFrame(
            [
                {
                    "ts_code": "000002.SZ",
                    "pe_ttm": None,
                    "pb": 0.3865,
                    "ps_ttm": 0.1992,
                    "total_mv": 1.0e7,
                    "circ_mv": 9.0e6,
                    "trade_date": "20261022",
                }
            ],
            columns=FIELDS,
        )
        attach(provider, FakePro([frame]))

        result = provider.get_fundamental("000002.SZ")

        assert result["pe_ttm"] is None
        assert result["pb"] == 0.3865
        assert result["ps_ttm"] == 0.1992
        assert result["total_mv"] == 1.0e7

    def test_nan_value_becomes_none(self, provider):
        """pandas 常把空值读成 NaN 而非 None，两种都要归一为 None"""
        frame = pd.DataFrame(
            [
                {
                    "ts_code": "000006.SZ",
                    "pe_ttm": float("nan"),
                    "pb": 1.6792,
                    "ps_ttm": 5.7728,
                    "total_mv": 2.0e7,
                    "circ_mv": 1.8e7,
                    "trade_date": "20261022",
                }
            ],
            columns=FIELDS,
        )
        attach(provider, FakePro([frame]))

        result = provider.get_fundamental("000006.SZ")

        assert result["pe_ttm"] is None
        assert result["pb"] == 1.6792


class TestFundamentalCache:
    def test_second_call_hits_cache(self, provider):
        fake = FakePro([make_frame(["20261022"])])
        attach(provider, fake)

        first = provider.get_fundamental("600519.SH")
        second = provider.get_fundamental("600519.SH")

        assert first == second
        assert len(fake.basic_calls) == 1, "缓存命中时不应再次请求接口"

    def test_cached_result_is_copy(self, provider):
        """调用方修改返回值不得污染缓存"""
        fake = FakePro([make_frame(["20261022"])])
        attach(provider, fake)

        first = provider.get_fundamental("600519.SH")
        first["pe_ttm"] = -1.0
        second = provider.get_fundamental("600519.SH")

        assert second["pe_ttm"] == 10.0

    def test_cache_evicts_oldest_when_full(self, monkeypatch):
        """容量超限时按插入顺序淘汰最早的，避免无界增长。

        直接测 `_evict_if_full`：通过 provider 走一遍会被 FakePro 的固定 frame 干扰，
        测不到纯粹的淘汰语义。
        """
        import shared.quote_provider.tushare as tushare_mod

        monkeypatch.setattr(tushare_mod, "FUNDAMENTAL_CACHE_MAX", 4)
        tushare_mod._FUNDAMENTAL_CACHE.clear()

        for i in range(8):
            tushare_mod._evict_if_full()  # 与写入路径一致：先淘汰再写
            tushare_mod._FUNDAMENTAL_CACHE[f"k{i}"] = (0.0, {})

        cache = tushare_mod._FUNDAMENTAL_CACHE
        assert len(cache) == 4, f"应稳定在容量上限，实际 {len(cache)}"
        assert "k7" in cache, "最后写入的必须保留"
        assert "k0" not in cache, "最早的应被淘汰"

    def test_ttl_shorter_in_refresh_window(self, monkeypatch):
        """15:00–17:00 是 daily_basic 更新窗口，TTL 应缩短，避免缓存掩盖刷新"""
        import datetime as dt_mod

        import shared.quote_provider.tushare as tushare_mod

        class _FakeDT:
            @staticmethod
            def now(tz=None):
                return dt_mod.datetime(2026, 10, 23, 15, 30, tzinfo=tz)

        monkeypatch.setattr(tushare_mod, "datetime", _FakeDT)
        assert tushare_mod._fundamental_cache_ttl() == 300

    def test_ttl_normal_outside_window(self, monkeypatch):
        import datetime as dt_mod

        import shared.quote_provider.tushare as tushare_mod

        class _FakeDT:
            @staticmethod
            def now(tz=None):
                return dt_mod.datetime(2026, 10, 23, 10, 0, tzinfo=tz)

        monkeypatch.setattr(tushare_mod, "datetime", _FakeDT)
        assert tushare_mod._fundamental_cache_ttl() == 3600

    def test_cn_tz_falls_back_when_tzdata_missing(self, monkeypatch):
        """缺 tzdata 时不得 ImportError —— 否则整个 quote_provider 会在 import 期被打挂。

        `CN_TZ` 是模块顶层求值，`ZoneInfo("Asia/Shanghai")` 在没有 tzdata 的镜像里会抛
        ZoneInfoNotFoundError，经 `shared/quote_provider/__init__ → factory` 传染所有调用方。
        兜底用固定 `UTC+08:00`：中国**无夏令时**，与 Asia/Shanghai 语义等价。
        """
        import datetime as dt_mod

        import shared.quote_provider.tushare as tushare_mod

        def _boom(_name):
            raise KeyError("no tzdata")

        monkeypatch.setattr(tushare_mod, "ZoneInfo", _boom)
        tz = tushare_mod._resolve_cn_tz()
        assert tz.utcoffset(dt_mod.datetime(2026, 10, 23, 12, 0)) == dt_mod.timedelta(hours=8), (
            f"兜底时区偏移应为 +08:00，实得 {tz}"
        )

    def test_ttl_uses_market_timezone_not_container(self, monkeypatch):
        """刷新窗口必须按**交易所时区**判定（2026-10-28 修复，CI 首暴）。

        缺陷：`_fundamental_cache_ttl()` 原用裸 `datetime.now().hour`，取的是容器本地时区。
        生产/CI 容器 TZ=UTC → 窗口落在 UTC 15–17 点 = 北京 23–01 点：
          ① 真正的收盘刷新窗口（北京 15–17）走 1h 长 TTL，缓存会掩盖当天新数据；
          ② 半夜被缩到 5min，纯浪费请求。
        本用例把「同一时刻」摆成 UTC 07:30（= 北京 15:30）：按交易所时区应命中窗口（300s），
        按容器钟（7 点）则会落到 3600s。断言能同时钉住「用了哪个时区」。
        """
        import datetime as dt_mod

        import shared.quote_provider.tushare as tushare_mod

        fixed_utc = dt_mod.datetime(2026, 10, 23, 7, 30, tzinfo=dt_mod.UTC)

        class _FakeDT:
            @staticmethod
            def now(tz=None):
                return fixed_utc.astimezone(tz) if tz else fixed_utc.replace(tzinfo=None)

        monkeypatch.setattr(tushare_mod, "datetime", _FakeDT)
        assert tushare_mod._market_hour() == 15, "交易所小时应为北京时间（UTC+8）"
        assert tushare_mod._fundamental_cache_ttl() == 300, "北京 15:30 必须在刷新窗口内"

    def test_cache_expires(self, provider, monkeypatch):
        """缓存过期后必须重新取数。

        2026-10-28 修复（CI 首暴，每天有 2 小时窗口必红）：原实现 monkeypatch 的是
        `FUNDAMENTAL_CACHE_TTL_SECONDS`，但 `_fundamental_cache_ttl()` 在
        「刷新窗口」分支返回的是另一个常量（300s）—— 于是只要跑测时刻落在窗口内，
        常量 0 就完全不生效，缓存没过期，断言 `10.0 == 99.0` 失败。
        真因是测试依赖跑测时刻，不是产品缺陷 → 直接钉死 TTL 函数，与钟点解耦。
        """
        fake = FakePro([make_frame(["20261022"]), make_frame(["20261022"], pe=99.0)])
        attach(provider, fake)

        provider.get_fundamental("600519.SH")
        monkeypatch.setattr(tushare_module, "_fundamental_cache_ttl", lambda: 0)
        refreshed = provider.get_fundamental("600519.SH")

        assert refreshed["pe_ttm"] == 99.0
        assert len(fake.basic_calls) == 2


class TestDailyKlineTruncation:
    def test_limit_truncation_logs_warning(self, provider, caplog):
        dates = [f"2026{idx % 12 + 1:02d}{idx % 28 + 1:02d}" for idx in range(50)]
        frame = pd.DataFrame(
            [
                {"ts_code": "600519.SH", "trade_date": d, "close": 100.0 + i}
                for i, d in enumerate(dates)
            ]
        )
        attach(provider, FakePro([], [frame]))

        with caplog.at_level(logging.WARNING):
            rows = provider.get_daily_kline("600519.SH", limit=10)

        assert len(rows) == 10
        assert any("被 limit 截断" in rec.message for rec in caplog.records)

    def test_no_warning_when_under_limit(self, provider, caplog):
        frame = pd.DataFrame([{"ts_code": "600519.SH", "trade_date": "20261022", "close": 100.0}])
        attach(provider, FakePro([], [frame]))

        with caplog.at_level(logging.WARNING):
            rows = provider.get_daily_kline("600519.SH", limit=10)

        assert len(rows) == 1
        assert not any("被 limit 截断" in rec.message for rec in caplog.records)
