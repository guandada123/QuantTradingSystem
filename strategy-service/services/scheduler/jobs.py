"""
任务实现 — 6 个预设定时任务的具体业务逻辑

结构化日志字段说明：
    - duration_ms: 任务执行耗时（毫秒）
    - count: 处理的数据量
    - tokens_in/tokens_out/cost: AI API 调用统计
    - fallback: 降级链标记
"""

import time
from datetime import date

from shared.structured_log import get_logger

logger = get_logger(__name__)


async def daily_data_refresh():
    """日行情刷新：拉取当日K线、更新数据库"""
    t0 = time.monotonic()
    logger.info("[定时任务] 执行日行情刷新")
    try:
        from core.config import settings

        from services.data_service import DataService

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        if hasattr(ds, "sync_daily_data"):
            await ds.sync_daily_data()  # type: ignore[misc]
            duration_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "[定时任务] 日行情刷新完成",
                duration_ms=round(duration_ms, 1),
            )
        else:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "[定时任务] 日行情刷新跳过(无sync_daily_data方法)",
                duration_ms=round(duration_ms, 1),
            )
    except Exception as e:
        duration_ms = (time.monotonic() - t0) * 1000
        logger.error(
            "[定时任务] 日行情刷新失败",
            error=str(e),
            duration_ms=round(duration_ms, 1),
        )


async def daily_close_settle():
    """收盘归总：市值快照、收益结算写入数据库"""
    t0 = time.monotonic()
    logger.info("[定时任务] 执行收盘归总")
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
                duration_ms = (time.monotonic() - t0) * 1000
                logger.info(
                    "[定时任务] 收盘归总完成",
                    stock_count=len(stock_pool),
                    index_count=len(indices),
                    duration_ms=round(duration_ms, 1),
                )
        except Exception as db_e:
            logger.warning(
                "[定时任务] 收盘归总 DB写入失败（非致命）",
                error=str(db_e),
                stock_count=len(stock_pool),
            )
            duration_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "[定时任务] 收盘归总完成（仅内存）",
                stock_count=len(stock_pool),
                duration_ms=round(duration_ms, 1),
            )

    except Exception as e:
        duration_ms = (time.monotonic() - t0) * 1000
        logger.error(
            "[定时任务] 收盘归总失败",
            error=str(e),
            duration_ms=round(duration_ms, 1),
        )


