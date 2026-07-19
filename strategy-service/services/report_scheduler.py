"""
回测报告定时调度器 v1.0
基于 APScheduler，注册日报/周报/月报定时任务
"""

import logging

from models.database import get_db_session

logger = logging.getLogger(__name__)


def register_report_tasks(scheduler):
    """
    向现有 APScheduler 注册回测报告定时任务

    Args:
        scheduler: TaskSchedulerService 实例
    """
    # 每日信号汇总：收盘后 15:30
    scheduler.add_cron_job(
        _job_daily_signal_summary,
        "signal_daily_summary",
        hour=15,
        minute=30,
        name="每日信号汇总",
        description="汇总当日交易信号并推送飞书",
        day_of_week="mon-fri",
    )

    # 日报：每日收盘后 15:35
    scheduler.add_cron_job(
        _job_daily_report,
        "report_daily",
        hour=15,
        minute=35,
        name="回测日报",
        description="生成每日回测报告并推送飞书",
        day_of_week="mon-fri",
    )

    # 周报：每周五收盘后 15:40
    scheduler.add_cron_job(
        _job_weekly_report,
        "report_weekly",
        hour=15,
        minute=40,
        name="回测周报",
        description="生成周回测汇总报告",
        day_of_week="fri",
    )

    # 月报：每月最后一个交易日 15:45
    scheduler.add_cron_job(
        _job_monthly_report,
        "report_monthly",
        hour=15,
        minute=45,
        name="回测月报",
        description="生成月回测综合分析报告",
        day="last",  # 每月最后一天触发（APScheduler 自动处理28/29/30/31日）
    )

    # Stock Insight 定时扫描任务
    # 每个工作日 09:00 主板精选扫描
    scheduler.add_cron_job(
        _job_stock_insight_mainboard,
        "stock_insight_mainboard",
        hour=9,
        minute=0,
        name="主板精选扫描",
        description="每个工作日开盘前执行主板精选选股",
        day_of_week="mon-fri",
    )

    # 每个工作日 15:00 理性10选股扫描
    scheduler.add_cron_job(
        _job_stock_insight_rational,
        "stock_insight_rational",
        hour=15,
        minute=0,
        name="理性10选股扫描",
        description="每个工作日收盘后执行理性10选股",
        day_of_week="mon-fri",
    )

    logger.info("[ReportScheduler] 已注册 6 个报告/扫描定时任务")

    # 数据质量检查（每天 09:00 + 15:00 各一次 — v2.2 修复 Prometheus 指标空洞）
    scheduler.add_cron_job(
        _job_data_quality_check,
        "data_quality_check",
        hour=9,
        minute=15,
        name="数据质量检查",
        description="检查行情数据新鲜度/完整性/异常值",
        day_of_week="mon-fri",
    )
    scheduler.add_cron_job(
        _job_data_quality_check,
        "data_quality_check_pm",
        hour=15,
        minute=15,
        name="数据质量检查(午后)",
        description="收盘前复查数据质量",
        day_of_week="mon-fri",
    )


# ========== 任务实现 ==========


