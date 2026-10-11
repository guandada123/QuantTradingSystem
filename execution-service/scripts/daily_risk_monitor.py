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
from pathlib import Path

# 路径修正
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "shared"))

from services.advanced_risk_rules import (
    AdvancedRiskChecker,
    create_portfolio_holding_from_dict,
    extract_live_holdings,
    extract_total_asset,
)
from services.market_data_provider import MarketDataProvider

from shared.risk_config import RiskConfig

# ──────────────────── 配置 ────────────────────

_WORK_DIR = Path(os.path.dirname(os.path.dirname(__file__)))

# 模拟盘镜像：由 Claw `sync_claw_to_qts_portfolio.py` 同步到 shared/claw_data/
PORTFOLIO_PATH = os.getenv(
    "QTS_PORTFOLIO_PATH", str(_WORK_DIR / "shared" / "claw_data" / "portfolio.json")
)

# 实盘账户权威源（国金证券）：与模拟盘**不是同一个文件**。
# 历史事故（2026-10-10 取证）：本脚本误从模拟盘文件取 `live.holdings`，
# 而该文件根本没有 live 字段 → `load_live_holdings()` 恒 []，实盘检查块静默恒空、
# 「缺数据告警」也永不触发。候选按顺序取第一个存在者；可用 QTS_LIVE_PORTFOLIO_PATH 覆盖。
LIVE_PORTFOLIO_CANDIDATES = [
    p
    for p in (
        os.getenv("QTS_LIVE_PORTFOLIO_PATH", ""),
        str(Path.home() / "WorkBuddy" / "Claw" / ".workbuddy" / "data" / "user" / "portfolio.json"),
        str(_WORK_DIR / "shared" / "claw_data" / "live_portfolio.json"),
    )
    if p
]

FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK", os.getenv("QTS_FEISHU_WEBHOOK_URL", ""))


class DailyRiskMonitor:
    """每日风控监控器"""

    def __init__(self, config: RiskConfig):
        self.config = config
        self.checker = AdvancedRiskChecker(config)
        self.portfolio_path = PORTFOLIO_PATH

    def load_portfolio(self) -> dict:
        """加载模拟盘镜像（shared/claw_data/portfolio.json）"""
        if not os.path.exists(self.portfolio_path):
            print(f"[WARN] portfolio.json not found at {self.portfolio_path}")
            return {}
        with open(self.portfolio_path, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _resolve_live_path() -> str | None:
        """按候选顺序返回第一个存在的实盘账户源路径。"""
        for p in LIVE_PORTFOLIO_CANDIDATES:
            if os.path.exists(p):
                return p
        return None

    def load_live_portfolio(self) -> dict:
        """加载实盘账户文档。取不到时**显式告警**（不静默当空持仓）。"""
        path = self._resolve_live_path()
        if not path:
            print(
                "[WARN] 未找到实盘账户源，实盘检查块将跳过：候选 "
                + " | ".join(LIVE_PORTFOLIO_CANDIDATES)
            )
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[WARN] 实盘账户源解析失败 {path}: {e} → 实盘检查块将跳过")
            return {}
        print(f"  实盘账户源: {path}")
        return data

    def load_live_holdings(self) -> list:
        """提取实盘持仓（国金权威源顶层 holdings[]，兼容旧 live.holdings[]）"""
        return extract_live_holdings(self.load_live_portfolio())

    @staticmethod
    def _current_price(market_data: dict, holding: dict) -> float:
        """风控判定用价：优先刚拉到的**实时价**，缺则回退组合内快照价（可能滞后）。

        历史缺陷：R1 止损直接用 `holding["current_price"]`（组合快照价），
        与刚 fetch 的 market_data 实时价不一致 → 盘中判定滞后。
        """
        rt = (market_data or {}).get("current_price")
        if rt:
            return float(rt)
        return float(holding.get("current_price", 0) or 0)

    def load_sim_holdings(self) -> list:
        """提取模拟盘持仓（兼容扁平 positions 与 sim 包裹两种格式）"""
        pf = self.load_portfolio()
        # 优先扁平结构（Claw simulation/portfolio.json 新版），回退 sim 包裹旧格式
        positions = pf.get("positions") or pf.get("sim", {}).get("positions", {}) or {}
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

        portfolio = self.load_portfolio()
        sim_total = extract_total_asset(portfolio, "sim")
        # 实盘总资产来自**实盘账户文档**（与模拟盘不是同一个文件）
        live_portfolio = self.load_live_portfolio()
        live_total = extract_total_asset(live_portfolio, "live")

        # 实盘持仓检查
        live_holdings = extract_live_holdings(live_portfolio)
        if not live_holdings:
            # 显式提示：读不到 ≠ 无风险（历史事故就是这里静默跳过）
            print("  [WARN] 实盘持仓为空（数据源缺失或无持仓）→ 实盘检查块跳过，不代表无风险")
        if live_holdings and live_total <= 0:
            print("  [WARN] 实盘总资产缺失（summary/live.total_assets）→ R7 仓位上限检查将被跳过")
        if live_holdings:
            print(f"  检查实盘持仓: {len(live_holdings)} 只")
            for h in live_holdings:
                holding = create_portfolio_holding_from_dict(h)
                symbol = f"sh{h['code']}" if h["code"].startswith("6") else f"sz{h['code']}"

                market_data = await self._get_market_data(symbol)
                price = self._current_price(market_data, h)

                results = self.checker.run_all_checks(
                    symbol=symbol,
                    current_price=price,
                    holding=holding,
                    market_data=market_data,
                    position_value=h.get("shares", 0) * price,
                    total_asset=live_total,
                )
                if results:
                    all_results.extend(results)
                    for r in results:
                        print(f"  [{r.severity.value.upper()}] {r.rule_name}: {r.message}")

        # 模拟盘持仓检查
        sim_holdings = self.load_sim_holdings()
        if sim_holdings and sim_total <= 0:
            print("  [WARN] 模拟盘 initial_capital 缺失 → R7 仓位上限检查将被跳过")
        if sim_holdings:
            print(f"  检查模拟盘持仓: {len(sim_holdings)} 只")
            for h in sim_holdings:
                holding = create_portfolio_holding_from_dict(h)
                symbol = f"sh{h['code']}" if h["code"].startswith("6") else f"sz{h['code']}"

                market_data = await self._get_market_data(symbol)
                price = self._current_price(market_data, h)

                results = self.checker.run_all_checks(
                    symbol=symbol,
                    current_price=price,
                    holding=holding,
                    market_data=market_data,
                    position_value=h.get("shares", 0) * price,
                    total_asset=sim_total,
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
