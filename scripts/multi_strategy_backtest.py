#!/usr/bin/env python3
"""多策略并行回测对比脚本 — 调用策略服务 API 生成对比报告"""

from datetime import datetime
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

API_BASE = "http://localhost:8000/api/v1/backtest"

# 测试配置
TEST_CONFIG = {
    "ts_code": "600519.SH",         # 贵州茅台
    "start_date": "2025-01-01",
    "end_date": "2026-06-13",
    "initial_cash": 1000000.0,
}

# 全部可用策略及其默认参数
STRATEGIES = [
    {"strategy": "ma-cross", "params": {"ma_fast": 10, "ma_slow": 30}},
    {"strategy": "breakout", "params": {"lookback": 20}},
    {"strategy": "rsi", "params": {"period": 14, "oversold": 30, "overbought": 70}},
    {"strategy": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}},
    {"strategy": "kdj", "params": {"period": 9, "k_smooth": 3, "d_smooth": 3}},
    # 高级策略
    {"strategy": "vwm", "params": {"ma_fast": 5, "ma_slow": 20, "vol_multiplier_buy": 1.0}},
    {"strategy": "bollinger", "params": {"period": 20, "std_mult": 2.0}},
    {"strategy": "adx", "params": {"period": 14, "adx_threshold": 22}},
    {"strategy": "obv", "params": {"lookback": 20, "obv_period": 20}},
    {"strategy": "vbm", "params": {"roc_period": 5, "vol_mult": 1.2, "roc_threshold": 0.03}},
    # v2.1 新策略
    {"strategy": "vpb", "params": {
        "event_lookback": 20, "vol_surge_mult": 1.5,
        "breakout_lookback": 15, "confirm_bars": 1,
        "max_hold_days": 15, "atr_mult_stop": 2.0,
        "use_enhanced_exits": True,
        "trailing_stop_pct": 0.06,
        "take_profit_pct": 0.15,
    }},
]


def wait_for_service(url: str, max_retries: int = 30, interval: int = 2):
    """等待服务就绪"""
    print(f"⏳ 等待服务就绪: {url} ...")
    for i in range(max_retries):
        try:
            resp = urllib.request.urlopen(url, timeout=3)
            if resp.status == 200:
                print(f"✅ 服务就绪 (尝试 {i+1}/{max_retries})")
                return True
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        if i < max_retries - 1:
            time.sleep(interval)
    print("❌ 服务未就绪，放弃")
    return False


def run_backtest(ts_code: str, strategy: str, params: dict) -> dict | None:
    """调用回测 API 执行单个策略回测"""
    payload = {
        "ts_code": ts_code,
        "strategy": strategy,
        "strategies": [strategy],
        "start_date": TEST_CONFIG["start_date"],
        "end_date": TEST_CONFIG["end_date"],
        "initial_cash": TEST_CONFIG["initial_cash"],
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result
    except Exception as e:
        print(f"  ❌ API 调用失败: {e}")
        return None


def main():
    print("=" * 70)
    print("📊 QTS 多策略回测对比分析")
    print(f"   标的: {TEST_CONFIG['ts_code']}")
    print(f"   期间: {TEST_CONFIG['start_date']} ~ {TEST_CONFIG['end_date']}")
    print(f"   初始资金: {TEST_CONFIG['initial_cash']:,.0f}")
    print(f"   策略数: {len(STRATEGIES)}")
    print("=" * 70)

    # 1. 等待服务
    if not wait_for_service(f"{API_BASE}/status"):
        print("❌ 服务不可用，退出")
        sys.exit(1)

    # 2. 逐策略执行回测
    results = []
    for s in STRATEGIES:
        name = s["strategy"]
        print(f"\n🚀 运行策略: {name} (参数: {s['params']})")
        result = run_backtest(TEST_CONFIG["ts_code"], name, s["params"])
        if result and result.get("success"):
            data = result.get("data", {})
            metrics = data.get("metrics", {})
            print(f"  ✅ 完成 | 年化: {metrics.get('annual_return', 0)*100:.2f}% "
                  f"| 夏普: {metrics.get('sharpe_ratio', 0):.2f} "
                  f"| 回撤: {metrics.get('max_drawdown', 0)*100:.2f}% "
                  f"| 交易: {metrics.get('total_trades', 0)}")
            results.append({"strategy": name, "params": s["params"], **metrics})
        else:
            err = result.get("error", "未知错误") if result else "无响应"
            print(f"  ❌ 失败: {err}")
            results.append({"strategy": name, "params": s["params"], "error": err})

    # 3. 生成对比报告
    report_path = Path(__file__).parent.parent / "reports" / "multi_strategy_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": datetime.now().isoformat(),
        "config": TEST_CONFIG,
        "num_strategies": len(results),
        "results": [],
    }

    print("\n" + "=" * 70)
    print("📈 多策略回测对比汇总")
    print("=" * 70)

    # 表头
    header = f"{'策略':<14} {'年化收益':<12} {'夏普':<8} {'最大回撤':<12} {'总交易':<8} {'胜率':<8} {'盈亏比':<8}"
    print(header)
    print("-" * 70)

    for r in results:
        if "error" in r:
            report["results"].append(r)
            print(f"{r['strategy']:<14} ❌ {r['error']}")
            continue

        record = {
            "strategy": r["strategy"],
            "params": r["params"],
            "annual_return": r.get("annual_return", 0),
            "sharpe_ratio": r.get("sharpe_ratio", 0),
            "sortino_ratio": r.get("sortino_ratio", 0),
            "max_drawdown": r.get("max_drawdown", 0),
            "total_return": r.get("total_return", 0),
            "volatility": r.get("volatility", 0),
            "total_trades": r.get("total_trades", 0),
            "winning_trades": r.get("winning_trades", 0),
            "losing_trades": r.get("losing_trades", 0),
            "win_rate": r.get("win_rate", 0),
            "profit_factor": r.get("profit_factor", 0),
            "calmar_ratio": r.get("calmar_ratio", 0),
            "beta": r.get("beta", 0),
            "alpha": r.get("alpha", 0),
            "information_ratio": r.get("information_ratio", 0),
        }
        report["results"].append(record)

        print(
            f"{r['strategy']:<14} "
            f"{record['annual_return']*100:+7.2f}%  "
            f"{record['sharpe_ratio']:<8.2f} "
            f"{record['max_drawdown']*100:<+7.2f}%   "
            f"{record['total_trades']:<8} "
            f"{record['win_rate']*100:<7.1f}% "
            f"{record['profit_factor']:<8.2f}"
        )

    print("-" * 70)

    # 排名
    valid_results = [r for r in report["results"] if "error" not in r]
    if valid_results:
        by_sharpe = sorted(valid_results, key=lambda x: x["sharpe_ratio"], reverse=True)
        print("\n🏆 夏普比率排名:")
        for i, r in enumerate(by_sharpe, 1):
            print(f"  {i}. {r['strategy']:<14} Sharpe={r['sharpe_ratio']:.2f}")

        by_return = sorted(valid_results, key=lambda x: x["annual_return"], reverse=True)
        print("\n💰 年化收益排名:")
        for i, r in enumerate(by_return, 1):
            print(f"  {i}. {r['strategy']:<14} 年化={r['annual_return']*100:.2f}%")

        by_dd = sorted(valid_results, key=lambda x: x["max_drawdown"])
        print("\n🛡️  最大回撤排名（越小越好）:")
        for i, r in enumerate(by_dd, 1):
            print(f"  {i}. {r['strategy']:<14} 回撤={r['max_drawdown']*100:.2f}%")

    # 保存 JSON 报告
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n📄 完整报告已保存: {report_path}")

    # 也生成 HTML 报告
    html_path = report_path.with_suffix(".html")
    _generate_html_report(report, html_path)
    print(f"🌐 HTML 报告: {html_path}")

    print("\n✅ 多策略回测对比完成！")


