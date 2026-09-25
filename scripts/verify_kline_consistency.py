#!/usr/bin/env python3
"""daily_kline 数值一致性对拍探针（Quant 数据管线 PHASE 3.4）。

背景（2026-09-03 事故）：PHASE 3.3 的结构校验只能拦"不可能值"
（close<=0 / high<low / vol<=0），拦不住"合法但错误"——盘中未收盘快照的
OHLC 完全自洽、成交量为正，结构 100% 合法，但数值是错的。
故必须补一层「DB vs 权威源（腾讯）」的对拍。

判据：
  - 成交量偏差 >1% 的行数 > 0        → 数值被污染，退出码 1
  - 收盘价偏差 >0.5% 的行数 > 0      → 数值被污染，退出码 1
  - DB 缺行（源有、库无）            → 写入不完整，退出码 1
成交量是最灵敏探针：日内单调递增，快照必然系统性偏小；
价格可能因尾盘回落恰好接近快照值而漏判，故两个都要看。

注意：只比对【非当日】日期。本管线在盘中运行，当日 K 必然是未收盘快照，
      属预期，靠下一轮 `--refresh` 自愈，不参与判定。

用法：
    python scripts/verify_kline_consistency.py [--samples N] [--dates M]
退出码：0 = 全部一致；1 = 检出偏差；2 = 探针自身执行失败
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_kline_tencent import DB_URL, fetch_kline_tencent  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

# 抽样标的（池内，覆盖不同板块）；不足时自动回退到库内前缀式标的
DEFAULT_SAMPLE = ["SZ002463", "SH600498", "SH601899", "SZ000333", "SH600584"]

VOL_TOLERANCE = 0.01  # 成交量相对偏差阈值
CLOSE_TOLERANCE = 0.005  # 收盘价相对偏差阈值


def pick_target_dates(conn, n_dates: int):
    """取最近 n_dates 个【非当日】交易日（即 T-1 .. T-n）。"""
    rows = conn.execute(
        text(
            "SELECT DISTINCT trade_date::date FROM daily_kline "
            "WHERE ts_code ~ '^[A-Z]{2}[0-9]{6}$' AND trade_date::date < CURRENT_DATE "
            "ORDER BY 1 DESC LIMIT :n"
        ),
        {"n": n_dates + 10},  # 多取一些，下面再挑稀疏点
    ).scalars().all()
    if not rows:
        return []
    picked = [str(rows[0])]  # T-1 必查（最可能被上一轮盘中快照污染）
    step = max(1, len(rows) // n_dates)
    for i in range(step, len(rows), step):
        picked.append(str(rows[i]))
        if len(picked) >= n_dates:
            break
    return picked[:n_dates]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=5, help="抽样标的数")
    ap.add_argument("--dates", type=int, default=4, help="每个标的抽查的历史日期数")
    args = ap.parse_args()

    engine = create_engine(DB_URL)
    rows_checked = 0
    vol_devs = []
    close_bad = []
    missing = []

    try:
        with engine.connect() as conn:
            target_dates = pick_target_dates(conn, args.dates)
            if not target_dates:
                print("❌ 探针失败：库内无历史交易日，无法抽样")
                return 2
            sample = DEFAULT_SAMPLE[: args.samples]

            for code in sample:
                src = {
                    str(r[0]): r for r in fetch_kline_tencent(code, days=95) if len(r) >= 6
                }
                for d in target_dates:
                    if d not in src:
                        continue  # 源无此日（停牌/新股），跳过
                    db = conn.execute(
                        text(
                            "SELECT close, vol FROM daily_kline "
                            "WHERE ts_code = :c AND trade_date::date = :d"
                        ),
                        {"c": code, "d": d},
                    ).fetchone()
                    if db is None:
                        missing.append(f"{code} {d}")
                        continue
                    s_vol, d_vol = float(src[d][5] or 0), float(db[1] or 0)
                    s_close, d_close = float(src[d][2] or 0), float(db[0] or 0)
                    rows_checked += 1
                    if s_vol > 0:
                        dev = abs(d_vol - s_vol) / s_vol
                        if dev > VOL_TOLERANCE:
                            vol_devs.append(
                                (code, d, dev, int(d_vol), int(s_vol))
                            )
                    if s_close > 0 and abs(d_close - s_close) / s_close > CLOSE_TOLERANCE:
                        close_bad.append(f"{code} {d}: db={d_close} src={s_close}")
    except Exception as exc:  # 探针自身失败不能伪装成"通过"
        print(f"❌ 探针执行失败: {exc}")
        return 2

    print(f"对拍: {len(sample)} 只 × 日期 {', '.join(target_dates)}")
    print(f"比对行数: {rows_checked}")
    print(f"成交量偏差 >{VOL_TOLERANCE:.0%} 的行数: {len(vol_devs)}/{rows_checked}")
    for x in sorted(vol_devs, key=lambda t: -t[2])[:10]:
        print(f"   {x[0]} {x[1]} dev={x[2]:.2%} db={x[3]} src={x[4]}")
    print(f"收盘价偏差 >{CLOSE_TOLERANCE:.1%} 的行数: {len(close_bad)}")
    for b in close_bad[:10]:
        print("   " + b)
    print(f"DB 缺行: {len(missing)}")
    for m in missing[:10]:
        print("   " + m)

    if vol_devs or close_bad or missing:
        print("🔴 结论：检出数值不一致，数据可能被盘中快照污染")
        return 1
    print("✅ 结论：DB 与权威源完全一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
