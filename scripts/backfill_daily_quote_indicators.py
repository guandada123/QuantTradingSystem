#!/usr/bin/env python3
"""回填 `daily_quote.ma20` / `daily_quote.rsi14`（2026-09-29，用户已授权）

背景：两列 2026-08-31 由 migration 建为**可空列**，但一直没有回填任务
（312 万行全 NULL，前端按代码逻辑显示 `N/A`，属诚实降级）。本次按用户授权补齐。

口径（写死在这里，避免"各部门口径不同"）：
- **ma20**：20 日简单移动平均（含当日）。窗口内**有效收盘价不足 20 个 → NULL**，
  不用"前 N 个也算"的口径（前 19 行的 ma20 本来就是无意义的）。
- **rsi14**：Wilder 平滑 RSI(14)。首值 = 前 14 个涨跌幅的简单均值做种子，
  其后 `avg = (prev*13 + cur) / 14`；`avg_loss == 0 → RSI = 100`；不足 15 个收盘价 → NULL。

为什么 rsi 不用 SQL 算：Wilder 是带状态的指数平滑，SQL 窗口函数表达不了
（递归 CTE 会退化成 O(n²)）。ma20 是纯窗口，交给 PG 一次算完最快。

幂等：只写"值不同"的行；重复跑结果一致（可安全重跑）。

用法：
    python backfill_daily_quote_indicators.py --dry-run          # 只算不写，抽样打印
    python backfill_daily_quote_indicators.py --limit-codes 3    # 只处理前 3 只票（验证用）
    python backfill_daily_quote_indicators.py                    # 全量
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("缺少 DATABASE_URL 环境变量", file=sys.stderr)
    sys.exit(2)

MA_WINDOW = 20
RSI_PERIOD = 14


def scope_clause(limit_codes: int | None) -> str:
    """把"只处理前 N 只票"做成**同一子查询**，保证 ma/rsi/update 三处范围一致。"""
    if not limit_codes:
        return ""
    return (
        "AND ts_code IN (SELECT ts_code FROM daily_quote "
        f"GROUP BY ts_code ORDER BY ts_code LIMIT {int(limit_codes)})"
    )


def build_ma_table(cur, scope: str) -> int:
    """用窗口函数一次算出 ma20，落进临时表。"""
    cur.execute(
        f"""
        CREATE TEMP TABLE bf_ma ON COMMIT DROP AS
        SELECT id,
               CASE WHEN COUNT(close) OVER w = {MA_WINDOW}
                    THEN ROUND(AVG(close) OVER w, 4) END AS ma20
        FROM daily_quote
        WHERE TRUE {scope}
        WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date
                     ROWS BETWEEN {MA_WINDOW - 1} PRECEDING AND CURRENT ROW)
        """
    )
    cur.execute("CREATE INDEX ON bf_ma (id)")
    cur.execute("SELECT count(*) FROM bf_ma")
    return cur.fetchone()[0]


def rsi_wilder(closes: list[float]) -> list[float | None]:
    """Wilder RSI。返回与 closes 等长、前 RSI_PERIOD 位为 None 的序列。"""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= RSI_PERIOD:
        return out
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(d if d > 0 else 0.0)
        losses.append(-d if d < 0 else 0.0)

    def rsi(g: float, l: float) -> float:
        if l == 0:
            return 100.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    avg_g = sum(gains[:RSI_PERIOD]) / RSI_PERIOD
    avg_l = sum(losses[:RSI_PERIOD]) / RSI_PERIOD
    out[RSI_PERIOD] = rsi(avg_g, avg_l)
    for i in range(RSI_PERIOD + 1, n):
        avg_g = (avg_g * (RSI_PERIOD - 1) + gains[i - 1]) / RSI_PERIOD
        avg_l = (avg_l * (RSI_PERIOD - 1) + losses[i - 1]) / RSI_PERIOD
        out[i] = rsi(avg_g, avg_l)
    return out


def stream_rsi(conn, scope: str, dry_run: bool) -> int:
    """流式按票算 rsi14，COPY 进临时表。返回写入行数。"""
    cur = conn.cursor()
    cur.execute("CREATE TEMP TABLE bf_rsi (id bigint PRIMARY KEY, rsi14 numeric)")
    read = conn.cursor(name="bf_stream")  # 服务端游标，避免 312 万行全进内存
    read.itersize = 100_000
    read.execute(
        f"SELECT id, ts_code, close FROM daily_quote WHERE TRUE {scope} "
        "ORDER BY ts_code, trade_date"
    )

    buf = io.StringIO()
    rows_total = 0
    cur_code, cur_ids, cur_closes = None, [], []

    def flush_one() -> int:
        """处理完一只票：算 RSI 并追加到 COPY 缓冲。"""
        if not cur_ids:
            return 0
        vals = rsi_wilder(cur_closes)
        n = 0
        for rid, v in zip(cur_ids, vals):
            if v is None:
                continue
            buf.write(f"{rid}\t{round(v, 4)}\n")
            n += 1
        return n

    for rid, code, close in read:
        if code != cur_code:
            rows_total += flush_one()
            cur_code, cur_ids, cur_closes = code, [], []
        cur_ids.append(rid)
        cur_closes.append(float(close))
    rows_total += flush_one()

    if not dry_run:
        buf.seek(0)
        cur.copy_expert("COPY bf_rsi (id, rsi14) FROM STDIN", buf)
    read.close()
    return rows_total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只计算不写库")
    ap.add_argument("--limit-codes", type=int, default=0, help="只处理前 N 只票（验证用）")
    args = ap.parse_args()

    t0 = time.time()
    scope = scope_clause(args.limit_codes)
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    n_ma = build_ma_table(cur, scope)
    n_ma_valid = 0
    if not args.dry_run:
        cur.execute("SELECT count(ma20) FROM bf_ma")
        n_ma_valid = cur.fetchone()[0]
    print(
        f"[1/3] ma20 窗口算完：{n_ma} 行，其中可算 {n_ma_valid or '—'}（{time.time() - t0:.1f}s）"
    )

    t1 = time.time()
    n_rsi = stream_rsi(conn, scope, args.dry_run)
    print(f"[2/3] rsi14 算完：{n_rsi} 行有值（{time.time() - t1:.1f}s）")

    if args.dry_run:
        cur.execute("SELECT id, ma20 FROM bf_ma ORDER BY id LIMIT 5")
        print("  ma 抽样:", cur.fetchall())
        conn.rollback()
        print(f"[dry-run] 未写库，总耗时 {time.time() - t0:.1f}s")
        return 0

    t2 = time.time()
    cur.execute(
        """
        UPDATE daily_quote q
        SET ma20 = m.ma20, rsi14 = r.rsi14
        FROM bf_ma m, bf_rsi r
        WHERE q.id = m.id AND q.id = r.id
          AND (q.ma20 IS DISTINCT FROM m.ma20 OR q.rsi14 IS DISTINCT FROM r.rsi14)
        """
    )
    updated = cur.rowcount
    conn.commit()
    print(f"[3/3] 已写回 {updated} 行（{time.time() - t2:.1f}s），总耗时 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
