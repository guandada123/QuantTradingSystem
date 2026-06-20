"""
测试数据质量监控服务
Cover services/data_quality.py 核心逻辑分支。

关键挑战：
1. prometheus_client 使用全局注册表 → 必须 mock 避免重复注册
2. akshare 是函数内 `import akshare as ak` → 通过 sys.modules mock
3. datetime.now() / date.today() → 替换模块级引用
"""

import datetime as dt
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 在 import 被测试模块前 mock prometheus_client，避免全局注册冲突
mprom = MagicMock()
mprom.Gauge = MagicMock(return_value=MagicMock())
mprom.Counter = MagicMock(return_value=MagicMock())
mprom.Histogram = MagicMock(return_value=MagicMock())

with patch.dict("sys.modules", {"prometheus_client": mprom}):
    from services.data_quality import DataQualityMonitor, DataQualityRule


# ============================================================
# DataQualityRule
# ============================================================


class TestDataQualityRule:
    """测试 DataQualityRule dataclass"""

    def test_default_values(self):
        """默认值正确 (line 40-45)"""
        rule = DataQualityRule(name="test", source="test_source")
        assert rule.name == "test"
        assert rule.source == "test_source"
        assert rule.max_freshness_minutes == 30
        assert rule.check_weekend is False
        assert rule.check_gaps is True
        assert rule.check_anomalies is True

    def test_custom_values(self):
        """自定义值正确"""
        rule = DataQualityRule(
            name="custom",
            source="cs",
            max_freshness_minutes=60,
            check_weekend=True,
            check_gaps=False,
            check_anomalies=False,
        )
        assert rule.max_freshness_minutes == 60
        assert rule.check_weekend is True


# ============================================================
# DataQualityMonitor — 基础段
# ============================================================


class TestDataQualityMonitorInit:
    """测试 __init__()"""

    def test_default_rules(self):
        """默认初始化包含5条规则 (line 53-62)"""
        monitor = DataQualityMonitor()
        assert len(monitor.rules) == 5
        assert monitor.rules[0].name == "每日行情"
        assert monitor.rules[0].source == "daily_quote"
        assert monitor.rules[0].max_freshness_minutes == 24 * 60
        assert monitor.last_check_time is None
        assert monitor.last_update == {}


class TestIsTradingDay:
    """测试 is_trading_day()"""

    def test_weekday(self):
        """周四 → True (line 68-69)"""
        monitor = DataQualityMonitor()
        monitor._today = lambda: dt.date(2026, 6, 18)  # Thursday
        assert monitor.is_trading_day() is True

    def test_weekend(self):
        """周六 → False (line 67-68)"""
        monitor = DataQualityMonitor()
        monitor._today = lambda: dt.date(2026, 6, 20)  # Saturday
        assert monitor.is_trading_day() is False


class TestIsTradingHours:
    """测试 is_trading_hours()"""

    def test_during_hours(self):
        """10:30 → True"""
        monitor = DataQualityMonitor()
        monitor._now = lambda: dt.datetime(2026, 6, 18, 10, 30)
        assert monitor.is_trading_hours() is True

    def test_before_open(self):
        """8:59 → False"""
        monitor = DataQualityMonitor()
        monitor._now = lambda: dt.datetime(2026, 6, 18, 8, 59)
        assert monitor.is_trading_hours() is False

    def test_after_close(self):
        """15:01 → False"""
        monitor = DataQualityMonitor()
        monitor._now = lambda: dt.datetime(2026, 6, 18, 15, 1)
        assert monitor.is_trading_hours() is False


class TestMarkUpdate:
    """测试 mark_update()"""

    def test_sets_last_update(self):
        """标记更新 → last_update 记录时间 (line 78-80)"""
        monitor = DataQualityMonitor()
        monitor.mark_update("daily_quote")
        assert "daily_quote" in monitor.last_update
        assert isinstance(monitor.last_update["daily_quote"], dt.datetime)

    def test_sets_freshness_gauge_zero(self):
        """更新标记 → freshness 指标设为0 (line 80)"""
        monitor = DataQualityMonitor()
        monitor.mark_update("daily_quote")
        mprom.Gauge.return_value.labels.assert_called_with(data_source="daily_quote")
        mprom.Gauge.return_value.labels.return_value.set.assert_called_with(0)


