"""A股交易时段判定 — 定时任务调度守卫的单一真源。

背景（2026-09-01 run#59 定位）：
    QTS 容器内 TZ 未设置，进程时钟为 UTC；而 APScheduler 的 trigger 硬编码
    ``timezone="Asia/Shanghai"``。二者不一致导致：
      · cron ``hour=15`` 触发在北京 15:00，但函数体内 ``datetime.now()`` 是 UTC；
      · 若直接用 ``datetime.now().hour`` 判断交易时段，会**整体偏移 8 小时**。

    因此本模块一律以「aware datetime + 显式转北京时间」实现，
    不依赖进程本地时区 —— 将来若给容器加上 TZ=Asia/Shanghai，本模块行为不变。

用法（定时任务开头守卫）::

    from shared.trading_calendar import should_run_now

    async def market_snapshot():
        if not should_run_now():
            logger.info("[定时任务] 非交易时段，跳过", job="大盘快照")
            return
        ...

设计取舍：
    **依然不硬编码猜测值**。A股节假日每年由交易所另行公布；一旦误把交易日当休市，
    会导致定时任务漏跑 → 当日数据缺失。「多跑几次无效任务」的代价远小于「漏跑一次」。
    因此（2026-10-11 审计 P1-9 整改后的口径）：
      · 休市表来自 ``shared/astock_holidays.json``（由用户既有权威源同步，带 year 标记）；
      · **只在「查询年份 == 文件覆盖年份」时应用**；年份不覆盖（如次年安排未公布）
        → 本文件失效，回退到「周一至周五」判定（fail-open，宁可多跑）；
      · 仍支持 ``extra_holidays`` 显式注入（可接 akshare ``tool_trade_date_hist_sina``）。
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

__all__ = [
    "CN_TZ",
    "SESSIONS",
    "holiday_calendar_stale",
    "is_trading_day",
    "is_trading_time",
    "should_run_now",
    "to_beijing",
]

#: 北京时间时区
CN_TZ = ZoneInfo("Asia/Shanghai")

#: 休市表（覆盖年份内生效；来源见文件内 note 字段）
HOLIDAYS_PATH = Path(__file__).resolve().parent / "astock_holidays.json"

_holidays_cache: tuple[frozenset[date], int | None] | None = None


def _load_holidays() -> tuple[frozenset[date], int | None]:
    """读取休市表 → (日期集合, 覆盖年份)。缺失/损坏一律 fail-open（空集 + None）。"""
    global _holidays_cache  # noqa: PLW0603 - 进程内单次缓存，避免每次判定读盘
    if _holidays_cache is not None:
        return _holidays_cache
    try:
        data = json.loads(HOLIDAYS_PATH.read_text(encoding="utf-8"))
        days = frozenset(date.fromisoformat(s) for s in (data.get("all_holiday_dates") or []))
        year = int(data["year"]) if data.get("year") is not None else None
        _holidays_cache = (days, year)
    except (OSError, ValueError, KeyError, TypeError):
        # 读不到 ≠ 全是交易日：此处 fail-open，由 holiday_calendar_stale() 暴露问题
        _holidays_cache = (frozenset(), None)
    return _holidays_cache


def clear_holidays_cache() -> None:
    """清缓存（测试/热更新用）。"""
    global _holidays_cache  # noqa: PLW0603
    _holidays_cache = None


def holiday_calendar_stale(day: date | None = None) -> bool:
    """休市表是否**不覆盖**给定日期所在年 —— 为真时 is_trading_day 不应用节假日（fail-open）。

    调用方（巡检/数据质量）应据此告警：此时会「多跑」，但不会「漏跑」。
    """
    if day is None:
        day = to_beijing().date()
    _, year = _load_holidays()
    return year is None or year != day.year


#: A股交易时段（北京时间）。开盘前后各留数分钟缓冲，
#: 尾盘放宽到 15:35 以便收盘后仍能采到一次收尾快照。
SESSIONS: tuple[tuple[dtime, dtime], ...] = (
    (dtime(9, 15), dtime(11, 35)),  # 早盘（含集合竞价）
    (dtime(12, 55), dtime(15, 35)),  # 午盘（含收盘后收尾）
)


def to_beijing(dt: datetime | None = None) -> datetime:
    """把任意 datetime 转成「北京时间 aware datetime」。

    naive 输入按 **UTC** 解释 —— 这是当前容器的既有约定
    （``datetime.now()`` 返回的是 UTC 墙钟）。若容器内 TZ 已改为
    Asia/Shanghai，请改传 aware datetime，不要用 naive。
    """
    if dt is None:
        # 显式取 UTC now，避免继承进程本地时区导致语义漂移
        dt = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(CN_TZ)


def is_trading_day(
    day: date | None = None,
    extra_holidays: frozenset[date] | set[date] | None = None,
    *,
    use_builtin_holidays: bool = True,
) -> bool:
    """是否为A股交易日（周一至周五，且不在休市表中）。

    Args:
        day: 待判日期，默认当前北京时间日期。
        extra_holidays: 额外休市日（法定节假日等），与内置表取并集。
        use_builtin_holidays: 是否应用 ``astock_holidays.json``。默认应用，
            **但仅在其覆盖年份 == day 所在年份时生效**（见模块 docstring 的 fail-open 取舍）。
    """
    if day is None:
        day = to_beijing().date()
    if day.weekday() >= 5:  # 5=周六 6=周日
        return False
    if extra_holidays and day in extra_holidays:
        return False
    if use_builtin_holidays:
        holidays, year = _load_holidays()
        # 年份不匹配 → 不应用内置表（宁可多跑，不可漏跑）
        if year is not None and day.year == year and day in holidays:
            return False
    return True


def is_trading_time(
    dt: datetime | None = None,
    extra_holidays: frozenset[date] | set[date] | None = None,
    grace_minutes: int = 0,
) -> bool:
    """当前是否处于A股交易时段。

    Args:
        dt: 待判时刻，默认当前时间（naive 按 UTC 解释）。
        extra_holidays: 额外休市日（法定节假日等）。
        grace_minutes: 时段两端放宽分钟数，用于容忍调度抖动。
    """
    bj = to_beijing(dt)
    if not is_trading_day(bj.date(), extra_holidays):
        return False
    t = bj.time()
    pad = timedelta(minutes=max(0, grace_minutes))
    for start, end in SESSIONS:
        # 用 timedelta 计算以支持跨时段放宽
        start_dt = datetime.combine(bj.date(), start) - pad
        end_dt = datetime.combine(bj.date(), end) + pad
        if start_dt.time() <= t <= end_dt.time():
            return True
    return False


def should_run_now(
    extra_holidays: frozenset[date] | set[date] | None = None,
    grace_minutes: int = 0,
) -> bool:
    """定时任务守卫：当前是否值得执行盘中任务。等价于 :func:`is_trading_time`。"""
    return is_trading_time(extra_holidays=extra_holidays, grace_minutes=grace_minutes)
