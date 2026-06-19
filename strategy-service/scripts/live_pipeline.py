"""
实盘数据管线 — 实时行情 + 策略信号生成

工作流:
  1. 读取 Claw 持仓 + 观察列表
  2. 获取实时行情（腾讯财经 API）
  3. 读取历史 K 线（Postgres daily_quote）
  4. 运行 VWM / BBR / COMBO 策略（个股优化参数）
  5. 合并信号输出 JSON

用法:
  python3 scripts/live_pipeline.py                          # 默认输出
  python3 scripts/live_pipeline.py --output /tmp/signals.json
  python3 scripts/live_pipeline.py --stocks 600498.SH,002049.SZ  # 指定股票
"""

import argparse
from datetime import date, datetime
import json
import logging
import os
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.backtest_engine_v2 import BacktestConfig, EnhancedBacktestEngine
from services.param_grids import get_stock_params
from services.signals import generate_signals
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 路径与数据库 ──
CLAW_SIM_DIR = Path("/tmp/claw_data")  # Claw simulation data mount point
_FALLBACK_SIM_DIR = Path(__file__).parent.parent.parent / "shared" / "claw_data"

_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@quant-postgres:5432/quantdb",
)
_ENGINE = None

# ── 腾讯实时行情 API ──
_TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={}"

# 策略配置
STRATEGIES = {
    "vwm": {"name": "VWM 动量", "weight": 0.6},
    "bollinger": {"name": "BBR 均值回归", "weight": 0.4},
    "combo-vwm-bbr": {"name": "COMBO 组合", "weight": 1.0},
}


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(_DATABASE_URL)
    return _ENGINE


# ============================================================
# 1. 读取 Claw 数据
# ============================================================


def read_claw_portfolio() -> dict:
    """读取 Claw 模拟盘持仓"""
    paths = [CLAW_SIM_DIR, _FALLBACK_SIM_DIR]
    for base in paths:
        f = base / "portfolio.json"
        if f.exists():
            try:
                return json.loads(f.read_text())
            except Exception:
                pass
    logger.warning("Claw portfolio.json not found, using empty")
    return {"positions": {}, "cash": 0, "config": {}}


def read_claw_watchlist() -> list:
    """读取 Claw 观察列表"""
    paths = [CLAW_SIM_DIR, _FALLBACK_SIM_DIR]
    for base in paths:
        f = base / "watchlist.json"
        if f.exists():
            try:
                return json.loads(f.read_text())
            except Exception:
                pass
    return []


def build_stock_list() -> list[dict]:
    """构建统一股票列表（持仓 + 观察列表 + 已优化参数全部）"""
    portfolio = read_claw_portfolio()
    watchlist = read_claw_watchlist()

    seen = set()
    stocks = []

    # 持仓股（优先）
    for code, info in portfolio.get("positions", {}).items():
        ts_code = f"{code}.SZ" if code.startswith("0") or code.startswith("3") else f"{code}.SH"
        if ts_code not in seen:
            seen.add(ts_code)
            stocks.append({"ts_code": ts_code, "name": info.get("name", ""), "source": "portfolio"})

    # 观察列表
    for s in watchlist:
        code = s["code"]
        ts_code = f"{code}.SZ" if code.startswith("0") or code.startswith("3") else f"{code}.SH"
        if ts_code not in seen:
            seen.add(ts_code)
            stocks.append({"ts_code": ts_code, "name": s.get("name", ""), "source": "watchlist"})

    return stocks


# ============================================================
# 2. 实时行情获取
# ============================================================


def fetch_realtime_quotes(stocks: list[dict]) -> dict:
    """批量获取实时行情（腾讯财经 qt.gtimg.cn）"""
    symbols = []
    code_map = {}
    for s in stocks:
        ts = s["ts_code"]
        code = ts.split(".")[0]
        suffix = "sz" if ts.endswith("SZ") else "sh" if ts.endswith("SH") else ""
        symbol = f"{suffix}{code}"
        symbols.append(symbol)
        code_map[symbol] = ts

    results = {}
    batch_size = 30
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        url = _TENCENT_QUOTE_URL.format(",".join(batch))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("gbk", errors="ignore")
                for line in raw.strip().split("\n"):
                    line = line.strip()
                    if not line or '="' not in line:
                        continue
                    try:
                        content = line.split('="', 1)[1]
                        if content.endswith('";'):
                            content = content[:-2]
                        fields = content.split("~")
                        if len(fields) < 40:
                            continue
                        sym = fields[0] if fields[0] else line.split("_")[0] if "_" in line else ""
                        ts_code = code_map.get(sym, "")
                        results[ts_code] = {
                            "name": fields[1],
                            "current_price": float(fields[3]) if fields[3] else 0,
                            "prev_close": float(fields[4]) if fields[4] else 0,
                            "open": float(fields[5]) if fields[5] else 0,
                            "volume": int(fields[6]) if fields[6] else 0,
                            "bid": float(fields[9]) if fields[9] else 0,
                            "ask": float(fields[10]) if fields[10] else 0,
                            "high": float(fields[33]) if fields[33] else 0,
                            "low": float(fields[34]) if fields[34] else 0,
                            "change_pct": float(fields[32]) if fields[32] else 0,
                            "amount": float(fields[37]) if fields[37] else 0,
                            "timestamp": datetime.now().isoformat(),
                        }
                    except (IndexError, ValueError):
                        continue
        except Exception as e:
            logger.warning("批量行情获取失败: %s", e)

    return results


