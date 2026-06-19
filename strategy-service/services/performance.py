"""
绩效指标计算模块
独立纯函数集合，用于计算回测绩效指标。
支持：收益率、风险指标（波动率/夏普/最大回撤/索提诺/Calmar）、
基准对比（Beta/Alpla/Information Ratio）、交易统计、月度收益。
"""

from __future__ import annotations

from datetime import datetime
import math
from typing import Dict, List, Tuple

# ============================================================
# 日收益率
# ============================================================


def calc_daily_returns(navs: list[float]) -> list[float]:
    """计算日收益率序列

    Args:
        navs: 净值序列

    Returns:
        日收益率列表（比净值短1个元素）
    """
    daily_returns: list[float] = []
    for i in range(1, len(navs)):
        if navs[i - 1] != 0:
            daily_returns.append((navs[i] - navs[i - 1]) / navs[i - 1])
        else:
            daily_returns.append(0.0)
    return daily_returns


# ============================================================
# 最大回撤
# ============================================================


def calc_max_drawdown(navs: list[float]) -> float:
    """计算最大回撤

    Args:
        navs: 净值序列

    Returns:
        最大回撤比率（0~1 之间）
    """
    peak = 0.0
    max_dd = 0.0
    for nav in navs:
        peak = max(peak, nav)
        dd = (peak - nav) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


# ============================================================
# 基准日收益率
# ============================================================


def calc_bench_returns(bench_nav: list[float]) -> list[float]:
    """计算基准日收益率序列

    Args:
        bench_nav: 基准净值序列

    Returns:
        基准日收益率列表
    """
    if len(bench_nav) <= 1:
        return []
    bench_returns: list[float] = []
    for i in range(1, len(bench_nav)):
        if bench_nav[i - 1] != 0:
            bench_returns.append((bench_nav[i] - bench_nav[i - 1]) / bench_nav[i - 1])
        else:
            bench_returns.append(0.0)
    return bench_returns


# ============================================================
# 基准净值曲线计算
# ============================================================


def calc_benchmark_nav(benchmark_data: list[dict], common_dates: list[str]) -> list[float]:
    """计算基准净值曲线

    将基准指数行情数据对齐到公共交易日列表，以初始价格归一化。

    Args:
        benchmark_data: 基准指数数据，每项含 trade_date, close 字段
        common_dates: 公共交易日列表

    Returns:
        基准净值列表（初始为1.0）
    """
    if not benchmark_data:
        return [1.0] * len(common_dates)

    bench_map = {d["trade_date"]: float(d["close"]) for d in benchmark_data}
    bench_navs: list[float] = []
    first_price = None

    for date in common_dates:
        if date in bench_map:
            if first_price is None:
                first_price = bench_map[date]
            bench_navs.append(bench_map[date] / first_price)
        else:
            bench_navs.append(bench_navs[-1] if bench_navs else 1.0)

    return bench_navs


# ============================================================
# 收益指标
# ============================================================


def calc_return_metrics(
    result,
    final_nav: float,
    trading_days: int,
):
    """计算总收益率和年化收益率"""
    result.total_return = final_nav - 1.0
    if trading_days > 0:
        result.annual_return = (final_nav ** (252.0 / trading_days)) - 1.0
    else:
        result.annual_return = 0.0


# ============================================================
# 风险指标
# ============================================================


def calc_risk_metrics(
    result,
    daily_returns: list[float],
    risk_free_rate: float,
    annual_return: float,
    navs: list[float],
):
    """计算波动率、夏普、最大回撤、Calmar、Sortino 等风险指标

    Args:
        result: 结果对象（会修改 risk_free_rate 之外的字段）
        daily_returns: 日收益率序列
        risk_free_rate: 无风险利率（年化）
        annual_return: 年化收益率
        navs: 净值序列
    """
    # 年化波动率
    if daily_returns:
        avg_ret = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg_ret) ** 2 for r in daily_returns) / len(daily_returns)
        result.volatility = math.sqrt(variance) * math.sqrt(252)
    else:
        result.volatility = 0.0

    # 夏普比率
    result.sharpe_ratio = (
        (annual_return - risk_free_rate) / result.volatility if result.volatility > 0 else 0.0
    )

    # 最大回撤
    result.max_drawdown = calc_max_drawdown(navs)

    # Calmar Ratio
    result.calmar_ratio = annual_return / result.max_drawdown if result.max_drawdown > 0 else 0.0

    # Sortino Ratio
    downside_returns = [r for r in daily_returns if r < 0]
    if downside_returns:
        downside_var = sum(r**2 for r in downside_returns) / len(daily_returns)
        downside_vol = math.sqrt(downside_var) * math.sqrt(252)
        result.sortino_ratio = (
            (annual_return - risk_free_rate) / downside_vol if downside_vol > 0 else 0.0
        )
    else:
        result.sortino_ratio = 0.0


# ============================================================
# 基准相关指标（Beta / Alpha / Information Ratio）
# ============================================================


