#!/usr/bin/env python3
"""VPB 退出机制对比回测 — 旧退出 vs v2.2 增强版退出

对比 same 入场信号下，不同退出逻辑的盈亏比/胜率/总收益差异。
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

API_BASE = "http://localhost:8000/api/v1/backtest"

STOCKS = [
    {"ts_code": "600519.SH", "name": "贵州茅台"},
    {"ts_code": "600570.SH", "name": "恒生电子"},
    {"ts_code": "000858.SZ", "name": "五粮液"},
    {"ts_code": "002371.SZ", "name": "北方华创"},
]

DATE_RANGE = ("2025-01-01", "2026-06-13")
INITIAL_CASH = 1_000_000.0

# VPB 参数 — 仅退出部分不同
BASE_PARAMS = {
    "event_lookback": 20,
    "vol_surge_mult": 1.5,
    "atr_surge_mult": 1.3,
    "gap_threshold": 0.02,
    "breakout_lookback": 15,
    "confirm_bars": 1,
    "require_volume": True,
    "vol_confirm_mult": 1.0,
    "rsi_overbought": 75,
    "rsi_lower_bound": 40,
    "min_price": 1.0,
    "max_hold_days": 15,
    "atr_mult_stop": 2.0,
    "rsi_trend_exit": 80,
    "ma_exit_period": 10,
}

EXIT_CONFIGS = {
    "old_fixed_atr": {
        "label": "旧退出 (原版 ATR 固定止损)",
        "params": {
            "use_enhanced_exits": False,
            "atr_mult_stop": 2.0,
        }
    },
    "new_trail06_tp15": {
        "label": "新退出 (6%回撤止损 + 15%止盈)",
        "params": {
            "use_enhanced_exits": True,
            "trailing_stop_pct": 0.06,
            "take_profit_pct": 0.15,
            "atr_mult_stop": 2.0,
        }
    },
    "new_trail05_tp12": {
        "label": "新退出 (5%回撤止损 + 12%止盈)",
        "params": {
            "use_enhanced_exits": True,
            "trailing_stop_pct": 0.05,
            "take_profit_pct": 0.12,
            "atr_mult_stop": 2.0,
        }
    },
    "new_trail08_tp18": {
        "label": "新退出 (8%回撤止损 + 18%止盈)",
        "params": {
            "use_enhanced_exits": True,
            "trailing_stop_pct": 0.08,
            "take_profit_pct": 0.18,
            "atr_mult_stop": 2.0,
        }
    },
}


def run_backtest(ts_code: str, params: dict) -> dict | None:
    payload = {
        "ts_code": ts_code,
        "strategies": ["vpb"],
        "start_date": DATE_RANGE[0],
        "end_date": DATE_RANGE[1],
        "initial_cash": INITIAL_CASH,
        "params": params,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/run",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ❌ API 失败: {e}")
        return None


def main():
    print("=" * 80)
    print("📊 VPB 退出机制对比回测")
    print(f"   期间: {DATE_RANGE[0]} ~ {DATE_RANGE[1]}  初始资金: {INITIAL_CASH:,.0f}")
    print(f"   退出配置数: {len(EXIT_CONFIGS)}  标的数: {len(STOCKS)}")
    print("=" * 80)

    all_results = {}

    for stock in STOCKS:
        ts = stock["ts_code"]
        name = stock["name"]
        print(f"\n{'='*60}")
        print(f"📈 标的: {name} ({ts})")
        print(f"{'='*60}")

        stock_results = []
        for exit_key, exit_cfg in EXIT_CONFIGS.items():
            full_params = {**BASE_PARAMS, **exit_cfg["params"]}
            print(f"\n  🔄 退出: {exit_cfg['label']}")
            print(f"     参数: trailing={full_params.get('trailing_stop_pct','N/A')} "
                  f"tp={full_params.get('take_profit_pct','N/A')} "
                  f"enhanced={full_params['use_enhanced_exits']}")

            result = run_backtest(ts, full_params)
            if result and result.get("success"):
                m = result.get("data", {}).get("metrics", {})
                total_ret = m.get("total_return", 0) * 100
                annual_ret = m.get("annual_return", 0) * 100
                sharpe = m.get("sharpe_ratio", 0)
                max_dd = m.get("max_drawdown", 0) * 100
                trades = m.get("total_trades", 0)
                win_rate = m.get("win_rate", 0) * 100
                profit_factor = m.get("profit_factor", 0)  # 盈亏比
                win_trades = m.get("winning_trades", 0)
                loss_trades = m.get("losing_trades", 0)

                print(f"     📊 总收益:{total_ret:+7.2f}% | 年化:{annual_ret:+7.2f}% "
                      f"| 夏普:{sharpe:.2f} | 回撤:{max_dd:.2f}%")
                print(f"     📊 交易:{trades}次 | 胜率:{win_rate:.1f}% | "
                      f"盈亏比:{profit_factor:.2f} | 赢/亏:{win_trades}/{loss_trades}")

                stock_results.append({
                    "exit_key": exit_key,
                    "exit_label": exit_cfg["label"],
                    "params": full_params,
                    "total_return": round(total_ret, 2),
                    "annual_return": round(annual_ret, 2),
                    "sharpe_ratio": round(sharpe, 2),
                    "max_drawdown": round(max_dd, 2),
                    "total_trades": trades,
                    "win_rate": round(win_rate, 1),
                    "profit_factor": round(profit_factor, 2),
                    "winning_trades": win_trades,
                    "losing_trades": loss_trades,
                })
            else:
                err = result.get("error", "失败") if result else "无响应"
                print(f"     ❌ {err}")
                stock_results.append({
                    "exit_key": exit_key,
                    "exit_label": exit_cfg["label"],
                    "error": err,
                })

        # 标的结果排名（按夏普）
        valid = [r for r in stock_results if "error" not in r]
        if valid:
            by_sharpe = sorted(valid, key=lambda x: x["sharpe_ratio"], reverse=True)
            print(f"\n  🏆 {name} — 夏普排名:")
            for i, r in enumerate(by_sharpe, 1):
                print(f"     {i}. {r['exit_label']:<30} "
                      f"夏普={r['sharpe_ratio']:.2f} | 收益={r['total_return']:+6.2f}% | "
                      f"盈亏比={r['profit_factor']:.2f} | 胜率={r['win_rate']:.1f}%")

        all_results[ts] = stock_results

    # 汇总对比表（只看旧退出 vs 最佳新退出）
    print(f"\n\n{'='*80}")
    print("📊 汇总对比: 旧退出 vs 最佳新退出配置")
    print(f"{'='*80}")
    print(f"{'标的':<12} {'旧退出收益':<14} {'最佳新退出':<30} {'新退出收益':<14} {'盈亏比提升':<12} {'新配置'}")
    print("-" * 80)

    for stock in STOCKS:
        ts = stock["ts_code"]
        results = all_results.get(ts, [])
        old = next((r for r in results if r.get("exit_key") == "old_fixed_atr"), None)
        valid_new = [r for r in results if "error" not in r and r.get("exit_key") != "old_fixed_atr"]
        if old and valid_new:
            best_new = max(valid_new, key=lambda x: x.get("profit_factor", 0))
            ret_old = old.get("total_return", 0)
            ret_new = best_new.get("total_return", 0)
            pf_old = old.get("profit_factor", 0)
            pf_new = best_new.get("profit_factor", 0)
            pf_delta = pf_new - pf_old
            print(f"{stock['name']:<12} {ret_old:+8.2f}%      "
                  f"{best_new['exit_label']:<30} {ret_new:+8.2f}%      "
                  f"{pf_delta:+5.2f}         {best_new['exit_key']}")
        elif old:
            print(f"{stock['name']:<12} {old.get('total_return',0):+8.2f}%      "
                  f"{'❌ 新退出无有效数据':<30} {'N/A':>10}")

    print("=" * 80)


if __name__ == "__main__":
    main()
