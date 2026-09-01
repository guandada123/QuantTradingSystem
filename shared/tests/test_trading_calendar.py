"""shared.trading_calendar 单元测试。

覆盖重点：
  1. naive UTC 输入必须按 UTC 解释（容器内 TZ 未设置，``datetime.now()`` 是 UTC 墙钟）；
     若被误当本地时间，判定时段会整体偏 8 小时 —— 这是本模块存在的直接原因。
  2. 已设 TZ=Asia/Shanghai 的环境（aware 输入）行为必须一致，保证将来加 TZ 不变性。
  3. 会话边界（9:15/11:35/12:55/15:35）取等号闭合。
  4. 周末全天不执行；extra_holidays 生效。
"""

from datetime import UTC, date, datetime
from datetime import time as dtime

import pytest

from shared.trading_calendar import (
    CN_TZ,
    is_trading_day,
    is_trading_time,
    should_run_now,
    to_beijing,
)


def _utc(y, m, d, h, mi=0):
    """构造 naive UTC datetime（模拟容器里 datetime.now() 的返回形态）"""
    return datetime(y, m, d, h, mi)


# ---------- to_beijing ----------


def test_naive_utc_is_interpreted_as_utc_not_local():
    """核心用例：naive 输入按 UTC 解释。

    2026-09-01 22:00 北京 = 14:00 UTC。若 naive 被当成本地时间，
    这里会得到 22:00+08:00（即北京时间 06:00 次日），判定时段整体错位。
    """
    bj = to_beijing(_utc(2026, 9, 1, 14, 0))
    assert bj.tzinfo is not None
    assert bj.hour == 22 and bj.date() == date(2026, 9, 1)


def test_naive_utc_crossing_day_boundary():
    """UTC 16:30 = 北京次日 00:30，跨日必须正确进位"""
    bj = to_beijing(_utc(2026, 9, 1, 16, 30))
    assert bj.date() == date(2026, 9, 2)
    assert bj.hour == 0 and bj.minute == 30


def test_aware_input_is_converted_not_reinterpreted():
    """aware 输入走 astimezone，不做「补 UTC」的假设"""
    sh = datetime(2026, 9, 1, 10, 0, tzinfo=CN_TZ)
    assert to_beijing(sh).hour == 10

    utc_aware = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    assert to_beijing(utc_aware).hour == 18


def test_default_arg_returns_aware_beijing_now():
    """不传参时必须返回 aware 北京时间，且与真实 UTC now 只差时区"""
    bj = to_beijing()
    ref = datetime.now(UTC).astimezone(CN_TZ)
    assert bj.tzinfo is not None
    assert abs((bj - ref).total_seconds()) < 5


# ---------- is_trading_day ----------


@pytest.mark.parametrize(
    "d,expected",
    [
        (date(2026, 8, 31), True),  # 周一
        (date(2026, 9, 1), True),  # 周二
        (date(2026, 9, 4), True),  # 周五
        (date(2026, 8, 29), False),  # 周六
        (date(2026, 8, 30), False),  # 周日
    ],
)
def test_is_trading_day_weekday_logic(d, expected):
    assert is_trading_day(d) is expected


def test_extra_holidays_skips_weekday():
    hol = frozenset({date(2026, 10, 1), date(2026, 10, 2)})
    assert is_trading_day(date(2026, 10, 1)) is True  # 默认不内置节假日
    assert is_trading_day(date(2026, 10, 1), hol) is False
    assert is_trading_day(date(2026, 10, 5), hol) is True  # 未列出的周一仍为交易日


# ---------- is_trading_time ----------


