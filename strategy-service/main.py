"""
策略研究服务 - 主应用入口 v2.0
新增：WebSocket实时推送、后台定时任务、Prometheus指标采集
"""

import asyncio
from contextlib import asynccontextmanager
import os

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)


# Safe metric creation — avoid ValueError when module is re-imported
def _gauge(name, desc, labels=None):
    """Safely create a Gauge, returning existing if already registered."""
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return Gauge(name, desc, labels or [])


def _counter(name, desc, labels=None):
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return Counter(name, desc, labels or [])


def _histogram(name, desc, labels=None):
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return Histogram(name, desc, labels or [])


import uvicorn

from shared.auth import get_current_user
from shared.logging_config import configure_logging, get_logger
from shared.middleware import TraceIDMiddleware, setup_trace_logging

configure_logging("strategy-service")
setup_trace_logging()
logger = get_logger(__name__)

# ============================================================
# Prometheus 指标定义
# ============================================================

# WebSocket
# WebSocket 指标（由 ws_manager 回调更新）
websocket_connections_active = _gauge(
    "websocket_connections_active", "Active WebSocket connections", ["service"]
)

# 交易信号
signals_generated_today = _counter("signals_generated_today", "Signals generated today")
signals_buy_count = _counter("signals_buy_count", "Buy signals generated")
signals_sell_count = _counter("signals_sell_count", "Sell signals generated")

# Grafana dashboard metrics (table sources)
trading_signals = _gauge(
    "trading_signals", "Trading signals for dashboard table", ["ts_code", "action", "reason"]
)
current_positions = _gauge(
    "current_positions", "Current positions for dashboard table", ["ts_code", "name"]
)
ai_review_completed_today = _gauge("ai_review_completed_today", "AI review completed today (1=yes)")

# 当日自动重置标志
_last_reset_date: str | None = None


async def _reset_daily_gauges():
    """每日重置当日指标"""
    global _last_reset_date
    from datetime import date

    today = date.today().isoformat()
    if _last_reset_date != today:
        ai_review_completed_today.set(0)
        _last_reset_date = today
        logger.debug(f"[Metrics] 当日指标已重置 ({today})")


async def _update_positions_metrics():
    """定期更新持仓指标"""
    try:
        from models.database import get_db_session

        with get_db_session() as db:
            result = db.execute(
                "SELECT p.ts_code, COALESCE(s.name, p.ts_code) as name "
                "FROM positions p LEFT JOIN stock_pool s ON p.ts_code = s.ts_code"
            )
            for row in result.fetchall():
                current_positions.labels(ts_code=row[0], name=row[1]).set(1)
    except Exception as e:
        logger.debug(f"更新持仓指标跳过（非关键）: {e}")


# 组合指标
portfolio_pnl_total = _gauge("portfolio_pnl_total", "Total portfolio P&L")
portfolio_return_daily = _gauge("portfolio_return_daily", "Daily portfolio return ratio")
position_market_value = _gauge("position_market_value", "Total position market value", ["ts_code"])

# 交易统计
trade_win_rate_7d = _gauge("trade_win_rate_7d", "7-day win rate")

# AI 调用
ai_calls_total = _counter("ai_calls_total", "Total AI calls", ["model", "task_type"])
ai_daily_cost = _gauge("ai_daily_cost", "Daily AI cost")
ai_budget_usage_ratio = _gauge("ai_budget_usage_ratio", "AI budget usage ratio")

# 账户指标
account_total_assets = _gauge("account_total_assets", "Total account assets")
account_total_return_ratio = _gauge("account_total_return_ratio", "Total return ratio")
account_day_profit_loss = _gauge("account_day_profit_loss", "Daily profit/loss")
account_daily_value = _gauge("account_daily_value", "Daily account value")
account_drawdown = _gauge("account_drawdown", "Current drawdown")

# 策略指标
strategy_sharpe_ratio = _gauge("strategy_sharpe_ratio", "Strategy Sharpe ratio")

# HTTP 指标
http_requests_total = _counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
http_request_duration_seconds = _histogram(
    "http_request_duration_seconds", "HTTP request duration", ["method", "endpoint"]
)

# WebSocket 连接管理 — 使用标准化模块
from api.ws_strategy import ws_manager as strategy_ws_manager

ws_manager = strategy_ws_manager  # 保持向后兼容
strategy_ws_manager._on_count_change = lambda n: websocket_connections_active.labels(  # type: ignore[assignment]
    service="strategy"
).set(n)


