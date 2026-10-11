#!/usr/bin/env python3
"""bench_backtest.py — 回测引擎的**可复跑提速基线**（2026-10-11 建立）。

━━ 为什么有这个文件 ━━
发现回路 `disc-20261010-02` 提出把 `backtest_engine_v2.py` 的逐行循环**向量化**，
验收指标是「相同全样本回测耗时较改造前下降 ≥50%，且收益曲线/交易信号不变」。
但提案**没有基线数字** —— 没有基线就无从判断"该不该改"，也无从验收"降了 50%"。

本脚本提供那个基线，且**完全确定**（整数 LCG 造行情，无网络、无 DB、无 random），
所以任何人在任何机器上跑出的规模-耗时关系都可比。

━━ 实测基线（2026-10-11，本机 py3.13；best-of-3，不含 cProfile 开销）━━
| 规模 | 行数 | wall-time | 每行 |
|---|---|---|---|
| 40 × 500   | 2 万   | 0.016s | 0.79µs |
| 100 × 1000 | 10 万  | 0.121s | 1.21µs |
| 200 × 2000 | 40 万  | 0.472s | 1.18µs |
→ **完全线性**（每行 ≈1.2µs）。按此外推：13M 行（≈5400 只 × 10 年日线）≈ **16s**。

━━ 结论（据此作出，见 disc-20261010-02 的终态）━━
回测耗时**不是当前瓶颈**（现实规模下亚秒~十几秒），因此**不做**向量化改造：
收益是"省零点几秒"，代价是重写算钱路径的信号/成交循环。留着基线，
等哪天真出现"回测太慢挡住了研究"的实例，再拿它当验收锚。

用法：
  python3 scripts/bench_backtest.py            # 默认跑 40×500 与 200×2000
  python3 scripts/bench_backtest.py 100 1000   # 指定规模
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta

# 同目录其它脚本固定写 `sys.path.insert(0, "/app")`（容器内约定）；
# 本脚本要**既能在容器跑、也能在宿主机直接跑**（基线复现不该要求先起容器），
# 故两个位置都加：/app（容器）+ 本文件上级目录（宿主机 checkout）。
for _p in ("/app", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from services.backtest_engine_v2 import BacktestConfig, EnhancedBacktestEngine  # noqa: E402


def bars(n: int, seed: int) -> list[dict]:
    """确定性行情（整数 LCG + 整数价「分」）—— 跨平台逐位一致，别改成 random/sin。"""
    d0 = date(2024, 1, 2)
    x, px = seed, 10000
    out = []
    for i in range(n):
        x = (1103515245 * x + 12345) % 2147483648
        px = max(500, int(px * (1 + ((x % 41 - 20) / 1000.0))))
        o = px
        c = max(100, int(px * (1 + ((x // 41) % 21 - 10) / 1000.0)))
        out.append(
            {
                "trade_date": (d0 + timedelta(days=i)).strftime("%Y%m%d"),
                "open": o / 100,
                "close": c / 100,
                "high": max(o, c) / 100 + 0.15,
                "low": min(o, c) / 100 - 0.15,
                "vol": 1_000_000 + (x % 500_000),
            }
        )
    return out


def bench(n_stock: int, n_bar: int, repeat: int = 3) -> dict:
    data = {f"000{i:03d}.SZ": bars(n_bar, 12345 + i) for i in range(n_stock)}
    cfg = BacktestConfig(
        ts_codes=list(data),
        strategies=["ma-cross"],
        start_date="20240101",
        end_date="20241231",
    )
    best, result = float("inf"), None
    for _ in range(repeat):
        t0 = time.perf_counter()
        result = EnhancedBacktestEngine(cfg).run(data=data, benchmark_data=[])
        best = min(best, time.perf_counter() - t0)
    rows = n_stock * n_bar
    return {
        "stocks": n_stock,
        "bars": n_bar,
        "rows": rows,
        "best_s": best,
        "s_per_row": best / rows,
        "trades": len(result.trades),
        "total_return": result.total_return,
    }


def main(argv: list[str]) -> int:
    if len(argv) >= 3:
        sizes = [(int(argv[1]), int(argv[2]))]
    else:
        sizes = [(40, 500), (200, 2000)]
    print(f"{'规模':>14} {'行数':>10} {'wall-time':>12} {'每行':>10} {'成交腿':>8}")
    for n_stock, n_bar in sizes:
        r = bench(n_stock, n_bar)
        print(
            f"{r['stocks']:>6} × {r['bars']:<5} {r['rows']:>10} "
            f"{r['best_s']:>11.3f}s {r['s_per_row'] * 1e6:>9.2f}µs {r['trades']:>8}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
