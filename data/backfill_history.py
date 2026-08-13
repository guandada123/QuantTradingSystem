"""
backfill_history.py — daily_quote 历史回填（2023-01-01 → 今日全市场）

背景: 原 fetch_data.py 增量模式从 2026-03 才铺开全市场, 历史深度 ~96 交易日,
不够 Alpha101 因子(250日窗口)使用。本脚本按 trade_date 逐日回填,
复用 Tushare token 与 daily_quote 表, ON CONFLICT DO NOTHING 幂等, 可重复跑。

用法(容器内): python3 /app/data/backfill_history.py --start 20230101
"""

import argparse
import os
import time
from datetime import datetime, timedelta

import tushare as ts
from sqlalchemy import create_engine, text

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://quant_user:quant_pass@postgres:5432/quant_trading"
)
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", os.environ.get("TS_TOKEN", ""))

EXCLUDE_PREFIXES = ("688", "689", "8", "4", "920")

DAILY_QUOTE_COLS = [
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_change",
    "volume",
    "amount",
]


def generate_trade_dates(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    dates, current = [], start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


def ensure_stock_pool(engine, ts_codes: list[str]):
    """确保这批 ts_code 在 stock_pool 中存在（daily_quote 外键约束）"""
    inserted = 0
    with engine.begin() as conn:
        for code in ts_codes:
            r = conn.execute(
                text("""
                    INSERT INTO stock_pool (ts_code, name, is_active)
                    VALUES (:code, '', true)
                    ON CONFLICT (ts_code) DO NOTHING
                """),
                {"code": code},
            )
            if r.rowcount > 0:
                inserted += 1
    if inserted:
        print(f"    stock_pool+{inserted} ")


def fetch_and_write(engine, pro, trade_date: str) -> int:
    df = pro.daily(trade_date=trade_date)
    if df is None or df.empty:
        return 0
    df = df[~df["ts_code"].str.startswith(EXCLUDE_PREFIXES)].copy()
    if df.empty:
        return 0
    ensure_stock_pool(engine, df["ts_code"].unique().tolist())
    df = df.rename(columns={"pct_chg": "pct_change", "vol": "volume"})
    df_db = df[DAILY_QUOTE_COLS].copy()
    written = 0
    with engine.begin() as conn:
        for _, row in df_db.iterrows():
            r = conn.execute(
                text("""
                    INSERT INTO daily_quote
                        (ts_code, trade_date, open, high, low, close,
                         pre_close, change, pct_change, volume, amount)
                    VALUES
                        (:ts_code, :trade_date, :open, :high, :low, :close,
                         :pre_close, :change, :pct_change, :volume, :amount)
                    ON CONFLICT (ts_code, trade_date) DO NOTHING
                """),
                row.to_dict(),
            )
            if r.rowcount > 0:
                written += 1
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20230101", help="起始日期 YYYYMMDD")
    ap.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--limit", type=int, default=0, help="只回填最近N个交易日(0=全部)")
    args = ap.parse_args()

    pro = ts.pro_api(TUSHARE_TOKEN)
    engine = create_engine(DB_URL)

    # 已有日期集合, 跳过已入库
    with engine.connect() as conn:
        existing = {
            r[0].strftime("%Y%m%d")
            for r in conn.execute(text("SELECT DISTINCT trade_date FROM daily_quote"))
        }
    print(f"已有 {len(existing)} 个交易日, 开始回填 {args.start} ~ {args.end}")

    dates = generate_trade_dates(args.start, args.end)
    todo = [d for d in dates if d not in existing]
    if args.limit > 0:
        todo = todo[-args.limit :]
    print(f"待回填 {len(todo)} 个交易日 (每日1次API=全市场当天)")

    total = 0
    t0 = time.time()
    for i, d in enumerate(todo, 1):
        try:
            w = fetch_and_write(engine, pro, d)
        except Exception as e:  # noqa: BLE001
            print(f"  {d}: 失败 {e}")
            continue
        total += w
        if i % 20 == 0:
            print(f"  [{i}/{len(todo)}] 累计+{total} 行, {time.time() - t0:.0f}s")
        if i % 100 == 0:
            time.sleep(1)  # Tushare 限流 200次/分钟
    print(f"完成: 回填 {len(todo)} 天, 写入 {total} 行, 耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