async def _job_daily_signal_summary():
    """每日信号汇总：统计当日信号 + 回看昨日信号命中率，推送飞书"""
    logger.info("[ReportScheduler] 开始生成每日信号汇总...")
    try:
        from datetime import date, timedelta

        today = date.today()
        today_str = today.isoformat()
        yesterday = today - timedelta(days=1)

        with get_db_session() as db:
            # 查询今日信号
            result = db.execute(
                "SELECT signal_type, confidence_score, ts_code, generated_at "
                "FROM trading_signals WHERE DATE(generated_at) = :today",
                {"today": today_str},
            )
            signals = result.fetchall() if result else []

            total_count = len(signals)
            buy_count = sum(1 for s in signals if s[0] in ("BUY", "buy"))
            sell_count = sum(1 for s in signals if s[0] in ("SELL", "sell"))
            hold_count = total_count - buy_count - sell_count
            high_conf_count = sum(1 for s in signals if s[1] and s[1] > 70)

            # ★ 信号质量回看：昨日高置信信号今日实际表现
            yesterday_signals = (
                db.execute(
                    "SELECT signal_type, ts_code, confidence_score FROM trading_signals "
                    "WHERE DATE(generated_at) = :yesterday AND signal_type = 'BUY' AND confidence_score > 50",
                    {"yesterday": yesterday.isoformat()},
                ).fetchall()
                if signals
                else []
            )

            hit_count = 0
            hit_detail = []
            for ys in yesterday_signals or []:
                ts_code = ys[1]
                conf = ys[2] if ys[2] else 50
                # 查今日涨跌（从 daily_quote）
                kline = db.execute(
                    "SELECT open, close, pct_chg FROM daily_quote WHERE ts_code = :code AND trade_date = :td",
                    {"code": ts_code, "td": today.strftime("%Y%m%d")},
                ).fetchone()
                if kline:
                    pct = float(kline[2] or 0)
                    hit = pct > 0  # 看多信号涨了=命中
                    if hit:
                        hit_count += 1
                    hit_detail.append(
                        {
                            "ts_code": ts_code,
                            "conf": int(conf),
                            "pct_chg": round(pct, 2),
                            "hit": hit,
                        }
                    )

            yesterday_total = len(hit_detail)
            hit_rate = (
                round(hit_count / max(yesterday_total, 1) * 100, 1) if yesterday_total else None
            )

            # 查询今日已执行的订单数（如果有执行记录表）
            executed_count = 0
            try:
                exec_result = db.execute(
                    "SELECT COUNT(*) FROM trade_orders WHERE DATE(created_at) = :today",
                    {"today": today_str},
                )
                row = exec_result.fetchone()
                executed_count = row[0] if row else 0
            except Exception as e:
                logger.debug("查询今日执行数失败（表可能不存在）: %s", e)

        # 构建汇总内容
        hit_text = (
            f"昨日信号命中率: {hit_count}/{yesterday_total} = {hit_rate}%"
            if yesterday_total
            else "昨日无高置信信号"
        )
        summary_content = (
            f"**日期**: {today_str}\n"
            f"**信号总数**: {total_count}\n"
            f"**买入信号**: {buy_count} | **卖出信号**: {sell_count} | **观望**: {hold_count}\n"
            f"**高置信度(>70%)**: {high_conf_count}\n"
            f"**已执行订单**: {executed_count}\n"
            f"**未执行**: {total_count - executed_count}\n"
            f"**{hit_text}**\n\n"
        )

        if total_count > 0:
            # 列出高置信度信号
            high_conf_signals = [s for s in signals if s[1] and s[1] > 70]
            if high_conf_signals:
                summary_content += "**高置信度信号明细:**\n"
                for s in high_conf_signals[:5]:
                    summary_content += f"- {s[2]} | {s[0]} | 置信度 {s[1]:.0f}%\n"
        else:
            summary_content += "_今日无交易信号生成_"

        # 推送飞书
        try:
            from core.config import settings

            from services.feishu_alert import AlertLevel, AlertType, get_alert_service

            alert = get_alert_service(settings.FEISHU_WEBHOOK)
            if alert and alert.enabled:
                await alert.send_alert(
                    alert_type=AlertType.SIGNAL,
                    level=AlertLevel.INFO,
                    title=f"每日信号汇总 ({today})",
                    content=summary_content,
                    data={
                        "总信号数": str(total_count),
                        "已执行": str(executed_count),
                        "高置信度": str(high_conf_count),
                    },
                )
                logger.info("[ReportScheduler] 每日信号汇总已推送飞书")
        except Exception as push_e:
            logger.warning(f"[ReportScheduler] 信号汇总飞书推送失败(非致命): {push_e}")

    except Exception as e:
        logger.error(f"[ReportScheduler] 每日信号汇总失败: {e}")


async def _job_daily_report():
    """生成日报 → 推送飞书 → 存储DB"""
    logger.info("[ReportScheduler] 开始生成回测日报...")
    try:
        from datetime import date

        from services.report_service import report_service

        report = report_service.generate_daily_report(target_date=date.today().isoformat())
        logger.info(
            f"[ReportScheduler] 日报生成完成: {report['backtest_count']} 条回测, "
            f"平均夏普 {report['summary']['avg_sharpe']}"
        )

        # 推送飞书
        try:
            from core.config import settings

            from services.feishu_alert import get_alert_service

            alert = (
                get_alert_service(settings.FEISHU_WEBHOOK)
                if hasattr(settings, "FEISHU_WEBHOOK")
                else None
            )
            if alert:
                await alert.send_backtest_report(report, "daily")
                logger.info("[ReportScheduler] 日报已推送飞书")
        except Exception as push_e:
            logger.warning(f"[ReportScheduler] 飞书推送失败(非致命): {push_e}")

        # 存储到数据库
        try:
            _save_report_to_db(report)
        except Exception as db_e:
            logger.warning(f"[ReportScheduler] DB存储失败(非致命): {db_e}")

    except Exception as e:
        logger.error(f"[ReportScheduler] 日报生成失败: {e}")


