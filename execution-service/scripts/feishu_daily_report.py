"""
飞书日报 + 交易日志联动脚本（试运行版）
基于实盘操作回溯审计报告的优化清单 #10-11。

功能：
  1. 每日17:00扫描持仓，运行全部11条高级风控规则
  2. 生成"卖飞/接飞刀/持仓风险/冷却违规"飞书日报卡片
  3. 每笔交易自动写交易日志（入场依据/风控位/退出计划）
  4. 联动 thesis_tracker 记录投资逻辑兑现情况

运行方式：
  python scripts/feishu_daily_report.py
"""

import asyncio
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "shared"))

from execution_service.services.advanced_risk_rules import (
    AdvancedRiskChecker,
    RuleCheckResult,
    RuleSeverity,
    create_portfolio_holding_from_dict,
)

from shared.risk_config import RiskConfig

# ─── 路径配置 ───
WORK_DIR = Path(os.path.dirname(os.path.dirname(__file__)))
PORTFOLIO_PATH = os.getenv(
    "QTS_PORTFOLIO_PATH", str(WORK_DIR / "shared" / "claw_data" / "portfolio.json")
)
TRADE_LOG_PATH = os.getenv(
    "QTS_TRADE_LOG_PATH", str(WORK_DIR / "shared" / "claw_data" / "trade_log.json")
)
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", os.getenv("QTS_FEISHU_WEBHOOK_URL", ""))

# ─── 交易日志 ───


class TradeLogger:
    """每笔交易写入结构化日志，联动 thesis tracker"""

    def __init__(self, log_path: str):
        self.log_path = log_path
        self.entries = self._load()

    def _load(self) -> list:
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                return []
        return []

    def _save(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)

    def log_entry(
        self,
        symbol: str,
        name: str,
        action: str,  # BUY / SELL / ADJUST
        price: float,
        shares: int,
        reason: str,
        target_price: float | None = None,
        stop_price: float | None = None,
        exit_plan: str | None = None,
        thesis: str | None = None,
    ) -> dict:
        entry = {
            "id": f"T{len(self.entries) + 1:04d}",
            "symbol": symbol,
            "name": name,
            "action": action,
            "price": price,
            "shares": shares,
            "amount": round(price * shares, 2),
            "reason": reason,
            "target_price": target_price,
            "stop_price": stop_price,
            "exit_plan": exit_plan,
            "thesis": thesis,
            "timestamp": datetime.now().isoformat(),
            "date": date.today().isoformat(),
            "review_status": "pending",  # → D+3 回填结果与差异
            "review_notes": None,
        }
        self.entries.append(entry)
        self._save()
        return entry

    def log_review(self, trade_id: str, result_pnl: float, pnl_pct: float, notes: str):
        """D+3 回填交易结果"""
        for e in self.entries:
            if e["id"] == trade_id:
                e["review_status"] = "reviewed"
                e["review_notes"] = {
                    "result_pnl": round(result_pnl, 2),
                    "result_pnl_pct": round(pnl_pct, 4),
                    "notes": notes,
                    "reviewed_at": datetime.now().isoformat(),
                }
                self._save()
                return True
        return False

    def get_pending_reviews(self) -> list:
        """获取D+3待复盘交易"""
        return [
            e
            for e in self.entries
            if e["review_status"] == "pending"
            and (date.today() - datetime.fromisoformat(e["timestamp"]).date()).days >= 3
        ]

    def daily_summary(self) -> dict:
        """今日交易摘要"""
        today_str = date.today().isoformat()
        today_trades = [e for e in self.entries if e["date"] == today_str]
        return {
            "date": today_str,
            "total_trades": len(today_trades),
            "buys": sum(1 for t in today_trades if t["action"] == "BUY"),
            "sells": sum(1 for t in today_trades if t["action"] == "SELL"),
            "total_buy_amount": sum(t["amount"] for t in today_trades if t["action"] == "BUY"),
            "total_sell_amount": sum(t["amount"] for t in today_trades if t["action"] == "SELL"),
            "pending_reviews": len(self.get_pending_reviews()),
        }


# ─── 日报生成器 ───


