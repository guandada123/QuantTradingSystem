"""COMBO 策略回测 HTML 报告生成器 — VWM + BBR + 组合对比"""

import json
import os
import sys

sys.path.insert(0, "/app")
from dataclasses import fields
from pathlib import Path

from services.backtest_engine_v2 import BacktestConfig, EnhancedBacktestEngine


def fmt_pct(v):
    return f"{v * 100:.2f}%"


def fmt_num(v, d=2):
    return f"{v:.{d}f}"


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


def bt_combo(ts_code):
    c = BacktestConfig(
        ts_codes=[ts_code],
        strategies=["combo-vwm-bbr"],
        start_date="20250601",
        end_date="20260617",
        initial_cash=100000,
    )
    return EnhancedBacktestEngine(c).run()


def bt_vwm(ts_code):
    c = BacktestConfig(
        ts_codes=[ts_code],
        strategies=["vwm"],
        start_date="20250601",
        end_date="20260617",
        initial_cash=100000,
    )
    return EnhancedBacktestEngine(c).run()


def bt_bbr(ts_code):
    c = BacktestConfig(
        ts_codes=[ts_code],
        strategies=["bollinger"],
        start_date="20250601",
        end_date="20260617",
        initial_cash=100000,
    )
    return EnhancedBacktestEngine(c).run()


def has_pnl_field(trade):
    """Check if trade record has pnl field"""
    try:
        return hasattr(trade, "pnl")
    except Exception:
        return False


def get_pnl(trade):
    try:
        return getattr(trade, "pnl", None)
    except Exception:
        return None


