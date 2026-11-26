"""价格合理性校验：拦住会让回测/展示失真的行情数据。

（2026-11-26 落地 disc-20261027-02）

## 为什么需要

`daily_quote` 表里只有**实际价**（open/high/low/close/pre_close），没有复权价与因子字段
（见 `repositories/daily_quote_repo.py::_daily_quote_to_dict`）。这带来两类真问题：

1. **fat finger / 占位价**：数据源偶发返回 0、负数、9999 这类哨兵值。
   它们一旦进入收益序列，会把整段回测的均值/方差带偏，而且**不会报错**——
   0 元收盘价算出来的跌幅是 -100%，看起来像"暴跌"。
2. **收益口径漂移（dual price）**：若某处用 `close` 环比算收益、另一处用
   `pct_change`，遇到除权除息日两者会打架 —— 前者出现假跌，后者是对的。
   这个不一致同样**不报错**，只是让回测结果悄悄失真。

## 术语

· **fat_finger**：0 / 负数 / 9999 这类哨兵价（`bar_problems` 拦）
· **dual_price**：同一份收益序列里混用复权价与实际价（`basis_drift_pct` 报）
· **adjustment_factor**：复权因子。本表**没有**该字段，正因为没有，才必须靠
  `pct_change` 与 `close/pre_close` 的互校来发现口径漂移（有因子的话直接比因子即可）

判据刻意「只拦明确坏数据」，不拦正常波动：宁可漏，不可误杀真实暴跌。

## 阈值来源

· 极端价：`<= 0` 或 `>= FAT_FINGER_HIGH`（9999 是常见哨兵值）
· 单日跳变：A 股涨跌停最宽 20%（科创/创业），留一倍余量取 25%；
  新股首日/复牌不受涨跌停限制，所以这个**只做告警不做过滤**（见 `screen_bars` 的说明）
· 口径漂移：`pct_change` 与 `close/pre_close-1` 的差超过 0.5 个百分点即算不一致
"""

from __future__ import annotations

from typing import Any

# 极端价哨兵：0 / 负数 / 9999（含以上）都不是真实成交价
FAT_FINGER_HIGH = 9999.0
# 单日涨跌幅告警线：A 股最宽 20%，留余量到 25%
JUMP_ALERT_PCT = 25.0
# 收益口径漂移容差（百分点）：两者本该一致，差超这个数就不是四舍五入能解释的
BASIS_DRIFT_TOL_PCT = 0.5

_PRICE_FIELDS = ("open", "high", "low", "close", "pre_close")


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def bar_problems(bar: dict[str, Any]) -> list[str]:
    """单条 bar 的硬问题（**该被过滤掉**的那些）。返回原因列表，空表示没问题。

    只判「这条数据不可能真实存在」的情形：
      · 任一价格字段为 0 或负数（停牌数据源的占位写法）
      · 任一价格字段 >= 9999（哨兵值）
      · high < low（字段错位）
      · close 落在 [low, high] 之外（同一条内部的矛盾）
    """
    probs: list[str] = []
    prices = {k: _f(bar.get(k)) for k in _PRICE_FIELDS}
    for k, v in prices.items():
        if v is None:
            continue  # 缺字段不算坏数据（不同数据源字段不全）
        if v <= 0:
            probs.append(f"{k}={v}（非正价格）")
        elif v >= FAT_FINGER_HIGH:
            probs.append(f"{k}={v}（哨兵值）")
    hi, lo = prices.get("high"), prices.get("low")
    if hi is not None and lo is not None and hi > 0 and lo > 0 and hi < lo:
        probs.append(f"high={hi} < low={lo}（字段错位）")
    close = prices.get("close")
    if close is not None and hi is not None and lo is not None and hi > 0 and lo > 0:
        if not (lo <= close <= hi):
            probs.append(f"close={close} 不在 [{lo}, {hi}] 内")
    return probs


def basis_drift_pct(bar: dict[str, Any]) -> float | None:
    """收益口径漂移的幅度（百分点）；无法判定时返回 None。

    比较「用 close/pre_close 算出来的涨跌幅」与「数据源自带的 pct_change」。
    两者本该一致（差异只来自四舍五入）。若差得远，说明其中一路用了**复权价**
    而另一路没有 —— 这就是 dual price 混用，回测在除权日会出现假跌。
    """
    close, pre = _f(bar.get("close")), _f(bar.get("pre_close"))
    pct = _f(bar.get("pct_change"))
    if close is None or pre is None or pct is None:
        return None
    if close <= 0 or pre <= 0:
        return None
    computed = (close / pre - 1.0) * 100.0
    return abs(computed - pct)


def jump_pct(bar: dict[str, Any]) -> float | None:
    """单日涨跌幅绝对值（百分点）；拿不到返回 None。优先 pct_change，退回 close/pre_close。"""
    pct = _f(bar.get("pct_change"))
    if pct is not None:
        return abs(pct)
    close, pre = _f(bar.get("close")), _f(bar.get("pre_close"))
    if close is None or pre is None or close <= 0 or pre <= 0:
        return None
    return abs((close / pre - 1.0) * 100.0)


def screen_bars(bars: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把 bar 列表分成（干净, 被剔除）。**只剔除 `bar_problems` 判定的硬问题**。

    为什么单日跳变不在这里剔除：新股首日、复牌、退市整理期都不受涨跌停约束，
    按 25% 砍会误杀真实暴跌。它由 `audit_bars` 单独报出来，供人看，不自动丢。
    """
    clean: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for b in bars:
        probs = bar_problems(b)
        if probs:
            dropped.append({"bar": b, "reasons": probs})
        else:
            clean.append(b)
    return clean, dropped


def audit_bars(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """整段序列的体检报告：硬问题条数、跳变告警、口径漂移告警。

    返回结构固定，便于巡检直接消费：
        {"total": N, "bad": [...], "jumps": [...], "drifts": [...], "ok": bool}
    """
    _clean, dropped = screen_bars(bars)
    jumps = []
    drifts = []
    for b in bars:
        jp = jump_pct(b)
        if jp is not None and jp > JUMP_ALERT_PCT:
            jumps.append({"trade_date": b.get("trade_date"), "jump_pct": round(jp, 2)})
        dp = basis_drift_pct(b)
        if dp is not None and dp > BASIS_DRIFT_TOL_PCT:
            drifts.append(
                {
                    "trade_date": b.get("trade_date"),
                    "drift_pct": round(dp, 2),
                    "close": b.get("close"),
                    "pre_close": b.get("pre_close"),
                    "pct_change": b.get("pct_change"),
                }
            )
    return {
        "total": len(bars),
        "bad": [
            {"trade_date": d["bar"].get("trade_date"), "reasons": d["reasons"]} for d in dropped
        ],
        "jumps": jumps,
        "drifts": drifts,
        # ok 只由**硬问题**决定：跳变与漂移是告警，不阻断
        "ok": not dropped,
    }