# ============================================================
# check_data_source_online
# ============================================================
# 源码使用 `import akshare as ak` 局部导入，通过 mock sys.modules 拦截


class TestCheckDataSourceOnline:
    """测试 check_data_source_online()"""

    @pytest.mark.asyncio
    async def test_akshare_online(self):
        """akshare 在线 → 返回 True (line 87-90)"""
        monitor = DataQualityMonitor()
        mock_ak = MagicMock()
        mock_df = MagicMock()
        mock_df.__len__.return_value = 5
        mock_ak.stock_zh_index_spot_em.return_value = mock_df

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            result = await monitor.check_data_source_online("akshare")
        assert result is True

    @pytest.mark.asyncio
    async def test_akshare_offline(self):
        """akshare 返回空数据 → 返回 False (line 90, 96-97)"""
        monitor = DataQualityMonitor()
        mock_ak = MagicMock()
        mock_df = MagicMock()
        mock_df.__len__.return_value = 0
        mock_ak.stock_zh_index_spot_em.return_value = mock_df

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            result = await monitor.check_data_source_online("akshare")
        assert result is False

    @pytest.mark.asyncio
    async def test_akshare_exception(self):
        """akshare 抛异常 → 返回 False (line 98-101)"""
        monitor = DataQualityMonitor()
        mock_ak = MagicMock()
        mock_ak.stock_zh_index_spot_em.side_effect = Exception("network error")

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            result = await monitor.check_data_source_online("akshare")
        assert result is False

    @pytest.mark.asyncio
    async def test_tushare_always_online(self):
        """tushare 不测试连接 → 返回 True (line 91-92)"""
        monitor = DataQualityMonitor()
        mock_ak = MagicMock()
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            result = await monitor.check_data_source_online("tushare")
        assert result is True

    @pytest.mark.asyncio
    async def test_unknown_source(self):
        """未知源 → 返回 True (line 93-94)"""
        monitor = DataQualityMonitor()
        mock_ak = MagicMock()
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            result = await monitor.check_data_source_online("unknown_source")
        assert result is True

    @pytest.mark.asyncio
    async def test_online_sets_gauge(self):
        """在线状态更新 gauge (line 96)"""
        monitor = DataQualityMonitor()
        mock_ak = MagicMock()
        mock_df = MagicMock()
        mock_df.__len__.return_value = 3
        mock_ak.stock_zh_index_spot_em.return_value = mock_df

        labels_call_count_before = len(mprom.Gauge.return_value.labels.call_args_list)

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            await monitor.check_data_source_online("akshare")

        assert len(mprom.Gauge.return_value.labels.call_args_list) > labels_call_count_before


# ============================================================
# check_freshness
# ============================================================


