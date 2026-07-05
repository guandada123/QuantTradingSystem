#!/usr/bin/env python3
"""
Fetch daily K-line data from Tencent API for a set of A-share stocks
and insert into QTS PostgreSQL daily_kline table.
No Tushare token needed — uses free Tencent API.
Usage: python3 fetch_kline_tencent.py [--stocks 000001.SZ,600519.SH,...] [--days 30]
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta

import requests
from sqlalchemy import create_engine, text

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://quant_user:quant_pass@127.0.0.1:15432/quant_trading"
)
engine = create_engine(DB_URL)

# Default: 20 popular main-board A-share stocks
DEFAULT_STOCKS = [
    "000001.SZ",  # 平安银行
    "000002.SZ",  # 万科A
    "000333.SZ",  # 美的集团
    "000651.SZ",  # 格力电器
    "000858.SZ",  # 五粮液
    "002415.SZ",  # 海康威视
    "002594.SZ",  # 比亚迪
    "600000.SH",  # 浦发银行
    "600036.SH",  # 招商银行
    "600276.SH",  # 恒瑞医药
    "600309.SH",  # 万华化学
    "600519.SH",  # 贵州茅台
    "600585.SH",  # 海螺水泥
    "600809.SH",  # 山西汾酒
    "600887.SH",  # 伊利股份
    "600900.SH",  # 长江电力
    "601012.SH",  # 隆基绿能
    "601166.SH",  # 兴业银行
    "601318.SH",  # 中国平安
    "601888.SH",  # 中国中免
]


def fetch_kline_tencent(stock_code: str, days: int = 60) -> list[dict]:
    """
    Fetch daily K-line from Tencent Finance API.
    stock_code: e.g. "000001" or "sh600519" as used by the API
    Returns list of daily records.
    """
    # Accept both "000001.SZ" and "SZ002463" formats
    if "." in stock_code:
        code = stock_code.split(".")[0]
        market = stock_code.split(".")[1].lower()
    else:
        # Format: SZ002463 or SH600498
        market = stock_code[:2].lower()
        code = stock_code[2:]

    # Tencent K-line API
    if market == "sz":
        qq_code = f"sz{code}"
    else:
        qq_code = f"sh{code}"

    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={qq_code},day,,,{days},qfq"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        klines = data.get("data", {}).get(qq_code, {}).get("day", [])
        if not klines and "qfqday" in data.get("data", {}).get(qq_code, {}):
            klines = data["data"][qq_code]["qfqday"]
        return klines if klines else []
    except Exception as e:
        print(f"  ❌ {stock_code}: {e}")
        return []


def insert_kline(ts_code: str, records: list):
    """Insert daily K-line data into daily_kline, skip duplicates."""
    count = 0
    with engine.connect() as conn:
        for r in records:
            if len(r) < 6:
                continue
            trade_date_str = str(r[0])
            open_p = float(r[1])
            close_p = float(r[2])
            high_p = float(r[3])
            low_p = float(r[4])
            vol = float(r[5])

            # Check if record already exists
            existing = conn.execute(
                text("SELECT 1 FROM daily_kline WHERE ts_code = :ts AND trade_date = :td"),
                {"ts": ts_code, "td": trade_date_str},
            ).fetchone()
            if existing:
                continue

            try:
                conn.execute(
                    text(
                        """INSERT INTO daily_kline (ts_code, trade_date, open, high, low, close, vol, amount)
                           VALUES (:ts, :td, :o, :h, :l, :c, :v, :a)"""
                    ),
                    {
                        "ts": ts_code,
                        "td": trade_date_str,
                        "o": open_p,
                        "h": high_p,
                        "l": low_p,
                        "c": close_p,
                        "v": vol,
                        "a": vol * close_p,
                    },
                )
                count += 1
            except Exception as e:
                print(f"    DB insert error: {e}")
                conn.rollback()
        conn.commit()
    return count


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--stocks", type=str, help="Comma-separated stock codes")
    parser.add_argument("--days", type=int, default=60, help="Days of history")
    parser.add_argument("--list", action="store_true", help="List current daily_kline stats")
    args = parser.parse_args()

    if args.list:
        with engine.connect() as conn:
            r = conn.execute(text("SELECT COUNT(*) FROM daily_kline"))
            total = r.scalar()
            r = conn.execute(text("SELECT COUNT(DISTINCT ts_code) FROM daily_kline"))
            symbols = r.scalar()
            r = conn.execute(text("SELECT MAX(trade_date) FROM daily_kline"))
            latest = r.scalar()
            print(f"daily_kline: {total} rows, {symbols} symbols, latest {latest}")
        return

    stocks = args.stocks.split(",") if args.stocks else DEFAULT_STOCKS
    days = args.days

    total = 0
    for ts_code in stocks:
        ts_code = ts_code.strip()
        print(f"Fetching {ts_code}...", end=" ")
        records = fetch_kline_tencent(ts_code, days)
        if not records:
            print("0 records")
            continue
        n = insert_kline(ts_code, records)
        total += n
        print(f"{n} inserted (total {len(records)} fetched)")
        time.sleep(0.5)  # rate limit

    print(f"\n✅ Done: {total} K-line records across {len(stocks)} stocks")


if __name__ == "__main__":
    main()