@pytest.mark.parametrize(
    "utc_dt,expected,label",
    [
        (_utc(2026, 9, 1, 1, 15), True, "北京09:15 早盘开盘"),
        (_utc(2026, 9, 1, 1, 0), False, "北京09:00 盘前"),
        (_utc(2026, 9, 1, 2, 0), True, "北京10:00 早盘中"),
        (_utc(2026, 9, 1, 3, 35), True, "北京11:35 早盘收尾边界"),
        (_utc(2026, 9, 1, 3, 40), False, "北京11:40 午休"),
        (_utc(2026, 9, 1, 4, 55), True, "北京12:55 午盘开盘边界"),
        (_utc(2026, 9, 1, 4, 50), False, "北京12:50 午休"),
        (_utc(2026, 9, 1, 6, 0), True, "北京14:00 午盘中"),
        (_utc(2026, 9, 1, 7, 35), True, "北京15:35 收盘后收尾边界"),
        (_utc(2026, 9, 1, 7, 40), False, "北京15:40 已收市"),
        (_utc(2026, 9, 1, 14, 0), False, "北京22:00 夜间"),
        (_utc(2026, 9, 1, 0, 0), False, "北京08:00 清晨"),
        (_utc(2026, 9, 1, 23, 0), False, "北京次日07:00 跨日"),
    ],
)
def test_is_trading_time_session_windows(utc_dt, expected, label):
    assert is_trading_time(utc_dt) is expected, label


def test_overnight_utc_maps_to_next_beijing_day():
    """UTC 16:00 = 北京次日 00:00 → 非交易时段（不是当天 16:00）"""
    assert is_trading_time(_utc(2026, 9, 1, 16, 0)) is False
    # UTC 23:00 = 北京 07:00 → 仍非交易时段
    assert is_trading_time(_utc(2026, 9, 1, 23, 0)) is False


def test_weekend_never_trading_time_even_at_10am():
    """周六北京 10:00 处于早盘时段，但周末必须跳过"""
    # UTC 2026-08-29(六) 02:00 = 北京 08-29 10:00
    assert is_trading_time(_utc(2026, 8, 29, 2, 0)) is False
    # 周日同理
    assert is_trading_time(_utc(2026, 8, 30, 2, 0)) is False


def test_grace_minutes_extends_windows():
    """grace_minutes 双向放宽边界"""
    # 北京 09:16 本就在时段内
    assert is_trading_time(_utc(2026, 9, 1, 1, 16)) is True
    # 北京 09:10 默认不在；放宽 10 分钟后进入
    assert is_trading_time(_utc(2026, 9, 1, 1, 10)) is False
    assert is_trading_time(_utc(2026, 9, 1, 1, 10), grace_minutes=10) is True
    # 收盘侧同样放宽
    assert is_trading_time(_utc(2026, 9, 1, 7, 40)) is False
    assert is_trading_time(_utc(2026, 9, 1, 7, 40), grace_minutes=10) is True


def test_extra_holidays_blocks_trading_time():
    """节假日：即使周一 10:00 也必须跳过"""
    hol = frozenset({date(2026, 10, 1)})  # 2026-10-01 是周四
    assert is_trading_time(_utc(2026, 10, 1, 2, 0)) is True
    assert is_trading_time(_utc(2026, 10, 1, 2, 0), extra_holidays=hol) is False


# ---------- should_run_now ----------


def test_should_run_now_matches_is_trading_time():
    assert should_run_now() == is_trading_time()


def test_accepts_aware_input_identically():
    """aware 与等价 naive-UTC 输入必须给出相同判定（TZ 无关性）"""
    naive_utc = _utc(2026, 9, 1, 2, 0)  # 北京 10:00 周二
    aware_utc = naive_utc.replace(tzinfo=UTC)
    assert is_trading_time(naive_utc) is is_trading_time(aware_utc) is True


def test_session_constants_sane():
    """会话边界常量自身合理性（防手滑写反）"""
    from shared.trading_calendar import SESSIONS

    assert len(SESSIONS) == 2
    for start, end in SESSIONS:
        assert isinstance(start, dtime) and isinstance(end, dtime)
        assert start < end
    # 两个会话不重叠
    assert SESSIONS[0][1] < SESSIONS[1][0]
