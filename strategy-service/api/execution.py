"""
Execution Integration API
Provides endpoints for signal-triggered trading and cross-service operations
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import logging

from services.execution_client import execution_client
from core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class SignalExecuteRequest(BaseModel):
    ts_code: str
    direction: str  # BUY or SELL
    price: float
    quantity: int
    strategy_name: Optional[str] = None
    account_id: str = "REAL_001"


class AutoTradeConfig(BaseModel):
    enabled: bool
    max_order_amount: float = 50000
    allowed_strategies: List[str] = []


@router.post("/signal-execute")
async def execute_signal(req: SignalExecuteRequest):
    """Execute a trading signal by submitting order to execution-service"""
    if not settings.AUTO_EXECUTE_SIGNALS:
        return {
            "success": False,
            "mode": "notify_only",
            "message": "自动执行已关闭，仅记录信号。如需自动执行请开启 AUTO_EXECUTE_SIGNALS",
            "signal": req.dict()
        }

    # Submit to execution service
    result = await execution_client.submit_order(
        account_id=req.account_id,
        ts_code=req.ts_code,
        direction=req.direction,
        order_type="LIMIT",
        price=req.price,
        quantity=req.quantity,
        strategy_name=req.strategy_name
    )

    # 飞书告警：自动执行结果通知
    try:
        from services.feishu_alert import get_alert_service, AlertType, AlertLevel
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
                    data={"策略": req.strategy_name or "未指定", "账户": req.account_id}
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
                    data={"账户": req.account_id, "金额": f"¥{req.price * req.quantity:.0f}"}
                )
    except Exception as alert_e:
        logger.warning(f"执行告警推送失败(非致命): {alert_e}")

    return {
        "success": True,
        "mode": "auto_execute",
        "execution_result": result
    }


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
        "status": "connected"
    }


@router.post("/config")
async def update_auto_trade_config(config: AutoTradeConfig):
    """Update auto-trade configuration (runtime only, not persisted)"""
    settings.AUTO_EXECUTE_SIGNALS = config.enabled
    return {"success": True, "auto_execute_enabled": settings.AUTO_EXECUTE_SIGNALS}
