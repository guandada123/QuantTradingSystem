"""
VWM 策略回测 HTML 报告生成器

用法:
  python3 bt_report.py 600498.SH          # 单只股票
  python3 bt_report.py 002049.SZ,000725.SZ  # 多只批量

输出:
  output/bt_report_{ts_code}.html
"""
import json
import sys
import os
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app")

from services.backtest_engine_v2 import EnhancedBacktestEngine, BacktestConfig


def fmt_pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def fmt_num(v: float, d: int = 2) -> str:
    return f"{v:.{d}f}"


def backtest_stock(ts_code: str, name: str = "", strategy: str = "vwm") -> dict:
    """运行单只股票回测，返回详细的回测数据"""
    config = BacktestConfig(
        ts_codes=[ts_code],
        strategies=[strategy],
        start_date="20250601",
        end_date="20260617",
        initial_cash=100000,
    )
    engine = EnhancedBacktestEngine(config)

    # 获取行情数据（用于图表）
    market_data = engine.fetch_market_data(ts_code, config.start_date, config.end_date)

    # 运行回测
    result = engine.run()

    # 提取 equity curve
    equity_curve = []
    for dv in engine.daily_values:
        equity_curve.append({
            "date": dv["date"],
            "nav": round(dv["nav"], 6),
            "value": round(dv["value"], 2),
            "drawdown": round(dv.get("drawdown", 0), 6),
            "benchmark": round(dv.get("benchmark_nav", 1.0), 6),
        })

    trades = []
    for t in result.trades:
        t_dict = {
            "date": t.date,
            "direction": t.direction,
            "price": round(t.price, 2),
            "qty": t.quantity,
            "amount": round(t.amount, 2),
        }
        if hasattr(t, "pnl") and t.pnl is not None:
            t_dict["pnl"] = round(t.pnl, 2)
        if hasattr(t, "hold_days"):
            t_dict["hold_days"] = t.hold_days
        trades.append(t_dict)

    return {
        "ts_code": ts_code,
        "name": name or ts_code,
        "strategy": strategy,
        "metrics": {
            "total_return": fmt_pct(result.total_return),
            "total_return_raw": result.total_return,
            "annual_return": fmt_pct(result.annual_return),
            "sharpe": fmt_num(result.sharpe_ratio, 3),
            "max_drawdown": fmt_pct(result.max_drawdown),
            "max_dd_raw": result.max_drawdown,
            "total_trades": result.total_trades,
            "win_rate": fmt_pct(result.win_rate),
            "profit_loss_ratio": fmt_num(result.profit_factor, 2),
            "avg_hold_days": fmt_num(result.avg_hold_days, 1),
            "initial_cash": config.initial_cash,
            "final_value": round(equity_curve[-1]["value"], 2) if equity_curve else 0,
        },
        "equity_curve": equity_curve,
        "trades": trades,
    }


def generate_html(data: dict) -> str:
    """生成回测报告 HTML"""
    m = data["metrics"]
    eq = data["equity_curve"]
    tds = data["trades"]
    ts_code = data["ts_code"]
    name = data["name"]

    # 净值数据 JSON 行（避免 HTML 中的特殊字符问题）
    eq_json = json.dumps(eq, ensure_ascii=False)
    trades_json = json.dumps(tds, ensure_ascii=False)

    # 交易水平线条
    trade_lines = ""
    for t in tds:
        c = "#22c55e" if t["direction"] == "BUY" else "#ef4444"
        pnl_str = f' ({t.get("pnl", 0):+.0f})' if t.get("pnl") else ""
        trade_lines += (
            f"  {{x: '{t['date']}', y: {t['price']}, direction: '{t['direction']}', "
            f"qty: {t['qty']}, pnl: '{pnl_str}'}},"
        )

    # 交易行
    trade_rows = []
    for t in tds:
        direction = 'buy' if t['direction'] == 'BUY' else 'sell'
        pnl = f'{t["pnl"]:+.0f}' if t.get('pnl') else '-'
        hd = t.get('hold_days', '-')
        trade_rows.append(
            f'<tr><td>{t["date"]}</td><td class="{direction}">{t["direction"]}</td>'
            f'<td>{t["price"]:.2f}</td><td>{t["qty"]}</td><td>{t["amount"]:.0f}</td>'
            f'<td>{pnl}</td><td>{hd}</td></tr>'
        )
    trade_html = "".join(trade_rows) if trade_rows else '<tr><td colspan="7" class="empty">No trades executed</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BT Report — {name} ({ts_code})</title>
