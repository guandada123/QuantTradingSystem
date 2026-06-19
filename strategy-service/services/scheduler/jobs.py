"""
任务实现 — 6 个预设定时任务的具体业务逻辑
"""

import logging

logger = logging.getLogger(__name__)


async def daily_data_refresh():
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


async def daily_close_settle():
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

            with get_db_session() as db:
                db.execute(
                    "INSERT INTO daily_snapshots (date, data) VALUES (:d, :data) "
                    "ON CONFLICT (date) DO UPDATE SET data = :data",
                    {"d": date.today(), "data": json.dumps(snapshot, ensure_ascii=False)},
                )
                db.commit()
                logger.info(
                    f"[定时任务] 收盘归总完成：{len(stock_pool)}只股票，{len(indices)}个指数"
                )
        except Exception as db_e:
            logger.warning(f"[定时任务] 收盘归总 DB写入失败（非致命）: {db_e}")
            logger.info(f"[定时任务] 收盘归总完成（仅内存）：{len(stock_pool)}只股票")

    except Exception as e:
        logger.error(f"[定时任务] 收盘归总失败: {e}")


async def ai_review():
    """AI每日复盘：调用AI服务分析当日持仓表现（v1.1 缓存优化版）"""
    logger.info("[定时任务] 执行AI每日复盘...")

    # 前置依赖检查：account_repo 可能已废弃
    try:
        from repositories.account_repo import account_repo
    except ImportError as e:
        logger.warning("[定时任务] AI复盘跳过: account_repo 不可用 (repo 可能已废弃): %s", e)
        return

    try:
        from core.config import settings

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


async def market_scan():
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
            from services.data_service import DataService  # noqa: F811
            from services.stock_insight_engine import StockInsightEngine

            engine = StockInsightEngine()
            results = engine.scan(candidates) if hasattr(engine, "scan") else []
            logger.info(f"[定时任务] 智能选股完成：{len(results)}只入选")
        except ImportError:
            logger.info(f"[定时任务] 智能选股跳过(AI引擎未就绪)：候选池{len(candidates)}只")
        except Exception as scan_e:
            logger.warning(f"[定时任务] AI扫描出错(非致命): {scan_e}")


async def market_snapshot():
    """大盘快照：记录指数行情到时间序列"""
    logger.info("[定时任务] 大盘快照...")
    try:
        from datetime import datetime

        from core.config import settings
        from models.database import get_db_session

        from services.data_service import DataService

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        indices = ds.get_index_realtime_quote() if hasattr(ds, "get_index_realtime_quote") else []

        # 写入时间序列
        try:
            ts = datetime.now()
            with get_db_session() as db:
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


async def health_check():
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
