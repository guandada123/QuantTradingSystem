#!/usr/bin/env python3
"""
科技股全策略回测对比
覆盖当前主流 A 股科技标的 × 全部 11 个策略
生成矩阵报告和排名
"""

from datetime import datetime
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

API_BASE = "http://localhost:8000/api/v1/backtest"
REPORTS_DIR = Path("/tmp") / "quant_reports"

# 科技股清单（覆盖主要细分赛道，排除 300/688以避免数据问题）
TECH_STOCKS = [
    # 股票代码      名称           细分赛道
    ("002371.SZ", "北方华创",   "半导体设备"),
    ("603501.SH", "韦尔股份",   "芯片设计"),
    ("600570.SH", "恒生电子",   "金融科技"),
    ("002415.SZ", "海康威视",   "AI安防/视觉"),
    ("002230.SZ", "科大讯飞",   "AI语音/大模型"),
    ("000063.SZ", "中兴通讯",   "通信/AI算力"),
    ("600588.SH", "用友网络",   "企业软件/AI"),
    ("600845.SH", "宝信软件",   "工业互联网"),
]

# 基准指数
BENCHMARK = "000300.SH"

# 所有策略及其默认参数（与 multi_strategy_backtest.py 对齐）
ALL_STRATEGIES = [
    {"strategy": "ma-cross", "params": {"ma_fast": 10, "ma_slow": 30}},
    {"strategy": "breakout", "params": {"lookback": 20}},
    {"strategy": "rsi", "params": {"period": 14, "oversold": 30, "overbought": 70}},
    {"strategy": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}},
    {"strategy": "kdj", "params": {"period": 9, "k_smooth": 3, "d_smooth": 3}},
    {"strategy": "vwm", "params": {"ma_fast": 5, "ma_slow": 20, "vol_multiplier_buy": 1.0}},
    {"strategy": "bollinger", "params": {"period": 20, "std_mult": 2.0}},
    {"strategy": "adx", "params": {"period": 14, "adx_threshold": 22}},
    {"strategy": "obv", "params": {"lookback": 20, "obv_period": 20}},
    {"strategy": "vbm", "params": {"roc_period": 5, "vol_mult": 1.2, "roc_threshold": 0.03}},
    {"strategy": "vpb", "params": {
        "event_lookback": 20, "vol_surge_mult": 1.5,
        "breakout_lookback": 15, "confirm_bars": 1,
        "max_hold_days": 15, "atr_mult_stop": 2.0,
        "use_enhanced_exits": True,
        "trailing_stop_pct": 0.06,
        "take_profit_pct": 0.15,
    }},
]

START_DATE = "2025-01-01"
END_DATE = "2026-06-18"
INITIAL_CASH = 1000000.0


def wait_for_service(url: str, max_retries: int = 15, interval: int = 2):
    """等待服务就绪"""
    print(f"⏳ 等待服务就绪: {url} ...")
    for i in range(max_retries):
        try:
            resp = urllib.request.urlopen(url, timeout=3)
            if resp.status == 200:
                print("✅ 服务就绪")
                return True
        except Exception:
            pass
        time.sleep(interval)
    print("❌ 服务未就绪")
    return False


