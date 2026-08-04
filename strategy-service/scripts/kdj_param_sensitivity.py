#!/usr/bin/env python3
"""
kdj_param_sensitivity.py — KDJ 参数敏感性专项（08-04 Q1-C 落地）
================================================================
背景：WF 稀疏度分析显示 KDJ 是唯一信号密集策略(13/17)，其余策略窗口内几乎无交易。
本脚本对 22 股 × 6 组 KDJ 参数做全样本回测，量化「信号密度(trades) vs 质量(win/sharpe)」，
验证调参能否在不降质量前提下进一步提升信号密度，为日报 KDJ 参数定稿提供依据。

Usage:
  docker exec quant-strategy python /app/scripts/kdj_param_sensitivity.py
输出: /app/output/kdj_param_sensitivity.json + 控制台对比表
"""

import json
import sys

sys.path.insert(0, "/app")
from pathlib import Path

from services.backtest_engine_v2 import BacktestConfig, EnhancedBacktestEngine

STOCK_NAMES = {
    "002049.SZ": "紫光国微",
    "600498.SH": "烽火通信",
    "000725.SZ": "京东方A",
    "600522.SH": "中天科技",
    "002601.SZ": "龙佰集团",
    "600206.SH": "有研新材",
    "000001.SZ": "平安银行",
    "000333.SZ": "美的集团",
    "002415.SZ": "海康威视",
    "600519.SH": "贵州茅台",
    "601318.SH": "中国平安",
    "000858.SZ": "五粮液",
    "600036.SH": "招商银行",
    "600276.SH": "恒瑞医药",
    "600887.SH": "伊利股份",
    "600570.SH": "恒生电子",
    "600585.SH": "海螺水泥",
    "600893.SH": "航发动力",
    "601899.SH": "紫金矿业",
    "002230.SZ": "科大讯飞",
    "300750.SZ": "宁德时代",
    "688981.SH": "中芯国际",
}
TS_CODES = list(STOCK_NAMES.keys())

# 6 组 KDJ 参数：基线 9/3/3（当前日报） + 5 组敏感度探测
PARAM_SETS = [
    ("baseline-9-3-3", {"period": 9, "k_smooth": 3, "d_smooth": 3}),
    ("fast-5-3-3", {"period": 5, "k_smooth": 3, "d_smooth": 3}),
    ("slow-14-3-3", {"period": 14, "k_smooth": 3, "d_smooth": 3}),
    ("mid-9-5-5", {"period": 9, "k_smooth": 5, "d_smooth": 5}),
    ("soft-9-3-5", {"period": 9, "k_smooth": 3, "d_smooth": 5}),
    ("fast5-9-5-3", {"period": 9, "k_smooth": 5, "d_smooth": 3}),
]

OUT_JSON = Path("/app/output/kdj_param_sensitivity.json")


def run():
    cfg = BacktestConfig(
        ts_codes=TS_CODES,
        strategies=["kdj"],
        start_date="2025-01-01",
        end_date="2026-08-03",
        initial_cash=100000,
    )
    engine = EnhancedBacktestEngine(cfg)

    data_cache: dict[str, list] = {}
    for code in TS_CODES:
        data = engine.fetch_market_data(code, "2025-01-01", "2026-08-03")
        if data and len(data) >= 60:
            data_cache[code] = data

    print(f"数据就绪: {len(data_cache)}/{len(TS_CODES)} 只股票")
    print(
        f"{'参数组':<18} {'有交易股':>6} {'平均trades':>10} {'中位trades':>10} {'平均胜率':>8} {'平均收益%':>9} {'平均夏普':>8}"
    )
    print("-" * 75)

    results: dict = {}
    for name, params in PARAM_SETS:
        trades_list, win_list, ret_list, sharpe_list = [], [], [], []
        for code, data in data_cache.items():
            try:
                r = engine.run_single_stock(code, "kdj", data, params=params)
                if r and r.total_trades > 0:
                    trades_list.append(r.total_trades)
                    win_list.append(r.win_rate * 100)
                    ret_list.append(r.total_return * 100)
                    sharpe_list.append(r.sharpe_ratio)
            except Exception as e:
                print(f"  [{name}] {code} 失败: {e}")

        n = len(trades_list)
        avg_t = sum(trades_list) / n if n else 0
        med_t = sorted(trades_list)[n // 2] if n else 0
        avg_w = sum(win_list) / n if n else 0
        avg_r = sum(ret_list) / n if n else 0
        avg_s = sum(sharpe_list) / n if n else 0
        print(
            f"{name:<18} {n:>6}/{len(data_cache):<4} {avg_t:>10.1f} {med_t:>10} {avg_w:>7.1f}% {avg_r:>8.2f}% {avg_s:>8.2f}"
        )

        results[name] = {
            "params": params,
            "stocks_with_trades": n,
            "stocks_total": len(data_cache),
            "avg_trades": round(avg_t, 1),
            "median_trades": med_t,
            "avg_win_rate": round(avg_w, 1),
            "avg_return_pct": round(avg_r, 2),
            "avg_sharpe": round(avg_s, 2),
        }

    OUT_JSON.write_text(
        json.dumps({"generated_at": "2026-08-04", "results": results}, ensure_ascii=False, indent=2)
    )
    print(f"\n输出: {OUT_JSON}")


if __name__ == "__main__":
    run()
