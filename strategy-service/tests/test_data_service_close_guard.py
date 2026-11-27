"""ADR 007 阶段 A：close 缺失「只观测、不丢弃」。

为什么这么测：`price_sanity.bar_problems()` 有意放行缺字段的 bar（不同数据源字段不全），
而 close 是收益计算的必需项。是否该拦，取决于真实发生率——
生产库实测 3,315,977 行里 close 为 NULL 的是 **0 行**，所以先观测一周再决定。

因此本文件锁两件事：
  ① 有缺失时**必须留下告警**（否则观测态等于不存在）；
  ② 有缺失时**条数不得变化**（否则就不是观测态，而是偷偷改了行为）。
第二条是这条用例的价值所在：只测「有没有告警」会放过「顺手把 bar 丢掉」的改动。
"""

from __future__ import annotations

import logging

from services.data_service import DataService


def _bar(date: str, close=10.0, pre=9.8, pct=2.0, hi=None, lo=None) -> dict:
    return {
        "trade_date": date,
        "open": close,
        "high": hi if hi is not None else close,
        "low": lo if lo is not None else pre,
        "close": close,
        "pre_close": pre,
        "pct_change": pct,
    }


CLEAN = [_bar("2026-11-24"), _bar("2026-11-25", close=10.2, pre=10.0)]


def test_missing_close_is_logged_not_dropped(caplog):
    """close 缺失（None 或 '--'）→ 告警，但**一条都不许丢**。"""
    bars = CLEAN + [
        _bar("2026-11-26", close=None),
        _bar("2026-11-27", close="--"),  # 停牌股在某些源里的写法
    ]
    with caplog.at_level(logging.WARNING):
        out = DataService._screen_quotes(bars, "600584.SH", "unit-test")

    assert len(out) == len(bars), f"观测态不得改变条数：{len(bars)} → {len(out)}"
    hits = [r for r in caplog.records if "ADR 007" in str(r.msg)]
    assert hits, f"缺失必须留下告警，实际记录：{[r.msg for r in caplog.records]}"
    # count 由 StructuredLogger 拼进 msg（不是 record 属性），故断言消息正文
    assert "count=2" in str(hits[0].msg), f"告警需带 count，实际：{hits[0].msg}"


def test_clean_bars_no_warning(caplog):
    """干净样本不得产生该告警（防「恒告警」式假信号）。"""
    with caplog.at_level(logging.WARNING):
        out = DataService._screen_quotes(CLEAN, "600584.SH", "unit-test")

    assert len(out) == len(CLEAN)
    assert not [r for r in caplog.records if "ADR 007" in str(r.msg)], (
        f"干净样本被误告警：{[r.msg for r in caplog.records]}"
    )
