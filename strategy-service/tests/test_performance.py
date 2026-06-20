"""
测试绩效指标计算函数
Cover services/performance.py 全部 9 个纯函数。

函数清单:
  calc_daily_returns, calc_max_drawdown,
  calc_bench_returns, calc_benchmark_nav,
  calc_return_metrics, calc_risk_metrics,
  calc_benchmark_metrics, calc_trade_metrics,
  calc_monthly_returns
"""

from types import SimpleNamespace

import pytest
from services.performance import (
    calc_bench_returns,
    calc_benchmark_metrics,
    calc_benchmark_nav,
    calc_daily_returns,
    calc_max_drawdown,
    calc_monthly_returns,
    calc_return_metrics,
    calc_risk_metrics,
    calc_trade_metrics,
)

# ============================================================
# calc_daily_returns
# ============================================================


class TestCalcDailyReturns:
    """测试 calc_daily_returns()"""

    def test_normal_returns(self):
        """正常净值序列 → 正确计算日收益率 (line 28-31)"""
        navs = [100.0, 110.0, 99.0]
        result = calc_daily_returns(navs)
        assert len(result) == 2
        assert result[0] == pytest.approx(0.1)  # (110-100)/100
        assert result[1] == pytest.approx(-0.1)  # (99-110)/110

    def test_single_element(self):
        """单元素序列 → 返回空列表 (line 29, range(1,1)=空)"""
        assert calc_daily_returns([100.0]) == []

    def test_empty_list(self):
        """空列表 → 返回空列表"""
        assert calc_daily_returns([]) == []

    def test_prev_nav_zero(self):
        """前一日净值为0 → 返回0 (line 32-33)"""
        navs = [0.0, 50.0]
        result = calc_daily_returns(navs)
        assert result == [0.0]

    def test_negative_nav(self):
        """负净值 → 正确计算 (line 30)"""
        navs = [-100.0, -50.0]
        result = calc_daily_returns(navs)
        assert result[0] == pytest.approx(-0.5)  # (-50 - (-100)) / (-100) = 50/-100 = -0.5


# ============================================================
# calc_max_drawdown
# ============================================================


class TestCalcMaxDrawdown:
    """测试 calc_max_drawdown()"""

    def test_uptrend_no_drawdown(self):
        """持续上涨 → 回撤为0"""
        navs = [100.0, 110.0, 120.0, 130.0]
        assert calc_max_drawdown(navs) == 0.0

    def test_down_then_up(self):
        """先涨后跌再涨 → 正确计算最大回撤"""
        navs = [100.0, 120.0, 90.0, 110.0]
        dd = calc_max_drawdown(navs)
        # peak=120, dd=(120-90)/120=0.25
        assert dd == pytest.approx(0.25)

    def test_continuous_drop(self):
        """持续下跌 → peak 始终是初始值"""
        navs = [100.0, 90.0, 80.0, 70.0]
        dd = calc_max_drawdown(navs)
        # peak=100, max dd = (100-70)/100 = 0.3
        assert dd == pytest.approx(0.3)

    def test_double_peak(self):
        """两个高峰 → 取最大回撤"""
        navs = [100.0, 150.0, 120.0, 140.0, 130.0]
        dd = calc_max_drawdown(navs)
        # peak=150, max dd = (150-120)/150 = 0.2 (随后120→140不重要)
        assert dd == pytest.approx(0.2)

    def test_zero_peak(self):
        """peak=0 → 回撤为0 (line 55)"""
        navs = [0.0, -10.0]
        assert calc_max_drawdown(navs) == 0.0

    def test_empty_returns_zero(self):
        """空列表 → 返回0.0"""
        assert calc_max_drawdown([]) == 0.0


# ============================================================
# calc_bench_returns
# ============================================================


