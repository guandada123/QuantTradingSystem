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

from shared.middleware import trace_id_var

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

        tid = trace_id_var.get()
        trace_tag = f" | [trace_id: {tid[:8]}]" if tid else ""
        
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
                                "content": f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{trace_tag} | QuantTradingSystem"
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

    async def send_backtest_report(self, report: dict, report_type: str = "daily"):
        """发送回测报告到飞书

        Args:
            report: ReportService 生成的报告 dict，包含 feishu_card 字段
            report_type: daily / weekly / monthly
        """
        card = report.get("feishu_card")
        if not card:
            logger.warning("[FeishuAlert] 报告中无 feishu_card 字段，跳过推送")
            return

        # 添加报告类型标签
        label_map = {"daily": "日报", "weekly": "周报", "monthly": "月报"}
        card["card"]["header"]["title"]["content"] = (
            f"🔬 回测{label_map.get(report_type, '报告')} · {report.get('report_date', '')}"
        )

        await self._send_card(card)

    async def _send_card(self, card: dict):
        """发送飞书交互式卡片"""
        tid = trace_id_var.get()
        trace_tag = f" | [trace_id: {tid[:8]}]" if tid else ""

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "timestamp": datetime.now().strftime("%s"),
            "sign": "",  # 签名需另行配置
            **card
        }
        # 追加 trace_id 到 note 元素
        if "card" in payload and "elements" in payload["card"]:
            payload["card"]["elements"].append({
                "tag": "note",
                "elements": [{
                    "tag": "plain_text",
                    "content": f"🕐 {timestamp}{trace_tag} | QuantTradingSystem"
                }]
            })

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(self.webhook_url, json=payload)
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("code") == 0:
                        logger.info(f"[FeishuAlert] 卡片推送成功")
                    else:
                        logger.warning(f"[FeishuAlert] 卡片推送返回异常: {result}")
                else:
                    logger.warning(f"[FeishuAlert] 卡片推送失败 HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[FeishuAlert] 卡片推送异常: {e}")

# 全局实例
alert_service = None

def get_alert_service(webhook_url: str = None) -> FeishuAlertService:
    """获取告警服务实例"""
    global alert_service
    if alert_service is None and webhook_url:
        alert_service = FeishuAlertService(webhook_url)
    return alert_service or FeishuAlertService()
