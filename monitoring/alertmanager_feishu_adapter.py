"""
Alertmanager → 飞书 Webhook Adapter
将 Prometheus Alertmanager 告警转换为飞书卡片消息

启动方式:
  python alertmanager_feishu_adapter.py
  uvicorn alertmanager_feishu_adapter:app --host 0.0.0.0 --port 9093
  # 或通过 Docker Compose 自动启动

配置:
  FEISHU_ALERT_WEBHOOK  — 飞书机器人 Webhook URL（必填）
  ADAPTER_PORT          — 监听端口（默认 9093）
"""

from datetime import UTC, datetime, timedelta, timezone
import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("alertmanager-feishu")

app = FastAPI(title="Alertmanager → Feishu Adapter")

# 配置
FEISHU_WEBHOOK = os.getenv("FEISHU_ALERT_WEBHOOK", os.getenv("FEISHU_WEBHOOK", ""))
BEIJING_TZ = timezone(timedelta(hours=8))

# 严重级别映射
SEVERITY_COLORS = {
    "critical": "red",
    "warning": "yellow",
    "info": "blue",
    "none": "grey",
}

STATUS_EMOJI = {
    "firing": "🔥",
    "resolved": "✅",
}


def format_alert_card(alert: dict[str, Any], status: str) -> dict[str, Any]:
    """将单条 Alertmanager 告警转换为飞书卡片"""
    annotations = alert.get("annotations", {})
    labels = alert.get("labels", {})

    severity = labels.get("severity", "info")
    color = SEVERITY_COLORS.get(severity, "blue")
    emoji = STATUS_EMOJI.get(status, "ℹ️")

    alertname = labels.get("alertname", "Unknown Alert")
    summary = annotations.get("summary", annotations.get("description", "No details"))
    instance = labels.get("instance", "")
    job = labels.get("job", "")

    starts_at = alert.get("startsAt", "")
    if starts_at:
        try:
            dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
            beijing_time = dt.astimezone(BEIJING_TZ).strftime("%m-%d %H:%M:%S")
        except Exception:
            beijing_time = starts_at
    else:
        beijing_time = ""

    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**{summary[:500]}**"}},
        {"tag": "hr"},
    ]

    # 关键标签
    label_items = []
    for key, val in labels.items():
        if key not in ("alertname", "severity", "__name__"):
            label_items.append(f"{key}: {val}")
    if label_items:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "\n".join([f"• {item}" for item in label_items[:8]]),
                },
            }
        )

    elements.extend(
        [
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"QuantTradingSystem | Alertmanager | {beijing_time}",
                    }
                ],
            },
        ]
    )

    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"{emoji} [{severity.upper()}] {alertname}"},
            "template": color,
        },
        "elements": elements,
    }


def format_group_summary(alerts: list[dict], status: str) -> dict[str, Any]:
    """告警组汇总卡片"""
    firing_count = len([a for a in alerts if a.get("status") == "firing"])
    resolved_count = len(alerts) - firing_count

    severity = alerts[0].get("labels", {}).get("severity", "info")
    color = SEVERITY_COLORS.get(severity, "blue")

    title_text = (
        f"📊 告警汇总: {len(alerts)} 条 "
        + (f"({firing_count} 🔥 / {resolved_count} ✅)" if resolved_count > 0 else "")
        if firing_count > 1
        else f"{STATUS_EMOJI.get(status, 'ℹ️')} [{severity.upper()}] {alerts[0].get('labels', {}).get('alertname', 'Alert')}"
    )

    lines = []
    for alert in alerts[:10]:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        name = labels.get("alertname", "?")
        summary = annotations.get("summary", "")[:60]
        alert_status = alert.get("status", status)
        emoji = STATUS_EMOJI.get(alert_status, "ℹ️")
        lines.append(f"{emoji} **{name}**: {summary}")

    if len(alerts) > 10:
        lines.append(f"... 还有 {len(alerts) - 10} 条告警")

    return {
        "header": {
            "title": {"tag": "plain_text", "content": title_text[:100]},
            "template": color,
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}},
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"QuantTradingSystem | {datetime.now(BEIJING_TZ).strftime('%m-%d %H:%M:%S')}",
                    }
                ],
            },
        ],
    }


async def send_feishu_card(card: dict[str, Any]) -> bool:
    """发送飞书卡片消息"""
    if not FEISHU_WEBHOOK:
        logger.warning("FEISHU_ALERT_WEBHOOK not configured, skipping")
        return False

    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(FEISHU_WEBHOOK, json={"msg_type": "interactive", "card": card})
            if resp.status_code == 200:
                result = resp.json()
                if result.get("code") == 0:
                    return True
                logger.error(f"Feishu API error: {result}")
            else:
                logger.error(f"Feishu HTTP error: {resp.status_code}")
    except Exception as e:
        logger.error(f"Failed to send feishu card: {e}")
    return False


@app.post("/webhook")
async def handle_alertmanager_webhook(request: Request):
    """接收 Alertmanager webhook"""
    if not FEISHU_WEBHOOK:
        raise HTTPException(status_code=503, detail="Feishu webhook not configured")

    body = await request.json()

    # Alertmanager v4 format
    alerts = body.get("alerts", [])
    status = body.get("status", "firing")
    external_url = body.get("externalURL", "")

    if not alerts:
        return JSONResponse({"status": "ok", "message": "no alerts"})

    logger.info(f"Received {len(alerts)} alerts, status={status}")

    # 单条告警 → 详细卡片
    if len(alerts) == 1:
        card = format_alert_card(alerts[0], alerts[0].get("status", status))
    else:
        card = format_group_summary(alerts, status)

    success = await send_feishu_card(card)
    logger.info(f"Alert sent: {len(alerts)} alerts → feishu {'OK' if success else 'FAILED'}")

    return JSONResponse({"status": "sent" if success else "failed", "count": len(alerts)})


@app.post("/test")
async def test_webhook(request: Request):
    """测试端点：发送一条测试告警到飞书"""
    body = await request.json()
    test_alert = {
        "annotations": {
            "summary": body.get("summary", "这是一条测试告警"),
            "description": body.get("description", "测试 Alertmanager → 飞书 Webhook 连通性"),
        },
        "labels": {
            "alertname": body.get("alertname", "TestAlert"),
            "severity": body.get("severity", "info"),
            "instance": "test-instance",
            "job": "test-job",
        },
        "startsAt": datetime.now(UTC).isoformat(),
        "status": "firing",
    }
    card = format_alert_card(test_alert, "firing")
    success = await send_feishu_card(card)
    return {"status": "sent" if success else "failed"}


@app.get("/health")
async def health():
    return {"status": "healthy", "feishu_configured": bool(FEISHU_WEBHOOK)}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("ADAPTER_PORT", "9093"))
    uvicorn.run(app, host="0.0.0.0", port=port)
