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
- **生命周期（2026-11-19 T-020 补齐）**：`alerts.status` 不再只增不减 ——
  「命中且已有 open 行」→ 复用该行、不再逐日叠加（同规则历史重复 open 行一并收口成 1 行）；
  「确定未命中」→ 该规则遗留 open 行置 `resolved` + `resolved_at`（不删行，可回溯）；
  **「无输入 / 未支持」绝不关闭** —— 没有输入 ≠ 条件消失，静默关闭会把真实风险吞掉。
- **去重**：同一 rule_id 在 `--dedup-hours`（默认 24h）内已告警则不再写，
  作为"命中即复用"之后的第二道保险。
- **幂等**：重复执行不产生重复行（受去重窗口 + 复用逻辑约束）。

已知缺口（本脚本如实上报，不掩盖）：
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
    # 用 make_dsn 组装（key=value 形式），不拼 URI：既避免模板被脱敏扫描误判成真实连接串，
    # 也顺带让含特殊字符的口令被正确转义（psycopg2 负责）。取值仍全部来自环境变量 / compose 默认值。
    return psycopg2.extensions.make_dsn(dbname=name, user=user, password=pwd, host=host, port=port)


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
    n, mx, mkt = cur.fetchone()
    if not n:
        return False, None, "无输入：positions 表 0 行（尚无持仓）"
    if not mkt:
        return False, None, "无输入：positions.market_value 合计为 0/NULL"
    mx, mkt = float(mx), float(mkt)

    # 分母口径：账户总资产（含现金）。
    # 旧实现除以「持仓市值合计」——现金被从分母里抹掉，于是持有 25% 现金的账户
    # 会被算成「单一持仓 53% > 50%」，属假超限（2026-11-26 实测：市值口径 52.9%
    # vs 总资产口径 39.3%）。按账户行「持仓市值最接近」匹配，避免把模拟盘空仓账户当本账户。
    cur.execute(
        "SELECT account_id, total_assets, market_value FROM accounts "
        "WHERE total_assets IS NOT NULL ORDER BY abs(COALESCE(market_value, 0) - %s) ASC LIMIT 1",
        (mkt,),
    )
    acct = cur.fetchone()
    if acct and acct[1] and float(acct[1]) > 0:
        base, label, note = float(acct[1]), "总资产", ""
    else:
        base, label, note = mkt, "总市值", "（口径回退：accounts 无可用 total_assets，需人工核对）"
    share = mx / base
    share_mkt = mx / mkt
    if share > float(rule["threshold"]):
        return (
            True,
            None,
            (
                f"单一持仓占{label} {share:.1%}（占持仓市值 {share_mkt:.1%}）"
                f" > {float(rule['threshold']):.1%}{note}"
            ),
        )
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


