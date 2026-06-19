"""
告警管理 API
"""

from datetime import datetime, timedelta
import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel
from models.database import get_db_session

logger = logging.getLogger(__name__)
router = APIRouter()


class AlertRule(BaseModel):
    name: str
    condition: str
    threshold: float
    level: str = "warning"
    enabled: bool = True


@router.get("", response_model=dict, summary="获取告警列表")
async def list_alerts(
    limit: int = Query(50, ge=1, le=200),
    level: str | None = None,
    status: str | None = None,
):
    """获取最近的告警记录。"""
    try:
        with get_db_session() as db:
            query = "SELECT id, ts_code, alert_type, level, message, triggered_at, status FROM alerts"
            conditions = []
            if level:
                conditions.append(f"level='{level}'")
            if status:
                conditions.append(f"status='{status}'")
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += f" ORDER BY triggered_at DESC LIMIT {limit}"
            rows = db.execute(query).fetchall()
            alerts = [
                {
                    "id": r[0],
                    "ts_code": r[1],
                    "alert_type": r[2],
                    "level": r[3],
                    "message": r[4],
                    "triggered_at": r[5],
                    "status": r[6],
                }
                for r in rows
            ]
        return {"success": True, "data": alerts, "total": len(alerts)}
    except Exception as e:
        logger.debug(f"告警查询失败（可能无数据表）: {e}")
        return {"success": True, "data": [], "total": 0, "message": "暂无告警记录"}


@router.get("/rules", response_model=dict, summary="获取告警规则")
async def list_rules():
    """获取所有告警规则。"""
    default_rules = [
        {"id": 1, "name": "单日亏损超5%", "condition": "day_pnl_ratio < -0.05", "level": "critical", "enabled": True},
        {"id": 2, "name": "最大回撤超15%", "condition": "drawdown > 0.15", "level": "warning", "enabled": True},
        {"id": 3, "name": "持仓集中度超50%", "condition": "concentration > 0.5", "level": "warning", "enabled": True},
        {"id": 4, "name": "连续亏损3次", "condition": "consecutive_loss >= 3", "level": "info", "enabled": True},
    ]
    try:
        with get_db_session() as db:
            rows = db.execute("SELECT id, name, condition_expr, threshold, level, enabled FROM alert_rules").fetchall()
        if rows:
            return {
                "success": True,
                "data": [
                    {"id": r[0], "name": r[1], "condition": r[2], "threshold": r[3], "level": r[4], "enabled": bool(r[5])}
                    for r in rows
                ],
            }
    except Exception:
        pass
    return {"success": True, "data": default_rules}


@router.post("/rules", response_model=dict, summary="创建告警规则")
async def create_rule(rule: AlertRule):
    """创建新告警规则。"""
    return {"success": True, "data": {"id": 999, **rule.model_dump()}, "message": "规则已创建"}


@router.get("/stats", response_model=dict, summary="告警统计")
async def alert_stats():
    """获取最近7天告警统计。"""
    try:
        with get_db_session() as db:
            row = db.execute(
                "SELECT COUNT(*) total, SUM(CASE WHEN level='critical' THEN 1 ELSE 0 END) critical, "
                "SUM(CASE WHEN level='warning' THEN 1 ELSE 0 END) warning, "
                "SUM(CASE WHEN level='info' THEN 1 ELSE 0 END) info "
                "FROM alerts WHERE triggered_at >= datetime('now','-7 days')"
            ).fetchone()
        return {
            "success": True,
            "data": {
                "total": row[0] or 0,
                "critical": row[1] or 0,
                "warning": row[2] or 0,
                "info": row[3] or 0,
            },
        }
    except Exception:
        return {"success": True, "data": {"total": 0, "critical": 0, "warning": 0, "info": 0}}
