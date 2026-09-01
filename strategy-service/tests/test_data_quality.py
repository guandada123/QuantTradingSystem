"""
测试数据质量监控服务
Cover services/data_quality.py 核心逻辑分支。

关键挑战：
1. prometheus_client 使用全局注册表 → 必须 mock 避免重复注册
2. akshare 是函数内 `import akshare as ak` → 通过 sys.modules mock
3. datetime.now() / date.today() → 替换模块级引用
"""

import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 在 import 被测试模块前 mock prometheus_client，避免全局注册冲突
mprom = MagicMock()
mprom.Gauge = MagicMock(return_value=MagicMock())
mprom.Counter = MagicMock(return_value=MagicMock())
mprom.Histogram = MagicMock(return_value=MagicMock())

with patch.dict("sys.modules", {"prometheus_client": mprom}):
    from services.data_quality import DataQualityMonitor, DataQualityRule, _Probe

# 探针状态别名，测试里写起来更紧凑
_Probe_OK = _Probe.OK
_Probe_EMPTY = _Probe.EMPTY
_Probe_ERROR = _Probe.ERROR
_Probe_UNMAPPED = _Probe.UNMAPPED


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
        # __init__ 会给每条规则播种一个当前时间戳，避免服务刚启动时
        # 所有数据源都被判为"从未更新"而集体扣分（源码有显式注释）
        assert set(monitor.last_update) == {r.source for r in monitor.rules}


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
    """测试 is_trading_hours()

    ⚠️ 2026-09-02 修正：_now() 在容器内返回 **UTC** naive 时间（TZ=UTC），
    而 A股时段是北京时间口径。旧断言把 _now() 当北京墙钟用（10:30→True），
    等于把「UTC 10:30」误判成「北京 10:30」—— 在偏移 8 小时。修正后一律
    显式写 UTC 时刻并换算：北京 10:30 = UTC 02:30。
    """

    def test_during_hours(self):
        """北京 10:30（UTC 02:30，周四）→ True"""
        monitor = DataQualityMonitor()
        monitor._now = lambda: dt.datetime(2026, 6, 18, 2, 30)
        assert monitor.is_trading_hours() is True

    def test_before_open(self):
        """北京 08:59（UTC 00:59）→ False"""
        monitor = DataQualityMonitor()
        monitor._now = lambda: dt.datetime(2026, 6, 18, 0, 59)
        assert monitor.is_trading_hours() is False

    def test_after_close(self):
        """北京 15:40（UTC 07:40）→ False

        注意：交易日历午盘刻意放宽到 15:35（收盘后还要采一次收尾快照），
        所以 15:01 仍算盘中 —— 别按"15:00 收盘"想当然。
        """
        monitor = DataQualityMonitor()
        monitor._now = lambda: dt.datetime(2026, 6, 18, 7, 40)
        assert monitor.is_trading_hours() is False

    def test_closing_buffer_counts_as_trading(self):
        """北京 15:20（UTC 07:20）仍在收尾窗口内 → True"""
        monitor = DataQualityMonitor()
        monitor._now = lambda: dt.datetime(2026, 6, 18, 7, 20)
        assert monitor.is_trading_hours() is True

    def test_lunch_break(self):
        """北京 12:00 午休（UTC 04:00）→ False"""
        monitor = DataQualityMonitor()
        monitor._now = lambda: dt.datetime(2026, 6, 18, 4, 0)
        assert monitor.is_trading_hours() is False

    def test_utc_clock_is_not_beijing_clock(self):
        """回归：UTC 10:30 是北京 18:30，已收盘 → 不得判为盘中"""
        monitor = DataQualityMonitor()
        monitor._now = lambda: dt.datetime(2026, 6, 18, 10, 30)
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
        # 源码探活接口已从 stock_zh_index_spot_em 换成更轻量的 stock_zh_index_daily
        mock_ak.stock_zh_index_daily.return_value = mock_df

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
        mock_ak.stock_zh_index_daily.return_value = mock_df

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            result = await monitor.check_data_source_online("akshare")
        assert result is False

    @pytest.mark.asyncio
    async def test_akshare_exception(self):
        """akshare 抛异常 → 返回 False (line 98-101)"""
        monitor = DataQualityMonitor()
        mock_ak = MagicMock()
        mock_ak.stock_zh_index_daily.side_effect = Exception("network error")

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