def _generate_html_report(report: dict, path: Path):
    """生成可读性更好的 HTML 对比报告"""
    results = [r for r in report["results"] if "error" not in r]
    config = report["config"]

    rows = ""
    for r in sorted(results, key=lambda x: x["sharpe_ratio"], reverse=True):
        rows += f"""
        <tr>
            <td><strong>{r['strategy']}</strong></td>
            <td class="num {'pos' if r['annual_return']>=0 else 'neg'}">{r['annual_return']*100:+.2f}%</td>
            <td class="num">{r['sharpe_ratio']:.2f}</td>
            <td class="num">{r['sortino_ratio']:.2f}</td>
            <td class="num {'neg' if r['max_drawdown']<0 else ''}">{r['max_drawdown']*100:.2f}%</td>
            <td class="num">{r['total_return']*100:+.2f}%</td>
            <td class="num">{r['volatility']*100:.2f}%</td>
            <td class="num">{r['total_trades']}</td>
            <td class="num">{r['win_rate']*100:.1f}%</td>
            <td class="num">{r['profit_factor']:.2f}</td>
            <td class="num">{r['calmar_ratio']:.2f}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>QTS 多策略回测对比报告</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #0f1117; color: #e1e4e8; }}
h1 {{ color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 12px; }}
.summary {{ background: #161b22; border-radius: 8px; padding: 16px; margin: 16px 0; border: 1px solid #30363d; }}
.summary span {{ margin-right: 24px; }}
table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
th {{ background: #1c2333; color: #8b949e; padding: 10px 12px; text-align: right; font-size: 13px; border-bottom: 2px solid #30363d; }}
th:first-child {{ text-align: left; }}
td {{ padding: 10px 12px; text-align: right; border-bottom: 1px solid #21262d; font-size: 14px; }}
td:first-child {{ text-align: left; font-weight: 500; }}
.num {{ font-family: 'SF Mono', 'Fira Code', monospace; }}
.pos {{ color: #3fb950; }}
.neg {{ color: #f85149; }}
.rank {{ text-align: center !important; }}
.rank-1 {{ color: #f0c000; font-weight: bold; }}
.rank-2 {{ color: #a0a0c0; font-weight: bold; }}
.rank-3 {{ color: #cd853f; font-weight: bold; }}
.footer {{ margin-top: 24px; color: #8b949e; font-size: 12px; text-align: center; }}
</style>
</head>
<body>
<h1>📊 QTS 多策略回测对比报告</h1>
<div class="summary">
    <span>📈 标的: <strong>{config['ts_code']}</strong></span>
    <span>📅 期间: <strong>{config['start_date']} ~ {config['end_date']}</strong></span>
    <span>💰 资金: <strong>{config['initial_cash']:,.0f}</strong></span>
    <span>🎯 策略数: <strong>{len(results)}</strong></span>
</div>
<table>
<thead>
<tr>
    <th>策略</th>
    <th>年化收益</th>
    <th>夏普比率</th>
    <th>Sortino</th>
    <th>最大回撤</th>
    <th>总收益率</th>
    <th>波动率</th>
    <th>交易次数</th>
    <th>胜率</th>
    <th>盈亏比</th>
    <th>Calmar</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
<div class="footer">生成时间: {report['generated_at']} | QTS Backtest Engine v2</div>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()