async def ai_review():
    """AI每日复盘：调用AI服务分析当日持仓表现（v1.1 缓存优化版）"""
    t0 = time.monotonic()
    logger.info("[定时任务] 执行AI每日复盘")

    # 前置依赖检查：account_repo 可能已废弃
    try:
        from repositories.account_repo import account_repo  # type: ignore[attr-defined]
    except ImportError as e:
        duration_ms = (time.monotonic() - t0) * 1000
        logger.warning(
            "[定时任务] AI复盘跳过: account_repo 不可用 (repo 可能已废弃)",
            error=str(e),
            duration_ms=round(duration_ms, 1),
        )
        return

    try:
        from core.config import settings

        from services.ai_client import AIClient, ModelProvider

        # 获取持仓数据
        positions = account_repo.get_positions() if hasattr(account_repo, "get_positions") else []
        if not positions:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "[定时任务] AI复盘跳过：无持仓数据",
                duration_ms=round(duration_ms, 1),
            )
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
        ai_t0 = time.monotonic()
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
        ai_duration = (time.monotonic() - ai_t0) * 1000

        if not response.success:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "[定时任务] AI复盘调用失败",
                error=response.error,
                ai_duration_ms=round(ai_duration, 1),
                duration_ms=round(duration_ms, 1),
            )
            return

        # 更新 Grafana 指标
        from main import ai_review_completed_today

        ai_review_completed_today.set(1)

        # ★ v1.2 推送飞书（此前产出只写日志，无人消费）
        try:
            from core.config import settings

            from services.feishu_alert import AlertLevel, AlertType, get_alert_service

            alert = get_alert_service(settings.FEISHU_WEBHOOK)
            if alert and alert.enabled:
                await alert.send_alert(
                    alert_type=AlertType.SIGNAL,
                    level=AlertLevel.INFO,
                    title=f"AI 每日复盘 ({date.today().isoformat()})",
                    content=response.content[:3000],  # 飞书卡片长度限制
                    data={
                        "tokens_in": str(response.input_tokens),
                        "tokens_out": str(response.output_tokens),
                        "cost": str(round(response.cost, 4)) if response.cost else "0",
                    },
                )
            # v2: 同时写入共享文件供 Claw 晚报引用
            try:
                import json as _json
                from pathlib import Path as _Path

                review_file = _Path("/app/shared/qts_ai_review.json")
                review_file.write_text(
                    _json.dumps(
                        {
                            "date": date.today().isoformat(),
                            "content": response.content,
                            "tokens": {"in": response.input_tokens, "out": response.output_tokens},
                            "generated_at": __import__("datetime").datetime.now().isoformat(),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except Exception:
                pass
        except Exception as push_e:
            logger.warning(f"[定时任务] AI复盘飞书推送失败(非致命): {push_e}")

        duration_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "[定时任务] AI复盘完成",
            chars=len(response.content),
            tokens_in=response.input_tokens,
            tokens_out=response.output_tokens,
            cost=round(response.cost, 4) if response.cost else 0,
            ai_duration_ms=round(ai_duration, 1),
            duration_ms=round(duration_ms, 1),
        )
    except Exception as e:
        duration_ms = (time.monotonic() - t0) * 1000
        logger.error(
            "[定时任务] AI复盘失败",
            error=str(e),
            duration_ms=round(duration_ms, 1),
        )


async def market_scan():
    """智能选股扫描：从股票池筛选当日标的（v1.1 修复AIScanEngine不存在的问题）"""
    t0 = time.monotonic()
    logger.info("[定时任务] 执行智能选股扫描")
    try:
        from core.config import settings

        from services.ai_scheduler import AIModelScheduler, TaskComplexity, TaskType
        from services.data_service import DataService

        ds = DataService(tushare_token=settings.TUSHARE_TOKEN or None)

        # 获取候选池
        candidates = ds.get_stock_pool(limit=100) if hasattr(ds, "get_stock_pool") else []
        candidates_count = len(candidates)
        if not candidates:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "[定时任务] 智能选股跳过：候选池为空",
                duration_ms=round(duration_ms, 1),
            )
            return

        # 使用 AIModelScheduler 进行选股分析
        budget = getattr(settings, "AI_BUDGET_TOTAL", 500)
        scheduler = AIModelScheduler(total_budget=budget)
        selected_model = scheduler.select_model(
            TaskType.STOCK_SELECTION, TaskComplexity.MEDIUM_HIGH
        )
        logger.info(
            "[定时任务] 智能选股使用模型",
            model=selected_model,
            candidate_count=candidates_count,
        )

        # 执行选股分析
        from services.ai_client import AIClient, ModelProvider

        api_key = settings.DEEPSEEK_API_KEY
        if api_key:
            client = AIClient(api_keys={ModelProvider.DEEPSEEK: api_key})
            # 构建扫描prompt — v1.3 批量查询技术指标（修复循环内反复开DB）
            candidates_text_parts = []
            try:
                codes_list = [c.get("ts_code", "") for c in candidates[:20] if c.get("ts_code")]
                if codes_list:
                    from models.database import get_db_session

                    placeholders = ",".join([f":c{i}" for i in range(len(codes_list))])
                    with get_db_session() as db:
                        # 批量查询：一次性获取所有股票的 MA20/RSI/换手率（最新一条）
                        rows = db.execute(
                            f"""SELECT DISTINCT ON (ts_code) ts_code, ma20, rsi14, turnover_rate
                                FROM daily_quote
                                WHERE ts_code IN ({placeholders})
                                ORDER BY ts_code, trade_date DESC""",  # noqa: S608 — safe: {placeholders} are :cN bind params
                            {f"c{i}": code for i, code in enumerate(codes_list)},
                        ).fetchall()
                    # 建立代码→指标映射
                    indicator_map: dict[str, tuple] = {}
                    for row in rows:
                        indicator_map[row[0]] = (row[1], row[2], row[3])

                    for c in candidates[:20]:
                        ts_code = c.get("ts_code", "")
                        name = c.get("name", "")
                        close = c.get("close", 0)
                        ind = indicator_map.get(ts_code)
                        if ind:
                            ma20_val = f"{float(ind[0]):.2f}" if ind[0] else "N/A"
                            rsi_val = f"{float(ind[1]):.0f}" if ind[1] else "N/A"
                            turnover_val = f"{float(ind[2]):.1f}%" if ind[2] else "N/A"
                        else:
                            ma20_val = rsi_val = turnover_val = "N/A"
                        candidates_text_parts.append(
                            f"- {ts_code} {name}: 现价{close:.2f} MA20={ma20_val} RSI={rsi_val} 换手={turnover_val}"
                        )
            except Exception:
                candidates_text_parts = [
                    f"- {c.get('ts_code', '未知')} {c.get('name', '')}: 现价{c.get('close', 0):.2f}"
                    for c in candidates[:20]
                ]
            candidates_text = "\n".join(candidates_text_parts)
            system_prompt = "你是一位量化选股分析师。请基于提供的技术指标从候选池中筛选出当日最有潜力的标的。优先考虑：MA20 附近企稳 + RSI 不超买（<70）+ 换手率活跃。"
            user_message = f"候选池（含技术指标）：\n{candidates_text}\n\n请选出TOP3并给出理由。"

            ai_t0 = time.monotonic()
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
            ai_duration = (time.monotonic() - ai_t0) * 1000

            duration_ms = (time.monotonic() - t0) * 1000
            if result.success:
                logger.info(
                    "[定时任务] 智能选股AI完成",
                    chars=len(result.content),
                    ai_duration_ms=round(ai_duration, 1),
                    candidate_count=candidates_count,
                    duration_ms=round(duration_ms, 1),
                )
            else:
                logger.warning(
                    "[定时任务] 智能选股AI调用失败，准备降级",
                    error=result.error,
                    ai_duration_ms=round(ai_duration, 1),
                    fallback="stock_insight_engine",
                    duration_ms=round(duration_ms, 1),
                )
        else:
            logger.warning(
                "[定时任务] 智能选股跳过：DEEPSEEK_API_KEY未配置",
                candidate_count=candidates_count,
            )

    except Exception as e:
        logger.warning(
            "[定时任务] 智能选股AI异常，尝试降级引擎",
            error=str(e),
            fallback="stock_insight_engine",
        )
        try:
            from services.data_service import DataService  # noqa: F811
            from services.stock_insight_engine import StockInsightEngine

            ds_fallback = DataService()
            engine = StockInsightEngine(data_service=ds_fallback)
            results = engine.scan(candidates) if hasattr(engine, "scan") else []
            duration_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "[定时任务] 智能选股降级完成",
                result_count=len(results),
                fallback="stock_insight_engine",
                duration_ms=round(duration_ms, 1),
            )
        except ImportError:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "[定时任务] 智能选股跳过(AI引擎未就绪)",
                candidate_count=candidates_count,
                duration_ms=round(duration_ms, 1),
            )
        except Exception as scan_e:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "[定时任务] AI扫描出错(非致命)",
                error=str(scan_e),
                candidate_count=candidates_count,
                duration_ms=round(duration_ms, 1),
            )