# ============================================================
# 3. 数据库查询历史数据
# ============================================================


def fetch_history(ts_code: str) -> list[dict]:
    """从 daily_quote 获取近 100 个交易日 K 线"""
    engine = get_engine()
    code = ts_code.split(".", maxsplit=1)[0]
    suffix = ts_code.split(".")[1] if "." in ts_code else "SZ"
    query = text("""
        SELECT trade_date, open, high, low, close, volume, amount
        FROM daily_quote
        WHERE ts_code = :code AND ts_code LIKE :suffix
        ORDER BY trade_date DESC
        LIMIT 120
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"code": code, "suffix": f"%.{suffix}"}).fetchall()
    result = []
    for r in reversed(rows):
        result.append(
            {
                "trade_date": str(r[0]),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "vol": int(r[5]),
                "amount": float(r[6]),
            }
        )
    return result


# ============================================================
# 4. 策略信号生成
# ============================================================


def compute_signals(ts_code: str, history: list[dict], realtime: dict) -> dict:
    """对单只股票运行所有策略"""
    if not history:
        return {"error": "无历史数据"}

    # 将实时行情追加到历史数据末尾作为最新 K 线
    if realtime and realtime.get("current_price", 0) > 0:
        today_str = date.today().isoformat()
        last_row = history[-1]
        if last_row["trade_date"] != today_str:
            merged = history + [
                {
                    "trade_date": today_str,
                    "close": realtime["current_price"],
                    "high": max(realtime["high"], realtime["current_price"]),
                    "low": min(realtime["low"], realtime["current_price"])
                    if realtime["low"] > 0
                    else realtime["current_price"],
                    "vol": realtime.get("volume", 0),
                    "amount": realtime.get("amount", 0),
                }
            ]
        else:
            merged = history
            merged[-1]["close"] = realtime["current_price"]
            merged[-1]["vol"] = realtime.get("volume", merged[-1].get("vol", 0))
    else:
        merged = history

    if len(merged) < 60:
        return {"error": f"数据不足 ({len(merged)}天)"}

    results = {}
    # VWM
    vwm_p = get_stock_params(ts_code, "vwm") or {}
    vwm_sig = generate_signals(merged, "vwm", vwm_p)
    results["vwm"] = {
        "signal": int(vwm_sig[-1]) if vwm_sig else 0,
        "latest_buy": sum(1 for s in vwm_sig[-10:] if s == 1) if vwm_sig else 0,
        "latest_sell": sum(1 for s in vwm_sig[-10:] if s == -1) if vwm_sig else 0,
    }

    # BBR
    bbr_p = get_stock_params(ts_code, "bollinger") or {}
    bbr_sig = generate_signals(merged, "bollinger", bbr_p)
    results["bbr"] = {
        "signal": int(bbr_sig[-1]) if bbr_sig else 0,
        "latest_buy": sum(1 for s in bbr_sig[-10:] if s == 1) if bbr_sig else 0,
        "latest_sell": sum(1 for s in bbr_sig[-10:] if s == -1) if bbr_sig else 0,
    }

    # COMBO
    combo_p = {"vwm_params": vwm_p, "bbr_params": bbr_p}
    combo_sig = generate_signals(merged, "combo-vwm-bbr", combo_p)
    results["combo"] = {
        "signal": int(combo_sig[-1]) if combo_sig else 0,
        "latest_buy": sum(1 for s in combo_sig[-10:] if s == 1) if combo_sig else 0,
        "latest_sell": sum(1 for s in combo_sig[-10:] if s == -1) if combo_sig else 0,
    }

    return results


# ============================================================
# 5. 信号汇总 + 输出
# ============================================================


def signal_to_action(sig: int) -> str:
    return {1: "BUY", -1: "SELL", 0: "HOLD"}.get(sig, "HOLD")


def generate_report(stocks: list[dict], signals: dict) -> dict:
    """生成结构化信号报告"""
    total_positions = 0
    total_cash = 0
    buy_signals = []
    sell_signals = []
    portfolio_value = 0

    # Load real portfolio value
    portfolio = read_claw_portfolio()
    total_cash = portfolio.get("cash", 0)

    for s in stocks:
        ts = s["ts_code"]
        if ts not in signals or "error" in signals.get(ts, {}):
            continue
        sig_data = signals[ts]
        if isinstance(sig_data, dict) and "error" in sig_data:
            continue

        combo = sig_data.get("combo", {})
        action = signal_to_action(combo.get("signal", 0))

        entry = {
            "ts_code": ts,
            "name": s["name"],
            "source": s["source"],
            "combo_signal": action,
            "combo_confidence": abs(combo.get("signal", 0)),
            "vwm": sig_data.get("vwm", {}),
            "bbr": sig_data.get("bbr", {}),
            "realtime": sig_data.get("realtime", {}),
        }

        if action == "BUY":
            buy_signals.append(entry)
        elif action == "SELL":
            sell_signals.append(entry)

    report = {
        "generated_at": datetime.now().isoformat(),
        "trade_date": date.today().isoformat(),
        "market_status": "open" if 9 <= datetime.now().hour < 15 else "closed",
        "summary": {
            "total_stocks": len(stocks),
            "buy_signals": len(buy_signals),
            "sell_signals": len(sell_signals),
            "hold_signals": len(stocks) - len(buy_signals) - len(sell_signals),
            "portfolio_value": total_cash,
        },
        "buy": buy_signals,
        "sell": sell_signals,
        "all": [
            {
                "ts_code": s["ts_code"],
                "name": s["name"],
                "signal": signal_to_action(
                    signals.get(s["ts_code"], {}).get("combo", {}).get("signal", 0)
                ),
            }
            for s in stocks
            if s["ts_code"] in signals and "error" not in signals.get(s["ts_code"], {})
        ],
        "watchlist_only": [
            {
                "ts_code": s["ts_code"],
                "name": s["name"],
                "signal": signal_to_action(
                    signals.get(s["ts_code"], {}).get("combo", {}).get("signal", 0)
                ),
            }
            for s in stocks
            if s["source"] == "watchlist" and s["ts_code"] in signals
        ],
    }
    return report


# ============================================================
# 主入口
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="实盘数据管线 — 策略信号生成")
    parser.add_argument(
        "--output", "-o", default="/app/output/live_signals.json", help="输出 JSON 路径"
    )
    parser.add_argument(
        "--stocks", "-s", default="", help="指定股票代码（逗号分隔），为空则自动从 Claw 读取"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 1. 确定股票列表
    if args.stocks:
        stocks = []
        for code in args.stocks.split(","):
            code = code.strip()
            if not code:
                continue
            suffix = "SZ" if code.startswith("0") or code.startswith("3") else "SH"
            if "." not in code:
                code = f"{code}.{suffix}"
            stocks.append({"ts_code": code, "name": code, "source": "manual"})
        logger.info("手动指定 %d 只股票", len(stocks))
    else:
        stocks = build_stock_list()
        # 如果 Claw 数据不到，从已优化参数列表补充
        if len(stocks) < 5:
            from services.param_grids import _STOCK_PARAMS_CACHE, _ensure_stock_params_loaded

            _ensure_stock_params_loaded()
            added = 0
            for key in sorted(_STOCK_PARAMS_CACHE or {}):
                if key.startswith("vwm:"):
                    ts_code = key.split(":", 1)[1]
                    if ts_code not in {s["ts_code"] for s in stocks} and added < 15:
                        stocks.append(
                            {"ts_code": ts_code, "name": ts_code, "source": "optimized_pool"}
                        )
                        added += 1
        logger.info("自动获取 %d 只股票（持仓+观察+已优化池）", len(stocks))

    logger.info("股票列表: %s", [s["ts_code"] for s in stocks])

    # 2. 获取实时行情
    logger.info("获取实时行情...")
    quotes = fetch_realtime_quotes(stocks)
    logger.info("  成功获取 %d/%d 只", len(quotes), len(stocks))

    # 3. 获取历史数据 → 生成信号
    logger.info("生成策略信号...")
    signals = {}
    for s in stocks:
        ts = s["ts_code"]
        history = fetch_history(ts)
        if not history:
            logger.debug("  %s: 无历史数据", ts)
            continue
        sig = compute_signals(ts, history, quotes.get(ts, {}))
        sig["realtime"] = quotes.get(ts, {})
        signals[ts] = sig

        combo = sig.get("combo", {})
        action = signal_to_action(combo.get("signal", 0))
        if action != "HOLD":
            logger.info("  %s (%s): → %s", ts, s.get("name", ""), action)

    # 4. 生成报告
    report = generate_report(stocks, signals)

    # 5. 输出
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    logger.info("信号输出: %s", output_path)
    logger.info(
        "摘要: %d BUY / %d SELL / %d HOLD",
        report["summary"]["buy_signals"],
        report["summary"]["sell_signals"],
        report["summary"]["hold_signals"],
    )

    # 打印 BUY 信号
    if report["buy"]:
        print("\n🔴 BUY 信号:")
        for b in report["buy"]:
            print(f"  {b['ts_code']} {b['name']}")

    if report["sell"]:
        print("\n🟢 SELL 信号:")
        for s in report["sell"]:
            print(f"  {s['ts_code']} {s['name']}")

    # 同步到共享目录（供 Claw 消费）
    shared_dir = Path("/shared/claw_data")
    if shared_dir.exists():
        (shared_dir / "live_signals.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
        logger.info("同步到: %s/live_signals.json", shared_dir)

    return report


if __name__ == "__main__":
    main()
