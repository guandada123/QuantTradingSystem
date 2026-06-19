"""
Execution Integration API
Provides endpoints for signal-triggered trading and cross-service operations
"""

import logging

from core.config import settings
from fastapi import APIRouter
from models.database import get_db_session
from models.enums import StrategyName
from pydantic import BaseModel
from services.execution_client import execution_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["交易执行"])


class SignalExecuteRequest(BaseModel):
    ts_code: str
    direction: str  # BUY or SELL
    price: float
    quantity: int
    strategy_name: StrategyName | None = None
    account_id: str = "REAL_001"


class AutoTradeConfig(BaseModel):
    enabled: bool
    max_order_amount: float = 50000
    allowed_strategies: list[StrategyName] = []


@router.post("/signal-execute")
async def execute_signal(req: SignalExecuteRequest):
    """Execute a trading signal by submitting order to execution-service"""
    if not settings.AUTO_EXECUTE_SIGNALS:
        return {
            "success": False,
            "mode": "notify_only",
            "message": "自动执行已关闭，仅记录信号。如需自动执行请开启 AUTO_EXECUTE_SIGNALS",
            "signal": req.dict(),
        }

    # Submit to execution service
    result = await execution_client.submit_order(
        account_id=req.account_id,
        ts_code=req.ts_code,
        direction=req.direction,
        order_type="LIMIT",
        price=req.price,
        quantity=req.quantity,
        strategy_name=req.strategy_name,
    )

    # 飞书告警：自动执行结果通知
    try:
        from services.feishu_alert import AlertLevel, AlertType, get_alert_service

        alert = get_alert_service(settings.FEISHU_WEBHOOK)
        if alert and alert.enabled:
            if result.get("success") is False:
                # 执行失败告警
                await alert.send_alert(
                    alert_type=AlertType.SYSTEM_ERROR,
                    level=AlertLevel.WARNING,
                    title=f"信号执行失败: {req.ts_code}",
                    content=(
                        f"**股票**: {req.ts_code}\n"
                        f"**方向**: {req.direction}\n"
                        f"**价格**: ¥{req.price:.2f}\n"
                        f"**数量**: {req.quantity}\n"
                        f"**错误**: {result.get('error', '未知错误')}"
                    ),
                    data={"策略": req.strategy_name or "未指定", "账户": req.account_id},
                )
            else:
                # 自动执行成功告警
                await alert.send_alert(
                    alert_type=AlertType.SIGNAL,
                    level=AlertLevel.INFO,
                    title=f"信号已自动执行: {req.direction} {req.ts_code}",
                    content=(
                        f"**股票**: {req.ts_code}\n"
                        f"**方向**: {req.direction}\n"
                        f"**价格**: ¥{req.price:.2f}\n"
                        f"**数量**: {req.quantity}\n"
                        f"**策略**: {req.strategy_name or '未指定'}\n\n"
                        f"✅ 订单已提交至执行服务"
                    ),
                    data={"账户": req.account_id, "金额": f"¥{req.price * req.quantity:.0f}"},
                )
    except Exception as alert_e:
        logger.warning(f"执行告警推送失败(非致命): {alert_e}")

    return {"success": True, "mode": "auto_execute", "execution_result": result}


@router.get("/positions")
async def get_execution_positions(account_id: str = "REAL_001"):
    """Proxy to execution-service positions"""
    return await execution_client.get_positions(account_id)


@router.get("/risk-check/{ts_code}")
async def check_execution_risk(ts_code: str):
    """Proxy risk check to execution-service"""
    return await execution_client.check_risk(ts_code)


@router.get("/config")
async def get_auto_trade_config():
    """Get current auto-trade configuration"""
    return {
        "auto_execute_enabled": settings.AUTO_EXECUTE_SIGNALS,
        "execution_service_url": settings.EXECUTION_SERVICE_URL,
        "status": "connected",
    }


@router.post("/config")
async def update_auto_trade_config(config: AutoTradeConfig):
    """Update auto-trade configuration (runtime only, not persisted)"""
    settings.AUTO_EXECUTE_SIGNALS = config.enabled
    return {"success": True, "auto_execute_enabled": settings.AUTO_EXECUTE_SIGNALS}


# ── orders.html 兼容路由（v1 前缀适配）──


@router.get("/v1/positions/")
async def get_execution_positions_v1(account_id: str = "REAL_001"):
    """Proxy to execution-service positions (v1 compat)"""
    return await execution_client.get_positions(account_id)


@router.get("/v1/positions/summary")
async def get_execution_positions_summary_v1(account_id: str = "REAL_001"):
    """Positions summary for orders.html (v1 compat)"""
    positions_resp = await execution_client.get_positions(account_id)
    data = positions_resp.get("data", []) if isinstance(positions_resp, dict) else []
    total_value = sum((p.get("market_value", 0) or 0) for p in data)
    day_pnl = sum((p.get("profit_loss", 0) or 0) for p in data)
    return {
        "code": 0,
        "data": {
            "total_assets": total_value + 100000,
            "available_cash": 100000,
            "market_value": total_value,
            "day_pnl": day_pnl,
        },
    }


@router.get("/v1/orders/")
async def get_execution_orders_v1(account_id: str = "REAL_001", limit: int = 50, status: str = ""):
    """订单列表（兼容 orders.html v1 路由）"""
    from models.models import Order

    try:
        with get_db_session() as session:
            q = session.query(Order).filter(Order.account_id == account_id)
            if status:
                q = q.filter(Order.status == status)
            records = q.order_by(Order.created_at.desc()).limit(limit).all()
            data = []
            for r in records:
                data.append(
                    {
                        "order_id": r.order_id,
                        "ts_code": r.ts_code,
                        "direction": r.direction,
                        "order_type": r.order_type or "LIMIT",
                        "price": float(r.price) if r.price else None,
                        "quantity": r.quantity,
                        "status": r.status or "PENDING",
                        "created_at": r.created_at.isoformat() if r.created_at else "",
                    }
                )
        return {"code": 0, "data": data}
    except Exception as e:
        logger.warning(f"订单查询失败(非致命): {e}")
        return {"code": 0, "data": []}


@router.post("/v1/orders/submit")
async def post_execution_order_submit_v1():
    """提交订单兼容端点（开发环境桩）"""
    from datetime import datetime

    return {
        "code": 0,
        "data": {
            "order_id": f"MOCK_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "status": "PENDING",
        },
    }


@router.get("/health")
async def execution_health():
    """执行服务健康检查（供 HealthMonitor 及前端告警页轮询）"""
    try:
        status = (
            await execution_client.check_health()
            if hasattr(execution_client, "check_health")
            else {"status": "ok"}
        )
        return {"status": "healthy", "execution_service": status}
    except Exception:
        return {"status": "degraded", "execution_service": "unreachable"}