class TestCalcBenchReturns:
    """测试 calc_bench_returns()"""

    def test_normal_returns(self):
        """正常序列 → 正确计算 (line 74-82)"""
        nav = [100.0, 105.0, 103.0]
        result = calc_bench_returns(nav)
        assert len(result) == 2
        assert result[0] == pytest.approx(0.05)
        assert result[1] == pytest.approx(-0.0190476, rel=1e-5)

    def test_single_element(self):
        """单元素 → 空列表 (line 74-75)"""
        assert calc_bench_returns([100.0]) == []

    def test_empty_list(self):
        """空列表 → 空列表 (line 74-75)"""
        assert calc_bench_returns([]) == []

    def test_prev_zero(self):
        """前一日为0 → 返回0 (line 80-81)"""
        nav = [0.0, 50.0]
        assert calc_bench_returns(nav) == [0.0]


# ============================================================
# calc_benchmark_nav
# ============================================================


class TestCalcBenchmarkNav:
    """测试 calc_benchmark_nav()"""

    def test_normal(self):
        """正常数据 → 对齐到公共日期并归一化"""
        bench_data = [
            {"trade_date": "20260105", "close": 2000.0},
            {"trade_date": "20260106", "close": 2100.0},
            {"trade_date": "20260107", "close": 2050.0},
        ]
        common_dates = ["20260105", "20260106", "20260107"]
        result = calc_benchmark_nav(bench_data, common_dates)
        assert len(result) == 3
        assert result[0] == pytest.approx(1.0)  # 2000/2000
        assert result[1] == pytest.approx(1.05)  # 2100/2000
        assert result[2] == pytest.approx(1.025)  # 2050/2000

    def test_missing_dates(self):
        """基准数据缺少某些公共日期 → 沿用前值 (line 115)"""
        bench_data = [
            {"trade_date": "20260105", "close": 2000.0},
            {"trade_date": "20260107", "close": 2100.0},
        ]
        common_dates = ["20260105", "20260106", "20260107"]
        result = calc_benchmark_nav(bench_data, common_dates)
        assert len(result) == 3
        assert result[0] == pytest.approx(1.0)  # 2000/2000
        assert result[1] == pytest.approx(1.0)  # 缺数据，沿用前值
        assert result[2] == pytest.approx(1.05)  # 2100/2000

    def test_missing_first_date(self):
        """第一个日期缺基准数据且无前值 → 返回1.0 (line 115 的 else 分支)"""
        bench_data = [{"trade_date": "20260106", "close": 2000.0}]
        common_dates = ["20260105", "20260106"]
        result = calc_benchmark_nav(bench_data, common_dates)
        assert len(result) == 2
        assert result[0] == 1.0  # 无前值 → 1.0
        assert result[1] == 1.0  # 2000/2000=1.0

    def test_empty_bench_data(self):
        """基准数据为空 → 全返回1.0 (line 102-103)"""
        result = calc_benchmark_nav([], ["20260105", "20260106"])
        assert result == [1.0, 1.0]


# ============================================================
# calc_return_metrics
# ============================================================


class TestCalcReturnMetrics:
    """测试 calc_return_metrics()"""

    def test_normal(self):
        """正常数据 → 正确设置 total_return 和 annual_return (line 131-135)"""
        result = SimpleNamespace()
        calc_return_metrics(result, final_nav=2.0, trading_days=252)
        assert result.total_return == pytest.approx(1.0)  # 2.0 - 1.0
        assert result.annual_return == pytest.approx(1.0)  # 2^(252/252)-1 = 1.0

    def test_zero_trading_days(self):
        """trading_days=0 → annual_return=0 (line 134-135)"""
        result = SimpleNamespace()
        calc_return_metrics(result, final_nav=1.5, trading_days=0)
        assert result.total_return == pytest.approx(0.5)
        assert result.annual_return == 0.0

    def test_final_nav_below_one(self):
        """最终净值小于1 → 负收益"""
        result = SimpleNamespace()
        calc_return_metrics(result, final_nav=0.8, trading_days=252)
        assert result.total_return == pytest.approx(-0.2)
        assert result.annual_return == pytest.approx(-0.2)


# ============================================================
# calc_risk_metrics
# ============================================================