def run_stock_backtest(ts_code: str, strategies_list: list) -> dict | None:
    """调用 API 对一只股票运行全策略回测"""
    payload = {
        "ts_code": ts_code,
        "strategies": [s["strategy"] for s in strategies_list],
        "start_date": START_DATE,
        "end_date": END_DATE,
        "initial_cash": INITIAL_CASH,
        "benchmark": BENCHMARK,
        # 每个策略的自定义参数通过各策略的 params 传入（API 会将 params 统一传给所有策略）
        # 注意：当多个策略有不同的 params 时，API 会将 params 按策略名分组
        # 这里我们使用统一 params，各策略将使用其内置默认值
        "params": {},
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
        print(f"  ❌ API 调用失败: {e}")
        return None


def extract_metrics(result: dict) -> dict:
    """从 API 返回值提取关键指标"""
    if not result or not result.get("success"):
        return {"error": result.get("error", "无响应") if result else "无响应"}
    data = result.get("data", {}) or {}
    results_list = data.get("results", [])
    if not results_list:
        return {"error": "无回测结果"}
    # 取第一个策略的结果
    r = results_list[0]
    metrics = r.get("metrics", {}) or r if r else {}
    return {
        "annual_return": metrics.get("annual_return", 0),
        "sharpe_ratio": metrics.get("sharpe_ratio", 0),
        "sortino_ratio": metrics.get("sortino_ratio", 0),
        "max_drawdown": metrics.get("max_drawdown", 0),
        "total_return": metrics.get("total_return", 0),
        "volatility": metrics.get("volatility", 0),
        "total_trades": metrics.get("total_trades", 0),
        "win_rate": metrics.get("win_rate", 0),
        "profit_factor": metrics.get("profit_factor", 0),
        "calmar_ratio": metrics.get("calmar_ratio", 0),
    }


def main():
    print("=" * 75)
    print("📊 A股科技股全策略回测对比")
    print(f"   科技股数: {len(TECH_STOCKS)}  |  策略数: {len(ALL_STRATEGIES)}")
    print(f"   期间: {START_DATE} ~ {END_DATE}")
    print(f"   初始资金: {INITIAL_CASH:,.0f}")
    print("=" * 75)

    if not wait_for_service(f"{API_BASE}/status"):
        sys.exit(1)

    # 矩阵存储: matrix[stock_code][strategy_name] = metrics
    matrix: dict[str, dict] = {}

    for ts_code, name, sector in TECH_STOCKS:
        print(f"\n{'─' * 75}")
        print(f"🚀 [{name}] {ts_code} ({sector}) — 运行 {len(ALL_STRATEGIES)} 个策略...")
        start_t = time.time()

        result = run_stock_backtest(ts_code, ALL_STRATEGIES)
        if not result or not result.get("success"):
            print(f"  ❌ [{name}] 回测失败: {result.get('error', '未知') if result else '无响应'}")
            matrix[ts_code] = {"_meta": {"name": name, "sector": sector, "error": True}}
            continue

        # API 多策略结果在 comparison 字段
        results_list = result.get("comparison", [])
        # 如果只有单一策略结果，包装成列表
        if not results_list and result.get("data"):
            results_list = [result["data"]]
        elapsed = time.time() - start_t

        print(f"  [{name}] ⏱ {elapsed:.0f}s | 返回 {len(results_list)} 个策略结果")

        stock_results: dict = {"_meta": {"name": name, "sector": sector, "elapsed": elapsed}}
        errors = 0

        for r in results_list:
            sname = r.get("strategy", "?")
            metrics = r.get("metrics", {}) or r
            if "error" in r or not metrics.get("total_trades") and metrics.get("total_trades") != 0:
                is_err = r.get("error", "?")
                stock_results[sname] = {"error": is_err}
                errors += 1
                print(f"    ⚠️  {sname:<14} ❌ {is_err}")
                continue

            record = {
                "annual_return": metrics.get("annual_return", 0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "sortino_ratio": metrics.get("sortino_ratio", 0),
                "max_drawdown": metrics.get("max_drawdown", 0),
                "total_return": metrics.get("total_return", 0),
                "volatility": metrics.get("volatility", 0),
                "total_trades": metrics.get("total_trades", 0),
                "win_rate": metrics.get("win_rate", 0),
                "profit_factor": metrics.get("profit_factor", 0),
                "calmar_ratio": metrics.get("calmar_ratio", 0),
            }
            stock_results[sname] = record

            ar = record["annual_return"]
            sr = record["sharpe_ratio"]
            dd = record["max_drawdown"]
            trades = record["total_trades"]
            wr = record["win_rate"]
            ar_str = f"{ar*100:+6.2f}%"
            sr_str = f"{sr:>6.2f}"
            dd_str = f"{dd*100:>6.2f}%"
            print(f"    {sname:<14} 年化{ar_str} 夏普{sr_str} 回撤{dd_str} 交易{trades:>3} 胜率{wr*100:>4.1f}%")

        if errors:
            print(f"    ⚠️  {errors}/{len(ALL_STRATEGIES)} 策略失败")
        matrix[ts_code] = stock_results

    # ─── 生成综合报告 ───
    print("\n" + "=" * 75)
    print("📈 科技股全策略回测综合报告")
    print("=" * 75)

    # 1. 按股票列出夏普排名
    print("\n" + "─" * 75)
    print("🏆 各科技股最佳策略（按夏普比率）")
    print("─" * 75)
    for ts_code, name, sector in TECH_STOCKS:
        stock_data = matrix.get(ts_code, {})
        if stock_data.get("_meta", {}).get("error"):
            print(f"  ❌ {name} ({sector}) — 回测失败")
            continue
        valid = [(s, m) for s, m in stock_data.items() if s != "_meta" and "error" not in m and m.get("total_trades", 0) > 0]
        if not valid:
            print(f"  ⚠️  {name} ({sector}) — 无有效策略")
            continue
        valid.sort(key=lambda x: x[1]["sharpe_ratio"], reverse=True)
        top3 = valid[:3]
        print(f"\n  🥇 {name} ({sector})")
        for rank, (sname, m) in enumerate(top3, 1):
            print(f"    {'🥇🥈🥉'[rank-1]} {sname:<14} Sharpe={m['sharpe_ratio']:.2f}  年化={m['annual_return']*100:+.2f}%  回撤={m['max_drawdown']*100:.2f}%")
        # 最差表现（选 trade >= 5 的）
        bad = [x for x in valid if x[1].get("total_trades", 0) >= 5]
        if bad:
            bad.sort(key=lambda x: x[1]["sharpe_ratio"])
            worst = bad[0]
            print(f"    💀 最差: {worst[0]:<14} Sharpe={worst[1]['sharpe_ratio']:.2f}  年化={worst[1]['annual_return']*100:+.2f}%")

    # 2. 策略跨股票综合排名
    print("\n" + "─" * 75)
    print("📊 各策略跨科技股综合表现（按平均夏普排名）")
    print("─" * 75)

    # 收集每个策略在所有股票上的表现
    strategy_cross: dict[str, list] = {}
    for ts_code, stock_data in matrix.items():
        if stock_data.get("_meta", {}).get("error"):
            continue
        for sname, metrics in stock_data.items():
            if sname == "_meta" or "error" in metrics:
                continue
            if metrics.get("total_trades", 0) == 0:
                continue
            strategy_cross.setdefault(sname, []).append(metrics)

    # 按平均夏普排名
    strategy_avg = []
    for sname, mlist in strategy_cross.items():
        avg_sharpe = sum(m["sharpe_ratio"] for m in mlist) / len(mlist)
        avg_return = sum(m["annual_return"] for m in mlist) / len(mlist)
        avg_dd = sum(m["max_drawdown"] for m in mlist) / len(mlist)
        avg_win_rate = sum(m["win_rate"] for m in mlist) / len(mlist)
        avg_pf = sum(m["profit_factor"] for m in mlist) / len(mlist)
        n_stocks = len(mlist)
        strategy_avg.append((sname, avg_sharpe, avg_return, avg_dd, avg_win_rate, avg_pf, n_stocks))

    strategy_avg.sort(key=lambda x: x[1], reverse=True)

    header = f"{'排名':>4} {'策略':<14} {'平均夏普':<10} {'平均年化':<12} {'平均回撤':<12} {'平均胜率':<10} {'盈亏比':<10} {'覆盖':<6}"
    print(header)
    print("-" * 80)
    for i, (sname, asr, aar, add, awr, apf, n) in enumerate(strategy_avg, 1):
        print(f"{i:>4} {sname:<14} {asr:>8.2f}   {aar*100:>+7.2f}%   {add*100:>7.2f}%   {awr*100:>6.1f}%   {apf:>8.2f}  {n}/{len(TECH_STOCKS)}")

    print("-" * 80)

    # 3. VPB 在科技股上的专项表现
    print("\n" + "─" * 75)
    print("🎯 VPB 量价事件突破 — 科技股专项表现")
    print("─" * 75)
    print(f"{'股票':<16} {'年化收益':<12} {'夏普':<8} {'回撤':<10} {'交易':<6} {'胜率':<8} {'盈亏比':<8}")
    print("-" * 68)
    for ts_code, name, sector in TECH_STOCKS:
        stock_data = matrix.get(ts_code, {})
        vpb = stock_data.get("vpb", {})
        if "error" in vpb:
            print(f"{name:<16} ❌ {vpb['error']}")
            continue
        if not vpb.get("total_trades"):
            print(f"{name:<16} 无信号触发")
            continue
        print(f"{name:<16} "
              f"{vpb['annual_return']*100:+7.2f}%  "
              f"{vpb['sharpe_ratio']:<8.2f} "
              f"{vpb['max_drawdown']*100:<7.2f}%  "
              f"{vpb['total_trades']:<6} "
              f"{vpb['win_rate']*100:<7.1f}% "
              f"{vpb['profit_factor']:<8.2f}")

    # ─── 保存 JSON 报告 ───
    report_path = REPORTS_DIR / "tech_stock_full_report.json"

    # 构建序列化友好的报告
    serializable_matrix = {}
    for ts_code, stock_data in matrix.items():
        serializable_matrix[ts_code] = {}
        for key, val in stock_data.items():
            if isinstance(val, dict):
                serializable_matrix[ts_code][key] = {k: v for k, v in val.items() if not isinstance(v, Exception)}
            else:
                serializable_matrix[ts_code][key] = val

    report = {
        "generated_at": datetime.now().isoformat(),
        "config": {
            "start_date": START_DATE,
            "end_date": END_DATE,
            "initial_cash": INITIAL_CASH,
            "benchmark": BENCHMARK,
            "stocks": [{"ts_code": c, "name": n, "sector": s} for c, n, s in TECH_STOCKS],
            "strategies": [s["strategy"] for s in ALL_STRATEGIES],
        },
        "strategy_cross_rank": [
            {"rank": i, "strategy": s, "avg_sharpe": round(asr, 4),
             "avg_annual_return": round(aar, 4), "avg_max_drawdown": round(add, 4),
             "avg_win_rate": round(awr, 4), "avg_profit_factor": round(apf, 4),
             "coverage": f"{n}/{len(TECH_STOCKS)}"}
            for i, (s, asr, aar, add, awr, apf, n) in enumerate(strategy_avg, 1)
        ],
        "matrix": serializable_matrix,
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n📄 完整报告已保存: {report_path}")

    # HTML 报告
    html_path = report_path.with_suffix(".html")
    _generate_html_report(report, html_path)
    print(f"🌐 HTML 报告: {html_path}")
    print("\n✅ 科技股全策略回测完成！")


def _generate_html_report(report: dict, path: Path):
    """生成 HTML 综合报告"""
    config = report["config"]
    stocks = config["stocks"]
    strategy_names = config["strategies"]

    # 构建矩阵表
    matrix = report.get("matrix", {})
    stock_names = {s["ts_code"]: s["name"] for s in stocks}

    # 策略跨股票排名表
    rank_rows = ""
    for r in report.get("strategy_cross_rank", []):
        rank_rows += f"""
        <tr>
            <td class="rank">{r['rank']}</td>
            <td><strong>{r['strategy']}</strong></td>
            <td class="num">{r['avg_sharpe']:.2f}</td>
            <td class="num {'pos' if r['avg_annual_return']>=0 else 'neg'}">{r['avg_annual_return']*100:+.2f}%</td>
            <td class="num neg">{r['avg_max_drawdown']*100:.2f}%</td>
            <td class="num">{r['avg_win_rate']*100:.1f}%</td>
            <td class="num">{r['avg_profit_factor']:.2f}</td>
            <td class="num">{r['coverage']}</td>
        </tr>"""

    # 每个股票一个卡片
    stock_cards = ""
    for ts_code, name, sector in stocks:
        sd = matrix.get(ts_code, {})
        if sd.get("_meta", {}).get("error"):
            stock_cards += f"""
            <div class="stock-card">
                <h3>❌ {name} <span class="sector">{sector}</span></h3>
                <p class="error">回测失败</p>
            </div>"""
            continue

        rows = ""
        for sn in strategy_names:
            m = sd.get(sn, {})
            if "error" in m:
                rows += f"<tr><td>{sn}</td><td class='error' colspan='6'>❌ {m['error']}</td></tr>"
                continue
            if not m.get("total_trades"):
                rows += f"<tr><td>{sn}</td><td class='no-data' colspan='6'>— 无交易 —</td></tr>"
                continue
            ar_class = "pos" if m.get("annual_return", 0) >= 0 else "neg"
            rows += f"""
            <tr>
                <td>{sn}</td>
                <td class="num {ar_class}">{m.get('annual_return', 0)*100:+.2f}%</td>
                <td class="num">{m.get('sharpe_ratio', 0):.2f}</td>
                <td class="num neg">{m.get('max_drawdown', 0)*100:.2f}%</td>
                <td class="num">{m.get('total_trades', 0)}</td>
                <td class="num">{m.get('win_rate', 0)*100:.1f}%</td>
                <td class="num">{m.get('profit_factor', 0):.2f}</td>
            </tr>"""

        stock_cards += f"""
        <div class="stock-card">
            <h3>{name} <span class="sector">{sector}</span> <span class="code">{ts_code}</span></h3>
            <table>
                <thead><tr>
                    <th>策略</th><th>年化收益</th><th>夏普</th><th>最大回撤</th><th>交易</th><th>胜率</th><th>盈亏比</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>A股科技股全策略回测对比报告</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 1400px; margin: 0 auto; padding: 20px; background: #0f1117; color: #e1e4e8; }}
h1 {{ color: #58a6ff; border-bottom: 2px solid #30363d; padding-bottom: 12px; }}
h2 {{ color: #c9d1d9; margin-top: 30px; }}
.summary {{ background: #161b22; border-radius: 12px; padding: 20px; margin: 16px 0; border: 1px solid #30363d; line-height: 1.6; }}
.summary span {{ margin-right: 28px; color: #8b949e; }}
.summary strong {{ color: #e1e4e8; }}
table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px; }}
th {{ background: #1c2333; color: #8b949e; padding: 10px 12px; text-align: right; border-bottom: 2px solid #30363d; white-space: nowrap; }}
th:first-child {{ text-align: left; }}
td {{ padding: 8px 12px; text-align: right; border-bottom: 1px solid #21262d; }}
td:first-child {{ text-align: left; }}
.num {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; }}
.pos {{ color: #3fb950; }}
.neg {{ color: #f85149; }}
.rank {{ text-align: center; font-weight: bold; color: #8b949e; }}
.error {{ color: #f85149; text-align: center; }}
.no-data {{ color: #8b949e; text-align: center; font-style: italic; }}
.stock-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 16px 20px; margin: 16px 0; }}
.stock-card h3 {{ margin: 0 0 12px 0; color: #c9d1d9; }}
.sector {{ font-size: 13px; color: #8b949e; font-weight: normal; margin-left: 8px; }}
.code {{ font-family: 'SF Mono', monospace; font-size: 12px; color: #58a6ff; margin-left: 8px; }}
.footer {{ margin-top: 24px; color: #8b949e; font-size: 12px; text-align: center; padding: 16px; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; }}
.badge-1 {{ background: #f0c00020; color: #f0c000; }}
.badge-2 {{ background: #a0a0c020; color: #a0a0c0; }}
.badge-3 {{ background: #cd853f20; color: #cd853f; }}
</style>
</head>
<body>
<h1>📊 A股科技股全策略回测对比报告</h1>
<div class="summary">
    <span>📅 期间: <strong>{config['start_date']} ~ {config['end_date']}</strong></span>
    <span>📈 基准: <strong>{config['benchmark']}</strong></span>
    <span>💰 资金: <strong>{config['initial_cash']:,.0f}</strong></span>
    <span>🏢 科技股: <strong>{len(stocks)}</strong></span>
    <span>🎯 策略: <strong>{len(strategy_names)}</strong></span>
</div>

<h2>🏆 策略跨科技股综合排名（按平均夏普）</h2>
<table>
<thead><tr>
    <th>#</th><th>策略</th><th>平均夏普</th><th>平均年化</th><th>平均回撤</th><th>平均胜率</th><th>平均盈亏比</th><th>覆盖</th>
</tr></thead>
<tbody>{rank_rows}</tbody>
</table>

<h2>📋 各科技股策略详情</h2>
{stock_cards}

<div class="footer">
    生成时间: {report['generated_at']} | QuantTradingSystem Backtest Engine v2
</div>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()