# ============================================================
# run_check 通过数一致性（2026-09-01 修复回归）
# ============================================================
class TestRunCheckPassedConsistency:
    """回归：「评分 55/100 却报 通过 7/7」

    2026-09-01 实测：24h 内 295 次数据质量检查，251 次打出
    「评分: 55/100 … 通过: 7/7」。根因是 freshness 检查项的 dict
    **没有 passed 键**，而统计用 c.get('passed', True) —— 键缺失即
    默认通过。于是 5 条 freshness 规则无论多陈旧都被算作通过，
    只剩 2 条 source_online 真实计分。

    本组用例锁定两件事：
    1. 扣分与「不通过」严格一一对应（评分 100 ⟺ 通过 N/N）
    2. 统计对**缺失 passed 键**是 fail-safe（算不通过，不算通过）
    """

    @staticmethod
    def _passed_count(results):
        return sum(1 for c in results["checks"] if c.get("passed") is True)

    @pytest.mark.asyncio
    async def test_failed_freshness_is_counted_as_not_passed(self):
        """freshness 超时 → 该项必须计入「不通过」，不得因缺键被默认通过"""
        monitor = DataQualityMonitor()
        monitor.check_data_source_online = AsyncMock(return_value=True)
        # 全部 5 条规则都陈旧 2 小时 → 每条扣 15 分
        monitor.check_freshness = AsyncMock(return_value=(False, 7200.0))

        results = await monitor.run_check()

        assert results["overall_score"] == 25  # 100 - 5*15
        assert self._passed_count(results) == 2  # 仅 2 条 source_online 通过
        assert len(results["checks"]) == 7

    @pytest.mark.asyncio
    async def test_all_fresh_yields_full_pass(self):
        """全新鲜 → 评分 100 且 通过 7/7（两个口径必须同时满分）"""
        monitor = DataQualityMonitor()
        monitor.check_data_source_online = AsyncMock(return_value=True)
        monitor.check_freshness = AsyncMock(return_value=(True, 60.0))

        results = await monitor.run_check()

        assert results["overall_score"] == 100
        assert self._passed_count(results) == 7

    @pytest.mark.asyncio
    async def test_every_check_carries_passed_key(self):
        """任一检查项都不得缺少 passed 键 —— 缺键即统计口径失效"""
        monitor = DataQualityMonitor()
        monitor.check_data_source_online = AsyncMock(return_value=False)
        monitor.check_freshness = AsyncMock(return_value=(False, 7200.0))

        results = await monitor.run_check()

        missing = [c for c in results["checks"] if "passed" not in c]
        assert missing == [], f"检查项缺少 passed 键: {missing}"

    @pytest.mark.asyncio
    async def test_missing_passed_key_counts_as_failed(self):
        """统计口径是 fail-safe：报不出状态的检查项算不通过"""
        results = {
            "checks": [
                {"type": "source_online", "source": "tushare", "passed": True},
                {"type": "freshness", "source": "daily_quote"},  # 缺 passed
            ]
        }
        assert self._passed_count(results) == 1

    @pytest.mark.asyncio
    async def test_offline_sources_reduce_passed_count(self):
        """两个数据源离线 → 2 条 source_online 计入不通过"""
        monitor = DataQualityMonitor()
        monitor.check_data_source_online = AsyncMock(return_value=False)
        monitor.check_freshness = AsyncMock(return_value=(True, 60.0))

        results = await monitor.run_check()

        assert results["overall_score"] == 80  # 100 - 2*10
        assert self._passed_count(results) == 5  # 仅 5 条 freshness 通过


# ============================================================
# 数据库真值新鲜度（2026-09-02 修复，回归防复发）
# ============================================================