def _create_data_service():
    """延迟创建 DataService 实例（避免启动时的循环依赖）"""
    from core.config import settings
    from services.data_service import DataService

    return DataService(tushare_token=settings.TUSHARE_TOKEN or None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("策略研究服务启动中...")

    # 启动时校验配置完整性
    from core.config import settings

    try:
        ok = settings.validate_startup()
        if ok:
            logger.info("✅ 配置校验通过")
        else:
            logger.warning("⚠️ 配置校验有告警项，服务继续启动")
    except Exception as e:
        logger.critical(f"❌ 配置加载失败: {e}")
        raise SystemExit(1) from e

    # 初始化飞书告警服务（供启动阶段使用）
    from core.config import settings
    from services.feishu_alert import AlertLevel, AlertType, get_alert_service

    alert = get_alert_service(settings.FEISHU_WEBHOOK)

    # 初始化数据库连接
    try:
        from models.database import init_db

        init_db()
    except Exception as db_e:
        logger.critical(f"数据库连接失败: {db_e}")
        try:
            if alert and alert.enabled:
                await alert.send_alert(
                    alert_type=AlertType.SYSTEM_ERROR,
                    level=AlertLevel.CRITICAL,
                    title="数据库连接失败",
                    content=f"**策略服务启动异常**\n\n数据库初始化失败，服务可能无法正常运行。\n\n**错误**: {str(db_e)[:300]}",
                    data={
                        "DATABASE_URL": settings.DATABASE_URL.split("@")[-1]
                        if "@" in settings.DATABASE_URL
                        else "未知"
                    },
                )
        except Exception as e:
            logger.error(f"飞书告警发送失败: {e}")
        raise

    # 检查数据源(AkShare)可用性
    try:
        import akshare as ak

        _ = ak.stock_zh_index_spot_em()
        logger.info("数据源(AkShare)连通性检查通过")
    except Exception as ds_e:
        logger.warning(f"数据源(AkShare)不可达: {ds_e}")
        try:
            if alert and alert.enabled:
                await alert.send_alert(
                    alert_type=AlertType.SYSTEM_ERROR,
                    level=AlertLevel.WARNING,
                    title="数据源不可达",
                    content=f"**AkShare 数据源**连接异常，部分行情功能可能受限。\n\n**错误**: {str(ds_e)[:200]}",
                    data={"数据源": "AkShare", "影响": "实时行情/K线获取可能失败"},
                )
        except Exception as e:
            logger.error(f"飞书告警发送失败: {e}")

    # 启动后台任务：每3秒广播指数行情（通过 ws_strategy 模块）
    from api.ws_strategy import run_index_broadcast_loop

    broadcast_task = asyncio.create_task(run_index_broadcast_loop(ds_getter=_create_data_service))
    # 启动定时任务调度器
    from services.report_scheduler import register_report_tasks
    from services.scheduler_service import register_default_tasks, task_scheduler

    register_default_tasks(task_scheduler)
    register_report_tasks(task_scheduler)
    task_scheduler.start()
    logger.info(f"Scheduler 已启动，{len(task_scheduler.list_jobs())}个任务")

    # 启动 Prometheus 指标后台更新任务
    metrics_task = asyncio.create_task(_background_metrics_updater())
    logger.info("[Metrics] 后台指标更新任务已启动")

    # 启动数据质量监控
    dq_monitor = asyncio.create_task(_background_data_quality())
    logger.info("[DataQuality] 数据质量监控已启动")

    yield
    dq_monitor.cancel()
    metrics_task.cancel()
    await task_scheduler.shutdown(wait=True)
    broadcast_task.cancel()
    logger.info("策略研究服务关闭中...")


async def _background_metrics_updater():
    """后台任务：定期更新 Prometheus 指标"""
    while True:
        try:
            await _reset_daily_gauges()
            await _update_positions_metrics()
        except Exception as e:
            logger.debug(f"[Metrics更新] 失败: {e}")
        await asyncio.sleep(60)  # 每60秒更新一次


async def _background_data_quality():
    """后台任务：数据质量监控"""
    from services.data_quality import monitor

    await monitor.run_loop(interval=300)  # 每5分钟检查一次


app = FastAPI(
    title="QuantTradingSystem — 策略研究服务",
    description="""A股超短线量化交易系统 v2.0 · 策略研究微服务。

## 核心功能
- **股票池管理** — 多维度筛选（行业/市值/技术指标）
- **交易信号生成** — 多策略信号（双均线金叉、MACD背离、放量突破）
- **策略回测** — 历史数据回测，输出夏普比率/最大回撤/胜率
- **AI 多智能体分析** — 基本面/技术面/情绪面/资金面四维分析

## 数据源降级链路
tdx (通达信·主) → tushare (备) → akshare (第二备) → 腾讯财经 (兜底)

## 认证
生产环境需 Bearer Token (JWT) 或 X-API-Key header。
""",
    version="2.0.0",
    lifespan=lifespan,
    dependencies=[],  # Auth handled at router level in production
    openapi_tags=[
        {
            "name": "Stocks",
            "description": "股票池管理 — 标的基本面查询、K线数据、多维度筛选",
        },
        {
            "name": "Signals",
            "description": "交易信号 — 策略信号生成、信号历史、实时推送",
        },
        {
            "name": "Backtest",
            "description": "策略回测 — 历史数据模拟交易、收益归因、参数优化",
        },
        {
            "name": "AI Analysis",
            "description": "AI 分析 — 多智能体（基本面/技术面/情绪面）联合分析",
        },
        {
            "name": "Health",
            "description": "健康检查 — 服务可用性、数据源连通性",
        },
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:3030,http://localhost:8080"
    ).split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# Trace ID 中间件 — 跨服务请求链路追踪
app.add_middleware(TraceIDMiddleware)

# 响应体脱敏中间件 — 自动脱敏 API Key / Token / Secret 等敏感字段
from shared.middleware import ResponseSanitizerMiddleware  # type: ignore[attr-defined]

app.add_middleware(ResponseSanitizerMiddleware)

# 限流中间件
from shared.rate_limiter import RateLimitMiddleware

app.add_middleware(RateLimitMiddleware, max_requests=60, window_seconds=60)

# HTTP 指标中间件
import time


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    if request.url.path not in ("/metrics", "/health"):
        http_requests_total.labels(
            method=request.method, endpoint=request.url.path, status=str(response.status_code)
        ).inc()
        http_request_duration_seconds.labels(
            method=request.method, endpoint=request.url.path
        ).observe(duration)
    return response


# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"code": -1, "message": "内部服务错误"})


# 注册路由
from api import ai_router, signal_router, stock_router
from api.account import router as account_router
from api.alerts import router as alerts_router
from api.backtest_v2 import router as backtest_v2_router
from api.config import router as config_router
from api.execution import router as execution_router
from api.scheduler import router as scheduler_router
from api.strategies import router as strategies_router
from api.trades import router as trades_router
from api.ws_strategy import router as ws_router

app.include_router(stock_router, prefix="/api/v1/stocks", tags=["股票数据"])
app.include_router(signal_router, prefix="/api/v1/signals", tags=["交易信号"])
# 仅保留 V2 回测路由，避免与 legacy /backtest 路由冲突
app.include_router(backtest_v2_router, prefix="/api/v1/backtest", tags=["回测V2"])
app.include_router(ai_router, prefix="/api/v1/ai", tags=["AI分析"])
app.include_router(account_router, prefix="/api/v1/account", tags=["账户"])
app.include_router(alerts_router, prefix="/api/v1/alerts", tags=["告警管理"])
app.include_router(trades_router, prefix="/api/v1/trades", tags=["交易记录"])
app.include_router(scheduler_router, prefix="/api/v1/scheduler", tags=["定时任务"])
app.include_router(strategies_router, prefix="/api/v1/strategies", tags=["策略市场"])
app.include_router(execution_router, prefix="/api/v1/execution", tags=["执行联动"])
app.include_router(config_router, prefix="/api/v1", tags=["数据源配置"])
app.include_router(ws_router, prefix="/ws", tags=["WebSocket实时推送"])

# Stock Insight 选股路由
from api.stock_insight import router as stock_insight_router

app.include_router(stock_insight_router, prefix="/api/v1/stock-insight", tags=["Stock Insight选股"])


# ============================================================
# 健康检查 & 指标 — 必须在静态文件兜底路由之前注册
# ============================================================
@app.get("/health", dependencies=[])
async def health():
    return {"status": "healthy"}


@app.get("/metrics", dependencies=[])
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


# ============================================================
# 静态文件 Dashboard — catch-all 兜底（最后注册）
# ============================================================
_DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")
_SERVE_DASHBOARD = os.path.isdir(_DASHBOARD_DIR)

if _SERVE_DASHBOARD:
    import mimetypes as _mimetypes

    _mimetypes.add_type("text/css", ".css")
    _mimetypes.add_type("application/javascript", ".js")
    _mimetypes.add_type("image/svg+xml", ".svg")
    _mimetypes.add_type("application/manifest+json", ".json")

    @app.get("/{filename:path}", dependencies=[])
    async def serve_dashboard(filename: str):
        """Dashboard 静态文件 — 所有 API 路由优先匹配，未匹配走此兜底"""
        file_path = os.path.normpath(os.path.join(_DASHBOARD_DIR, filename))  # noqa: ASYNC240
        if not file_path.startswith(
            os.path.normpath(_DASHBOARD_DIR) + os.sep  # noqa: ASYNC240
        ) and file_path != os.path.normpath(_DASHBOARD_DIR):  # noqa: ASYNC240
            raise HTTPException(status_code=403, detail="Forbidden")

        if os.path.isfile(file_path):  # noqa: ASYNC240
            mt, _ = _mimetypes.guess_type(file_path)
            return FileResponse(file_path, media_type=mt)

        # SPA fallback → index.html
        index_path = os.path.join(_DASHBOARD_DIR, "index.html")
        if os.path.isfile(index_path):  # noqa: ASYNC240
            return FileResponse(index_path)

        raise HTTPException(status_code=404, detail="Not found")

    logger.info(f"Dashboard 静态文件就绪: {_DASHBOARD_DIR}")
else:
    logger.warning(f"Dashboard 目录未找到: {_DASHBOARD_DIR}")

    @app.get("/", dependencies=[])
    async def root():
        return {
            "service": "QuantTradingSystem Strategy Service",
            "version": "2.0.0",
            "status": "running",
        }


# WebSocket 端点 — 向后兼容别名，新客户端使用 /ws/strategy
@app.websocket("/ws")
async def websocket_endpoint_legacy(ws: WebSocket):
    """旧版 WebSocket 端点（兼容），新客户端请使用 /ws/strategy"""
    from api.ws_strategy import strategy_ws_handler

    await strategy_ws_handler(ws)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