async def _job_weekly_report():
    """生成周报"""
    logger.info("[ReportScheduler] 开始生成回测周报...")
    try:
        from services.report_service import report_service

        report = report_service.generate_weekly_report()
        logger.info(f"[ReportScheduler] 周报生成完成: {report['backtest_count']} 条回测")

        try:
            from core.config import settings

            from services.feishu_alert import get_alert_service

            alert = (
                get_alert_service(settings.FEISHU_WEBHOOK)
                if hasattr(settings, "FEISHU_WEBHOOK")
                else None
            )
            if alert:
                await alert.send_backtest_report(report, "weekly")
                logger.info("[ReportScheduler] 周报已推送飞书")
        except Exception as push_e:
            logger.warning(f"[ReportScheduler] 飞书推送失败(非致命): {push_e}")

        try:
            _save_report_to_db(report)
        except Exception as db_e:
            logger.warning(f"[ReportScheduler] DB存储失败(非致命): {db_e}")

    except Exception as e:
        logger.error(f"[ReportScheduler] 周报生成失败: {e}")


async def _job_monthly_report():
    """生成月报"""
    logger.info("[ReportScheduler] 开始生成回测月报...")
    try:
        from services.report_service import report_service

        report = report_service.generate_monthly_report()
        logger.info(f"[ReportScheduler] 月报生成完成: {report['backtest_count']} 条回测")

        try:
            from core.config import settings

            from services.feishu_alert import get_alert_service

            alert = (
                get_alert_service(settings.FEISHU_WEBHOOK)
                if hasattr(settings, "FEISHU_WEBHOOK")
                else None
            )
            if alert:
                await alert.send_backtest_report(report, "monthly")
                logger.info("[ReportScheduler] 月报已推送飞书")
        except Exception as push_e:
            logger.warning(f"[ReportScheduler] 飞书推送失败(非致命): {push_e}")

        try:
            _save_report_to_db(report)
        except Exception as db_e:
            logger.warning(f"[ReportScheduler] DB存储失败(非致命): {db_e}")

    except Exception as e:
        logger.error(f"[ReportScheduler] 月报生成失败: {e}")


# ========== Stock Insight 定时扫描任务 ==========


async def _job_stock_insight_mainboard():
    """主板精选定时扫描：每个工作日 09:00 执行"""
    logger.info("[ReportScheduler] 开始主板精选定时扫描...")
    try:
        from core.config import settings

        from services.data_service import DataService
        from services.stock_insight_engine import StockInsightEngine

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        engine = StockInsightEngine(ds)

        # 执行主板精选扫描
        results = engine.scan_mainboard(top_n=10)
        count = len(results) if results else 0

        logger.info(f"[ReportScheduler] 主板精选扫描完成，选中 {count} 只股票")

        # 推送飞书通知
        if count > 0:
            try:
                from services.feishu_alert import AlertLevel, AlertType, get_alert_service

                alert = get_alert_service(settings.FEISHU_WEBHOOK)
                if alert and alert.enabled:
                    content = f"**主板精选扫描完成**\n\n共选中 {count} 只股票：\n\n"
                    for i, stock in enumerate(results[:5]):
                        content += f"{i + 1}. {stock.get('code', 'N/A')} {stock.get('name', 'N/A')} - 综合得分: {stock.get('final_score', 0):.1f}\n"
                    if count > 5:
                        content += f"\n... 还有 {count - 5} 只股票\n"

                    await alert.send_alert(
                        alert_type=AlertType.SIGNAL,
                        level=AlertLevel.INFO,
                        title="主板精选扫描结果",
                        content=content,
                        data={"选中数量": str(count)},
                    )
            except Exception as push_e:
                logger.warning(f"[ReportScheduler] 主板精选飞书推送失败(非致命): {push_e}")

        # 保存结果到数据库（可选）
        try:
            _save_scan_result_to_db("mainboard", results)
        except Exception as db_e:
            logger.warning(f"[ReportScheduler] 扫描结果DB存储失败(非致命): {db_e}")

    except Exception as e:
        logger.error(f"[ReportScheduler] 主板精选扫描失败: {e}")