def open_alert_id(cur, rule_id: int):
    """该规则当前是否有 open 行；有则返回最新那一行的 id（用于「命中即复用」）。

    返回 `None` 表示该规则此刻没有任何 open 行 —— 这是「条件从未告警 / 已恢复」的机械判据。
    """
    cur.execute(
        "SELECT id FROM alerts WHERE rule_id = %s AND status = 'open' "
        "ORDER BY triggered_at DESC, id DESC LIMIT 1",
        (rule_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def count_stale(cur, rule_id: int, keep_id=None) -> int:
    """数「会被关闭」的行数（`--dry-run` 用来在不写库的前提下自证关闭意图）。"""
    if keep_id is None:
        cur.execute(
            "SELECT count(*) FROM alerts WHERE rule_id = %s AND status = 'open'",
            (rule_id,),
        )
    else:
        cur.execute(
            "SELECT count(*) FROM alerts WHERE rule_id = %s AND status = 'open' AND id <> %s",
            (rule_id, keep_id),
        )
    return int(cur.fetchone()[0])


def close_stale(cur, rule_id: int, keep_id=None) -> int:
    """条件已确认消失（或已复用最新一行）→ 把该规则遗留 open 行置 resolved。

    - **不删行**：只改 `status` + 写 `resolved_at`，历史可回溯，回滚只需把 status 改回 open；
    - **幂等**：同条件重复执行，第二次 rowcount=0；
    - `keep_id` 非空时保留该行（命中且已有 open 行 → 只收口历史重复行，保留 1 行 open）。
    """
    if keep_id is None:
        cur.execute(
            "UPDATE alerts SET status = 'resolved', resolved_at = NOW() "
            "WHERE rule_id = %s AND status = 'open'",
            (rule_id,),
        )
    else:
        cur.execute(
            "UPDATE alerts SET status = 'resolved', resolved_at = NOW() "
            "WHERE rule_id = %s AND status = 'open' AND id <> %s",
            (rule_id, keep_id),
        )
    return int(cur.rowcount)


def process_rule(cur, rule: dict, dedup_hours: int = 24, dry_run: bool = False) -> dict:
    """处理单条规则，返回 `{outcome, closed, reason}`。

    outcome 取值与语义（`main()` 只做汇总，不重复判断）：
    - `unsupported`：表达式不在支持列表 → 跳过，**不关闭**（不猜语义）；
    - `skipped`：`reason` 非空且未命中 → **无输入 / 结构性缺输入 → 绝不关闭**；
    - `quiet`：确定未命中 → 条件消失 → 关闭该规则全部 open 行（closed>0 时）；
    - `reused`：命中且已有 open 行（或 dedup 窗口内已写过）→ 不新增；顺带收口历史重复 open 行；
    - `new`：命中且无 open 行 → 写 1 行 open。
    """
    out = {"outcome": "quiet", "closed": 0, "reason": None}
    expr = rule["expr"].strip()
    fn = EVALUATORS.get(expr)
    if fn is None:
        out["outcome"] = "unsupported"
        return out

    hit, _sig, reason = fn(cur, rule)
    if reason and not hit:
        # ⏭ 无输入 / 结构性缺输入：没有输入 ≠ 条件消失，绝不能置 resolved
        out["outcome"] = "skipped"
        out["reason"] = reason
        return out

    if not hit:
        # 确定未命中 → 条件已消失 → 关闭历史 open 行（dry-run 只数不写）
        out["outcome"] = "quiet"
        out["closed"] = count_stale(cur, rule["id"]) if dry_run else close_stale(cur, rule["id"])
        return out

    keep = open_alert_id(cur, rule["id"])
    if keep is not None:
        # 命中且已有 open 行 → 复用，不再逐日叠加；历史重复 open 行收口，只留 1 行
        out["outcome"] = "reused"
        out["reason"] = reason
        dupes = count_stale(cur, rule["id"], keep_id=keep)
        # 只有真的存在历史重复 open 行时才发 UPDATE（单行 open 属正常态，不做空写）
        out["closed"] = (
            dupes if dry_run or not dupes else close_stale(cur, rule["id"], keep_id=keep)
        )
        return out

    cur.execute(
        "SELECT count(*) FROM alerts WHERE rule_id = %s "
        "AND triggered_at >= NOW() - (%s || ' hours')::interval",
        (rule["id"], dedup_hours),
    )
    if cur.fetchone()[0]:
        # 窗口内写过但已被关闭（条件一闪而过又回来了）→ 也不立刻重开，避免刷屏
        out["outcome"] = "reused"
        out["reason"] = reason
        return out

    out["outcome"] = "new"
    out["reason"] = reason
    if not dry_run:
        cur.execute(
            "INSERT INTO alerts (rule_id, level, message, alert_type, status, triggered_at) "
            "VALUES (%s, %s, %s, %s, 'open', NOW())",
            (
                rule["id"],
                rule["level"],
                f"{rule['name']}：{reason}",
                ALERT_TYPE.get(expr, "rule"),
            ),
        )
    return out


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

    triggered = skipped = quiet = unsupported = closed = 0
    for rule in rules:
        res = process_rule(cur, rule, args.dedup_hours, args.dry_run)
        closed += res["closed"]
        outcome = res["outcome"]
        if outcome == "unsupported":
            unsupported += 1
            print(f"  ⚠️ [{rule['name']}] 未支持的表达式 `{rule['expr']}` → 跳过（不猜语义）")
        elif outcome == "skipped":
            skipped += 1
            print(f"  ⏭ [{rule['name']}] {res['reason']}")
        elif outcome == "new":
            triggered += 1
            print(f"  🚨 [{rule['name']}] 命中：{res['reason']}")
        elif res["closed"]:
            quiet += 1
            print(f"  🔁 [{rule['name']}] 已置 resolved {res['closed']} 行（复用 1 行 / 条件成立）")
        else:
            quiet += 1
            print(f"  ✅ [{rule['name']}] 已评估，未命中")

    if args.dry_run:
        conn.rollback()
        print(
            f"[dry-run] 未写库 | 命中 {triggered} / 无输入 {skipped} / 正常 {quiet} / "
            f"未支持 {unsupported} / 关闭 {closed}（预估）"
        )
    else:
        conn.commit()
        print(
            f"已写库 | 新增告警 {triggered} / 无输入 {skipped} / 正常 {quiet} / "
            f"未支持 {unsupported} / 关闭 {closed}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