def gen_report(ts_codes):
    out_dir = Path("/app/output")
    out_dir.mkdir(parents=True, exist_ok=True)
    for ts_code in ts_codes.strip().split(","):
        ts_code = ts_code.strip()
        name = STOCK_NAMES.get(ts_code, ts_code)
        print(f"生成: {name} ({ts_code})...")
        rc = bt_combo(ts_code)
        rv = bt_vwm(ts_code)
        rb = bt_bbr(ts_code)
        trade_rows = ""
        trades = list(getattr(rc, "trades", []) or [])
        nav_data = []
        cash = 100000
        shares = 0
        tref = {}
        for t in trades:
            if t.direction == "BUY":
                shares += t.quantity
                cash -= t.quantity * t.price
            else:
                shares -= t.quantity
                cash += t.quantity * t.price
            nav_data.append([t.date, int(cash + shares * t.price)])
            tref[t.ts_code] = t.price
            pnl = get_pnl(t)
            pnl_s = f"¥{pnl:+.0f}" if pnl is not None else "-"
            trade_rows += f'<tr><td>{t.date}</td><td>{t.ts_code}</td><td class="{"buy" if t.direction == "BUY" else "sell"}">{t.direction}</td><td>{t.price:.2f}</td><td>{t.quantity}</td><td>{pnl_s}</td></tr>'
        if not trade_rows:
            trade_rows = '<tr><td colspan="6" class="empty">无交易记录</td></tr>'

        def mb(l, v, c=""):
            return f'<div class="card"><div class="label">{l}</div><div class="value {" " + c if c else ""}">{v}</div></div>'

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>COMBO策略回测 — {name}</title>
<script src="https://cdn.jsdelivr.net/npm/apexcharts@4"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0c121c;color:#e0e6f0;padding:24px}}
h1{{font-size:24px;margin-bottom:6px;color:#f0f4ff}}
.subtitle{{color:#8892a4;font-size:14px;margin-bottom:24px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}}
.card{{background:#141e2b;border-radius:10px;padding:14px 16px;border:1px solid #1e2a3a}}
.card .label{{font-size:11px;text-transform:uppercase;color:#6a7a8e;letter-spacing:.5px;margin-bottom:4px}}
.card .value{{font-size:20px;font-weight:700}}
.positive{{color:#22c55e}}.negative{{color:#ef4444}}
.comparison,.trades{{background:#141e2b;border-radius:10px;padding:16px;margin-bottom:24px;border:1px solid #1e2a3a}}
.comparison h3,.trades h3{{font-size:14px;color:#8892a4;margin-bottom:12px}}
.comparison table,.trades table{{width:100%;border-collapse:collapse;font-size:13px}}
.comparison th,.trades th{{text-align:left;padding:8px 12px;border-bottom:1px solid #1e2a3a;color:#6a7a8e;font-weight:500}}
.comparison td,.trades td{{padding:8px 12px;border-bottom:1px solid #141e2b;font-variant-numeric:tabular-nums}}
.comparison tr:last-child td,.trades tr:last-child td{{border:none}}
.buy{{color:#22c55e;font-weight:600}}.sell{{color:#ef4444;font-weight:600}}
.empty{{text-align:center;color:#6a7a8e;padding:24px}}
#navChart{{margin-bottom:24px}}
</style></head>
<body>
<h1>📊 组合策略回测 — {name}</h1>
<div class="subtitle">{ts_code} · 2025-06-01 → 2026-06-17</div>
<div id="navChart"></div>
<div class="metrics">
{mb("COMBO总收益", fmt_pct(rc.total_return), "positive" if rc.total_return > 0 else "negative")}
{mb("COMBO夏普", fmt_num(rc.sharpe_ratio, 3))}
{mb("最大回撤", fmt_pct(rc.max_drawdown))}
{mb("交易次数", str(rc.total_trades))}
{mb("胜率", fmt_pct(rc.win_rate))}
</div>
<div class="comparison">
<h3>三策略对比</h3>
<table><tr><th>指标</th><th>VWM趋势</th><th>BBR均值回归</th><th>COMBO组合</th></tr>
<tr><td>总收益率</td><td class="{"positive" if rv.total_return >= 0 else "negative"}">{fmt_pct(rv.total_return)}</td><td class="{"positive" if rb.total_return >= 0 else "negative"}">{fmt_pct(rb.total_return)}</td><td class="{"positive" if rc.total_return >= 0 else "negative"}">{fmt_pct(rc.total_return)}</td></tr>
<tr><td>夏普</td><td>{fmt_num(rv.sharpe_ratio, 3)}</td><td>{fmt_num(rb.sharpe_ratio, 3)}</td><td>{fmt_num(rc.sharpe_ratio, 3)}</td></tr>
<tr><td>最大回撤</td><td>{fmt_pct(rv.max_drawdown)}</td><td>{fmt_pct(rb.max_drawdown)}</td><td>{fmt_pct(rc.max_drawdown)}</td></tr>
<tr><td>交易次数</td><td>{rv.total_trades}</td><td>{rb.total_trades}</td><td>{rc.total_trades}</td></tr>
<tr><td>胜率</td><td>{fmt_pct(rv.win_rate)}</td><td>{fmt_pct(rb.win_rate)}</td><td>{fmt_pct(rc.win_rate)}</td></tr>
<tr><td>年化收益</td><td>{fmt_pct(rv.annual_return)}</td><td>{fmt_pct(rb.annual_return)}</td><td>{fmt_pct(rc.annual_return)}</td></tr>
</table></div>
<div class="trades">
<h3>COMBO交易明细</h3>
<table><thead><tr><th>日期</th><th>代码</th><th>方向</th><th>价格</th><th>数量</th><th>盈亏</th></tr></thead>
<tbody>{trade_rows}</tbody></table></div>
<script>
const navData = {json.dumps(nav_data)};
new ApexCharts(document.querySelector('#navChart'),{{
  series:[{{name:'COMBO净值',data:navData.map(d=>({{x:d[0],y:d[1]}}))}}],
  chart:{{type:'area',height:280,toolbar:{{show:false}},background:'#0c121c',foreColor:'#6a7a8e'}},
  dataLabels:{{enabled:false}},
  stroke:{{curve:'smooth',width:2,colors:['#818cf8']}},
  fill:{{type:'gradient',gradient:{{shadeIntensity:1,opacityFrom:0.3,opacityTo:0,
    colorStops:[{{offset:0,color:'#818cf8',opacity:0.3}},{{offset:100,color:'#818cf8',opacity:0}}]}}}},
  xaxis:{{type:'datetime',labels:{{format:'MM-dd'}}}},
  yaxis:{{labels:{{formatter:v=>'¥'+v.toLocaleString()}}}},
  grid:{{borderColor:'#1e2a3a',strokeDashArray:3}},
  tooltip:{{theme:'dark',x:{{format:'yyyy-MM-dd'}}}},
}}).render();
</script>
</body></html>'''
        safe = ts_code.replace(".", "_")
        path = out_dir / f"bt_combo_{safe}.html"
        path.write_text(html)
        print(f"  → {path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 bt_combo_report.py 600498.SH,002049.SZ")
        sys.exit(1)
    gen_report(sys.argv[1])