async def market_snapshot():
    """大盘快照：记录指数行情到时间序列"""
    t0 = time.monotonic()
    logger.info("[定时任务] 大盘快照")
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
            written = 0
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
                    written += 1
                db.commit()
            duration_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "[定时任务] 大盘快照完成",
                index_count=written,
                duration_ms=round(duration_ms, 1),
            )
        except Exception as db_e:
            logger.warning(
                "[定时任务] 大盘快照 DB写入失败（非致命）",
                error=str(db_e),
                index_count=len(indices),
            )

    except Exception as e:
        duration_ms = (time.monotonic() - t0) * 1000
        logger.error(
            "[定时任务] 大盘快照失败",
            error=str(e),
            duration_ms=round(duration_ms, 1),
        )


async def health_check():
    """系统健康检查：检查各服务端点"""
    t0 = time.monotonic()
    logger.info("[定时任务] 系统健康检查")
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
        total = len(services)
        duration_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "[定时任务] 健康检查完成",
            up_count=up_count,
            total=total,
            services=str(statuses),
            duration_ms=round(duration_ms, 1),
        )

        if up_count < total:
            down_services = [k for k, v in statuses.items() if v != "UP"]
            logger.warning(
                "[定时任务] 部分服务不可用",
                down_services=",".join(down_services),
                up_count=up_count,
                total=total,
            )

    except ImportError:
        duration_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "[定时任务] 健康检查跳过(aiohttp未安装)",
            duration_ms=round(duration_ms, 1),
        )
    except Exception as e:
        duration_ms = (time.monotonic() - t0) * 1000
        logger.error(
            "[定时任务] 健康检查失败",
            error=str(e),
            duration_ms=round(duration_ms, 1),
        )
