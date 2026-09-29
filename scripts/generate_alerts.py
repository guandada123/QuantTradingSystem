#!/usr/bin/env python3
"""告警生产者：按 `alert_rules` 评估当前数据，把命中的写成 `alerts` 行（2026-09-29）

背景：`alert_rules` / `alerts` 自建库起就是空转 —— 规则表 0 行（API 只能读硬编码默认值）、
alerts 表**无任何写入方**，而且表结构跟 API 读的列不一致（见 docs/init.sql 注释）。
本脚本补上"生产者"这一环：`规则(DB) → 评估 → alerts(DB) → API → 面板`。

设计要点：
- **不发明业务规则**：评估口径严格对齐 `strategy-service/api/alerts.py` 里原本硬编码的
  4 条默认规则（现已播种进 `alert_rules`）。表达式不在支持列表里的规则 → 如实报"未支持"，不猜。
- **输入自证**：每条规则都要报「评估了 / 命中 / 跳过（为什么）」——
  前两者是结论，第三者才是关键：数据没写进来时要说"无输入"，不能静默成"没告警"。
- **去重**：同一 rule_id 在 `--dedup-hours`（默认 24h）内已告警则不再写，
  避免每小时调度时把同一条刷满表。
- **幂等**：重复执行不产生重复行（受去重窗口约束）。

已知缺口（本脚本如实上报，不掩盖）：
- `positions` / `trades` 目前 0 行 → 规则 3/4 无输入；
- `accounts` 的 `day_profit_loss_ratio` / `max_drawdown` 全为 NULL → 规则 1/2 无输入；
- `trades` 表**没有盈亏字段**（只有 price/quantity/direction）→ 规则 4「连续亏损3次」
  即使有成交也无法计算，属**结构性缺输入**，需要先补字段或改从 orders/复盘数据取。

用法：
    python generate_alerts.py --dry-run          # 只评估不写库
    python generate_alerts.py                    # 评估并写库
    python generate_alerts.py --dedup-hours 6    # 自定义去重窗口
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg2


def _dsn() -> str:
    """连接串优先级：DATABASE_URL → QTS_DB_* → 与 docker-compose 一致的本地默认值。

    为什么要回落：本仓 `.env` 里 `DATABASE_URL=` 是**空值**，而调度（宿主机 cron）不会带环境变量；
    回落到 compose 里同一组默认值（quant_user/quant_pass@localhost:15432/quant_trading）能让
    "计划任务直接跑得起来"，不把口令硬编码进 crontab。生产部署请显式设 DATABASE_URL。
    """
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url:
        return url
    user = os.environ.get("QTS_DB_USER", "quant_user")
    pwd = os.environ.get("QTS_DB_PASSWORD", "quant_pass")
    name = os.environ.get("QTS_DB_NAME", "quant_trading")
    host = os.environ.get("QTS_DB_HOST", "localhost")
    port = os.environ.get("QTS_DB_PORT", "15432")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{name}"


DATABASE_URL = _dsn()


def fetch_rules(cur) -> list[dict]:
    cur.execute(
        "SELECT id, name, condition_expr, threshold, level FROM alert_rules "
        "WHERE enabled IS TRUE ORDER BY id"
    )
    return [
        {"id": r[0], "name": r[1], "expr": r[2], "threshold": r[3], "level": r[4]}
        for r in cur.fetchall()
    ]


def acct_metric(cur, col: str):
    """取账户级指标（当前只有一个账户有意义时取最保守的那个：最差情况优先）。"""
    cur.execute(
        f"SELECT account_id, {col} FROM accounts WHERE {col} IS NOT NULL ORDER BY {col} ASC LIMIT 1"
    )
    row = cur.fetchone()
    return (row[0], float(row[1])) if row else (None, None)


def eval_day_pnl(cur, rule, **_) -> tuple[bool, str | None, str | None]:
    acct, v = acct_metric(cur, "day_profit_loss_ratio")
    if v is None:
        return False, None, "无输入：accounts.day_profit_loss_ratio 全为 NULL（账户指标未写入）"
    if v < float(rule["threshold"]):
        return True, None, f"账户 {acct} 当日收益率 {v:.2%} < {float(rule['threshold']):.2%}"
    return False, None, None


def eval_drawdown(cur, rule, **_) -> tuple[bool, str | None, str | None]:
    acct, v = acct_metric(cur, "max_drawdown")
    if v is None:
        return False, None, "无输入：accounts.max_drawdown 全为 NULL（账户指标未写入）"
    if v > float(rule["threshold"]):
        return True, None, f"账户 {acct} 最大回撤 {v:.2%} > {float(rule['threshold']):.2%}"
    return False, None, None


def eval_concentration(cur, rule, **_) -> tuple[bool, str | None, str | None]:
    cur.execute("SELECT count(*), max(market_value), sum(market_value) FROM positions")
    n, mx, total = cur.fetchone()
    if not n:
        return False, None, "无输入：positions 表 0 行（尚无持仓）"
    if not total:
        return False, None, "无输入：positions.market_value 合计为 0/NULL"
    share = float(mx) / float(total)
    if share > float(rule["threshold"]):
        return True, None, f"单一持仓占比 {share:.1%} > {float(rule['threshold']):.1%}"
    return False, None, None


def eval_consecutive_loss(cur, rule, **_) -> tuple[bool, str | None, str | None]:
    cur.execute("SELECT count(*) FROM trades")
    if not cur.fetchone()[0]:
        return False, None, "无输入：trades 表 0 行"
    # 结构性缺输入：trades 只有 price/quantity/direction，没有盈亏字段，
    # 无法判定"亏损"，更不能判"连续"。如实上报，不用成交方向硬凑。
    return False, None, "结构性缺输入：trades 无盈亏字段（需先补 pnl 列或改从 orders/复盘数据取）"


EVALUATORS = {
    "day_pnl_ratio < -0.05": eval_day_pnl,
    "drawdown > 0.15": eval_drawdown,
    "concentration > 0.5": eval_concentration,
    "consecutive_loss >= 3": eval_consecutive_loss,
}

ALERT_TYPE = {
    "day_pnl_ratio < -0.05": "day_pnl",
    "drawdown > 0.15": "drawdown",
    "concentration > 0.5": "concentration",
    "consecutive_loss >= 3": "consecutive_loss",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dedup-hours", type=int, default=24)
    args = ap.parse_args()

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()
    rules = fetch_rules(cur)
    if not rules:
        print("alert_rules 无启用规则 → 无事可做（先播种规则，见 docs/init.sql）")
        return 0

    triggered = skipped = quiet = unsupported = 0
    for rule in rules:
        fn = EVALUATORS.get(rule["expr"].strip())
        if fn is None:
            unsupported += 1
            print(f"  ⚠️ [{rule['name']}] 未支持的表达式 `{rule['expr']}` → 跳过（不猜语义）")
            continue
        hit, _sig, reason = fn(cur, rule)
        if reason and not hit:
            skipped += 1
            print(f"  ⏭ [{rule['name']}] {reason}")
            continue
        if not hit:
            quiet += 1
            print(f"  ✅ [{rule['name']}] 已评估，未命中")
            continue

        cur.execute(
            "SELECT count(*) FROM alerts WHERE rule_id = %s "
            "AND triggered_at >= NOW() - (%s || ' hours')::interval",
            (rule["id"], args.dedup_hours),
        )
        if cur.fetchone()[0]:
            quiet += 1
            print(f"  ✅ [{rule['name']}] 命中但 {args.dedup_hours}h 内已告警 → 去重跳过")
            continue

        triggered += 1
        print(f"  🚨 [{rule['name']}] 命中：{reason}")
        if not args.dry_run:
            cur.execute(
                "INSERT INTO alerts (rule_id, level, message, alert_type, status, triggered_at) "
                "VALUES (%s, %s, %s, %s, 'open', NOW())",
                (
                    rule["id"],
                    rule["level"],
                    f"{rule['name']}：{reason}",
                    ALERT_TYPE.get(rule["expr"].strip(), "rule"),
                ),
            )

    if args.dry_run:
        conn.rollback()
        print(
            f"[dry-run] 未写库 | 命中 {triggered} / 无输入 {skipped} / 正常 {quiet} / 未支持 {unsupported}"
        )
    else:
        conn.commit()
        print(
            f"已写库 | 新增告警 {triggered} / 无输入 {skipped} / 正常 {quiet} / 未支持 {unsupported}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
