"""回测引擎**值级金标**（golden master）—— 为改造提供回归网（2026-10-11 建立）。

━━ 为什么需要 ━━
发现回路 `disc-20261010-02` 提出把 `backtest_engine_v2.py` 的逐行循环向量化提速，
其提案写「保留 test_backtest_engine_v2.py 断言收益曲线与交易信号不变」。
**实测该前提不成立**：存量 100 个用例只断言**结构** ——
`len(equity_curve) > 0`、`total_trades >= 0`、日期单调、字段存在 ——
**没有任何值级断言**。也就是说：改造一旦让收益曲线数值漂移，存量测试**全绿**。

本文件补上这张网：固定输入 → 钉住关键数值。任何后续改造（向量化 / 换数据结构 /
重构循环）都必须让这些数字**逐位不变**；若确实要改口径，必须**显式改本文件并说明原因**。

━━ 为什么"钉值"不叫脆 ━━
回测引擎的收益/交易数值就是它的**对外承诺**。把它钉住 = 把"不知道有没有变"变成
"变了会响"。这与本项目铁律「策略回测须过带成本全样本+随机对照」同源：
先能证明"没变"，才敢动实现。

━━ 为什么输入用整数 LCG 而不是 random/sin ━━
金标要求**任何机器算出的输入逐位相同**：`random` 要种子、`sin` 在 glibc / macOS libm
之间可能差最后一位 → 都会让金标在 CI(ubuntu) 与本机(macOS)之间漂移。
整数线性同余 + 整数价（分）→ 跨平台逐位一致。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from services.backtest_engine_v2 import BacktestConfig, EnhancedBacktestEngine

# 数据规模：120 个交易日 —— 足够让 ma-cross 走完「信号 → 建仓 → 离场」完整回合
N_BARS = 120


def _bars(n: int = N_BARS, seed: int = 12345) -> list[dict]:
    """确定性行情序列（整数 LCG，跨平台逐位一致）。

    价格用「分」做整数运算，最后才 /100 成浮点 —— 避免累乘浮点误差在不同平台分叉。
    """
    d0 = date(2024, 1, 2)
    x, px = seed, 10000
    out = []
    for i in range(n):
        x = (1103515245 * x + 12345) % 2147483648
        pct = (x % 41 - 20) / 1000.0  # ±2.0%
        px = max(500, int(px * (1 + pct)))
        o = px
        c = max(100, int(px * (1 + ((x // 41) % 21 - 10) / 1000.0)))
        hi, lo = max(o, c) + 15, min(o, c) - 15
        out.append(
            {
                "trade_date": (d0 + timedelta(days=i)).strftime("%Y%m%d"),
                "open": o / 100,
                "close": c / 100,
                "high": hi / 100,
                "low": lo / 100,
                "vol": 1_000_000 + (x % 500_000),
            }
        )
    return out


def _run(strategies: list[str]):
    cfg = BacktestConfig(
        ts_codes=["000001.SZ"],
        strategies=strategies,
        start_date="20240101",
        end_date="20241231",
        initial_cash=100000.0,
    )
    eng = EnhancedBacktestEngine(cfg)
    return eng.run(data={"000001.SZ": _bars()}, benchmark_data=[])


def _trade_tuples(result) -> list[tuple]:
    """不含四舍五入 —— 金标要能看见漂移，就别自己先把末位抹平。"""
    return [(t.date, t.direction, t.price, t.quantity, t.pnl) for t in result.trades]


# ──────────────────── ma-cross 单策略 ────────────────────


MA_CROSS_GOLDEN = {
    "total_trades": 3,
    "total_return": -0.0028579550499999717,
    "annual_return": -0.005992272571640367,
    "max_drawdown": 0.014863902125229917,
    "win_rate": 0.3333333333333333,
    "profit_factor": 0.5050330145434996,
    "equity_len": 120,
    "last_nav": 0.99714204495,
    "last_value": 99714.204495,
}

MA_CROSS_TRADES = [
    ("20240130", "BUY", 107.22712, 200, 0.0),
    ("20240219", "SELL", 105.75413999999999, 200, -321.0345350000025),
    ("20240227", "BUY", 107.99788999999998, 200, 0.0),
    ("20240309", "SELL", 109.51038, 200, 275.1204050000051),
    ("20240312", "BUY", 107.94783999999999, 200, 0.0),
    ("20240313", "SELL", 106.96293, 200, -223.72273249999853),
]


def test_ma_cross_golden_master_values():
    """ma-cross 全流程关键数值逐位不变（改造回归的主闸门）。"""
    r = _run(["ma-cross"])
    assert r.total_trades == MA_CROSS_GOLDEN["total_trades"]
    assert len(r.equity_curve) == MA_CROSS_GOLDEN["equity_len"]
    assert r.total_return == pytest.approx(MA_CROSS_GOLDEN["total_return"], rel=1e-9)
    assert r.annual_return == pytest.approx(MA_CROSS_GOLDEN["annual_return"], rel=1e-9)
    assert r.max_drawdown == pytest.approx(MA_CROSS_GOLDEN["max_drawdown"], rel=1e-9)
    assert r.win_rate == pytest.approx(MA_CROSS_GOLDEN["win_rate"], rel=1e-9)
    assert r.profit_factor == pytest.approx(MA_CROSS_GOLDEN["profit_factor"], rel=1e-9)
    last = r.equity_curve[-1]
    assert last["date"] == "20240430"
    assert last["nav"] == pytest.approx(MA_CROSS_GOLDEN["last_nav"], rel=1e-9)
    assert last["value"] == pytest.approx(MA_CROSS_GOLDEN["last_value"], rel=1e-9)


def test_ma_cross_golden_master_trades():
    """交易信号逐笔不变（日期/方向/成交价/数量/单笔盈亏）。

    同时钉住一处**语义**：`total_trades` 数的是**完整回合**（3），
    而 `trades` 是逐腿明细（6 = 3 买 + 3 卖）—— 两者不相等不是 bug。
    """
    r = _run(["ma-cross"])
    assert r.total_trades == 3, "total_trades = 完整回合数"
    assert len(r.trades) == 6, "trades = 逐腿明细（买/卖各计一条）"
    got = _trade_tuples(r)
    assert len(got) == len(MA_CROSS_TRADES)
    for i, (g, e) in enumerate(zip(got, MA_CROSS_TRADES)):
        assert g[0] == e[0], f"第 {i} 笔日期漂移"
        assert g[1] == e[1], f"第 {i} 笔方向漂移"
        assert g[3] == e[3], f"第 {i} 笔数量漂移"
        assert g[2] == pytest.approx(e[2], rel=1e-12), f"第 {i} 笔成交价漂移"
        assert g[4] == pytest.approx(e[4], rel=1e-12), f"第 {i} 笔盈亏漂移"


def test_golden_master_carries_transaction_costs():
    """钉住的这条路径**确实带成本**（滑点/佣金/印花税），不是零成本裸跑。

    否则"数值不变"守的是一个不含成本的简化路径，与实盘口径无关
    （对应铁律：策略回测须过**带成本**全样本）。
    """
    trades = _run(["ma-cross"]).trades
    assert all(t.slippage_cost > 0 for t in trades), "滑点未计入"
    assert all(t.commission > 0 for t in trades), "佣金未计入"
    sells = [t for t in trades if t.direction == "SELL"]
    assert sells and all(t.tax > 0 for t in sells), "卖出印花税未计入"
    assert all(t.tax == 0 for t in trades if t.direction == "BUY"), "买入不应计印花税"


# ──────────────────── 多策略 ────────────────────


def test_multi_strategy_golden_master_values():
    """ma-cross + rsi 并行：多策略合并后的数值也必须稳定。"""
    r = _run(["ma-cross", "rsi"])
    assert r.total_trades == 4
    assert len(r.equity_curve) == 120
    assert r.total_return == pytest.approx(-0.03742833011500002, rel=1e-9)
    assert r.max_drawdown == pytest.approx(0.04653595826690869, rel=1e-9)
    assert r.win_rate == pytest.approx(0.25, rel=1e-9)


# ──────────────────── 自证：金标本身是确定的 ────────────────────


def test_golden_master_is_deterministic_across_runs():
    """同输入跑两次必须完全一致 —— 否则金标本身无效（会随机红）。

    这一条是金标的**自证**：它失败说明引擎引入了隐藏状态/顺序依赖，
    此时上面的数值断言即使通过也没有意义。
    """
    a, b = _run(["ma-cross"]), _run(["ma-cross"])
    assert _trade_tuples(a) == _trade_tuples(b)
    assert [p["nav"] for p in a.equity_curve] == [p["nav"] for p in b.equity_curve]
    assert a.total_return == b.total_return
