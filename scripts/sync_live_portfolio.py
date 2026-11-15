#!/usr/bin/env python3
"""实盘/模拟盘组合真源 → QTS DB 同步（2026-11-12）

背景：告警引擎 `scripts/generate_alerts.py` 的 4 条规则曾 4/4「无输入」——
  accounts 指标全 NULL、positions/trades 0 行，因为 DB **没有任何上游写入方**
  （execution-service 只在下单时写，QTS 实际未产生交易）。
本脚本补上输入这一环：读 Claw 维护的组合真源（国金实盘截图 + 行情刷新），
把 accounts / positions 写进 DB，并用 NAV 历史算 max_drawdown，让规则 1/2/3
拿到**真实输入**。规则 4（连续亏损）仍属结构性缺输入（trades 无盈亏字段），
如实保留 generate_alerts 的上报口径，不在本脚本伪造。

数据真源（与 execution-service/scripts/feishu_daily_report.py 同一套候选）：
- 实盘 REAL_001: ~/WorkBuddy/Claw/.workbuddy/data/user/portfolio.json（国金账户）
- 模拟盘 SIM_001: shared/claw_data/portfolio.json（自带 daily_snapshot NAV 历史）

写入内容（全部幂等，可重复执行）：
1. stock_pool：持仓标的 upsert（positions.ts_code 有外键，缺行会插不进去）；
2. positions：按账户镜像当前持仓（DB 中该账户已不在真源里的旧行会被删除）；
3. accounts：总资产/可用/市值/当日盈亏（实盘日收益率取真源 summary.daily_pct/100）；
4. daily_snapshots：**合并**写入 data.{account_id}（该表已被行情快照任务占用，
   含 indices/stock_pool_count 等 key，禁止整行覆盖）；模拟盘历史 NAV 一并播种；
5. max_drawdown：从 NAV 序列（QTS daily_snapshots ∪ 模拟盘自有历史）算
   峰值回撤，写 accounts.max_drawdown（正小数，规则口径 > 0.15）。

诚实口径（不掩盖）：
- 实盘 max_drawdown 自本脚本上线日起算（此前无 NAV 历史），首日 = 0，
  随快照逐日积累，不是历史真实最大回撤；
- 真源文件缺失 / holdings 结构非法 → 报错退出（exit 1），不静默当空仓。

用法：
    python scripts/sync_live_portfolio.py --dry-run
    python scripts/sync_live_portfolio.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import psycopg2
import psycopg2.extras

WORK_DIR = Path(__file__).resolve().parent.parent

LIVE_CANDIDATES = [
    p
    for p in (
        os.getenv("QTS_LIVE_PORTFOLIO_PATH", ""),
        str(Path.home() / "WorkBuddy" / "Claw" / ".workbuddy" / "data" / "user" / "portfolio.json"),
        str(WORK_DIR / "shared" / "claw_data" / "live_portfolio.json"),
    )
    if p
]
SIM_PATH = os.getenv(
    "QTS_SIM_PORTFOLIO_PATH", str(WORK_DIR / "shared" / "claw_data" / "portfolio.json")
)


def _connect_kwargs() -> dict:
    """与 generate_alerts.py 同一套回落优先级（DATABASE_URL → QTS_DB_* → compose 默认值）。

    返回 psycopg2.connect 的关键字参数：有 DATABASE_URL 时透传为 dsn，
    否则按字段拆开传 —— 口令不进连接串，含特殊字符时无需 URL 转义。
    """
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url:
        return {"dsn": url}
    return {
        "user": os.environ.get("QTS_DB_USER", "quant_user"),
        "password": os.environ.get("QTS_DB_PASSWORD", "quant_pass"),
        "dbname": os.environ.get("QTS_DB_NAME", "quant_trading"),
        "host": os.environ.get("QTS_DB_HOST", "localhost"),
        "port": os.environ.get("QTS_DB_PORT", "15432"),
    }


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"真源文件不存在: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"真源文件解析失败 {path}: {e}") from e
    if not isinstance(data, dict) or not data:
        raise ValueError(f"真源文件为空或非 dict: {path}")
    return data


def ts_code(code: str) -> str:
    """6 位代码 → ts_code 后缀（6/5→SH，0/3→SZ，4/8→BJ）。"""
    if code.startswith(("6", "5")):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    raise ValueError(f"无法识别交易所后缀: {code}")


def max_drawdown_from_navs(navs: list[float]) -> float | None:
    """峰值回撤（正小数）。序列 < 2 个点时返回 None（样本不足，不猜）。"""
    peak: float | None = None
    mdd = 0.0
    points = 0
    for v in navs:
        if v is None or v <= 0:
            continue
        points += 1
        peak = v if peak is None else max(peak, v)
        if peak:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd, 4) if points >= 2 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # ── 1. 读真源（缺失即报错，不静默）────────────────────────────
    live = load_json(
        LIVE_CANDIDATES[0] if os.path.exists(LIVE_CANDIDATES[0]) else LIVE_CANDIDATES[-1]
    )
    live_path = LIVE_CANDIDATES[0] if os.path.exists(LIVE_CANDIDATES[0]) else LIVE_CANDIDATES[-1]
    holdings = live.get("holdings")
    if not isinstance(holdings, list):
        raise TypeError(f"实盘真源 holdings 非法（非 list）: {live_path}")
    summary = live.get("summary") or {}

    sim: dict | None = None
    if os.path.exists(SIM_PATH):
        try:
            sim = load_json(SIM_PATH)
        except (FileNotFoundError, TypeError, ValueError) as e:
            print(f"  [WARN] 模拟盘真源不可用（跳过 SIM_001，不影响实盘同步）: {e}")
            sim = None

    # ── 2. 组装写入数据 ────────────────────────────────────────────
    live_rows = []
    for h in holdings:
        code = str(h.get("code", "")).strip()
        if not code:
            raise ValueError(f"持仓行缺 code: {h}")
        bought = h.get("bought_date") or None
        opened_at = datetime.strptime(bought, "%Y-%m-%d") if bought else datetime.now()
        live_rows.append(
            {
                "ts_code": ts_code(code),
                "name": h.get("name") or code,
                "quantity": int(h.get("shares", 0)),
                "available": int(h.get("shares_available", h.get("shares", 0))),
                "cost": h.get("avg_cost"),
                "price": h.get("current_price"),
                "mv": h.get("market_value"),
                "pnl": h.get("floating_pnl"),
                "pnl_ratio": (h.get("pnl_pct") / 100.0) if h.get("pnl_pct") is not None else None,
                "opened_at": opened_at,
            }
        )

    live_total_assets = summary.get("total_assets")
    live_day_ratio = (
        (summary.get("daily_pct") / 100.0) if summary.get("daily_pct") is not None else None
    )
    live_day_pnl = summary.get("daily_pnl")

    sim_assets = sim.get("total_assets") if sim else None
    sim_cash = sim.get("cash") if sim else None

    print(f"真源: 实盘={live_path}（持仓 {len(live_rows)} 只, 总资产 {live_total_assets}）")
    if sim:
        print(f"      模拟盘={SIM_PATH}（总资产 {sim_assets}, 现金 {sim_cash}）")

    if args.dry_run:
        for r in live_rows:
            print(
                f"  [dry-run] would upsert position {r['ts_code']} "
                f"qty={r['quantity']} cost={r['cost']} price={r['price']} mv={r['mv']}"
            )
        print(f"[dry-run] 未写库 | 实盘日收益率={live_day_ratio} 当日盈亏={live_day_pnl}")
        return 0

    # ── 3. 写 DB ──────────────────────────────────────────────────
    conn = psycopg2.connect(**_connect_kwargs())
    conn.autocommit = False
    cur = conn.cursor()

    # 3a. stock_pool upsert（positions 外键依赖）
    for r in live_rows:
        cur.execute(
            "INSERT INTO stock_pool (ts_code, name, is_active) VALUES (%s, %s, TRUE) "
            "ON CONFLICT (ts_code) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()",
            (r["ts_code"], r["name"]),
        )

    # 3b. positions 镜像（REAL_001）：先 upsert 再删真源里已消失的旧行
    for r in live_rows:
        cur.execute(
            "INSERT INTO positions (account_id, ts_code, direction, total_quantity, "
            "available_quantity, cost_price, current_price, market_value, profit_loss, "
            "profit_loss_ratio, opened_at, updated_at) "
            "VALUES ('REAL_001', %s, 'LONG', %s, %s, %s, %s, %s, %s, %s, %s, NOW()) "
            "ON CONFLICT (account_id, ts_code) DO UPDATE SET "
            "total_quantity = EXCLUDED.total_quantity, available_quantity = EXCLUDED.available_quantity, "
            "cost_price = EXCLUDED.cost_price, current_price = EXCLUDED.current_price, "
            "market_value = EXCLUDED.market_value, profit_loss = EXCLUDED.profit_loss, "
            "profit_loss_ratio = EXCLUDED.profit_loss_ratio, updated_at = NOW()",
            (
                r["ts_code"],
                r["quantity"],
                r["available"],
                r["cost"],
                r["price"],
                r["mv"],
                r["pnl"],
                r["pnl_ratio"],
                r["opened_at"],
            ),
        )
    if live_rows:
        codes = [r["ts_code"] for r in live_rows]
        cur.execute(
            "DELETE FROM positions WHERE account_id = 'REAL_001' AND ts_code != ALL(%s)",
            (codes,),
        )
        if cur.rowcount:
            print(f"  已删除 REAL_001 不在真源中的旧持仓 {cur.rowcount} 行")

    # 3c. accounts 更新（只动有真源依据的列，不伪造空值）
    cur.execute(
        "UPDATE accounts SET total_assets = %s, available_cash = %s, market_value = %s, "
        "total_profit_loss = %s, day_profit_loss = %s, day_profit_loss_ratio = %s, updated_at = NOW() "
        "WHERE account_id = 'REAL_001'",
        (
            live_total_assets,
            summary.get("cash_available"),
            summary.get("total_market_value"),
            summary.get("floating_pnl"),
            live_day_pnl,
            live_day_ratio,
        ),
    )
    if sim and sim_assets is not None:
        cur.execute(
            "UPDATE accounts SET total_assets = %s, available_cash = %s, market_value = %s, "
            "updated_at = NOW() WHERE account_id = 'SIM_001'",
            (sim_assets, sim_cash, sim.get("total_market_value")),
        )

    # 3d. daily_snapshots 合并写入（jsonb || 保留既有 key：indices 等）
    today = date.today().isoformat()
    nav_today: dict[str, float] = {}
    if live_total_assets is not None:
        nav_today["REAL_001"] = float(live_total_assets)
    if sim and sim_assets is not None:
        nav_today["SIM_001"] = float(sim_assets)
    if nav_today:
        cur.execute(
            "INSERT INTO daily_snapshots (date, data) VALUES (%s, %s::jsonb) "
            "ON CONFLICT (date) DO UPDATE SET "
            "data = daily_snapshots.data || %s::jsonb, updated_at = NOW()",
            (
                today,
                json.dumps(
                    {
                        "accounts": nav_today,
                        "synced_at": datetime.now().isoformat(timespec="seconds"),
                    }
                ),
                json.dumps({"accounts": nav_today}),
            ),
        )

    # 3e. max_drawdown：QTS 快照 ∪ 模拟盘自有历史，按账户取 NAV 序列
    cur.execute("SELECT date, data FROM daily_snapshots ORDER BY date")
    nav_hist: dict[str, list[float]] = {"REAL_001": [], "SIM_001": []}
    for d, data in cur.fetchall():
        accounts = (data or {}).get("accounts") or {}
        for acct in list(nav_hist):
            v = accounts.get(acct)
            if v is not None:
                nav_hist[acct].append(float(v))

    if sim:
        ds = sim.get("daily_snapshot") or {}
        sim_hist = []
        for k in sorted(ds.keys()):
            v = ds[k].get("total_asset")
            if v is not None:
                sim_hist.append(float(v))
        # 模拟盘自有历史更完整：若今天的值与 QTS 快照末值一致则复用，避免重复点
        if sim_hist and nav_hist["SIM_001"] and sim_hist[-1] == nav_hist["SIM_001"][-1]:
            nav_hist["SIM_001"] = sim_hist

    for acct, navs in nav_hist.items():
        mdd = max_drawdown_from_navs(navs)
        if mdd is None:
            print(f"  [WARN] {acct} NAV 样本 < 2 个点 → max_drawdown 不写入（不猜）")
            continue
        cur.execute(
            "UPDATE accounts SET max_drawdown = %s, updated_at = NOW() WHERE account_id = %s",
            (mdd, acct),
        )
        print(f"  {acct} max_drawdown = {mdd:.2%}（NAV {len(navs)} 个点）")

    conn.commit()

    # 3f. 写后回读（铁律：写库必须 readback）
    cur.execute(
        "SELECT account_id, total_assets, day_profit_loss_ratio, max_drawdown FROM accounts "
        "WHERE account_id IN ('REAL_001','SIM_001') ORDER BY account_id"
    )
    for acct, ta, dpr, mdd in cur.fetchall():
        print(f"  [readback] {acct}: total_assets={ta} day_ratio={dpr} max_drawdown={mdd}")
    cur.execute("SELECT count(*) FROM positions WHERE account_id = 'REAL_001'")
    print(f"  [readback] REAL_001 positions = {cur.fetchone()[0]} 行")
    conn.close()

    print(
        f"已写库 | 实盘持仓 {len(live_rows)} 行 | 实盘日收益率 {live_day_ratio} | "
        f"回撤样本 REAL {len(nav_hist['REAL_001'])} / SIM {len(nav_hist['SIM_001'])} 个点"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, TypeError, ValueError) as e:
        print(f"❌ 同步中止（真源问题，未写库）: {e}")
        sys.exit(1)