class FeishuDailyReport:
    """生成飞书日报告警卡片"""

    def __init__(self, checker: AdvancedRiskChecker, logger: TradeLogger):
        self.checker = checker
        self.logger = logger

    def build_card(self, all_results: list[RuleCheckResult]) -> dict:
        """构建飞书交互式日报卡片"""
        critical = [r for r in all_results if r.severity == RuleSeverity.CRITICAL]
        warnings = [r for r in all_results if r.severity == RuleSeverity.WARNING]
        infos = [r for r in all_results if r.severity == RuleSeverity.INFO]

        # 卖飞统计
        sell_fly_results = [
            r for r in all_results if "卖飞" in r.rule_name or "冷却" in r.rule_name
        ]
        # 接飞刀统计
        knife_results = [r for r in all_results if "冻结" in r.rule_name or "止损" in r.rule_name]
        # 持仓风险
        position_results = [
            r for r in all_results if "仓位" in r.rule_name or "高位" in r.rule_name
        ]

        # 交易摘要
        summary = self.logger.daily_summary()

        elements = []

        # Header
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"## 📊 每日风控日报 | {date.today().strftime('%m/%d')} {datetime.now().strftime('%H:%M')}",
                },
            }
        )

        # 总览
        total_risk = len(critical) + len(warnings)
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**风险概览**: 🔴{len(critical)}严重 🟡{len(warnings)}警告 🔵{len(infos)}提示 | "
                        f"卖飞 {len(sell_fly_results)} | 接飞刀 {len(knife_results)} | 仓位 {len(position_results)}\n"
                        f"**今日交易**: 买{summary['buys']}笔(¥{summary['total_buy_amount']:,.0f}) "
                        f"卖{summary['sells']}笔(¥{summary['total_sell_amount']:,.0f}) | "
                        f"待复盘 {summary['pending_reviews']} 笔"
                    ),
                },
            }
        )
        elements.append({"tag": "hr"})

        # 严重告警
        if critical:
            elements.append(
                {"tag": "div", "text": {"tag": "lark_md", "content": "### 🔴 严重告警"}}
            )
            for r in critical[:5]:
                elements.append(
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": f"🔴 [{r.rule_name}] {r.message}"},
                    }
                )
            elements.append({"tag": "hr"})

        # 警告
        if warnings:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "### 🟡 关注项"}})
            for r in warnings[:8]:
                elements.append(
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": f"🟡 [{r.rule_name}] {r.message}"},
                    }
                )

        # 无异常
        if not critical and not warnings:
            elements.append(
                {"tag": "div", "text": {"tag": "lark_md", "content": "### ✅ 全部规则通过"}}
            )

        elements.append({"tag": "hr"})

        # Footer moved to card-level note
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📋 风控日报 {'🔴' if critical else '🟡' if warnings else '✅'}",
                },
                "template": "red" if critical else ("orange" if warnings else "green"),
            },
            "elements": elements,
            "note": {
                "elements": [
                    {"tag": "plain_text", "content": "试运行 | 自动执行: OFF | 下次检查: 明日17:00"}
                ]
            },
        }
        return card

    async def send(self, card: dict):
        if not FEISHU_WEBHOOK:
            print("[SKIP] Feishu webhook not configured")
            return
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    FEISHU_WEBHOOK,
                    json={"msg_type": "interactive", "card": card},
                )
                print(f"  Feishu: {resp.status_code}")
        except Exception as e:
            print(f"  Feishu error: {e}")


# ─── 主流程 ───


async def main():
    print(f"[{datetime.now()}] 📋 每日风控日报生成...")

    config = RiskConfig()
    checker = AdvancedRiskChecker(config)
    trade_logger = TradeLogger(TRADE_LOG_PATH)
    report = FeishuDailyReport(checker, trade_logger)

    # 加载持仓
    portfolio = {}
    if os.path.exists(PORTFOLIO_PATH):
        try:
            with open(PORTFOLIO_PATH, encoding="utf-8") as f:
                portfolio = json.load(f)
        except Exception as e:
            print(f"  Portfolio load error: {e}")

    all_results = []

    # 实盘持仓逐只检查
    live_holdings = portfolio.get("live", {}).get("holdings", [])
    for h in live_holdings:
        holding = create_portfolio_holding_from_dict(h)
        symbol = f"sh{h['code']}" if h["code"].startswith("6") else f"sz{h['code']}"
        position_value = h["shares"] * h.get("current_price", 0)
        total_asset = portfolio.get("live", {}).get("total_assets", 0)

        # R6: 卖飞保留仓检查
        r6 = checker._check_sell_retention(symbol, holding, position_value, total_asset)

        # R7: 仓位上限检查
        r7 = checker._check_position_limit(symbol, holding, position_value, total_asset)

        # 全量规则
        results = checker.run_all_checks(symbol, h.get("current_price", 0), holding, {})
        if r6 and r6.triggered:
            results.append(r6)

        all_results.extend(results)

    # 模拟盘持仓检查
    sim_positions = portfolio.get("sim", {}).get("positions", {})
    sim_total = portfolio.get("sim", {}).get("config", {}).get("initial_capital", 30000)
    for code, p in sim_positions.items():
        holding = create_portfolio_holding_from_dict(
            {
                "code": code,
                "name": p.get("name", ""),
                "shares": p.get("shares", 0),
                "avg_cost": p.get("avg_cost", 0),
                "current_price": p.get("current_price", 0),
                "buy_date": p.get("first_buy_date", ""),
            }
        )
        symbol = f"sh{code}" if code.startswith("6") else f"sz{code}"
        position_value = p.get("shares", 0) * p.get("current_price", 0)
        results = checker.run_all_checks(symbol, p.get("current_price", 0), holding, {})
        all_results.extend(results)

    # 待复盘提醒
    pending = trade_logger.get_pending_reviews()
    if pending:
        import_sys_path_hack = None  # placeholder
        names_str = "、".join([f"{t['name']}({t['id']})" for t in pending[:5]])
        from execution_service.services.advanced_risk_rules import (
            RuleAction,
            RuleCheckResult,
            RuleSeverity,
        )

        all_results.append(
            RuleCheckResult(
                rule_id="R11_TRADE_REVIEW",
                rule_name="交易复盘提醒",
                severity=RuleSeverity.INFO,
                action=RuleAction.ALERT_ONLY,
                triggered=True,
                symbol="",
                message=f"📝 待复盘交易 {len(pending)} 笔: {names_str}",
                details={"pending_count": len(pending)},
            )
        )

    # 生成并发送日报
    card = report.build_card(all_results)

    if FEISHU_WEBHOOK:
        await report.send(card)
    else:
        print(f"\n[飞书卡片预览] {json.dumps(card, ensure_ascii=False)[:500]}...")

    print(
        f"[{datetime.now()}] ✅ 日报完成: {len(all_results)} 条规则检查, "
        f"{sum(1 for r in all_results if r.severity == RuleSeverity.CRITICAL)}严重"
    )


if __name__ == "__main__":
    asyncio.run(main())