class TestCalcRiskMetrics:
    """测试 calc_risk_metrics()"""

    def test_normal(self):
        """正常数据 → 正确计算所有风险指标 (line 160-187)"""
        result = SimpleNamespace()
        daily_returns = [0.01, -0.005, 0.02, -0.01, 0.015]
        navs = [100.0, 101.0, 100.5, 102.5, 101.5, 103.0]
        calc_risk_metrics(result, daily_returns, 0.03, 0.15, navs)

        # 波动率
        assert hasattr(result, "volatility")
        assert result.volatility > 0

        # 夏普
        assert hasattr(result, "sharpe_ratio")
        # (0.15 - 0.03) / volatility

        # 最大回撤
        assert hasattr(result, "max_drawdown")
        # peak=102.5, dd=(102.5-101.5)/102.5≈0.00976
        assert result.max_drawdown == pytest.approx(0.009756, rel=1e-4)

        # Calmar
        assert hasattr(result, "calmar_ratio")
        assert result.calmar_ratio > 0

        # Sortino
        assert hasattr(result, "sortino_ratio")

    def test_empty_daily_returns(self):
        """日收益率为空 → volatility=0, sortino=0 (line 164-165, 186)"""
        result = SimpleNamespace()
        calc_risk_metrics(result, [], 0.03, 0.1, [100.0])
        assert result.volatility == 0.0
        assert result.sharpe_ratio == 0.0
        assert result.sortino_ratio == 0.0

    def test_zero_volatility(self):
        """波动率为0 → 夏普为0 (line 168-170)"""
        result = SimpleNamespace()
        calc_risk_metrics(result, [0.0, 0.0, 0.0], 0.03, 0.1, [100.0, 100.0])
        assert result.volatility == 0.0
        assert result.sharpe_ratio == 0.0

    def test_no_negative_returns(self):
        """无负收益 → sortino=0 (line 179, 186)"""
        result = SimpleNamespace()
        calc_risk_metrics(result, [0.01, 0.02, 0.015], 0.03, 0.15, [100.0, 101.0, 103.0])
        assert hasattr(result, "sortino_ratio")
        assert result.sortino_ratio == 0.0

    def test_zero_max_drawdown(self):
        """最大回撤=0 → Calmar=0 (line 176)"""
        result = SimpleNamespace()
        calc_risk_metrics(result, [0.01, 0.01], 0.03, 0.1, [100.0, 101.0, 102.0])
        assert result.max_drawdown == 0.0
        assert result.calmar_ratio == 0.0


# ============================================================
# calc_benchmark_metrics
# ============================================================


class TestCalcBenchmarkMetrics:
    """测试 calc_benchmark_metrics()"""

    def make_result(self):
        r = SimpleNamespace()
        r.total_return = 0.2
        r.benchmark_return = 0.0
        r.excess_return = 0.0
        r.beta = 0.0
        r.alpha = 0.0
        r.information_ratio = 0.0
        return r

    def test_normal(self):
        """正常数据 → 正确计算 Beta/Alpha/IR (line 213-248)"""
        result = self.make_result()
        daily_returns = [0.01, 0.005, 0.02, -0.01, 0.015]
        bench_returns = [0.008, 0.004, 0.015, -0.008, 0.012]
        bench_nav = [1.0, 1.008, 1.012, 1.027, 1.019, 1.031]
        calc_benchmark_metrics(result, daily_returns, bench_returns, bench_nav, 0.03, 0.15)

        assert result.benchmark_return == pytest.approx(0.031)  # 1.031-1.0
        assert result.excess_return == pytest.approx(0.169)  # 0.2-0.031
        assert result.beta > 0  # 策略与基准正相关
        assert hasattr(result, "alpha")
        assert hasattr(result, "information_ratio")

    def test_empty_bench_nav(self):
        """bench_nav 为空 → benchmark_return=0, excess_return=total_return (line 213)"""
        result = self.make_result()
        calc_benchmark_metrics(result, [0.01], [0.01], [], 0.03, 0.15)
        assert result.benchmark_return == 0.0
        assert result.excess_return == 0.2

    def test_min_len_one_or_less(self):
        """数据点不足 → beta/alpha/IR 为0 (line 246-248)"""
        result = self.make_result()
        # daily_returns 只有1个元素，min_len=1 -> 进入 else
        calc_benchmark_metrics(result, [0.01], [0.01], [1.0, 1.01], 0.03, 0.15)
        assert result.beta == 0.0
        assert result.alpha == 0.0
        assert result.information_ratio == 0.0

    def test_bench_returns_zero_var(self):
        """基准收益率为常数 → var_b=0 → beta=0 (line 227)"""
        result = self.make_result()
        daily_returns = [0.01, 0.005]
        bench_returns = [0.01, 0.01]  # 常数 → var=0
        bench_nav = [1.0, 1.01, 1.02]
        calc_benchmark_metrics(result, daily_returns, bench_returns, bench_nav, 0.03, 0.15)
        assert result.beta == 0.0

    def test_partial_overlap(self):
        """两个收益序列长度不同 → 以 min_len 为准 (line 216)"""
        result = self.make_result()
        daily_returns = [0.01, 0.02, 0.015]  # len=3
        bench_returns = [0.008, 0.012]  # len=2 -> min_len=2
        bench_nav = [1.0, 1.008, 1.02, 1.035]
        calc_benchmark_metrics(result, daily_returns, bench_returns, bench_nav, 0.03, 0.15)
        assert result.beta != 0.0

    def test_zero_tracking_error(self):
        """策略和基准完全一致 → tracking_error=0 → IR=0 (line 241-244)"""
        result = self.make_result()
        daily_returns = [0.01, 0.02]
        bench_returns = [0.01, 0.02]  # 完全一致
        bench_nav = [1.0, 1.01, 1.03]
        calc_benchmark_metrics(result, daily_returns, bench_returns, bench_nav, 0.03, 0.15)
        assert result.information_ratio == 0.0


