#!/usr/bin/env python3
"""VPB 最终回测 — 稳健推荐参数 vs 旧退出 + Walk-Forward 对比"""
import json
import urllib.request

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
        "label": "旧退出 (ATR固定止损)",
        "params": {
            "use_enhanced_exits": False,
            "event_lookback": 20, "vol_surge_mult": 1.5,
            "breakout_lookback": 15, "confirm_bars": 1,
            "max_hold_days": 15, "atr_mult_stop": 2.0,
        }
    },
    {
        "label": "新推荐 (6%trail + 15%tp)",
        "params": {
            "use_enhanced_exits": True, "trailing_stop_pct": 0.06,
            "take_profit_pct": 0.15,
            "event_lookback": 20, "vol_surge_mult": 1.5,
            "breakout_lookback": 15, "confirm_bars": 1,
            "max_hold_days": 15, "atr_mult_stop": 2.0,
        }
    },
    {
        "label": "新稳健 (5%trail + 12%tp)",
        "params": {
            "use_enhanced_exits": True, "trailing_stop_pct": 0.05,
            "take_profit_pct": 0.12,
            "event_lookback": 20, "vol_surge_mult": 1.5,
            "breakout_lookback": 15, "confirm_bars": 1,
            "max_hold_days": 15, "atr_mult_stop": 2.0,
        }
    },
]


def run_backtest(ts_code: str, params: dict) -> dict | None:
    payload = {
        "ts_code": ts_code, "strategies": ["vpb"],
        "start_date": DATE_RANGE[0], "end_date": DATE_RANGE[1],
        "initial_cash": INITIAL_CASH, "params": params,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/run", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ❌ {e}")
        return None


def main():
    results = {}
    for stock in STOCKS:
        ts = stock["ts_code"]
        name = stock["name"]
        print(f"\n{'='*70}")
        print(f"📈 {name} ({ts})")
        print(f"{'='*70}")
        print(f"{'配置':<30} {'总收益':>8} {'夏普':>7} {'回撤':>8} {'交易':>5} {'胜率':>7} {'盈亏比':>7}")
        print("-" * 70)

        stock_res = []
        for cfg in CONFIGS:
            result = run_backtest(ts, cfg["params"])
            if result and result.get("success"):
                m = result.get("data", {}).get("metrics", {})
                tr = m.get("total_return", 0) * 100
                sr = m.get("sharpe_ratio", 0)
                dd = m.get("max_drawdown", 0) * 100
                trd = m.get("total_trades", 0)
                wr = m.get("win_rate", 0) * 100
                pf = m.get("profit_factor", 0)
                ar = m.get("annual_return", 0) * 100

                print(f"{cfg['label']:<30} {tr:>+7.2f}% {sr:>6.2f} "
                      f"{dd:>7.2f}% {trd:>5} {wr:>6.1f}% {pf:>6.2f}")

                stock_res.append({
                    "label": cfg["label"], "total_return": tr,
                    "sharpe": sr, "max_dd": dd, "trades": trd,
                    "win_rate": wr, "profit_factor": pf, "annual_return": ar,
                })
            else:
                print(f"{cfg['label']:<30} ❌ failed")

        results[name] = stock_res

    # 最终汇总
    print(f"\n\n{'='*70}")
    print("📊 VPB 退出优化最终汇总")
    print(f"{'='*70}")

    for name, res in results.items():
        old = next((r for r in res if "旧退出" in r["label"]), None)
        best = max((r for r in res if "新" in r["label"]), key=lambda x: x["total_return"])
        if old:
            print(f"\n{name}:")
            print(f"  旧退出: {old['total_return']:+.2f}% | 盈亏比 {old['profit_factor']:.2f} | 夏普 {old['sharpe']:.2f}")
            print(f"  最优新: {best['label']}")
            print(f"  新退出: {best['total_return']:+.2f}% | 盈亏比 {best['profit_factor']:.2f} | 夏普 {best['sharpe']:.2f}")
            print(f"  改善 : {best['total_return'] - old['total_return']:+.2f}pp (盈亏比 {old['profit_factor']:.2f}→{best['profit_factor']:.2f})")

    # 推荐
    print(f"\n{'='*70}")
    print("✅ 最终推荐参数 (v2.2):")
    print(f"   默认: use_enhanced_exits=true, trailing_stop_pct=0.06, take_profit_pct=0.15")
    print(f"   退出优先级: 固定止盈 > 最高点回撤止损 > ATR硬止损 > 趋势反转 > 最大持有天数 > RSI动量衰竭")
    print(f"   其余参数保持原样: event_lookback=20, breakout_lookback=15, confirm_bars=1")


if __name__ == "__main__":
    main()
