"""
统一定时任务调度器 v1.0
基于 APScheduler 3.x AsyncIOScheduler
管理所有后台定时任务的注册/启动/停止/暂停/恢复
"""

import logging
from typing import Any

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class TaskSchedulerService:
    """后台任务调度器"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            job_defaults={
                "coalesce": True,  # 合并错过的执行
                "max_instances": 1,  # 同一任务不并行
                "misfire_grace_time": 60,  # 错过执行容差(秒)
            },
            timezone="Asia/Shanghai",
        )
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started

    def add_cron_job(
        self,
        func,
        job_id: str,
        hour: int,
        minute: int,
        args: list = None,
        kwargs: dict = None,
        name: str = "",
        day_of_week: str = None,
        day: int = None,
        description: str = "",
    ) -> str:
        """添加 cron 定时任务"""
        trigger_kwargs = {"hour": hour, "minute": minute, "timezone": "Asia/Shanghai"}
        if day_of_week:
            trigger_kwargs["day_of_week"] = day_of_week
        if day:
            trigger_kwargs["day"] = day
        trigger = CronTrigger(**trigger_kwargs)
        self.scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            name=name or job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True,
        )
        logger.info(f"[Scheduler] 添加cron任务 {job_id}: {hour:02d}:{minute:02d} {description}")
        return job_id

    def add_interval_job(
        self,
        func,
        job_id: str,
        minutes: int,
        args: list = None,
        kwargs: dict = None,
        name: str = "",
        description: str = "",
    ) -> str:
        """添加间隔重复任务"""
        trigger = IntervalTrigger(minutes=minutes, timezone="Asia/Shanghai")
        self.scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            name=name or job_id,
            args=args or [],
            kwargs=kwargs or {},
            replace_existing=True,
        )
        logger.info(f"[Scheduler] 添加间隔任务 {job_id}: 每{minutes}分钟 {description}")
        return job_id

    def remove_job(self, job_id: str) -> bool:
        """移除任务"""
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"[Scheduler] 移除任务 {job_id}")
            return True
        except Exception as e:
            logger.warning(f"[Scheduler] 移除任务失败 {job_id}: {e}")
            return False

    def pause_job(self, job_id: str) -> bool:
        """暂停任务"""
        try:
            self.scheduler.pause_job(job_id)
            logger.info(f"[Scheduler] 暂停任务 {job_id}")
            return True
        except Exception:
            return False

    def resume_job(self, job_id: str) -> bool:
        """恢复任务"""
        try:
            self.scheduler.resume_job(job_id)
            logger.info(f"[Scheduler] 恢复任务 {job_id}")
            return True
        except Exception:
            return False

    def list_jobs(self) -> list[dict[str, Any]]:
        """列出所有任务"""
        jobs = []
        for job in self.scheduler.get_jobs():
            trigger_desc = str(job.trigger) if job.trigger else ""
            # next_run_time 在调度器未启动时可能无法计算
            try:
                next_run = job.next_run_time
                next_run_str = next_run.isoformat() if next_run else None
            except (AttributeError, ValueError):
                next_run_str = None
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": next_run_str,
                    "trigger": trigger_desc,
                    "pending": job.pending,
                }
            )
        return jobs

    def start(self):
        """启动调度器"""
        if not self._started:
            self.scheduler.start()
            self._started = True
            logger.info("[Scheduler] ✅ 调度器已启动")
        else:
            logger.info("[Scheduler] 调度器已在运行中")

    def shutdown(self, wait: bool = True):
        """关闭调度器"""
        if self._started:
            self.scheduler.shutdown(wait=wait)
            self._started = False
            logger.info("[Scheduler] 调度器已关闭")


# ========== 预设任务定义 ==========

# 全局实例
task_scheduler = TaskSchedulerService()


def register_default_tasks(scheduler: TaskSchedulerService):
    """注册默认预设定时任务"""

    # -------- 收盘时段任务(15:00后) --------
    scheduler.add_cron_job(
        _job_daily_data_refresh,
        "daily_data_refresh",
        hour=15,
        minute=10,
        name="日行情刷新",
        description="拉取当日K线、更新数据库",
    )
    scheduler.add_cron_job(
        _job_daily_close_settle,
        "daily_close_settle",
        hour=15,
        minute=20,
        name="收盘归总",
        description="市值快照、收益结算",
    )
    scheduler.add_cron_job(
        _job_ai_review,
        "daily_ai_review",
        hour=15,
        minute=30,
        name="AI每日复盘",
        description="AI分析当日持仓表现",
    )

    # -------- 盘前任务(09:00前) --------
    scheduler.add_cron_job(
        _job_market_scan,
        "market_scan",
        hour=9,
        minute=0,
        name="智能选股扫描",
        description="从股票池筛选当日标的",
        day_of_week="mon-fri",
    )

    # -------- 盘中循环(每30分钟) --------
    scheduler.add_interval_job(
        _job_market_snapshot,
        "market_snapshot",
        minutes=30,
        name="大盘快照",
        description="记录指数行情快照",
    )

    # -------- 系统维护(每小时) --------
    scheduler.add_interval_job(
        _job_health_check, "health_check", minutes=60, name="健康检查", description="各服务健康检查"
    )

    logger.info(f"[Scheduler] 已注册 {len(scheduler.list_jobs())} 个默认任务")


# ========== 任务实现 ==========


async def _job_daily_data_refresh():
    """日行情刷新：拉取当日K线、更新数据库"""
    logger.info("[定时任务] 执行日行情刷新...")
    try:
        from core.config import settings

        from services.data_service import DataService

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        if hasattr(ds, "sync_daily_data"):
            await ds.sync_daily_data()
            logger.info("[定时任务] 日行情刷新完成")
        else:
            logger.info("[定时任务] 日行情刷新跳过(无sync_daily_data方法)")
    except Exception as e:
        logger.error(f"[定时任务] 日行情刷新失败: {e}")


async def _job_daily_close_settle():
    """收盘归总：市值快照、收益结算写入数据库"""
    logger.info("[定时任务] 执行收盘归总...")
    try:
        from datetime import date, datetime

        from core.config import settings
        from models.database import get_db_session

        from services.data_service import DataService

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)

        # 获取股票池行情
        stock_pool = ds.get_stock_pool(limit=50) if hasattr(ds, "get_stock_pool") else []
        indices = ds.get_index_realtime_quote() if hasattr(ds, "get_index_realtime_quote") else []

        # 写入每日快照
        snapshot = {
            "date": date.today().isoformat(),
            "indices": {i.get("code", ""): i for i in indices} if indices else {},
            "stock_pool_count": len(stock_pool),
            "created_at": datetime.now().isoformat(),
        }

        # 尝试写入数据库
        try:
            import json

            db = get_db_session()
            db.execute(
                "INSERT INTO daily_snapshots (date, data) VALUES (:d, :data) "
                "ON CONFLICT (date) DO UPDATE SET data = :data",
                {"d": date.today(), "data": json.dumps(snapshot, ensure_ascii=False)},
            )
            db.commit()
            logger.info(f"[定时任务] 收盘归总完成：{len(stock_pool)}只股票，{len(indices)}个指数")
        except Exception as db_e:
            logger.warning(f"[定时任务] 收盘归总 DB写入失败（非致命）: {db_e}")
            logger.info(f"[定时任务] 收盘归总完成（仅内存）：{len(stock_pool)}只股票")

    except Exception as e:
        logger.error(f"[定时任务] 收盘归总失败: {e}")


async def _job_ai_review():
    """AI每日复盘：调用AI服务分析当日持仓表现（v1.1 缓存优化版）"""
    logger.info("[定时任务] 执行AI每日复盘...")
    try:
        from core.config import settings
        from repositories.account_repo import account_repo

        from services.ai_client import AIClient, ModelProvider

        # 获取持仓数据
        positions = account_repo.get_positions() if hasattr(account_repo, "get_positions") else []
        if not positions:
            logger.info("[定时任务] AI复盘跳过：无持仓数据")
            return

        # 构建持仓文本（动态→不命中）
        pos_text = "\n".join(
            [
                f"- {p.get('ts_code', '未知')}: 成本{p.get('cost_price', 0):.2f}, 现价{p.get('current_price', 0):.2f}, 盈亏{p.get('pnl_pct', 0) * 100:.1f}%"
                for p in positions[:10]
            ]
        )

        # 系统提示词（固定→缓存命中）+ 用户消息（仅变量→不命中）
        system_prompt = """你是一位专业量化分析师。分析要求：