# ============================================================
# calc_trade_metrics
# ============================================================


class TestCalcTradeMetrics:
    """测试 calc_trade_metrics()"""

    def test_normal(self):
        """正常交易数据 → 正确计算所有交易统计指标 (line 270-289)"""
        result = SimpleNamespace()
        trades = [
            SimpleNamespace(direction="SELL", pnl=100.0, hold_days=5),
            SimpleNamespace(direction="SELL", pnl=-50.0, hold_days=3),
            SimpleNamespace(direction="SELL", pnl=200.0, hold_days=7),
            SimpleNamespace(direction="BUY", pnl=0.0, hold_days=0),  # 买入不计入 total
        ]
        daily_values = [{"value": 10000.0}, {"value": 12000.0}, {"value": 11000.0}]
        calc_trade_metrics(result, trades, daily_values, 50000.0)

        assert result.total_trades == 3  # 3 笔 SELL
        assert result.winning_trades == 2  # 100, 200
        assert result.losing_trades == 1  # -50
        assert result.win_rate == pytest.approx(2.0 / 3.0)
        assert result.profit_factor == pytest.approx(300.0 / 50.0)  # 100+200 / 50
        assert result.avg_hold_days == pytest.approx(5.0)  # (5+3+7)/3
        assert result.turnover_rate == pytest.approx(
            50000.0 / 11000.0
        )  # 50000/avg(10000,12000,11000)

    def test_no_sell_trades(self):
        """无卖出交易 → 各项指标为0或None (line 270-288)"""
        result = SimpleNamespace()
        trades = [SimpleNamespace(direction="BUY", pnl=0.0, hold_days=0)]
        daily_values = [{"value": 10000.0}]
        calc_trade_metrics(result, trades, daily_values, 0.0)

        assert result.total_trades == 0
        assert result.winning_trades == 0
        assert result.losing_trades == 0
        assert result.win_rate == 0.0
        assert result.profit_factor == 0.0
        assert not hasattr(result, "avg_hold_days")  # if sell_trades: 不执行
        assert result.turnover_rate == 0.0

    def test_zero_avg_value(self):
        """avg_value=0 → turnover_rate=0 (line 288)"""
        result = SimpleNamespace()
        trades = [SimpleNamespace(direction="SELL", pnl=10.0, hold_days=2)]
        calc_trade_metrics(result, trades, [{"value": 0.0}], 5000.0)
        assert result.turnover_rate == 0.0

    def test_empty_daily_values(self):
        """daily_values 为空 → avg_value=1.0 (line 288 的 else)"""
        result = SimpleNamespace()
        trades = [SimpleNamespace(direction="SELL", pnl=10.0, hold_days=2)]
        calc_trade_metrics(result, trades, [], 1000.0)
        assert result.turnover_rate == 1000.0  # 1000/1.0

    def test_zero_total_loss(self):
        """无亏损交易 → profit_factor=0 (line 281)"""
        result = SimpleNamespace()
        trades = [
            SimpleNamespace(direction="SELL", pnl=100.0, hold_days=5),
            SimpleNamespace(direction="SELL", pnl=50.0, hold_days=3),
        ]
        calc_trade_metrics(result, trades, [{"value": 10000.0}], 0.0)
        assert result.total_trades == 2
        assert result.winning_trades == 2
        assert result.losing_trades == 0
        assert result.profit_factor == 0.0  # total_loss=0 → else