class TestFreshnessUsesDatabaseTruth:
    """freshness 必须读数据库真值，不能退化成「容器运行时长」

    背景：mark_update() 在生产侧零调用，self.last_update 恒为 __init__ 播种的
    启动时刻，于是评分变成 uptime 的纯函数（<1h→100 / 1h~24h→55 / >24h→25），
    与真实数据无关 —— 实测 6 次 100→55 跃迁全部落在重启后 60~82 分钟。
    """

    @staticmethod
    def _monitor(now_utc: dt.datetime):
        m = DataQualityMonitor()
        m._now = lambda: now_utc
        return m

    @pytest.mark.asyncio
    async def test_db_truth_overrides_fresh_inmemory_state(self):
        """核心回归：进程内记录很新、库里数据很旧 → 必须判陈旧"""
        now = dt.datetime(2026, 6, 18, 2, 30)  # 北京 10:30 周四，盘中
        m = self._monitor(now)
        rule = DataQualityRule(
            name="t",
            source="test_source",
            max_freshness_minutes=5,
            db_table="some_table",
            db_ts_col="updated_at",
        )
        # 进程内记录"刚刚更新过"（修复前这正是评分虚高的来源）
        m.last_update["test_source"] = now
        # 库里真实数据却是 3 小时前
        m._probe_latest = lambda r: (_Probe_OK, now - dt.timedelta(hours=3))

        ok, delay = await m.check_freshness(rule)

        assert ok is False
        assert delay == pytest.approx(3 * 3600.0)

    @pytest.mark.asyncio
    async def test_score_is_not_a_function_of_uptime(self):
        """同一份陈旧数据，进程刚启动 vs 已跑 5 小时 → 结论必须一致"""
        stale = dt.datetime(2026, 6, 18, 2, 30) - dt.timedelta(hours=3)
        rule = DataQualityRule(
            name="t",
            source="test_source",
            max_freshness_minutes=5,
            db_table="some_table",
            db_ts_col="updated_at",
        )
        results = []
        for uptime_hours in (0, 5, 23):
            now = dt.datetime(2026, 6, 18, 2, 30) + dt.timedelta(hours=uptime_hours)
            m = self._monitor(now)
            m._probe_latest = lambda r: (_Probe_OK, stale)
            results.append(await m.check_freshness(rule))
        # 修复前：uptime<1h 判新鲜、之后判陈旧 —— 同一份数据给出两种结论
        assert {ok for ok, _ in results} == {False}, f"结论随时长漂移: {results}"

    @pytest.mark.asyncio
    async def test_market_hours_only_skipped_outside_session(self):
        """盘中数据源：非交易时段不判陈旧（收盘后本就不更新）"""
        m = self._monitor(dt.datetime(2026, 6, 18, 10, 30))  # 北京 18:30 已收盘
        rule = DataQualityRule(
            name="t",
            source="test_source",
            max_freshness_minutes=5,
            db_table="some_table",
            db_ts_col="updated_at",
            market_hours_only=True,
        )
        m._probe_latest = lambda r: (_Probe_OK, dt.datetime(2026, 6, 18, 1, 0))
        ok, delay = await m.check_freshness(rule)
        assert ok is True
        assert delay == 0.0

    @pytest.mark.asyncio
    async def test_empty_table_is_not_fresh(self):
        """表存在但 0 行 = 从未采集，不是"旧"，必须判不通过"""
        m = self._monitor(dt.datetime(2026, 6, 18, 2, 30))
        rule = DataQualityRule(
            name="t",
            source="test_source",
            max_freshness_minutes=24 * 60,
            db_table="some_table",
            db_ts_col="updated_at",
        )
        m.last_update["test_source"] = m._now()  # 进程内谎报"刚更新"
        m._probe_latest = lambda r: (_Probe_EMPTY, None)
        ok, delay = await m.check_freshness(rule)
        assert ok is False
        assert delay == float("inf")

    @pytest.mark.asyncio
    async def test_probe_error_fails_safe(self):
        """查库失败 = 无法判定 → 按不通过计，不得悄悄退回 uptime 口径"""
        m = self._monitor(dt.datetime(2026, 6, 18, 2, 30))
        rule = DataQualityRule(
            name="t",
            source="test_source",
            db_table="some_table",
            db_ts_col="updated_at",
        )
        m.last_update["test_source"] = m._now()
        m._probe_latest = lambda r: (_Probe_ERROR, None)
        ok, delay = await m.check_freshness(rule)
        assert ok is False
        assert delay == float("inf")

    @pytest.mark.asyncio
    async def test_invalid_identifier_never_reaches_sql(self):
        """非法表名/列名必须被白名单拦下，不得拼进 SQL"""
        m = self._monitor(dt.datetime(2026, 6, 18, 2, 30))
        rule = DataQualityRule(
            name="t",
            source="test_source",
            db_table="some_table; DROP TABLE users--",
            db_ts_col="updated_at",
        )
        status, _ = m._probe_latest(rule)
        assert status == _Probe_UNMAPPED

    @pytest.mark.asyncio
    async def test_delay_uses_beijing_clock(self):
        """延迟按北京时间口径计算，与时区无关"""
        m = self._monitor(dt.datetime(2026, 6, 18, 2, 30))  # 北京 10:30
        rule = DataQualityRule(
            name="t",
            source="test_source",
            max_freshness_minutes=120,
            db_table="some_table",
            db_ts_col="updated_at",
        )
        # 北京 09:30 的数据，到北京 10:30 恰好 3600s
        m._probe_latest = lambda r: (_Probe_OK, dt.datetime(2026, 6, 18, 1, 30))
        ok, delay = await m.check_freshness(rule)
        assert ok is True
        assert delay == pytest.approx(3600.0)


class TestTodayIsBeijingAware:
    """_today() 必须按北京时间取值（容器 TZ=UTC，date.today() 会差一天）"""

    def test_midnight_beijing_rolls_to_next_day(self):
        """北京 09-02 01:00 = UTC 09-01 17:00 → _today() 应为 09-02"""
        m = DataQualityMonitor()
        m._now = lambda: dt.datetime(2026, 9, 1, 17, 0)
        assert m._today() == dt.date(2026, 9, 2)

    def test_is_trading_day_follows_beijing_date(self):
        """北京周日 01:00（UTC 周六 17:00）→ 非交易日"""
        m = DataQualityMonitor()
        m._now = lambda: dt.datetime(2026, 8, 29, 17, 0)  # UTC 周六 → 北京周日
        assert m.is_trading_day() is False