async def _job_stock_insight_rational():
    """理性10选股定时扫描：每个工作日 15:00 执行"""
    logger.info("[ReportScheduler] 开始理性10选股定时扫描...")
    try:
        from core.config import settings

        from services.data_service import DataService
        from services.stock_insight_engine import StockInsightEngine

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        engine = StockInsightEngine(ds)

        # 执行理性10选股扫描
        results = engine.scan_rational(top_n=10)
        count = len(results) if results else 0

        logger.info(f"[ReportScheduler] 理性10选股扫描完成，选中 {count} 只股票")

        # 分类统计
        long_term_count = (
            len([r for r in results if r.get("selection_type") == "long_term"]) if results else 0
        )
        short_term_count = (
            len([r for r in results if r.get("selection_type") == "short_term"]) if results else 0
        )

        # 推送飞书通知
        if count > 0:
            try:
                from services.feishu_alert import AlertLevel, AlertType, get_alert_service

                alert = get_alert_service(settings.FEISHU_WEBHOOK)
                if alert and alert.enabled:
                    content = "**理性10选股扫描完成**\n\n"
                    content += f"共选中 {count} 只股票（长线 {long_term_count} 只 + 短线 {short_term_count} 只）\n\n"

                    # 长线前3
                    long_term = [r for r in results if r.get("selection_type") == "long_term"][:3]
                    if long_term:
                        content += "**长线精选（前3）:**\n"
                        for i, stock in enumerate(long_term):
                            content += f"{i + 1}. {stock.get('code', 'N/A')} {stock.get('name', 'N/A')} - 长线得分: {stock.get('long_final', 0):.1f}\n"

                    # 短线前3
                    short_term = [r for r in results if r.get("selection_type") == "short_term"][:3]
                    if short_term:
                        content += "\n**短线精选（前3）:**\n"
                        for i, stock in enumerate(short_term):
                            content += f"{i + 1}. {stock.get('code', 'N/A')} {stock.get('name', 'N/A')} - 短线得分: {stock.get('short_final', 0):.1f}\n"

                    await alert.send_alert(
                        alert_type=AlertType.SIGNAL,
                        level=AlertLevel.INFO,
                        title="理性10选股扫描结果",
                        content=content,
                        data={
                            "总数": str(count),
                            "长线": str(long_term_count),
                            "短线": str(short_term_count),
                        },
                    )
            except Exception as push_e:
                logger.warning(f"[ReportScheduler] 理性10选股飞书推送失败(非致命): {push_e}")

        # 保存结果到数据库（可选）
        try:
            _save_scan_result_to_db("rational", results)
        except Exception as db_e:
            logger.warning(f"[ReportScheduler] 扫描结果DB存储失败(非致命): {db_e}")

    except Exception as e:
        logger.error(f"[ReportScheduler] 理性10选股扫描失败: {e}")