<script src="https://cdn.jsdelivr.net/npm/apexcharts@5.15.0/dist/apexcharts.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif;
  background: #f8fafc; color: #1e293b; padding: 24px;
}}
h1 {{ font-size: 20px; font-weight: 600; margin-bottom: 4px; }}
.subtitle {{ color: #64748b; font-size: 13px; margin-bottom: 20px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }}
.card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; }}
.card .label {{ font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}
.card .value {{ font-size: 18px; font-weight: 600; margin-top: 4px; }}
.card .value.positive {{ color: #16a34a; }}
.card .value.negative {{ color: #dc2626; }}
.card .value.neutral {{ color: #1e293b; }}
.chart-container {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; margin-bottom: 16px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ text-align: left; padding: 10px 12px; border-bottom: 2px solid #e2e8f0; color: #64748b; font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
td {{ padding: 8px 12px; border-bottom: 1px solid #f1f5f9; }}
tr:hover td {{ background: #f8fafc; }}
.buy {{ color: #16a34a; font-weight: 500; }}
.sell {{ color: #dc2626; font-weight: 500; }}
.empty {{ color: #94a3b8; text-align: center; padding: 40px; font-size: 14px; }}
</style>
</head>
<body>

<h1>{name} <span style="color:#64748b;font-weight:400;">{ts_code}</span></h1>
<p class="subtitle">VWM 策略 · 2025-06-01 → 2026-06-17 · 个股优化参数</p>

<div class="grid">
  <div class="card"><div class="label">Total Return</div><div class="value {'positive' if m['total_return_raw'] >= 0 else 'negative'}">{m['total_return']}</div></div>
  <div class="card"><div class="label">Annual Return</div><div class="value {'positive' if m['total_return_raw'] >= 0 else 'negative'}">{m['annual_return']}</div></div>
  <div class="card"><div class="label">Sharpe Ratio</div><div class="value neutral">{m['sharpe']}</div></div>
  <div class="card"><div class="label">Max Drawdown</div><div class="value negative">{m['max_drawdown']}</div></div>
  <div class="card"><div class="label">Win Rate</div><div class="value neutral">{m['win_rate']}</div></div>
  <div class="card"><div class="label">Total Trades</div><div class="value neutral">{m['total_trades']}</div></div>
  <div class="card"><div class="label">Profit Factor</div><div class="value neutral">{m['profit_loss_ratio']}</div></div>
  <div class="card"><div class="label">Avg Hold Days</div><div class="value neutral">{m['avg_hold_days']}</div></div>
  <div class="card"><div class="label">Initial / Final</div><div class="value neutral" style="font-size:14px;">¥{m['initial_cash']:,.0f} → ¥{m['final_value']:,.0f}</div></div>
</div>

<div class="chart-container">
  <div id="equityChart" style="height:360px;"></div>
</div>

<div class="chart-container">
  <h3 style="font-size:14px;font-weight:500;margin-bottom:12px;">Trade Log ({len(tds)} 笔)</h3>
  <table>
    <thead><tr><th>Date</th><th>Direction</th><th>Price</th><th>Qty</th><th>Amount</th><th>PnL</th><th>Hold Days</th></tr></thead>
    <tbody>
      {trade_html}
    </tbody>
  </table>
</div>

<script>
(function() {{
  var eq = {eq_json};
  var dates = eq.map(function(d) {{ return d.date; }});
  var nav = eq.map(function(d) {{ return d.nav; }});
  var bm = eq.map(function(d) {{ return d.benchmark; }});
  var dd = eq.map(function(d) {{ return d.drawdown * 100; }});

  new ApexCharts(document.getElementById('equityChart'), {{
    series: [
      {{ name: 'Strategy (VWM)', type: 'line', data: nav }},
      {{ name: 'Benchmark', type: 'line', data: bm }},
    ],
    chart: {{ height: 360, toolbar: {{ show: false }}, background: 'transparent' }},
    colors: ['#3b82f6', '#94a3b8'],
    stroke: {{ width: [2, 1.5], curve: 'smooth', dashArray: [0, 5] }},
    xaxis: {{ type: 'datetime', categories: dates, labels: {{ format: 'MM/dd', style: {{ fontSize: '11px' }} }} }},
    yaxis: {{
      labels: {{ formatter: function(v) {{ return v.toFixed(2); }}, style: {{ fontSize: '11px' }} }},
      title: {{ text: 'NAV' }}
    }},
    grid: {{ borderColor: '#f1f5f9' }},
    legend: {{ position: 'top', horizontalAlign: 'left', fontSize: '12px' }},
    tooltip: {{ shared: true, x: {{ format: 'yyyy-MM-dd' }} }},
    annotations: {{
      yaxis: [{{ y: 1.0, borderColor: '#f1f5f9', strokeDashArray: 2, label: {{ text: 'Break Even' }} }}],
      points: [{trade_lines}]
    }}
  }}).render();
}})();
</script>
</body>
</html>"""


def main():
    args = sys.argv[1] if len(sys.argv) > 1 else "002049.SZ"
    codes = [c.strip() for c in args.split(",")]

    name_map = {
        "002049.SZ": "紫光国微", "601899.SH": "紫金矿业", "002601.SZ": "龙佰集团",
        "600498.SH": "烽火通信", "600522.SH": "中天科技", "600206.SH": "有研新材",
        "000725.SZ": "京东方A", "002415.SZ": "海康威视", "600276.SH": "恒瑞医药",
        "600570.SH": "恒生电子", "688981.SH": "中芯国际", "300750.SZ": "宁德时代",
        "600519.SH": "贵州茅台", "000858.SZ": "五粮液", "600036.SH": "招商银行",
        "601318.SH": "中国平安", "000333.SZ": "美的集团", "600887.SH": "伊利股份",
        "000001.SZ": "平安银行", "600585.SH": "海螺水泥", "600893.SH": "航发动力",
        "002230.SZ": "科大讯飞",
    }

    out_dir = Path("/app/output")
    out_dir.mkdir(exist_ok=True)

    for code in codes:
        name = name_map.get(code, code)
        print(f"  {name:8s} {code:10s} 回测中...", end=" ", flush=True)
        data = backtest_stock(code, name)
        html = generate_html(data)
        out_path = out_dir / f"bt_report_{code.replace('.', '_')}.html"
        out_path.write_text(html, encoding="utf-8")
        m = data["metrics"]
        print(f"回测完成: {m['total_return']} | Sharpe={m['sharpe']} | {m['total_trades']} 笔交易")
        print(f"    报告: {out_path}")


if __name__ == "__main__":
    main()
