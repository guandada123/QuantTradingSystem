"""
回测报告生成服务 v1.0
支持日报/周报/月报自动生成，输出飞书卡片 + Markdown格式
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# 日报/周报/月报默认策略列表（11 策略全量同台竞技）
DEFAULT_STRATEGIES = [
    "ma-cross",
    "breakout",
    "rsi",
    "macd",
    "kdj",  # 5 经典
    "vwm",
    "bollinger",
    "adx",
    "combo-vwm-bbr",  # 4 中级
    "vbm",
    "vpb",  # 2 高级
]


def normalize_ts_code(ts_code: str) -> str:
    """归一化股票代码为标准格式 ts_code (如 002636.SZ)

    兼容 daily_kline 表中混用的非标格式: SZ002636/SH603002 -> 002636.SZ/603002.SH
    """
    s = ts_code.strip().upper()
    if "." in s:
        return s
    if len(s) >= 8 and s[:2] in ("SZ", "SH", "BJ"):
        mkt, num = s[:2], s[2:]
        return f"{num}.{mkt}"
    return s


class ReportService:
    """回测报告生成服务"""

    def __init__(self, stock_pool: list[str] = None):
        """
        Args:
            stock_pool: 默认回测股票池。不传则从数据库 daily_kline 表读取有K线数据的股票。
        """
        if stock_pool:
            self.stock_pool = [normalize_ts_code(c) for c in stock_pool]
        else:
            self.stock_pool = self._load_stock_pool_from_db()

    def _get_stock_name(self, ts_code: str) -> str:
        """查询单只股票名称（委托 shared.stock_name）"""
        from shared.stock_name import resolve_name

        return resolve_name(ts_code)

    def _load_stock_pool_from_db(self) -> list[str]:
        """从数据库读取有足够K线数据且流动性好的股票作为回测池

        v2.2 优化: 从 3494 只全量 → 过滤成交量/换手率 → ~500 只（节省 85% 算力）
        规则: 近20日均成交额>=3亿 OR 换手率>=1% → 排除僵尸股/仙股
        """
        min_date = date.today() - timedelta(days=60)
        try:
            from models.database import get_db_session

            with get_db_session() as db:
                # 查询最新交易日的总量
                latest_date_row = db.execute(
                    text("SELECT MAX(trade_date) FROM daily_quote")
                ).fetchone()
                latest_date = latest_date_row[0] if latest_date_row else None

                if latest_date:
                    # 过滤流动性：当日总成交额 >= 3亿（粗略: 成交量*均价 / 1e8）
                    result = db.execute(
                        text("""SELECT ts_code FROM daily_quote
                           WHERE trade_date = :ld
                           AND volume > 0
                           AND amount >= 300000000
                           AND (ts_code LIKE '60%' OR ts_code LIKE '00%' OR ts_code LIKE '30%' OR ts_code LIKE '68%')
                           ORDER BY ts_code"""),
                        {"ld": latest_date},
                    )
                    codes = (
                        [normalize_ts_code(row[0]) for row in result.fetchall()] if result else []
                    )
                    if codes:
                        logger.info(
                            f"[ReportService] 从 daily_quote 加载 {len(codes)} 只流动性充足股票: "
                            f"{codes[:5]}..."
                        )
                        return codes

                # 降级：无最新日数据时回退到原始查询
                result = db.execute(
                    text("""SELECT ts_code FROM daily_quote
                       WHERE trade_date >= :min_date
                       AND (ts_code LIKE '60%' OR ts_code LIKE '00%' OR ts_code LIKE '30%' OR ts_code LIKE '68%')
                       GROUP BY ts_code
                       HAVING COUNT(*) >= 20
                       ORDER BY ts_code"""),
                    {"min_date": min_date},
                )
                codes = [normalize_ts_code(row[0]) for row in result.fetchall()] if result else []
                if codes:
                    logger.info(
                        f"[ReportService] 从 daily_quote 加载 {len(codes)} 只回测股票（降级模式）: "
                        f"{codes[:5]}..."
                    )
                    return codes
        except Exception as e:
            logger.warning(f"[ReportService] 从 daily_quote 加载失败: {e}")
        # 2) 回退 daily_kline (小样本池)
        try:
            from models.database import get_db_session

            with get_db_session() as db:
                result = db.execute(
                    text("""SELECT ts_code FROM daily_kline
                       WHERE trade_date >= :min_date
                       GROUP BY ts_code
                       HAVING COUNT(*) >= 20
                       ORDER BY ts_code"""),
                    {"min_date": min_date.isoformat()},
                )
                codes = [row[0] for row in result.fetchall()] if result else []
                if codes:
                    codes = [normalize_ts_code(c) for c in codes]
                    logger.info(
                        f"[ReportService] 从 daily_kline 加载 {len(codes)} 只回测股票: {codes[:5]}..."
                    )
                    return codes
        except Exception as e:
            logger.warning(f"[ReportService] 从 daily_kline 加载失败: {e}")
        # 兜底
        logger.warning("[ReportService] 使用兜底股票池: 000001.SZ")
        return ["000001.SZ"]

    def generate_daily_report(
        self, target_date: str = None, strategies: list[str] = None
    ) -> dict[str, Any]:
        """
        生成日报：对每只股票运行所有策略回测，汇总排名

        Args:
            target_date: 回测截止日期，默认今天
            strategies: 策略列表，默认全部11个

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
        strategies = strategies or DEFAULT_STRATEGIES
        start_date = self._default_start_date("daily", target)

        all_results: list[dict[str, Any]] = []
        stock_ranking: list[dict[str, Any]] = []

        for ts_code in self.stock_pool:
            stock_results: list[dict[str, Any]] = []
            try:
                data = self._fetch_backtest_data(ts_code, start_date, target)
                if not data or len(data) < 60:
                    logger.warning(f"[Report] 数据不足 {ts_code}, 跳过")
                    continue

                from services.backtest_engine_v2 import BacktestConfig, EnhancedBacktestEngine

                _REPORT_INITIAL_CASH = 30000.0
                engine = EnhancedBacktestEngine(
                    BacktestConfig(
                        initial_cash=_REPORT_INITIAL_CASH,
                        position_size=1.0,
                        max_positions=1,
                        enable_t1=True,  # ← 开 T+1，滤掉日内反转
                        enable_limit=True,  # ← 开涨跌停，涨停买不进
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

        # 策略排名（初排 — 全样本单窗口，用于筛选 Top N 进入 Walk-Forward）
        initial_top = sorted(all_results, key=lambda x: x["sharpe"], reverse=True)[:50]

        # ── Walk-Forward 验证（对初排 Top 30 跑滚动窗口，防过拟合）──
        wf_validated: dict[str, dict] = {}  # key: "ts_code|strategy"
        wf_candidates = initial_top[:30]

        from services.param_grids import get_daily_param_grid

        logger.info(f"[Report] Walk-Forward 验证 Top {len(wf_candidates)} 个候选")
        for entry in wf_candidates:
            ts_code = entry["ts_code"]
            strat = entry["strategy"]
            try:
                wf = engine.walk_forward(
                    ts_code,
                    strat,
                    train_days=120,  # 半年训练（减少窗口计算量）
                    test_days=30,  # 一个半月测试
                    step_days=40,  # 步长≈2个月
                    param_grid=get_daily_param_grid(strat),  # 精简网格（1-4 combos）
                )
                if wf.get("error"):
                    continue
                num_w = wf.get("num_windows", 0)
                if num_w < 2:
                    continue  # 数据不够走至少 2 个窗口

                # 稳定性：测试期盈利窗口占比
                profitable = sum(1 for w in wf["windows"] if w["test_return"] > 0)
                stability = profitable / num_w

                # 过拟合比率：测试夏普 / 训练夏普（均值），应 > 0.3 才有参考价值
                of_ratio = wf.get("overfit_ratio", 0)

                wf_validated[f"{ts_code}|{strat}"] = {
                    "wf_return": round(wf["overall_test_return"] * 100, 2),
                    "stability": round(stability * 100, 1),
                    "overfit_ratio": round(of_ratio, 2),
                    "windows": num_w,
                }
            except Exception as e:
                logger.debug(f"[Report] Walk-Forward 失败 {ts_code}/{strat}: {e}")

        # 最终排名：Walk-Forward 验证过的优先（加权 = wf_return × stability），未验证的降权
        def _rank_score(e: dict) -> float:
            key = f"{e['ts_code']}|{e['strategy']}"
            wf = wf_validated.get(key)
            if wf:
                # WF 验证通过：稳定性 > 50% 且 overfit_ratio > 0.2 才给高分
                if wf["stability"] >= 50 and wf["overfit_ratio"] > 0.2:
                    return wf["wf_return"] * (wf["stability"] / 100)
                return wf["wf_return"] * 0.5  # 验证不达标则打折
            return e["sharpe"] * 0.1  # 未验证的原始 Sharpe 严重打折

        top_strategies = sorted(all_results, key=_rank_score, reverse=True)[:10]

        # stock_ranking 也按 WF 验证重排
        stock_best: dict[str, dict] = {}
        for e in all_results:
            key = e["ts_code"]
            if key not in stock_best or _rank_score(e) > _rank_score(stock_best[key]):
                stock_best[key] = e
        stock_ranking = []
        for ts_code, e in sorted(stock_best.items(), key=lambda x: _rank_score(x[1]), reverse=True):
            stock_ranking.append(
                {
                    "ts_code": ts_code,
                    "best_strategy": e["strategy"],
                    "sharpe": e["sharpe"],
                    "return": e["total_return"],
                    "drawdown": e["max_drawdown"],
                    "wf_return": wf_validated.get(f"{ts_code}|{e['strategy']}", {}).get(
                        "wf_return"
                    ),
                    "stability": wf_validated.get(f"{ts_code}|{e['strategy']}", {}).get(
                        "stability"
                    ),
                    "overfit_ratio": wf_validated.get(f"{ts_code}|{e['strategy']}", {}).get(
                        "overfit_ratio"
                    ),
                }
            )

        # 汇总摘要
        wf_passed = len(
            [w for w in wf_validated.values() if w["stability"] >= 50 and w["overfit_ratio"] > 0.2]
        )
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
            "wf_candidates": len(wf_candidates),
            "wf_passed": wf_passed,
        }

        return {
            "report_type": "daily",
            "report_date": target,
            "backtest_count": len(all_results),
            "top_strategies": top_strategies,
            "stock_ranking": stock_ranking,
            "summary": summary,
            "wf_validated": wf_validated,
            "markdown": self._format_markdown(
                summary, top_strategies, stock_ranking, wf_validated, "日报"
            ),
            "feishu_card": self._format_feishu_card(
                summary, top_strategies, stock_ranking, wf_validated, "日报"
            ),
        }

    def generate_weekly_report(
        self, end_date: str = None, strategies: list[str] = None
    ) -> dict[str, Any]:
        """生成周报：汇总本周回测 + 策略排名 + 风险事件"""
        end = end_date or date.today().isoformat()
        start = (date.fromisoformat(end) - timedelta(days=7)).isoformat()
        strategies = strategies or DEFAULT_STRATEGIES

        # 用本周最后一天作为回测基准，标记为周报
        report = self.generate_daily_report(end, strategies)
        report["report_type"] = "weekly"
        report["report_date"] = f"{start} ~ {end}"
        report["markdown"] = self._format_markdown(
            report["summary"],
            report["top_strategies"],
            report["stock_ranking"],
            report.get("wf_validated", {}),
            "周报",
        )
        report["feishu_card"] = self._format_feishu_card(
            report["summary"],
            report["top_strategies"],
            report["stock_ranking"],
            report.get("wf_validated", {}),
            "周报",
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
        strategies = strategies or DEFAULT_STRATEGIES

        report = self.generate_daily_report(end_str, strategies)
        report["report_type"] = "monthly"
        report["report_date"] = f"{year}-{month:02d}"
        report["markdown"] = self._format_markdown(
            report["summary"],
            report["top_strategies"],
            report["stock_ranking"],
            report.get("wf_validated", {}),
            "月报",
        )
        report["feishu_card"] = self._format_feishu_card(
            report["summary"],
            report["top_strategies"],
            report["stock_ranking"],
            report.get("wf_validated", {}),
            "月报",
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
        wf_validated: dict,
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
            name = self._get_stock_name(s["ts_code"])
            label = f"{name}({s['ts_code']})" if name else s["ts_code"]
            lines.append(
                f"| {i} | {s['strategy']} | {label} | "
                f"{s['sharpe']} | {return_sign} {s['total_return']}% | "
                f"{s['max_drawdown']}% | {s['win_rate']}% |"
            )

        if stock_ranking:
            lines.append("")
            lines.append("## 📈 股票综合排名")
            lines.append("| 排名 | 标的 | 最优策略 | 夏普 | 收益率 |")
            lines.append("|------|------|----------|------|--------|")
            for i, s in enumerate(stock_ranking[:5], 1):
                name = self._get_stock_name(s["ts_code"])
                label = f"{name}({s['ts_code']})" if name else s["ts_code"]
                lines.append(
                    f"| {i} | {label} | {s['best_strategy']} | {s['sharpe']} | {s['return']}% |"
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
        wf_validated: dict,
        report_label: str,
    ) -> dict[str, Any]:
        """生成飞书交互式卡片格式"""
        # 构建策略排名文本（含股票名称 + Walk-Forward 验证标记）
        rank_lines = []
        for i, s in enumerate(top_strategies[:5], 1):
            emoji = "🔴" if s["total_return"] > 0 else "🟢"
            name = self._get_stock_name(s["ts_code"])
            label = f"{name}({s['ts_code']})" if name else s["ts_code"]
            # Walk-Forward 标记
            wf_tag = ""
            wf_key = f"{s['ts_code']}|{s['strategy']}"
            if wf_validated.get(wf_key):
                wf = wf_validated[wf_key]
                wf_tag = f" | WF稳{wf['stability']}%"
                if wf["stability"] < 50 or wf["overfit_ratio"] < 0.2:
                    wf_tag += " ⚠️过拟合"
            elif len(s.get("ts_code", "")) > 0:
                wf_tag = " | ⚪未验证"
            rank_lines.append(
                f"{i}. **{s['strategy']}** @ {label} | "
                f"夏普 {s['sharpe']} | {emoji} {s['total_return']}% | 胜率 {s['win_rate']}%{wf_tag}"
            )

        # 构建股票排名文本（含 Walk-Forward 验证）
        stock_lines = []
        ranked_stocks = stock_ranking[:5]
        for s in ranked_stocks:
            name = self._get_stock_name(s["ts_code"])
            label = f"{name}({s['ts_code']})" if name else s["ts_code"]
            wf_tag = ""
            if s.get("stability") is not None and s.get("stability", 0) >= 50:
                wf_tag = f" WF稳{s['stability']}%"
            elif s.get("stability") is not None:
                wf_tag = f" ⚠️过拟合(稳{s['stability']}%)"
            stock_lines.append(f"• {label} → **{s['best_strategy']}** (夏普 {s['sharpe']}{wf_tag})")

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
                        f"**正收益占比**: {summary['positive_strategies']}/{summary['total_backtests']}\n"
                        f"**Walk-Forward 验证**: Top {summary.get('wf_candidates', 0)} 候选，通过 {summary.get('wf_passed', 0)} 个",
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

    def generate_daily_brief(
        self, output_path: str = "/tmp/qts_daily_brief.json"
    ) -> dict[str, Any]:
        """生成日报摘要 JSON，供晚报 / 外部系统消费 — 含 WF 验证标记

        与 generate_daily_report() 的唯一区别：跑完整日报后提取 Top 5 + 汇总，
        写入 JSON 文件，返回同样结构。避免晚报重复跑 33825 次回测。

        Args:
            output_path: 输出 JSON 文件路径，默认 /tmp/qts_daily_brief.json

        Returns:
            {"status": "ok"/"error", "path": ..., "brief": {...}}
        """
        import json as _json
        from datetime import date as _date
        from datetime import datetime as _dt

        try:
            target = _date.today().isoformat()
            report = self.generate_daily_report(target)

            top5 = report.get("top_strategies", [])[:5]
            wf = report.get("wf_validated", {})
            summary = report.get("summary", {})

            # Top 5 每条附 WF 稳定性标记
            for entry in top5:
                key = f"{entry['ts_code']}|{entry['strategy']}"
                wf_data = wf.get(key, {})
                entry["wf_stability"] = wf_data.get("stability")
                entry["wf_overfit_ratio"] = wf_data.get("overfit_ratio")
                # 判别标签：WF稳≥50%且overfit_ratio>0.2 = 可信，否则标记过拟合/未验证
                if wf_data.get("stability", 0) >= 50 and wf_data.get("overfit_ratio", 0) > 0.2:
                    entry["wf_label"] = "✅ 可信"
                elif wf_data.get("stability") is not None:
                    entry["wf_label"] = "⚠️ 过拟合"
                else:
                    entry["wf_label"] = "⚪ 未验证"

            # 极端市场日检测：WF 全部失败且 OF 普遍为负 → 不是策略问题，是市场反转
            of_values = [
                e["wf_overfit_ratio"] for e in top5 if e.get("wf_overfit_ratio") is not None
            ]
            extreme_day = (
                summary.get("wf_passed", 0) == 0
                and len(of_values) >= 3
                and all(v < 0 for v in of_values)
            )
            if extreme_day:
                for entry in top5:
                    if entry.get("wf_label") == "⚠️ 过拟合":
                        entry["wf_label"] = "🌪️ 极端日"

            brief = {
                "generated_at": _dt.now().isoformat(),
                "report_date": target,
                "summary": summary,
                "top5": top5,
                "flags": {"extreme_day": extreme_day},
            }

            with open(output_path, "w", encoding="utf-8") as f:
                _json.dump(brief, f, ensure_ascii=False, indent=2, default=str)

            logger.info(
                f"[Brief] 日报摘要已写入 {output_path} "
                f"(回测{summary.get('total_backtests', 0)}次, "
                f"Top1={top5[0]['strategy'] if top5 else 'N/A'})"
            )

            return {"status": "ok", "path": output_path, "brief": brief}
        except Exception as e:
            logger.error(f"[Brief] 生成失败: {e}")
            return {"status": "error", "path": output_path, "error": str(e)}


# 全局单例
report_service = ReportService()
