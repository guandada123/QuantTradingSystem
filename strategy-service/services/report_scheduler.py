"""
回测报告定时调度器 v1.0
基于 APScheduler，注册日报/周报/月报定时任务
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def register_report_tasks(scheduler):
    """
    向现有 APScheduler 注册回测报告定时任务

    Args:
        scheduler: TaskSchedulerService 实例
    """
    # 每日信号汇总：收盘后 15:30
    scheduler.add_cron_job(
        _job_daily_signal_summary, "signal_daily_summary",
        hour=15, minute=30, name="每日信号汇总",
        description="汇总当日交易信号并推送飞书",
        day_of_week="mon-fri"
    )

    # 日报：每日收盘后 15:35
    scheduler.add_cron_job(
        _job_daily_report, "report_daily",
        hour=15, minute=35, name="回测日报",
        description="生成每日回测报告并推送飞书",
        day_of_week="mon-fri"
    )

    # 周报：每周五收盘后 15:40
    scheduler.add_cron_job(
        _job_weekly_report, "report_weekly",
        hour=15, minute=40, name="回测周报",
        description="生成周回测汇总报告",
        day_of_week="fri"
    )

    # 月报：每月最后一个交易日 15:45
    scheduler.add_cron_job(
        _job_monthly_report, "report_monthly",
        hour=15, minute=45, name="回测月报",
        description="生成月回测综合分析报告",
        day=28  # 每月28日触发（A股最后交易日通常在28日前）
    )

    logger.info("[ReportScheduler] 已注册 4 个报告定时任务")


# ========== 任务实现 ==========

async def _job_daily_signal_summary():
    """每日信号汇总：统计当日信号并推送飞书"""
    logger.info("[ReportScheduler] 开始生成每日信号汇总...")
    try:
        from models.database import get_db_session
        from datetime import date

        db = get_db_session()
        today = date.today().isoformat()

        # 查询今日信号
        result = db.execute(
            "SELECT signal_type, confidence_score, ts_code, generated_at "
            "FROM trading_signals WHERE DATE(generated_at) = :today",
            {"today": today}
        )
        signals = result.fetchall() if result else []

        total_count = len(signals)
        buy_count = sum(1 for s in signals if s[0] in ('BUY', 'buy'))
        sell_count = sum(1 for s in signals if s[0] in ('SELL', 'sell'))
        hold_count = total_count - buy_count - sell_count
        high_conf_count = sum(1 for s in signals if s[1] and s[1] > 70)

        # 查询今日已执行的订单数（如果有执行记录表）
        executed_count = 0
        try:
            exec_result = db.execute(
                "SELECT COUNT(*) FROM trade_orders WHERE DATE(created_at) = :today",
                {"today": today}
            )
            row = exec_result.fetchone()
            executed_count = row[0] if row else 0
        except Exception:
            pass  # 表可能不存在

        # 构建汇总内容
        summary_content = (
            f"**日期**: {today}\n"
            f"**信号总数**: {total_count}\n"
            f"**买入信号**: {buy_count} | **卖出信号**: {sell_count} | **观望**: {hold_count}\n"
            f"**高置信度(>70%)**: {high_conf_count}\n"
            f"**已执行订单**: {executed_count}\n"
            f"**未执行**: {total_count - executed_count}\n\n"
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
            from services.feishu_alert import get_alert_service, AlertType, AlertLevel
            from core.config import settings

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
                        "高置信度": str(high_conf_count)
                    }
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
        from services.report_service import report_service
        from datetime import date

        report = report_service.generate_daily_report(target_date=date.today().isoformat())
        logger.info(f"[ReportScheduler] 日报生成完成: {report['backtest_count']} 条回测, "
                     f"平均夏普 {report['summary']['avg_sharpe']}")

        # 推送飞书
        try:
            from services.feishu_alert import get_alert_service
            from core.config import settings

            alert = get_alert_service(settings.FEISHU_WEBHOOK) if hasattr(settings, 'FEISHU_WEBHOOK') else None
            if alert:
                alert.send_backtest_report(report, "daily")
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
            from services.feishu_alert import get_alert_service
            from core.config import settings

            alert = get_alert_service(settings.FEISHU_WEBHOOK) if hasattr(settings, 'FEISHU_WEBHOOK') else None
            if alert:
                alert.send_backtest_report(report, "weekly")
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
            from services.feishu_alert import get_alert_service
            from core.config import settings

            alert = get_alert_service(settings.FEISHU_WEBHOOK) if hasattr(settings, 'FEISHU_WEBHOOK') else None
            if alert:
                alert.send_backtest_report(report, "monthly")
                logger.info("[ReportScheduler] 月报已推送飞书")
        except Exception as push_e:
            logger.warning(f"[ReportScheduler] 飞书推送失败(非致命): {push_e}")

        try:
            _save_report_to_db(report)
        except Exception as db_e:
            logger.warning(f"[ReportScheduler] DB存储失败(非致命): {db_e}")

    except Exception as e:
        logger.error(f"[ReportScheduler] 月报生成失败: {e}")


def _save_report_to_db(report: dict) -> bool:
    """保存报告到 backtest_reports 表"""
    import json
    try:
        from models.database import get_db_session
        from datetime import date as dt_date

        db = get_db_session()
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
                "covered": json.dumps(report.get("top_strategies", [])[:10], ensure_ascii=False),
                "summary": json.dumps(report.get("summary", {}), ensure_ascii=False),
                "content": report.get("markdown", ""),
                "push": True
            }
        )
        db.commit()
        logger.info(f"[ReportScheduler] 报告已保存到数据库")
        return True
    except Exception as e:
        logger.warning(f"[ReportScheduler] DB保存失败: {e}")
        return False
