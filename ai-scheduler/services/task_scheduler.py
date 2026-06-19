"""
任务调度执行器 — 后台异步执行 scan / review 任务

核心职责：
1. 协调 StrategyClient + LLMClient 完成业务逻辑
2. 更新任务进度和状态（pending → running → completed/failed）
3. 通过 WebSocket 广播任务状态变更
4. 异常兜底，保证任务不会永久 stuck
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

from api.ws_scheduler import broadcast_task_update
from services.llm_client import LLMClient
from services.strategy_client import StrategyClient

logger = logging.getLogger(__name__)


class TaskScheduler:
    """任务调度执行器

    管理 scan/review 两类后台任务的异步执行生命周期。
    任务状态存储由外部传入的 dict 管理（与 api/schedule.py 共享 _tasks 引用）。
    """

    def __init__(
        self,
        task_store: dict,
        strategy_client: StrategyClient | None = None,
        llm_client: LLMClient | None = None,
    ):
        """
        Args:
            task_store: 任务状态存储字典引用（通常是 api.schedule._tasks）
            strategy_client: 策略服务客户端（未传入则自动创建）
            llm_client: AI 模型客户端（未传入则自动创建）
        """
        self._tasks = task_store
        self._strategy_client = strategy_client or StrategyClient()
        self._llm_client = llm_client or LLMClient()

    # ─── 公开方法 ──────────────────────────────────────────────────────

    async def execute_scan(self, task_id: str, params: dict) -> None:
        """异步执行选股扫描任务

        流程: 策略扫描 → AI 分析候选股 → 完成
        """
        try:
            self._update_task(task_id, "running", 0.1, "正在连接策略服务...")

            # 阶段 1: 调用策略服务扫描选股 (progress 0.1 → 0.5)
            candidates = await self._strategy_client.scan_stocks(
                limit=params.get("limit", 100),
                strategy_ids=params.get("strategy_ids"),
                ts_codes=params.get("ts_codes"),
            )
            self._update_task(
                task_id, "running", 0.5,
                f"策略扫描完成，共 {len(candidates)} 只候选股票",
            )

            # 阶段 2: AI 分析候选股票 (progress 0.5 → 0.9)
            if candidates and params.get("ai_analysis", True):
                analyses = []
                top_n = min(len(candidates), 5)
                for i, stock in enumerate(candidates[:top_n]):
                    try:
                        analysis = await self._llm_client.analyze_stock(stock)
                        analyses.append({
                            "stock": stock.get("ts_code"),
                            "analysis": analysis,
                        })
                    except Exception as e:
                        logger.warning(
                            "[%s] AI分析失败(%s): %s",
                            task_id, stock.get("ts_code"), e,
                        )
                    progress = 0.5 + (i + 1) / top_n * 0.4
                    self._update_task(
                        task_id, "running", round(progress, 2),
                        f"AI分析中 ({i + 1}/{top_n})",
                    )
                self._update_task(
                    task_id, "running", 0.9,
                    f"AI分析完成，共分析 {len(analyses)} 只股票",
                )
            else:
                self._update_task(task_id, "running", 0.9, "跳过AI分析")

            # 阶段 3: 完成 (progress 1.0)
            skip_note = ""
            if candidates and not params.get("ai_analysis", True):
                skip_note = "（跳过AI分析）"
            self._update_task(
                task_id, "completed", 1.0,
                f"扫描完成，共处理 {len(candidates)} 只股票{skip_note}",
            )
            logger.info("[%s] 扫描任务完成", task_id)

        except Exception as e:
            logger.error("[%s] 扫描任务失败: %s", task_id, e)
            self._update_task(task_id, "failed", 0.0, f"扫描失败: {e}")

    async def execute_review(self, task_id: str, params: dict) -> None:
        """异步执行每日复盘任务

        流程: 获取市场数据 → AI 生成复盘报告 → 完成
        """
        try:
            self._update_task(task_id, "running", 0.1, "正在获取市场数据...")

            # 阶段 1: 获取市场数据 (progress 0.1 → 0.3)
            try:
                market_data = await self._fetch_market_data()
            except Exception as e:
                logger.warning("[%s] 获取市场数据失败: %s", task_id, e)
                market_data = {}

            self._update_task(task_id, "running", 0.3, "市场数据获取完成")

            # 阶段 2: AI 生成复盘报告 (progress 0.3 → 0.9)
            if params.get("include_ai", True):
                try:
                    report = await self._llm_client.generate_review(market_data)
                    self._update_task(
                        task_id, "running", 0.9,
                        "AI复盘报告生成完成",
                    )
                    logger.info(
                        "[%s] AI复盘报告已生成（%d chars）",
                        task_id, len(report),
                    )
                except Exception as e:
                    logger.warning("[%s] AI复盘生成失败: %s", task_id, e)
                    report = f"AI复盘生成失败: {e}"
                    self._update_task(task_id, "running", 0.9, "AI复盘生成失败")
            else:
                report = "（未包含AI分析）"
                self._update_task(task_id, "running", 0.9, "跳过AI复盘")

            # 阶段 3: 完成 (progress 1.0)
            raw_review_date = params.get("date")
            review_date = raw_review_date if raw_review_date else datetime.now().strftime("%Y-%m-%d")
            ai_note = ""
            if not params.get("include_ai", True):
                ai_note = "（跳过AI复盘）"
            elif isinstance(report, str) and "AI复盘生成失败" in report:
                ai_note = "（AI复盘生成失败）"
            self._update_task(
                task_id, "completed", 1.0,
                f"复盘报告已生成（日期: {review_date}）{ai_note}".strip(),
            )
            logger.info("[%s] 复盘任务完成", task_id)

        except Exception as e:
            logger.error("[%s] 复盘任务失败: %s", task_id, e)
            self._update_task(task_id, "failed", 0.0, f"复盘失败: {e}")

    # ─── 内部方法 ──────────────────────────────────────────────────────

    async def _fetch_market_data(self) -> dict:
        """从策略服务获取简版市场数据"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                indices = []
                for idx_code in ["000001.SH", "399001.SZ", "399006.SZ"]:
                    try:
                        resp = await client.get(
                            f"{self._strategy_client.base_url}"
                            f"/api/v1/quotes/{idx_code}",
                        )
                        if resp.status_code == 200:
                            indices.append(resp.json())
                    except Exception:
                        pass
                return {"indices": indices, "advance": 0, "decline": 0}
        except Exception as e:
            logger.debug("获取市场数据失败: %s", e)
            return {"indices": [], "advance": 0, "decline": 0}

    def _update_task(
        self,
        task_id: str,
        status: str,
        progress: float,
        message: str,
    ) -> None:
        """更新任务状态并广播到 WebSocket"""
        # 更新存储
        task = self._tasks.get(task_id)
        if task:
            task["status"] = status
            task["progress"] = progress
            task["message"] = message

        logger.debug(
            "[%s] %s (%.0f%%) - %s", task_id, status, progress * 100, message,
        )

        # 广播到 WebSocket（非阻塞）
        try:
            asyncio.ensure_future(
                broadcast_task_update(
                    task_id=task_id,
                    task_name=task.get("task_type", "unknown") if task else "unknown",
                    status=status,
                    detail=message,
                ),
            )
        except Exception as e:
            logger.debug("[%s] WebSocket广播失败（非关键）: %s", task_id, e)
