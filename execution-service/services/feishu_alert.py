"""
飞书告警通知服务 - 交易执行服务专用
支持：订单成交/拒绝、风控触发、持仓异常、每日汇总、系统异常
特性：速率限制（每类告警60秒内最多1条）、异步HTTP调用、优雅错误处理
"""

from datetime import datetime
from enum import Enum
import logging
import time
from typing import Any

import httpx

from shared.middleware import trace_id_var

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# AlertLevel -> 飞书卡片 header template color
_LEVEL_COLORS = {
    AlertLevel.INFO: "blue",
    AlertLevel.WARNING: "orange",
    AlertLevel.CRITICAL: "red",
}


class FeishuAlertService:
    """飞书告警服务（execution-service）"""

    def __init__(self, webhook_url: str | None = None, rate_limit_seconds: int = 60):
        self.webhook_url = webhook_url
        self.enabled = bool(webhook_url)
        self.rate_limit_seconds = rate_limit_seconds
        # key: alert_type_string -> last_sent_timestamp
        self._last_sent: dict[str, float] = {}

    def _is_rate_limited(self, alert_key: str) -> bool:
        """检查该类型告警是否在速率限制窗口内"""
        now = time.time()
        last = self._last_sent.get(alert_key, 0)
        if now - last < self.rate_limit_seconds:
            logger.debug(f"告警被速率限制: {alert_key}")
            return True
        self._last_sent[alert_key] = now
        return False

    async def _send_card(
        self, header_title: str, level: AlertLevel, elements: list, alert_key: str
    ) -> bool:
        """发送飞书交互式卡片消息"""
        if not self.enabled:
            logger.debug("飞书Webhook未配置，跳过告警")
            return False

        if self._is_rate_limited(alert_key):
            return False

        tid = trace_id_var.get()
        trace_tag = f" | [trace_id: {tid[:8]}]" if tid else ""

        card = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": header_title},
                    "template": _LEVEL_COLORS.get(level, "blue"),
                },
                "elements": elements
                + [
                    {"tag": "hr"},
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{trace_tag} | ExecutionService",
                            }
                        ],
                    },
                ],
            },
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.webhook_url, json=card)
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("code", 0) == 0:
                        logger.info(f"飞书告警发送成功: {alert_key}")
                        return True
                    logger.warning(f"飞书告警返回异常: {result}")
                    return False
                logger.warning(f"飞书告警HTTP失败: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"飞书告警发送异常: {e}")
            return False

    # ─── 订单成交通知 ───────────────────────────────────────────────

    async def send_order_filled(self, order_info: dict[str, Any]) -> bool:
        """订单成交通知"""
        direction = order_info.get("direction", "")
        ts_code = order_info.get("ts_code", "")
        emoji = "📈" if direction == "BUY" else "📉"
        color_word = "买入" if direction == "BUY" else "卖出"

        title = f"{emoji} 订单成交：{color_word} {ts_code}"
        elements = [
            {
                "tag": "markdown",
                "content": (
                    f"**股票**: {ts_code}\n"
                    f"**方向**: {color_word}\n"
                    f"**成交价**: ¥{order_info.get('price', 0):.2f}\n"
                    f"**数量**: {order_info.get('quantity', 0)}股\n"
                    f"**金额**: ¥{order_info.get('amount', 0):.2f}\n"
                    f"**佣金**: ¥{order_info.get('commission', 0):.2f}\n"
                    f"**税费**: ¥{order_info.get('tax', 0):.2f}"
                ),
            }
        ]
        if order_info.get("order_id"):
            elements.append(
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"订单号: {order_info['order_id']}"}
                    ],
                }
            )

        return await self._send_card(title, AlertLevel.INFO, elements, f"order_filled:{ts_code}")

    # ─── 订单拒绝告警 ───────────────────────────────────────────────

    async def send_order_rejected(self, order_info: dict[str, Any], reason: str) -> bool:
        """订单拒绝告警"""
        ts_code = order_info.get("ts_code", "")
        direction = order_info.get("direction", "")

        title = f"⚠ 订单被拒绝：{direction} {ts_code}"
        elements = [
            {
                "tag": "markdown",
                "content": (
                    f"**股票**: {ts_code}\n"
                    f"**方向**: {direction}\n"
                    f"**数量**: {order_info.get('quantity', 0)}股\n"
                    f"**价格**: ¥{order_info.get('price', 0):.2f}\n"
                    f"**拒绝原因**: {reason}"
                ),
            }
        ]

        return await self._send_card(
            title, AlertLevel.WARNING, elements, f"order_rejected:{ts_code}"
        )

    # ─── 风控触发告警 ───────────────────────────────────────────────

    async def send_risk_triggered(self, ts_code: str, risk_type: str, details: str) -> bool:
        """风控触发告警"""
        title = f"🚨 风控触发：{risk_type}"
        elements = [
            {
                "tag": "markdown",
                "content": (f"**股票**: {ts_code}\n**风控类型**: {risk_type}\n**详情**: {details}"),
            }
        ]

        return await self._send_card(
            title, AlertLevel.CRITICAL, elements, f"risk:{risk_type}:{ts_code}"
        )

    # ─── 持仓异常 ─────────────────────────────────────────────────

    async def send_position_alert(self, position_info: dict[str, Any], alert_type: str) -> bool:
        """持仓异常告警"""
        ts_code = position_info.get("ts_code", "")
        title = f"📊 持仓异常：{alert_type} {ts_code}"

        cost_price = position_info.get("cost_price", 0)
        current_price = position_info.get("current_price", 0)
        pnl_ratio = ((current_price - cost_price) / cost_price * 100) if cost_price > 0 else 0

        elements = [
            {
                "tag": "markdown",
                "content": (
                    f"**股票**: {ts_code}\n"
                    f"**告警类型**: {alert_type}\n"
                    f"**成本价**: ¥{cost_price:.2f}\n"
                    f"**当前价**: ¥{current_price:.2f}\n"
                    f"**盈亏比**: {pnl_ratio:+.1f}%\n"
                    f"**持仓量**: {position_info.get('quantity', 0)}股"
                ),
            }
        ]

        level = AlertLevel.CRITICAL if "止损" in alert_type else AlertLevel.WARNING
        return await self._send_card(title, level, elements, f"position:{alert_type}:{ts_code}")

    # ─── 每日交易汇总 ─────────────────────────────────────────────

    async def send_daily_summary(self, summary_data: dict[str, Any]) -> bool:
        """每日交易汇总"""
        title = f"📋 每日交易汇总 - {summary_data.get('date', datetime.now().strftime('%Y-%m-%d'))}"

        total_trades = summary_data.get("total_trades", 0)
        buy_count = summary_data.get("buy_count", 0)
        sell_count = summary_data.get("sell_count", 0)
        total_commission = summary_data.get("total_commission", 0)
        realized_pnl = summary_data.get("realized_pnl", 0)
        pnl_emoji = "🟢" if realized_pnl >= 0 else "🔴"

        elements = [
            {
                "tag": "markdown",
                "content": (
                    f"**交易笔数**: {total_trades}笔（买入{buy_count} / 卖出{sell_count}）\n"
                    f"**总佣金**: ¥{total_commission:.2f}\n"
                    f"{pnl_emoji} **已实现盈亏**: ¥{realized_pnl:+.2f}\n"
                    f"**持仓数**: {summary_data.get('position_count', 0)}只\n"
                    f"**总资产**: ¥{summary_data.get('total_assets', 0):,.2f}"
                ),
            }
        ]

        return await self._send_card(title, AlertLevel.INFO, elements, "daily_summary")

    # ─── 系统异常 ─────────────────────────────────────────────────

    async def send_system_error(self, service_name: str, error_msg: str) -> bool:
        """系统异常告警"""
        title = f"🔥 系统异常：{service_name}"
        elements = [
            {
                "tag": "markdown",
                "content": (
                    f"**服务**: {service_name}\n"
                    f"**错误信息**: {error_msg}\n"
                    f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                ),
            }
        ]

        return await self._send_card(
            title, AlertLevel.CRITICAL, elements, f"system_error:{service_name}"
        )


# ─── 单例管理 ─────────────────────────────────────────────────────

_alert_service_instance: FeishuAlertService | None = None


def get_alert_service() -> FeishuAlertService:
    """获取飞书告警服务单例（从 config.settings 读取 webhook URL）"""
    global _alert_service_instance
    if _alert_service_instance is None:
        from core.config import settings

        _alert_service_instance = FeishuAlertService(webhook_url=settings.FEISHU_WEBHOOK)
    return _alert_service_instance
