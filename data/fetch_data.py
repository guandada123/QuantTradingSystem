"""
从Tushare获取A股日K线数据并写入PostgreSQL（批量化 v2）
运行环境：Docker容器内（quant-strategy）

设计理念：
- 按 trade_date 批量拉取（每天1次API调用 = 全市场当天数据）
- 自动维护 stock_pool（ON CONFLICT DO NOTHING）
- 写入 daily_quote 表（统一表名）
- 支持全量初始化 + 每日增量两种模式
"""

from datetime import datetime, timedelta
import os
import sys
import time

import pandas as pd
from sqlalchemy import create_engine, text
import tushare as ts

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://quant_user:quant_pass@postgres:5432/quant_trading"
)
TUSHARE_TOKEN = os.environ.get(
    "TUSHARE_TOKEN",
    os.environ.get("ts_token", "deda9ab7f4f62de8351e88f93751373eff49542f9005c547389dfc88"),
)

# 仅主板（排除创业板300/301，科创板688/689，北交所8/4开头）
EXCLUDE_PREFIXES = ("300", "301", "688", "689", "8", "4")

# 分批写入 daily_quote 的列
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
    """生成日期范围（含首尾），格式 YYYYMMDD"""
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    dates = []
    current = start
    while current <= end:
        # 跳过周六日（Tushare daily 对非交易日返回空）
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


def init_stock_pool(engine, pro):
    """首次运行时批量初始化 stock_pool（全量主板股票）"""
    df = pro.stock_basic(
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,area,industry,list_date",
    )
    df = df[~df["ts_code"].str.startswith(EXCLUDE_PREFIXES)].copy()

    inserted = 0
    with engine.begin() as conn:
        for _, row in df.iterrows():
            r = conn.execute(
                text("""
                    INSERT INTO stock_pool (ts_code, name, industry, list_date, is_active)
                    VALUES (:ts_code, :name, :industry, :list_date, true)
                    ON CONFLICT (ts_code) DO NOTHING
                """),
                {
                    "ts_code": row["ts_code"],
                    "name": row.get("name", ""),
                    "industry": row.get("industry", ""),
                    "list_date": row.get("list_date", None),
                },
            )
            if r.rowcount > 0:
                inserted += 1

    print(f"  stock_pool 初始化: 新增 {inserted}/{len(df)} 只")
    return inserted


def ensure_stock_pool(engine, ts_codes: list[str]):
    """确保这批 ts_code 在 stock_pool 中存在"""
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
    return inserted


def fetch_and_write(engine, pro, trade_date: str) -> int:
    """
    拉取单个交易日全市场数据 → 写入 daily_quote
    返回写入记录数
    """
    print(f"  📅 {trade_date}: ", end="", flush=True)

    df = pro.daily(trade_date=trade_date)
    if df is None or df.empty:
        print("无数据")
        return 0

    raw_count = len(df)

    # 过滤创业板/科创板/北交所
    df = df[~df["ts_code"].str.startswith(EXCLUDE_PREFIXES)].copy()
    if df.empty:
        print(f"原始{raw_count}条 → 主板0条（全是创业板/科创板）")
        return 0

    filtered_count = len(df)

    # 确保 stock_pool 有记录（外键约束）
    new_stocks = ensure_stock_pool(engine, df["ts_code"].unique().tolist())
    if new_stocks:
        print(f"stock_pool+{new_stocks} ", end="", flush=True)

    # 列映射
    df = df.rename(columns={"pct_chg": "pct_change", "vol": "volume"})
    df_db = df[DAILY_QUOTE_COLS].copy()

    # 写入 daily_quote（逐条 UPSERT 避免 duplicate 中断）
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

    print(f"写入{written}/{filtered_count}条 ✅")
    return written


def main():
    """主入口：全量初始化 + 最近30交易日增量"""
    start_ts = datetime.now()
    print(f"[{start_ts}] 📊 Quant 数据管线 v2 启动")
    print("  数据源: Tushare | 目标表: daily_quote")

    # 连接
    pro = ts.pro_api(TUSHARE_TOKEN)
    print("  Tushare: OK")

    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("  DB: OK")

    # ===== Step 1: stock_pool 初始化（仅首次无数据时调用） =====
    print("\n[1/3] 检查 stock_pool...")
    with engine.connect() as conn:
        pool_count = conn.execute(text("SELECT COUNT(*) FROM stock_pool")).scalar()
    if pool_count == 0:
        print("  stock_pool 为空，从 Tushare 初始化全量主板股票...")
        init_stock_pool(engine, pro)
    else:
        print(f"  stock_pool 已有 {pool_count} 只，跳过初始化")

    # ===== Step 2: 检查 daily_quote 已有数据范围 =====
    print("\n[2/3] 检查已有数据...")
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM daily_quote")
        ).fetchone()
    if row and row[0]:
        print(f"  daily_quote 已有 {row[2]} 条数据, 范围 {row[0]} ~ {row[1]}")
        last_date = row[1]
    else:
        print("  daily_quote 为空，将全量初始化")
        last_date = None

    # ===== Step 3: 拉取缺失日期 =====
    print("\n[3/3] 拉取缺失日数据...")

    today_str = datetime.now().strftime("%Y%m%d")
    start_str = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")

    if last_date:
        # 增量：从上一次最大日期+1 开始
        start_delta = datetime.strptime(str(last_date), "%Y-%m-%d") + timedelta(days=1)
        start_str = start_delta.strftime("%Y%m%d")

    trade_dates = generate_trade_dates(start_str, today_str)
    print(f"  待检查交易日: {len(trade_dates)} 天 ({start_str} ~ {today_str})")

    total_written = 0
    for i, d in enumerate(trade_dates):
        written = fetch_and_write(engine, pro, d)
        total_written += written
        # API 限流保护（普通用户 200次/分钟）
        if i > 0 and i % 10 == 0:
            time.sleep(1)
            print(f"  ...已处理 {i + 1}/{len(trade_dates)} 天, 休息1s")

    # ===== 汇总 =====
    elapsed = (datetime.now() - start_ts).total_seconds()
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM daily_quote")).scalar()
        pool_count = conn.execute(text("SELECT COUNT(*) FROM stock_pool")).scalar()

    print(f"\n{'=' * 50}")
    print(f"✅ 数据管线 v2 完成 ({elapsed:.1f}s)")
    print(f"  stock_pool: {pool_count} 只")
    print(f"  daily_quote: {count} 条")
    print(f"  本次写入: {total_written} 条")
    print(f"[{datetime.now()}] 完成")


if __name__ == "__main__":
    main()
