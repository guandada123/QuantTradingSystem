"""
高级风控规则 — 每日监控脚本（试运行版）
基于实盘操作回溯审计报告的优化规则。

功能：
  1. 读取 Claw portfolio.json 获取持仓数据
  2. 获取实时行情和 ATR
  3. 运行 AdvancedRiskChecker 四大规则
  4. 生成飞书交互式卡片推送

运行方式：
  python scripts/daily_risk_monitor.py

可配置为定时任务（每天 17:00 A股收盘后运行）
"""

import asyncio
import json
import os
import sys
from datetime import datetime

# 路径修正
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "shared"))

from execution_service.services.advanced_risk_rules import (
    AdvancedRiskChecker,
    create_portfolio_holding_from_dict,
)
from execution_service.services.market_data_provider import MarketDataProvider

from shared.risk_config import RiskConfig

# ──────────────────── 配置 ────────────────────

PORTFOLIO_PATH = os.getenv(
    "QTS_PORTFOLIO_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "shared", "claw_data", "portfolio.json"
    ),
)

FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK", os.getenv("QTS_FEISHU_WEBHOOK_URL", ""))


class DailyRiskMonitor:
    """每日风控监控器"""

    def __init__(self, config: RiskConfig):
        self.config = config
        self.checker = AdvancedRiskChecker(config)
        self.portfolio_path = PORTFOLIO_PATH

    def load_portfolio(self) -> dict:
        """加载持仓数据"""
        if not os.path.exists(self.portfolio_path):
            print(f"[WARN] portfolio.json not found at {self.portfolio_path}")
            return {}
        with open(self.portfolio_path, encoding="utf-8") as f:
            return json.load(f)

    def load_live_holdings(self) -> list:
        """提取实盘持仓"""
        pf = self.load_portfolio()
        live = pf.get("live", {})
        holdings = live.get("holdings", [])
        return holdings

    def load_sim_holdings(self) -> list:
        """提取模拟盘持仓"""
        pf = self.load_portfolio()
        sim = pf.get("sim", {})
        positions = sim.get("positions", {})
        return [
            {
                "code": code,
                "name": p.get("name", ""),
                "shares": p.get("shares", 0),
                "avg_cost": p.get("avg_cost", 0),
                "current_price": p.get("current_price", 0),
                "buy_date": p.get("first_buy_date", ""),
            }
            for code, p in positions.items()
        ]

    async def run(self):
        """执行每日监控"""
        print(f"[{datetime.now()}] 开始每日高级风控检查...")

        all_results = []

        # 实盘持仓检查
        live_holdings = self.load_live_holdings()
        if live_holdings:
            print(f"  检查实盘持仓: {len(live_holdings)} 只")
            for h in live_holdings:
                holding = create_portfolio_holding_from_dict(h)
                symbol = f"sh{h['code']}" if h["code"].startswith("6") else f"sz{h['code']}"

                # 获取市场数据（简化版，实际应从行情源获取）
                market_data = await self._get_market_data(symbol)

                results = self.checker.run_all_checks(
                    symbol=symbol,
                    current_price=h.get("current_price", 0),
                    holding=holding,
                    market_data=market_data,
                )
                if results:
                    all_results.extend(results)
                    for r in results:
                        print(f"  [{r.severity.value.upper()}] {r.rule_name}: {r.message}")

        # 模拟盘持仓检查
        sim_holdings = self.load_sim_holdings()
        if sim_holdings:
            print(f"  检查模拟盘持仓: {len(sim_holdings)} 只")
            for h in sim_holdings:
                holding = create_portfolio_holding_from_dict(h)
                symbol = f"sh{h['code']}" if h["code"].startswith("6") else f"sz{h['code']}"

                market_data = await self._get_market_data(symbol)

                results = self.checker.run_all_checks(
                    symbol=symbol,
                    current_price=h.get("current_price", 0),
                    holding=holding,
                    market_data=market_data,
                )
                if results:
                    all_results.extend(results)

        # 生成飞书卡片
        card = self.checker.to_feishu_card(all_results)

        # 推送飞书
        if FEISHU_WEBHOOK_URL:
            await self._send_feishu_card(card)
        else:
            print(f"\n[飞书卡片预览]:\n{json.dumps(card, ensure_ascii=False, indent=2)}")

        print(f"[{datetime.now()}] 每日高级风控检查完成，共触发 {len(all_results)} 条告警")

    async def _send_feishu_card(self, card: dict):
        """发送飞书交互式卡片"""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    FEISHU_WEBHOOK_URL,
                    json={"msg_type": "interactive", "card": card},
                )
                if resp.status_code == 200:
                    print("  飞书卡片推送成功")
                else:
                    print(f"  飞书推送失败: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"  飞书推送异常: {e}")

    async def _get_market_data(self, symbol: str) -> dict:
        """从行情源获取 ATR、行业指数、涨跌停统计等"""
        try:
            return await MarketDataProvider().fetch_market_data(symbol)
        except Exception as e:
            print(f"  [WARN] Market data fetch failed for {symbol}: {e}")
            return {}


async def main():
    config = RiskConfig()
    monitor = DailyRiskMonitor(config)
    await monitor.run()


if __name__ == "__main__":
    asyncio.run(main())