class TestCheckFreshness:
    """测试 check_freshness()"""

    @pytest.mark.asyncio
    async def test_no_last_update(self):
        """从未更新 → 返回 (False, inf) (line 106-108)"""
        monitor = DataQualityMonitor()
        rule = DataQualityRule(name="test", source="test_source")
        ok, delay = await monitor.check_freshness(rule)
        assert ok is False
        assert delay == float("inf")

    @pytest.mark.asyncio
    async def test_fresh(self):
        """在新鲜度窗口内 → 返回 (True, delay) (line 110-121)"""
        now = dt.datetime(2026, 6, 18, 10, 0, 0)
        monitor = DataQualityMonitor()
        monitor._now = lambda: now
        monitor._today = lambda: now.date()

        monitor.last_update["test_source"] = now - dt.timedelta(seconds=60)
        rule = DataQualityRule(name="test", source="test_source", max_freshness_minutes=5)
        ok, delay = await monitor.check_freshness(rule)
        assert ok is True
        assert delay == pytest.approx(60.0)

    @pytest.mark.asyncio
    async def test_stale(self):
        """超时未更新 → 返回 (False, delay) (line 117-118)"""
        now = dt.datetime(2026, 6, 18, 10, 0, 0)
        monitor = DataQualityMonitor()
        monitor._now = lambda: now
        monitor._today = lambda: now.date()

        monitor.last_update["test_source"] = now - dt.timedelta(minutes=10)
        rule = DataQualityRule(name="test", source="test_source", max_freshness_minutes=5)
        ok, delay = await monitor.check_freshness(rule)
        assert ok is False
        assert delay == pytest.approx(600.0)

    @pytest.mark.asyncio
    async def test_skip_non_trading_day(self):
        """非交易日 + check_weekend=False → 跳过检查 (line 114-115)"""
        now = dt.datetime(2026, 6, 20, 10, 0, 0)  # Saturday
        monitor = DataQualityMonitor()
        monitor._now = lambda: now
        monitor._today = lambda: now.date()

        monitor = DataQualityMonitor()
        monitor.last_update["test_source"] = now - dt.timedelta(hours=24)
        rule = DataQualityRule(
            name="test",
            source="test_source",
            max_freshness_minutes=5,
            check_weekend=False,
        )
        ok, delay = await monitor.check_freshness(rule)
        assert ok is True  # 跳过检查，返回成功


# ============================================================
# check_gaps
# ============================================================


class TestCheckGaps:
    """测试 check_gaps()"""

    @pytest.mark.asyncio
    async def test_less_than_two(self):
        """少于2个时间戳 → 0 间隔 (line 125-126)"""
        monitor = DataQualityMonitor()
        assert await monitor.check_gaps("src", "sym", [dt.datetime(2026, 1, 1)]) == 0
        assert await monitor.check_gaps("src", "sym", []) == 0

    @pytest.mark.asyncio
    async def test_no_gaps(self):
        """连续数据 → 无间隔 (line 129-134)"""
        monitor = DataQualityMonitor()
        timestamps = [dt.datetime(2026, 1, 1, 10, 0, i) for i in range(5)]
        gaps = await monitor.check_gaps("src", "sym", timestamps)
        assert gaps == 0

    @pytest.mark.asyncio
    async def test_with_gaps(self):
        """存在时间间隔超过3分钟 → 计为缺失 (line 133-134)"""
        monitor = DataQualityMonitor()
        timestamps = [
            dt.datetime(2026, 1, 1, 10, 0, 0),
            dt.datetime(2026, 1, 1, 10, 1, 0),
            dt.datetime(2026, 1, 1, 10, 5, 0),  # +4min > 3min → gap
            dt.datetime(2026, 1, 1, 10, 6, 0),
        ]
        gaps = await monitor.check_gaps("src", "sym", timestamps)
        assert gaps == 1

    @pytest.mark.asyncio
    async def test_gap_count_gauge_set(self):
        """gap 数量更新到 gauge (line 136)"""
        monitor = DataQualityMonitor()
        timestamps = [
            dt.datetime(2026, 1, 1, 10, 0, 0),
            dt.datetime(2026, 1, 1, 10, 5, 0),  # +5min → gap
        ]
        await monitor.check_gaps("src", "sym", timestamps)
        mprom.Gauge.return_value.labels.assert_any_call(data_source="src", symbol="sym")


# ============================================================
# check_anomalies
# ============================================================


