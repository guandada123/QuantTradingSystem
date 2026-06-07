"""
飞书告警通知服务
支持：止损/止盈/风险事件/AI成本超标/系统异常
"""

import logging
import httpx
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

class AlertType(Enum):
    STOP_LOSS = "止损触发"
    TAKE_PROFIT = "止盈触发"
    RISK_BREACH = "风险超标"
    AI_COST = "AI成本预警"
    SYSTEM_ERROR = "系统异常"
    SIGNAL = "交易信号"

class FeishuAlertService:
    """飞书告警服务"""
    
    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url
        self.enabled = bool(webhook_url)
    
    async def send_alert(
        self,
        alert_type: AlertType,
        level: AlertLevel,
        title: str,
        content: str,
        data: Dict[str, Any] = None
    ) -> bool:
        """发送飞书告警"""
        if not self.enabled:
            logger.warning("飞书Webhook未配置，跳过告警")
            return False
        
        level_colors = {
            AlertLevel.INFO: "blue",
            AlertLevel.WARNING: "yellow",
            AlertLevel.CRITICAL: "red"
        }
        
        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"🔔 {alert_type.value}: {title}"
                    },
                    "template": level_colors.get(level, "blue")
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content
                    },
                    {
                        "tag": "hr"
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | QuantTradingSystem"
                            }
                        ]
                    }
                ]
            }
        }
        
        if data:
            data_text = "\n".join([f"- {k}: {v}" for k, v in data.items()])
            card['card']['elements'].insert(-1, {
                "tag": "markdown",
                "content": f"**数据详情:**\n{data_text}"
            })
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.webhook_url, json=card)
                if resp.status_code == 200:
                    logger.info(f"飞书告警发送成功: {alert_type.value}")
                    return True
                else:
                    logger.error(f"飞书告警发送失败: {resp.status_code}")
                    return False
        except Exception as e:
            logger.error(f"飞书告警发送异常: {e}")
            return False
    
    async def send_stop_loss_alert(self, ts_code: str, entry_price: float, current_price: float, loss_ratio: float):
        """止损告警"""
        await self.send_alert(
            alert_type=AlertType.STOP_LOSS,
            level=AlertLevel.CRITICAL,
            title=f"{ts_code} 触发止损",
            content=f"**股票**: {ts_code}\n**成本价**: ¥{entry_price:.2f}\n**当前价**: ¥{current_price:.2f}\n**亏损**: {loss_ratio:.1%}\n\n⚠ 系统将自动执行止损操作",
            data={"止损价": f"¥{entry_price * (1 - 0.08):.2f}", "建议操作": "立即卖出"}
        )
    
    async def send_take_profit_alert(self, ts_code: str, entry_price: float, current_price: float, profit_ratio: float):
        """止盈告警"""
        await self.send_alert(
            alert_type=AlertType.TAKE_PROFIT,
            level=AlertLevel.INFO,
            title=f"{ts_code} 触发止盈",
            content=f"**股票**: {ts_code}\n**成本价**: ¥{entry_price:.2f}\n**当前价**: ¥{current_price:.2f}\n**盈利**: {profit_ratio:.1%}\n\n🎉 恭喜！已达到止盈目标",
            data={"止盈价": f"¥{entry_price * 1.30:.2f}", "建议操作": "考虑减仓或止盈"}
        )
    
    async def send_risk_alert(self, risk_type: str, detail: str, data: Dict = None):
        """风险告警"""
        await self.send_alert(
            alert_type=AlertType.RISK_BREACH,
            level=AlertLevel.WARNING,
            title=risk_type,
            content=f"**风险类型**: {risk_type}\n**详情**: {detail}",
            data=data
        )
    
    async def send_ai_cost_alert(self, current_cost: float, budget: float, usage_ratio: float):
        """AI成本预警"""
        level = AlertLevel.WARNING if usage_ratio > 0.8 else AlertLevel.INFO
        await self.send_alert(
            alert_type=AlertType.AI_COST,
            level=level,
            title=f"AI成本预警: 已使用{usage_ratio:.1%}",
            content=f"**已使用**: ${current_cost:.2f}\n**预算**: ${budget:.2f}\n**使用率**: {usage_ratio:.1%}\n\n{'⚠ 接近预算上限，请关注' if usage_ratio > 0.8 else '📊 预算使用正常'}",
            data={"月预算": f"${budget:.2f}", "已用": f"${current_cost:.2f}"}
        )
    
    async def send_signal_alert(self, ts_code: str, action: str, price: float, confidence: float, reason: str):
        """交易信号告警"""
        emoji = "📈" if action == "BUY" else ("📉" if action == "SELL" else "⏸")
        await self.send_alert(
            alert_type=AlertType.SIGNAL,
            level=AlertLevel.INFO,
            title=f"{emoji} {action} {ts_code}",
            content=f"**股票**: {ts_code}\n**操作**: {action}\n**价格**: ¥{price:.2f}\n**置信度**: {confidence:.1f}%\n**理由**: {reason}",
            data={"信号": action, "置信度": f"{confidence:.1f}%"}
        )

# 全局实例
alert_service = None

def get_alert_service(webhook_url: str = None) -> FeishuAlertService:
    """获取告警服务实例"""
    global alert_service
    if alert_service is None and webhook_url:
        alert_service = FeishuAlertService(webhook_url)
    return alert_service or FeishuAlertService()