1. 整体收益评估
2. 风险敞口分析
3. 明日操作建议（含止损止盈价位）
4. 市场环境匹配度
输出简洁报告格式。"""

        user_message = f"请分析以下持仓表现：\n{pos_text}"

        api_key = settings.DEEPSEEK_API_KEY
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY 未配置")

        client = AIClient(api_keys={ModelProvider.DEEPSEEK: api_key})
        response = await client.call(
            provider=ModelProvider.DEEPSEEK,
            model_name="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=4096,
        )

        if not response.success:
            logger.warning(f"[定时任务] AI复盘调用失败: {response.error}")
            return

        # 更新 Grafana 指标
        from main import ai_review_completed_today

        ai_review_completed_today.set(1)

        logger.info(
            f"[定时任务] AI复盘完成 ({len(response.content)}字符, {response.input_tokens}+{response.output_tokens}tokens, ${response.cost:.4f})"
        )
    except Exception as e:
        logger.error(f"[定时任务] AI复盘失败: {e}")


async def _job_market_scan():
    """智能选股扫描：从股票池筛选当日标的（v1.1 修复AIScanEngine不存在的问题）"""
    logger.info("[定时任务] 执行智能选股扫描...")
    try:
        from core.config import settings

        from services.ai_scheduler import AIModelScheduler, TaskComplexity, TaskType
        from services.data_service import DataService

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)

        # 获取候选池
        candidates = ds.get_stock_pool(limit=100) if hasattr(ds, "get_stock_pool") else []
        if not candidates:
            logger.info("[定时任务] 智能选股跳过：候选池为空")
            return

        # 使用 AIModelScheduler 进行选股分析
        budget = getattr(settings, "AI_BUDGET_TOTAL", 500)
        scheduler = AIModelScheduler(total_budget=budget)
        selected_model = scheduler.select_model(
            TaskType.STOCK_SELECTION, TaskComplexity.MEDIUM_HIGH
        )
        logger.info(f"[定时任务] 智能选股使用模型: {selected_model}，候选{len(candidates)}只")

        # 执行选股分析
        from services.ai_client import AIClient, ModelProvider

        api_key = settings.DEEPSEEK_API_KEY
        if api_key:
            client = AIClient(api_keys={ModelProvider.DEEPSEEK: api_key})
            # 构建扫描prompt
            candidates_text = "\n".join(
                [
                    f"- {c.get('ts_code', '未知')} {c.get('name', '')}: 现价{c.get('close', 0):.2f}"
                    for c in candidates[:20]
                ]
            )
            system_prompt = "你是一位量化选股分析师。请从候选池中筛选出当日最有潜力的标的。"
            user_message = f"候选池：\n{candidates_text}\n\n请选出TOP3并给出理由。"

            result = client.call_sync(
                provider=ModelProvider.DEEPSEEK,
                model_name="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=2048,
            )
            if result.success:
                logger.info(f"[定时任务] 智能选股完成 ({len(result.content)}字符)")
            else:
                logger.warning(f"[定时任务] 智能选股AI调用失败: {result.error}")
        else:
            logger.warning("[定时任务] 智能选股跳过：DEEPSEEK_API_KEY未配置")

    except Exception as e:
        logger.error(f"[定时任务] 智能选股失败: {e}")
        try:
            engine = AIScanEngine()
            results = await engine.scan(candidates) if hasattr(engine, "scan") else []
            logger.info(f"[定时任务] 智能选股完成：{len(results)}只入选")
        except ImportError:
            logger.info(f"[定时任务] 智能选股跳过(AI引擎未就绪)：候选池{len(candidates)}只")
        except Exception as scan_e:
            logger.warning(f"[定时任务] AI扫描出错(非致命): {scan_e}")

    except Exception as e:
        logger.error(f"[定时任务] 智能选股失败: {e}")


async def _job_market_snapshot():
    """大盘快照：记录指数行情到时间序列"""
    logger.info("[定时任务] 大盘快照...")
    try:
        from datetime import datetime

        from core.config import settings

        from services.data_service import DataService

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        indices = ds.get_index_realtime_quote() if hasattr(ds, "get_index_realtime_quote") else []

        # 写入时间序列
        try:
            from models.database import get_db_session

            db = get_db_session()
            ts = datetime.now()
            for idx in indices:
                code = idx.get("code", "")
                db.execute(
                    "INSERT INTO index_snapshots (ts_code, price, pct_change, volume, recorded_at) "
                    "VALUES (:code, :price, :pct, :vol, :ts)",
                    {
                        "code": code,
                        "price": idx.get("price", 0),
                        "pct": idx.get("pct_change", 0),
                        "vol": idx.get("volume", 0),
                        "ts": ts,
                    },
                )
            db.commit()
            logger.info(f"[定时任务] 大盘快照完成：{len(indices)}个指数")
        except Exception as db_e:
            logger.warning(f"[定时任务] 大盘快照 DB写入失败（非致命）: {db_e}")

    except Exception as e:
        logger.error(f"[定时任务] 大盘快照失败: {e}")


async def _job_health_check():
    """系统健康检查：检查各服务端点"""
    logger.info("[定时任务] 系统健康检查...")
    try:
        import aiohttp

        from shared.middleware import get_trace_headers

        services = {
            "strategy": "http://localhost:8000/health",
            "execution": "http://localhost:8001/health",
        }

        statuses = {}
        async with aiohttp.ClientSession(headers=get_trace_headers()) as session:
            for name, url in services.items():
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        statuses[name] = "UP" if resp.status == 200 else f"DOWN({resp.status})"
                except Exception:
                    statuses[name] = "DOWN"

        up_count = sum(1 for v in statuses.values() if v == "UP")
        logger.info(f"[定时任务] 健康检查完成：{up_count}/{len(services)} UP - {statuses}")

        if up_count < len(services):
            logger.warning(
                f"[定时任务] ⚠️ 部分服务不可用: {[k for k, v in statuses.items() if v != 'UP']}"
            )

    except ImportError:
        logger.info("[定时任务] 健康检查跳过(aiohttp未安装)")
    except Exception as e:
        logger.error(f"[定时任务] 健康检查失败: {e}")