def _save_scan_result_to_db(scan_type: str, results: list) -> bool:
    """保存选股扫描结果到数据库"""
    import json

    try:
        from datetime import datetime

        with get_db_session() as db:
            scan_time = datetime.now()

            # 创建扫描结果表（如果不存在）
            db.execute("""
                CREATE TABLE IF NOT EXISTS stock_insight_scans (
                    id SERIAL PRIMARY KEY,
                    scan_type VARCHAR(50) NOT NULL,
                    scan_time TIMESTAMP NOT NULL,
                    total_count INTEGER NOT NULL,
                    results_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 插入扫描结果
            db.execute(
                """INSERT INTO stock_insight_scans (scan_type, scan_time, total_count, results_json)
                   VALUES (:scan_type, :scan_time, :total_count, :results_json)""",
                {
                    "scan_type": scan_type,
                    "scan_time": scan_time,
                    "total_count": len(results) if results else 0,
                    "results_json": json.dumps(results, ensure_ascii=False) if results else "[]",
                },
            )
            db.commit()
            logger.info(f"[ReportScheduler] {scan_type} 扫描结果已保存到数据库")
        return True
    except Exception as e:
        logger.warning(f"[ReportScheduler] 扫描结果DB保存失败: {e}")
        return False


def _save_report_to_db(report):
    """保存报告到 backtest_reports 表"""
    import json

    try:
        from datetime import date as dt_date

        with get_db_session() as db:
            report_date = report.get("report_date", dt_date.today().isoformat())

            db.execute(
                """INSERT INTO backtest_reports (report_type, report_date, ts_codes, strategy_count,
                   strategies_covered, summary, detail_content, push_success)
                   VALUES (:type, :date, :codes, :count, :covered, :summary, :content, :push)""",
                {
                    "type": report["report_type"],
                    "date": report_date[:10] if isinstance(report_date, str) else report_date,
                    "codes": [s["ts_code"] for s in report.get("top_strategies", [])[:10]],
                    "count": report["backtest_count"],
                    "covered": json.dumps(
                        report.get("top_strategies", [])[:10], ensure_ascii=False
                    ),
                    "summary": json.dumps(report.get("summary", {}), ensure_ascii=False),
                    "content": report.get("markdown", ""),
                    "push": True,
                },
            )
            db.commit()
            logger.info("[ReportScheduler] 报告已保存到数据库")
        return True
    except Exception as e:
        logger.warning(f"[ReportScheduler] DB保存失败: {e}")
        return False


async def _job_data_quality_check():
    """数据质量检查：更新 Prometheus 指标（此前指标定义了但从无定时更新 — v2.2 修复）"""
    import time as _time

    t0 = _time.monotonic()
    logger.info("[ReportScheduler] 执行数据质量检查")
    try:
        from datetime import datetime

        from models.database import get_db_session

        with get_db_session() as db:
            # 检查 daily_quote 最新数据时间（新鲜度）
            row = db.execute("SELECT MAX(trade_date) FROM daily_quote").fetchone()
            latest_date = row[0] if row else None

            # 检查数据空窗（连续缺失天数）
            row2 = db.execute(
                "SELECT COUNT(*) FROM daily_quote WHERE trade_date IS NULL OR close IS NULL"
            ).fetchone()
            null_count = row2[0] if row2 else 0

            # 更新 Prometheus 指标
            try:
                from services.data_quality import (
                    data_anomaly_count,
                    data_freshness_seconds,
                    data_gap_count,
                    data_quality_score,
                    source_online,
                )

                # 新鲜度（秒）
                if latest_date:
                    latest_dt = datetime.strptime(str(latest_date), "%Y%m%d")
                    delta = (datetime.now() - latest_dt).total_seconds()
                    data_freshness_seconds.labels(data_source="daily_quote").set(delta)

                # 数据缺口
                data_gap_count.labels(data_source="daily_quote", symbol="all").set(null_count)

                # 质量评分（0-100）：新鲜度 + 完整性
                if latest_date:
                    days_behind = max(
                        0, (datetime.now() - datetime.strptime(str(latest_date), "%Y%m%d")).days
                    )
                    score = max(0, 100 - days_behind * 10 - null_count)
                    data_quality_score.labels(data_source="daily_quote").set(score)

                # 数据源在线状态
                source_online.labels(source_name="daily_quote_postgres").set(1)

                # 异常计数（按需统计）
                anomaly_cnt = null_count
                if anomaly_cnt > 0:
                    data_anomaly_count.labels(
                        data_source="daily_quote", anomaly_type="null_value"
                    ).inc(anomaly_cnt)

            except ImportError:
                logger.debug("[ReportScheduler] data_quality 指标模块未就绪")
            except Exception as metric_e:
                logger.debug(f"[ReportScheduler] Prometheus 指标更新异常(非致命): {metric_e}")

        duration_ms = (_time.monotonic() - t0) * 1000
        logger.info(
            "[ReportScheduler] 数据质量检查完成",
            latest_date=str(latest_date),
            null_count=null_count,
            duration_ms=round(duration_ms, 1),
        )

    except Exception as e:
        logger.error(f"[ReportScheduler] 数据质量检查失败: {e}")