# ============================================================
# calc_monthly_returns
# ============================================================


class TestCalcMonthlyReturns:
    """测试 calc_monthly_returns()"""

    def test_normal(self):
        """正常数据 → 按月聚合收益率 (line 308-341)"""
        equity_curve = [
            {"date": "20260105", "nav": 1.0},
            {"date": "20260115", "nav": 1.1},
            {"date": "20260125", "nav": 1.05},
            {"date": "20260201", "nav": 1.08},
            {"date": "20260215", "nav": 1.15},
        ]
        result = calc_monthly_returns(equity_curve)
        assert len(result) == 2
        assert result[0]["year"] == 2026
        assert result[0]["month"] == 1
        # 1月收益：last_nav(Jan)/prev_nav(初始1.0) - 1 = 1.05/1.0 - 1 = 0.05
        assert result[0]["return"] == pytest.approx(0.05)
        assert result[1]["year"] == 2026
        assert result[1]["month"] == 2
        # 2月收益：1.15/1.05 - 1 ≈ 0.095238
        assert result[1]["return"] == pytest.approx(0.095238, rel=1e-5)

    def test_empty_equity_curve(self):
        """空数据 → 空列表 (line 308-309)"""
        assert calc_monthly_returns([]) == []

    def test_date_format_yyyy_mm_dd(self):
        """YYYY-MM-DD 格式日期 (line 318-321)"""
        equity_curve = [
            {"date": "2026-01-05", "nav": 1.0},
            {"date": "2026-01-20", "nav": 1.1},
        ]
        result = calc_monthly_returns(equity_curve)
        assert len(result) == 1
        assert result[0]["year"] == 2026
        assert result[0]["month"] == 1

    def test_invalid_date_skipped(self):
        """非法日期 → 跳过 (line 322-323)"""
        equity_curve = [
            {"date": "20260105", "nav": 1.0},
            {"date": "not-a-date", "nav": 1.05},
            {"date": "20260120", "nav": 1.1},
        ]
        result = calc_monthly_returns(equity_curve)
        assert len(result) == 1  # 非法日期被跳过
        assert result[0]["month"] == 1

    def test_prev_nav_zero(self):
        """prev_nav=0 → 收益率0 (line 337)"""
        equity_curve = [
            {"date": "20260105", "nav": 0.0},
            {"date": "20260201", "nav": 1.0},
        ]
        result = calc_monthly_returns(equity_curve)
        assert len(result) == 2
        assert result[0]["return"] == pytest.approx(-1.0)  # (0/1.0) - 1 = -1.0
        # 2月: prev_nav=0, last_nav(Feb)=1.0, prev_nav > 0 is False → 0.0
        assert result[1]["return"] == 0.0

    def test_sorted_months(self):
        """月份按时间排序 (line 335)"""
        equity_curve = [
            {"date": "20260301", "nav": 1.2},
            {"date": "20260105", "nav": 1.0},
            {"date": "20260201", "nav": 1.1},
        ]
        result = calc_monthly_returns(equity_curve)
        assert len(result) == 3
        assert result[0]["month"] == 1
        assert result[1]["month"] == 2
        assert result[2]["month"] == 3
