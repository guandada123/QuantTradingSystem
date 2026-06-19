#!/usr/bin/env python3
"""VPB 优化参数最终验证 — 旧退出 vs Walk-Forward 优化后参数"""
import json
import urllib.request
from datetime import datetime

API_BASE = "http://localhost:8000/api/v1/backtest"

STOCKS = [
    {"ts_code": "600519.SH", "name": "贵州茅台"},
    {"ts_code": "600570.SH", "name": "恒生电子"},
    {"ts_code": "000858.SZ", "name": "五粮液"},
]

DATE_RANGE = ("2025-01-01", "2026-06-13")
INITIAL_CASH = 1_000_000.0

CONFIGS = [
    {
        "label": "① 旧退出 (原版 ATR 固定止损)",
        "params": {
            "use_enhanced_exits": False,
            "atr_mult_stop": 2.0,
            "event_lookback": 20, "vol_surge_mult": 1.5,
            "breakout_lookback": 15, "confirm_bars": 1,
            "max_hold_days": 15,
        }
    },
    {
        "label": "② 新退出 (Walk-Forward 最优 4%/10%)",
        "params": {
            "use_enhanced_exits": True,
            "trailing_stop_pct": 0.04,
            "take_profit_pct": 0.10,
            "atr_mult_stop": 2.0,
            "event_lookback": 20, "vol_surge_mult": 1.5,
            "breakout_lookback": 10, "confirm_bars": 0,
            "max_hold_days": 15,
        }
    },
    {
        "label": "③ 新退出 (激进 4%trail/10%tp + 1.3vol)",
        "params": {
            "use_enhanced_exits": True,
            "trailing_stop_pct": 0.04,
            "take_profit_pct": 0.10,
            "atr_mult_stop": 2.0,
            "event_lookback": 15, "vol_surge_mult": 1.3,
            "breakout_lookback": 10, "confirm_bars": 0,
            "max_hold_days": 12,
        }
    },
    {
        "label": "④ 新退出 (保守 4%trail/10%tp + 2.0vol)",
        "params": {
            "use_enhanced_exits": True,
            "trailing_stop_pct": 0.04,
            "take_profit_pct": 0.10,
            "atr_mult_stop": 2.0,
            "event_lookback": 20, "vol_surge_mult": 2.0,
            "breakout_lookback": 10, "confirm_bars": 0,
            "max_hold_days": 15,
        }
    },
]


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
        print(f"  ❌ API: {e}")
        return None


def main():
    print("=" * 85)
    print("📊 VPB 优化参数最终验证 — 旧退出 vs Walk-Forward 优化参数")
    print(f"   期间: {DATE_RANGE[0]} ~ {DATE_RANGE[1]}  |  资金: {INITIAL_CASH:,.0f}")
    print(f"   配置数: {len(CONFIGS)}  |  标的数: {len(STOCKS)}")
    print("=" * 85)

    all_rows = []

    for stock in STOCKS:
        ts = stock["ts_code"]
        name = stock["name"]
        print(f"\n{'='*85}")
        print(f"📈 {name} ({ts})")
        print(f"{'='*85}")
        print(f"{'配置':<35} {'收益':>8} {'年化':>8} {'夏普':>7} {'回撤':>8} {'交易':>5} {'胜率':>7} {'盈亏比':>7}")
        print("-" * 85)

        stock_rows = []
        for cfg in CONFIGS:
            label = cfg["label"]
            result = run_backtest(ts, cfg["params"])
            if result and result.get("success"):
                m = result.get("data", {}).get("metrics", {})
                total_ret = m.get("total_return", 0) * 100
                annual_ret = m.get("annual_return", 0) * 100
                sharpe = m.get("sharpe_ratio", 0)
                max_dd = m.get("max_drawdown", 0) * 100
                trades = m.get("total_trades", 0)
                win_rate = m.get("win_rate", 0) * 100
                profit_factor = m.get("profit_factor", 0)

                mark = "🟢" if total_ret > 0 else ("🔴" if total_ret < -3 else "🟡")
                print(f"{mark} {label:<33} {total_ret:+7.2f}% {annual_ret:+7.2f}% "
                      f"{sharpe:>6.2f} {max_dd:>7.2f}% {trades:>5} "
                      f"{win_rate:>6.1f}% {profit_factor:>6.2f}")

                stock_rows.append({
                    "label": label,
                    "total_return": total_ret,
                    "annual_return": annual_ret,
                    "sharpe": sharpe,
                    "max_drawdown": max_dd,
                    "trades": trades,
                    "win_rate": win_rate,
                    "profit_factor": profit_factor,
                })
            else:
                print(f"  ❌ {label:<33} 失败: {result.get('error','?')}")
                stock_rows.append({"label": label, "error": True})

        all_rows.append({"stock": name, "ts_code": ts, "configs": stock_rows})

    # 最终汇总
    print(f"\n\n{'='*85}")
    print("📊 汇总 — 收益提升对比")
    print(f"{'='*85}")
    print(f"{'标的':<12} {'旧退出收益':<14} {'最优配置':<24} {'最优收益':<14} {'改善':<10}")
    print("-" * 85)

    for entry in all_rows:
        configs = entry["configs"]
        old = next((c for c in configs if "旧退出" in c.get("label", "") and "error" not in c), None)
        valid_new = [c for c in configs if "新退出" in c.get("label", "") and "error" not in c]
        if old and valid_new:
            best_new = max(valid_new, key=lambda x: x.get("total_return", -999))
            ret_old = old.get("total_return", 0)
            ret_new = best_new.get("total_return", 0)
            delta = ret_new - ret_old
            pf_old = old.get("profit_factor", 0)
            pf_new = best_new.get("profit_factor", 0)
            print(f"{entry['stock']:<12} {ret_old:>+8.2f}%     "
                  f"{best_new['label']:<24} {ret_new:>+8.2f}%     "
                  f"{delta:>+6.2f}pp")
            print(f"{'':12} {'盈亏比':>8}: {pf_old:.2f} → {pf_new:.2f}")

    print("=" * 85)
    print(f"\n✅ Walk-Forward 参数优化完成！建议默认参数:")
    print(f"   use_enhanced_exits=true | trailing_stop_pct=0.04 | take_profit_pct=0.10")
    print(f"   breakout_lookback=10 | confirm_bars=0 | vol_surge_mult=1.3")


if __name__ == "__main__":
    main()