def calc_benchmark_metrics(
    result,
    daily_returns: list[float],
    bench_returns: list[float],
    bench_nav: list[float],
    risk_free_rate: float,
    annual_return: float,
):
    """计算基准相关指标：基准收益率、Beta、Alpha、Information Ratio

    Args:
        result: 结果对象（会修改 benchmark 相关字段）
        daily_returns: 策略日收益率序列
        bench_returns: 基准日收益率序列
        bench_nav: 基准净值序列
        risk_free_rate: 无风险利率
        annual_return: 年化收益率
    """
    result.benchmark_return = (bench_nav[-1] - 1.0) if bench_nav else 0.0
    result.excess_return = result.total_return - result.benchmark_return

    min_len = min(len(daily_returns), len(bench_returns))

    if min_len > 1:
        strat_r = daily_returns[:min_len]
        bench_r = bench_returns[:min_len]
        avg_s = sum(strat_r) / min_len
        avg_b = sum(bench_r) / min_len

        # Beta = cov / var
        cov = sum((strat_r[i] - avg_s) * (bench_r[i] - avg_b) for i in range(min_len)) / min_len
        var_b = sum((bench_r[i] - avg_b) ** 2 for i in range(min_len)) / min_len
        result.beta = cov / var_b if var_b > 0 else 0.0

        # Alpha (Jensen's Alpha)
        bench_annual = (
            (bench_nav[-1] ** (252.0 / max(len(bench_nav), 1))) - 1.0 if bench_nav else 0.0
        )
        result.alpha = annual_return - (
            risk_free_rate + result.beta * (bench_annual - risk_free_rate)
        )

        # Information Ratio
        tracking_diff = [strat_r[i] - bench_r[i] for i in range(min_len)]
        avg_td = sum(tracking_diff) / min_len
        te_var = sum((td - avg_td) ** 2 for td in tracking_diff) / min_len
        tracking_error = math.sqrt(te_var) * math.sqrt(252)
        result.information_ratio = (
            (annual_return - bench_annual) / tracking_error if tracking_error > 0 else 0.0
        )
    else:
        result.beta = 0.0
        result.alpha = 0.0
        result.information_ratio = 0.0


# ============================================================
# 交易统计
# ============================================================


def calc_trade_metrics(
    result,
    trades: list,
    daily_values: list[dict],
    total_trade_amount: float,
):
    """计算交易统计指标

    Args:
        result: 结果对象（会修改交易相关字段）
        trades: 交易记录列表
        daily_values: 每日净值数据列表
        total_trade_amount: 总交易金额
    """
    sell_trades = [t for t in trades if t.direction == "SELL"]
    result.total_trades = len(sell_trades)
    result.winning_trades = sum(1 for t in sell_trades if t.pnl > 0)
    result.losing_trades = sum(1 for t in sell_trades if t.pnl <= 0)
    result.win_rate = (
        result.winning_trades / result.total_trades if result.total_trades > 0 else 0.0
    )

    # 盈亏比 Profit Factor
    total_profit = sum(t.pnl for t in sell_trades if t.pnl > 0)
    total_loss = abs(sum(t.pnl for t in sell_trades if t.pnl < 0))
    result.profit_factor = total_profit / total_loss if total_loss > 0 else 0.0

    # 平均持仓天数
    if sell_trades:
        result.avg_hold_days = sum(t.hold_days for t in sell_trades) / len(sell_trades)

    # 换手率
    avg_value = sum(dv["value"] for dv in daily_values) / len(daily_values) if daily_values else 1.0
    result.turnover_rate = total_trade_amount / avg_value if avg_value > 0 else 0.0


# ============================================================
# 月度收益
# ============================================================


def calc_monthly_returns(equity_curve: list[dict]) -> list[dict]:
    """计算每月收益率

    将净值曲线按月聚合，计算每个自然月的收益率。

    Args:
        equity_curve: 每日净值列表 [{date, nav, ...}]

    Returns:
        月度收益列表 [{year, month, return}, ...]
    """
    if not equity_curve:
        return []

    monthly: dict[tuple[int, int], list[float]] = {}  # (year, month) -> [first_nav, last_nav]
    for dv in equity_curve:
        date_str = dv["date"]
        try:
            if len(date_str) == 8:  # YYYYMMDD
                year = int(date_str[:4])
                month = int(date_str[4:6])
            else:  # YYYY-MM-DD
                parts = date_str.split("-")
                year = int(parts[0])
                month = int(parts[1])
        except (ValueError, IndexError):
            continue

        key = (year, month)
        nav = dv["nav"]
        if key not in monthly:
            monthly[key] = [nav, nav]
        else:
            monthly[key][1] = nav

    results: list[dict] = []
    sorted_keys = sorted(monthly.keys())
    prev_nav = 1.0
    for key in sorted_keys:
        first_nav, last_nav = monthly[key]
        month_ret = (last_nav / prev_nav) - 1.0 if prev_nav > 0 else 0.0
        results.append({"year": key[0], "month": key[1], "return": round(month_ret, 6)})
        prev_nav = last_nav

    return results
