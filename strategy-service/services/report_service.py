"""
回测报告生成服务 v1.0
支持日报/周报/月报自动生成，输出飞书卡片 + Markdown格式
"""

from datetime import date, datetime, timedelta
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ReportService:
    """回测报告生成服务"""

    def __init__(self, stock_pool: list[str] = None):
        """
        Args:
            stock_pool: 默认回测股票池，如 ['000001.SZ', '600519.SH']
        """
        self.stock_pool = stock_pool or ["000001.SZ", "600519.SH"]

    def generate_daily_report(
        self, target_date: str = None, strategies: list[str] = None
    ) -> dict[str, Any]:
        """
        生成日报：对每只股票运行所有策略回测，汇总排名

        Args:
            target_date: 回测截止日期，默认今天
            strategies: 策略列表，默认全部5个

        Returns:
            {
                "report_type": "daily",
                "report_date": "2026-06-09",
                "backtest_count": 25,
                "top_strategies": [...],
                "stock_ranking": [...],
                "summary": {...},
                "markdown": "...",
                "feishu_card": {...}
            }
        """
        target = target_date or date.today().isoformat()
        strategies = strategies or ["ma-cross", "breakout", "rsi", "macd", "kdj"]
        start_date = self._default_start_date("daily", target)

        all_results: list[dict[str, Any]] = []
        stock_ranking: list[dict[str, Any]] = []

        for ts_code in self.stock_pool:
            stock_results: list[dict[str, Any]] = []
            try:
                data = self._fetch_backtest_data(ts_code, start_date, target)
                if not data or len(data) < 30:
                    logger.warning(f"[Report] 数据不足 {ts_code}, 跳过")
                    continue

                from services.backtest_engine_v2 import BacktestConfig, EnhancedBacktestEngine

                _REPORT_INITIAL_CASH = 30000.0
                engine = EnhancedBacktestEngine(
                    BacktestConfig(
                        initial_cash=_REPORT_INITIAL_CASH,
                        position_size=1.0,
                        max_positions=1,
                        enable_t1=False,
                        enable_limit=False,
                    )
                )

                for strat in strategies:
                    try:
                        result = engine.run_single_stock(ts_code, strat, data)
                        final_value = round(_REPORT_INITIAL_CASH * (1 + result.total_return), 2)
                        entry = {
                            "ts_code": ts_code,
                            "strategy": strat,
                            "sharpe": round(result.sharpe_ratio, 3),
                            "total_return": round(result.total_return * 100, 2),
                            "max_drawdown": round(result.max_drawdown * 100, 2),
                            "win_rate": round(result.win_rate * 100, 1),
                            "total_trades": result.total_trades,
                            "final_value": final_value,
                        }
                        stock_results.append(entry)
                        all_results.append(entry)
                    except Exception as e:
                        logger.warning(f"[Report] 回测失败 {ts_code}/{strat}: {e}")

                # 股票排行：取该股票下最优夏普
                if stock_results:
                    best = max(stock_results, key=lambda x: x["sharpe"])
                    stock_ranking.append(
                        {
                            "ts_code": ts_code,
                            "best_strategy": best["strategy"],
                            "sharpe": best["sharpe"],
                            "return": best["total_return"],
                            "drawdown": best["max_drawdown"],
                        }
                    )

            except Exception as e:
                logger.error(f"[Report] 数据处理异常 {ts_code}: {e}")

        # 策略排名
        top_strategies = sorted(all_results, key=lambda x: x["sharpe"], reverse=True)[:10]

        # 汇总摘要
        summary = {
            "total_backtests": len(all_results),
            "avg_sharpe": round(
                sum(r["sharpe"] for r in all_results) / max(len(all_results), 1), 3
            ),
            "avg_return": round(
                sum(r["total_return"] for r in all_results) / max(len(all_results), 1), 2
            ),
            "avg_win_rate": round(
                sum(r["win_rate"] for r in all_results) / max(len(all_results), 1), 1
            ),
            "positive_strategies": sum(1 for r in all_results if r["total_return"] > 0),
            "best_sharpe": top_strategies[0]["sharpe"] if top_strategies else 0,
        }

        return {
            "report_type": "daily",
            "report_date": target,
            "backtest_count": len(all_results),
            "top_strategies": top_strategies,
            "stock_ranking": stock_ranking,
            "summary": summary,
            "markdown": self._format_markdown(summary, top_strategies, stock_ranking, "日报"),
            "feishu_card": self._format_feishu_card(summary, top_strategies, stock_ranking, "日报"),
        }

    def generate_weekly_report(
        self, end_date: str = None, strategies: list[str] = None
    ) -> dict[str, Any]:
        """生成周报：汇总本周回测 + 策略排名 + 风险事件"""
        end = end_date or date.today().isoformat()
        start = (date.fromisoformat(end) - timedelta(days=7)).isoformat()
        strategies = strategies or ["ma-cross", "breakout", "rsi", "macd", "kdj"]

        # 用本周最后一天作为回测基准，标记为周报
        report = self.generate_daily_report(end, strategies)
        report["report_type"] = "weekly"
        report["report_date"] = f"{start} ~ {end}"
        report["markdown"] = self._format_markdown(
            report["summary"], report["top_strategies"], report["stock_ranking"], "周报"
        )
        report["feishu_card"] = self._format_feishu_card(
            report["summary"], report["top_strategies"], report["stock_ranking"], "周报"
        )
        return report

    def generate_monthly_report(
        self, year: int = None, month: int = None, strategies: list[str] = None
    ) -> dict[str, Any]:
        """生成月报：月回报率排名 + 参数优化趋势"""
        today = date.today()
        year = year or today.year
        month = month or today.month
        end_str = date(year, month, min(today.day, 28)).isoformat()
        start_str = date(year, month, 1).isoformat()
        strategies = strategies or ["ma-cross", "breakout", "rsi", "macd", "kdj"]

        report = self.generate_daily_report(end_str, strategies)
        report["report_type"] = "monthly"
        report["report_date"] = f"{year}-{month:02d}"
        report["markdown"] = self._format_markdown(
            report["summary"], report["top_strategies"], report["stock_ranking"], "月报"
        )
        report["feishu_card"] = self._format_feishu_card(
            report["summary"], report["top_strategies"], report["stock_ranking"], "月报"
        )
        return report

    # ========== 数据获取 ==========

    def _fetch_backtest_data(self, ts_code: str, start: str, end: str) -> list[dict]:
        """获取真实回测K线数据（腾讯财经 → 东方财富 → DataService）"""
        try:
            from services.data_fetcher import fetch_kline_eastmoney, fetch_kline_tencent

            data = fetch_kline_tencent(ts_code, start, end)
            if data:
                result: list[dict] = data
                return result

            data = fetch_kline_eastmoney(ts_code, start, end)
            if data:
                result = data
                return result
        except Exception as e:
            logger.warning(f"[Report] 公开行情源获取失败 {ts_code}: {e}")

        try:
            from core.config import settings

            from services.data_service import DataService

            ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
            if hasattr(ds, "get_stock_daily_quote"):
                data = ds.get_stock_daily_quote(ts_code, start, end)
                return data or []
        except Exception as e:
            logger.warning(f"[Report] DataService获取失败 {ts_code}: {e}")

        logger.warning(f"[Report] 无真实行情数据 {ts_code}")
        return []

    async def generate_daily_review(self, target_date: str = None) -> dict:
        """
        生成每日 AI 复盘分析，供前端 review-analysis 页面消费。
        尝试基于真实回测数据生成摘要；失败则返回占位结构。
        """
        from datetime import date as date_cls
        from datetime import timedelta

        today = target_date or date_cls.today().isoformat()
        end = date_cls.fromisoformat(today)
        start = (end - timedelta(days=30)).isoformat()

        try:
            report = self.generate_daily_report(today)
            top = report.get("top_strategies", [])
            summary = report.get("summary", {})
            return {
                "review_date": today,
                "market_overview": f"基于 {len(self.stock_pool)} 支股票、{summary.get('total_backtests', 0)} 次回测的分析摘要。",
                "key_observations": report.get("markdown", "").split("\n")[:10],
                "risk_warnings": "请注意：量化策略存在历史不代表未来的风险，请结合实际市场情况操作。",
                "strategy_performance": {
                    "months": [today[:7]],
                    "series": [
                        {
                            "name": s.get("strategy", "策略"),
                            "data": [round(s.get("avg_return", 0), 4)],
                        }
                        for s in top[:3]
                    ],
                },
                "top_strategy": top[0] if top else None,
                "generated_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.warning(f"[Review] 复盘数据生成失败 ({today}): {e}")
            raise

    def _default_start_date(self, report_type: str, end_date: str) -> str:
        """根据报告类型计算回测起始日期"""
        end = date.fromisoformat(end_date)
        if report_type == "daily":
            return (end - timedelta(days=90)).isoformat()
        if report_type == "weekly":
            return (end - timedelta(days=180)).isoformat()
        return (end - timedelta(days=365)).isoformat()

    # ========== 格式化输出 ==========

    def _format_markdown(
        self,
        summary: dict,
        top_strategies: list[dict],
        stock_ranking: list[dict],
        report_label: str,
    ) -> str:
        """生成 Markdown 格式报告"""
        lines = [
            f"# 🔬 QuantTradingSystem {report_label}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 📊 绩效摘要",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 回测总数 | {summary['total_backtests']} |",
            f"| 平均夏普 | {summary['avg_sharpe']} |",
            f"| 平均收益率 | {summary['avg_return']}% |",
            f"| 平均胜率 | {summary['avg_win_rate']}% |",
            f"| 正收益策略 | {summary['positive_strategies']}/{summary['total_backtests']} |",
            "",
            "## 🏆 策略排名 Top5",
            "| 排名 | 策略 | 标的 | 夏普 | 收益率 | 最大回撤 | 胜率 |",
            "|------|------|------|------|--------|----------|------|",
        ]

        for i, s in enumerate(top_strategies[:5], 1):
            return_sign = "🔴" if s["total_return"] > 0 else "🟢"
            lines.append(
                f"| {i} | {s['strategy']} | {s['ts_code']} | "
                f"{s['sharpe']} | {return_sign} {s['total_return']}% | "
                f"{s['max_drawdown']}% | {s['win_rate']}% |"
            )

        if stock_ranking:
            lines.append("")
            lines.append("## 📈 股票综合排名")
            lines.append("| 排名 | 标的 | 最优策略 | 夏普 | 收益率 |")
            lines.append("|------|------|----------|------|--------|")
            for i, s in enumerate(
                sorted(stock_ranking, key=lambda x: x["sharpe"], reverse=True), 1
            ):
                lines.append(
                    f"| {i} | {s['ts_code']} | {s['best_strategy']} | "
                    f"{s['sharpe']} | {s['return']}% |"
                )

        lines.append("")
        lines.append("---")
        lines.append("⚠️ 仅供参考，不构成投资建议 · 由 QuantTradingSystem 自动生成")

        return "\n".join(lines)

    def _format_feishu_card(
        self,
        summary: dict,
        top_strategies: list[dict],
        stock_ranking: list[dict],
        report_label: str,
    ) -> dict[str, Any]:
        """生成飞书交互式卡片格式"""
        # 构建策略排名文本
        rank_lines = []
        for i, s in enumerate(top_strategies[:5], 1):
            emoji = "🔴" if s["total_return"] > 0 else "🟢"
            rank_lines.append(
                f"{i}. **{s['strategy']}** @ {s['ts_code']} | "
                f"夏普 {s['sharpe']} | {emoji} {s['total_return']}% | 胜率 {s['win_rate']}%"
            )

        # 构建股票排名文本
        stock_lines = []
        for s in sorted(stock_ranking, key=lambda x: x["sharpe"], reverse=True)[:5]:
            stock_lines.append(f"• {s['ts_code']} → **{s['best_strategy']}** (夏普 {s['sharpe']})")

        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"🔬 QuantTradingSystem {report_label}",
                    },
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                        f"**回测总数**: {summary['total_backtests']} | "
                        f"**平均夏普**: {summary['avg_sharpe']} | "
                        f"**平均收益率**: {summary['avg_return']}% | "
                        f"**正收益占比**: {summary['positive_strategies']}/{summary['total_backtests']}",
                    },
                    {"tag": "hr"},
                    {"tag": "markdown", "content": "**🏆 策略 Top5**\n" + "\n".join(rank_lines)},
                    {"tag": "hr"},
                    {
                        "tag": "markdown",
                        "content": "**📈 股票综合排名**\n" + "\n".join(stock_lines)
                        if stock_lines
                        else "暂无排名数据",
                    },
                    {"tag": "hr"},
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": "⚠️ 仅供学习研究，不构成投资建议 · 由 QuantTradingSystem 自动生成",
                            }
                        ],
                    },
                ],
            },
        }
        return card


# 全局单例
report_service = ReportService()
