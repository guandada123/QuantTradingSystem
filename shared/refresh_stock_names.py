#!/usr/bin/env python3
"""刷新 shared/astock_code_name.json（股票代码 → 名称映射）

为什么需要这个脚本
------------------
`shared/stock_name.py` 用这份映射做 ST/*ST 识别，供 QTS 全市场回测的
`report_service._exclude_banned()` 过滤禁买标的。

该文件自 2026-07-17 生成后**没有任何刷新机制**，7 周后快照已过期：
新戴帽的 ST 股在映射里仍显示原名 → ST 过滤漏网 → 回测样本被污染，
且**不报错**（名称查得到，只是过时），属于静默失效。

设计约束
--------
1. **拉取失败保留旧值**：某只股票取不到时沿用原有名称，绝不写空、绝不丢键。
   宁可用 07-17 的旧名，也不能让键消失导致过滤逻辑退化。
2. **原子写**：先写 .tmp 再 os.replace，避免刷新到一半被回测进程读到半截文件。
3. **不通告即失败**：退出码非 0 + 明确的成功/失败统计，便于自动化接入后告警。

数据源
------
腾讯 `qt.gtimg.cn` 批量行情接口（GBK 编码，字段 1 为股票名称）。
**刻意不用** `ifzq.gtimg.cn` / `web.ifzq.gtimg.cn` —— 那两个域名对单 IP
有 WAF 频控（约 2000 次请求后稳定 501），不适合批量刷新。

用法
----
    python shared/refresh_stock_names.py            # 刷新
    python shared/refresh_stock_names.py --dry-run  # 只对比不落盘
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

MAPPING_FILE = Path(__file__).resolve().parent / "astock_code_name.json"

# qt.gtimg.cn 未被 WAF 频控（区别于 ifzq.gtimg.cn，见文件头说明）
QUOTE_HOSTS = (
    "https://qt.gtimg.cn/q=",
    "https://web.qt.gtimg.cn/q=",
)

BATCH_SIZE = 100  # 单次请求股票数；5528 只 → 约 56 次请求
BATCH_SLEEP = 0.35  # 批次间隔(秒)，留足余量避免触发频控
TIMEOUT = 10
MAX_ATTEMPTS = 2  # 每个批次最多尝试次数（跨 host 各一次）


def market_prefix(code: str) -> str:
    """6 位代码 → 腾讯市场前缀"""
    if code.startswith(("60", "68")):
        return "sh"
    if code.startswith(("00", "30")):
        return "sz"
    if code.startswith(("92", "43", "83", "87")):
        return "bj"
    if code.startswith("900"):  # B 股
        return "sh"
    return "sz"


def fetch_batch(codes: list[str]) -> dict[str, str]:
    """批量拉取名称；返回 {6位代码: 名称}。失败返回空 dict（由调用方保留旧值）"""
    symbols = ",".join(f"{market_prefix(c)}{c}" for c in codes)

    for attempt in range(MAX_ATTEMPTS):
        host = QUOTE_HOSTS[attempt % len(QUOTE_HOSTS)]
        url = f"{host}{symbols}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read().decode("gbk", errors="ignore")

            out: dict[str, str] = {}
            for line in raw.split(";"):
                line = line.strip()
                if not line.startswith("v_"):
                    continue
                try:
                    body = line.split('="', 1)[1].rstrip('"')
                    fields = body.split("~")
                    if len(fields) < 2 or not fields[1]:
                        continue
                    full = line[2:].split("=", 1)[0]  # v_sh600745 → sh600745
                    out[full[2:]] = fields[1].strip()
                except (IndexError, ValueError):
                    continue
            if out:
                return out
        except Exception as e:
            print(f"  ⚠️  批次拉取失败(attempt {attempt + 1}/{MAX_ATTEMPTS}): {e}", file=sys.stderr)

        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(0.8)

    return {}


def main() -> int:
    ap = argparse.ArgumentParser(description="刷新股票代码→名称映射")
    ap.add_argument("--dry-run", action="store_true", help="只对比不落盘")
    args = ap.parse_args()

    if not MAPPING_FILE.exists():
        print(f"❌ 映射文件不存在: {MAPPING_FILE}", file=sys.stderr)
        return 1

    old: dict[str, str] = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    codes = sorted(old)
    print(f"映射文件: {MAPPING_FILE}")
    print(f"待刷新: {len(codes)} 只（分 {len(codes) // BATCH_SIZE + 1} 批）")

    new: dict[str, str] = {}
    failed_batches = 0

    for i in range(0, len(codes), BATCH_SIZE):
        batch = codes[i : i + BATCH_SIZE]
        got = fetch_batch(batch)
        if not got:
            failed_batches += 1
            # 保留旧值，不让键消失
            for c in batch:
                new[c] = old[c]
        else:
            for c in batch:
                new[c] = got.get(c, old[c])  # 单只缺失也保留旧值

        done = min(i + BATCH_SIZE, len(codes))
        print(f"  进度 {done}/{len(codes)}", end="\r", flush=True)
        if i + BATCH_SIZE < len(codes):
            time.sleep(BATCH_SLEEP)

    print()  # 换行结束 \r 进度行

    # 统计差异
    changed = [(c, old[c], new[c]) for c in codes if old[c] != new[c]]
    old_st = {c for c, v in old.items() if "ST" in str(v).upper()}
    new_st = {c for c, v in new.items() if "ST" in str(v).upper()}
    newly_st = new_st - old_st
    un_st = old_st - new_st  # 摘帽

    print(f"\n{'=' * 56}")
    print(f"名称变更      : {len(changed)} 只")
    print(f"新戴帽 ST     : {len(newly_st)} 只")
    print(f"已摘帽        : {len(un_st)} 只")
    print(f"失败批次      : {failed_batches}")
    print(f"{'=' * 56}")

    for c, o, n in changed[:20]:
        print(f"  {c}: {o} → {n}")
    if len(changed) > 20:
        print(f"  ... 另有 {len(changed) - 20} 只变更")

    if newly_st:
        print("\n🔴 新戴帽（旧快照会漏过 ST 过滤）:")
        for c in sorted(newly_st)[:20]:
            print(f"  {c}: {old.get(c, '(新)')} → {new[c]}")

    # 完整性守卫：新映射不得比旧映射少键
    missing = set(old) - set(new)
    if missing:
        print(f"\n❌ 新映射缺少 {len(missing)} 个键，拒绝写入（防止过滤退化）", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n[dry-run] 未落盘")
        return 0

    tmp = MAPPING_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, MAPPING_FILE)
    print(f"\n✅ 已原子写入 {MAPPING_FILE}（{len(new)} 条）")
    return 0 if failed_batches == 0 else 2  # 2 = 部分成功，供自动化判告警级别


if __name__ == "__main__":
    sys.exit(main())
