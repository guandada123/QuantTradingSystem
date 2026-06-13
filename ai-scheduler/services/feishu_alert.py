"""
飞书告警服务 - AI调度器健康监控专用
"""

from datetime import datetime
from enum import Enum
import logging

import httpx

from shared.middleware import trace_id_var

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# 告警级别对应飞书卡片模板颜色
LEVEL_TEMPLATE = {
    AlertLevel.INFO: "blue",
    AlertLevel.WARNING: "orange",
    AlertLevel.CRITICAL: "red",
}


class HealthAlertService:
    """飞书健康告警服务"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self._last_alerts: dict[str, datetime] = {}
        self._rate_limit_seconds = 300  # 同一告警5分钟内不重复发送

    def _should_send(self, alert_key: str) -> bool:
        """速率限制：相同告警5分钟内只发一次"""
        now = datetime.now()
        if alert_key in self._last_alerts:
            elapsed = (now - self._last_alerts[alert_key]).total_seconds()
            if elapsed < self._rate_limit_seconds:
                return False
        self._last_alerts[alert_key] = now
        return True

    async def send_alert(self, title: str, content: str, level: AlertLevel = AlertLevel.INFO):
        """发送飞书卡片告警"""
        alert_key = f"{level.value}:{title}"
        if not self._should_send(alert_key):
            logger.debug(f"告警被速率限制: {title}")
            return

        template = LEVEL_TEMPLATE.get(level, "blue")
        tid = trace_id_var.get()
        trace_note = f" | [trace_id: {tid[:8]}]" if tid else ""

        card = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": template,
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": content},
                    },
                    {
                        "tag": "hr",
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{trace_note}",
                            }
                        ],
                    },
                ],
            },
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.webhook_url, json=card)
                if resp.status_code != 200:
                    logger.error(f"飞书告警发送失败: {resp.status_code} {resp.text}")
                else:
                    logger.info(f"飞书告警已发送: {title}")
        except Exception as e:
            logger.error(f"飞书告警发送异常: {e}")

    async def send_health_report(self, services_status: dict[str, bool]):
        """发送所有服务健康状态报告"""
        lines = ["**服务健康状态总览**\n"]
        all_healthy = True
        for name, healthy in services_status.items():
            icon = "✅" if healthy else "❌"
            status_text = "正常" if healthy else "异常"
            lines.append(f"{icon} **{name}**: {status_text}")
            if not healthy:
                all_healthy = False

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"\n⏰ 检查时间: {timestamp}")

        level = AlertLevel.INFO if all_healthy else AlertLevel.WARNING
        title = "🏥 系统健康报告" if all_healthy else "⚠️ 系统健康异常报告"
        content = "\n".join(lines)

        await self.send_alert(title, content, level)

    async def send_service_down(self, service_name: str, error: str):
        """服务不可达告警"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = (
            f"**服务名称**: {service_name}\n"
            f"**错误信息**: {error}\n"
            f"**告警时间**: {timestamp}\n\n"
            f"请立即检查服务状态！"
        )
        await self.send_alert(
            f"🚨 服务宕机: {service_name}",
            content,
            AlertLevel.CRITICAL,
        )

    async def send_service_recovered(self, service_name: str):
        """服务恢复通知"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tid = trace_id_var.get()
        trace_note = f" | [trace_id: {tid[:8]}]" if tid else ""

        content = f"**服务名称**: {service_name}\n**恢复时间**: {timestamp}\n\n服务已恢复正常运行。"
        # 恢复通知用绿色
        card = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": f"✅ 服务恢复: {service_name}"},
                    "template": "green",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": content},
                    },
                    {
                        "tag": "hr",
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {"tag": "plain_text", "content": f"🕐 {timestamp}{trace_note}"}
                        ],
                    },
                ],
            },
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.webhook_url, json=card)
                if resp.status_code != 200:
                    logger.error(f"飞书告警发送失败: {resp.status_code} {resp.text}")
                else:
                    logger.info(f"飞书恢复通知已发送: {service_name}")
        except Exception as e:
            logger.error(f"飞书告警发送异常: {e}")