class TestCheckAnomalies:
    """测试 check_anomalies()"""

    @pytest.mark.asyncio
    async def test_less_than_ten_values(self):
        """少于10个数据点 → 0 (line 143-144)"""
        monitor = DataQualityMonitor()
        assert await monitor.check_anomalies("src", [100.0] * 5) == 0

    @pytest.mark.asyncio
    async def test_no_anomalies(self):
        """正常值 → 0 异常 (line 143-168)"""
        monitor = DataQualityMonitor()
        values = [100.0 + i for i in range(50)]
        anomalies = await monitor.check_anomalies("src", values)
        assert anomalies == 0

    @pytest.mark.asyncio
    async def test_zscore_anomaly(self):
        """Z-score 超出阈值 → 检测为异常 (line 155-159)"""
        monitor = DataQualityMonitor()
        values = [100.0] * 20 + [500.0] + [100.0] * 20
        anomalies = await monitor.check_anomalies("src", values)
        assert anomalies >= 1

    @pytest.mark.asyncio
    async def test_negative_price(self):
        """负价格 → 记录为异常 (line 162-165)"""
        monitor = DataQualityMonitor()
        values = [100.0] * 20 + [-50.0]
        anomalies = await monitor.check_anomalies("src", values)
        assert anomalies >= 1
        mprom.Counter.return_value.labels.assert_any_call(
            data_source="src", anomaly_type="negative_price"
        )

    @pytest.mark.asyncio
    async def test_extreme_value(self):
        """超大价格 → 记录为异常 (line 166-168)"""
        monitor = DataQualityMonitor()
        values = [100.0] * 20 + [1000000.0]
        anomalies = await monitor.check_anomalies("src", values)
        assert anomalies >= 1
        mprom.Counter.return_value.labels.assert_any_call(
            data_source="src", anomaly_type="extreme_value"
        )

    @pytest.mark.asyncio
    async def test_zero_stdev(self):
        """标准差为0 → 返回0 (line 151-152)"""
        monitor = DataQualityMonitor()
        values = [100.0] * 20
        anomalies = await monitor.check_anomalies("src", values)
        assert anomalies == 0


# ============================================================
# run_check — 集成
# ============================================================


class TestRunCheck:
    """测试 run_check() 集成"""

    @pytest.mark.asyncio
    async def test_run_check_basic(self):
        """完整运行一次检查 (line 172-222)"""
        monitor = DataQualityMonitor()

        monitor.check_data_source_online = AsyncMock(return_value=True)
        monitor.check_freshness = AsyncMock(return_value=(True, 30.0))
        monitor.is_trading_day = MagicMock(return_value=True)
        monitor.is_trading_hours = MagicMock(return_value=True)

        results = await monitor.run_check()

        assert "timestamp" in results
        assert "trading_day" in results
        assert "checks" in results
        assert "overall_score" in results
        assert len(results["checks"]) == 2 + 5  # 2 source + 5 rules
        assert 0 <= results["overall_score"] <= 100
        assert monitor.last_check_time is not None

    @pytest.mark.asyncio
    async def test_source_offline_score_reduction(self):
        """数据源离线 → 扣分 (line 193-194)"""
        monitor = DataQualityMonitor()
        monitor.check_data_source_online = AsyncMock(return_value=False)
        monitor.check_freshness = AsyncMock(return_value=(True, 30.0))

        results = await monitor.run_check()
        assert results["overall_score"] <= 80

    @pytest.mark.asyncio
    async def test_stale_freshness_score_reduction(self):
        """数据超过1小时未更新 → 扣分 (line 208-209)"""
        monitor = DataQualityMonitor()
        monitor.check_data_source_online = AsyncMock(return_value=True)
        monitor.check_freshness = AsyncMock(return_value=(False, 7200.0))

        results = await monitor.run_check()
        assert results["overall_score"] <= 85

    @pytest.mark.asyncio
    async def test_score_clamped(self):
        """分数被限制在 0-100 范围内 (line 212)"""
        monitor = DataQualityMonitor()
        monitor.check_data_source_online = AsyncMock(return_value=False)
        monitor.check_freshness = AsyncMock(return_value=(False, 7200.0))

        results = await monitor.run_check()
        assert results["overall_score"] >= 0
        assert results["overall_score"] <= 100
