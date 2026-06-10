"""
ai-scheduler 测试公共 fixtures
"""
import os
import sys
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# 确保 ai-scheduler 在 Python path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 清除可能影响测试的环境变量
os.environ.pop("FEISHU_WEBHOOK", None)
os.environ.pop("DEEPSEEK_API_KEY", None)


@pytest.fixture
def mock_webhook_url():
    """Mock 飞书 Webhook URL"""
    return "https://open.feishu.cn/open-apis/bot/v2/hook/test-mock"


@pytest.fixture
def alert_service(mock_webhook_url):
    """创建 HealthAlertService 实例（带 mock webhook）"""
    from services.feishu_alert import HealthAlertService
    return HealthAlertService(webhook_url=mock_webhook_url)


@pytest.fixture
def mock_httpx_post():
    """Mock httpx.AsyncClient.post 返回 200"""
    with patch("services.feishu_alert.httpx.AsyncClient.post", new_callable=AsyncMock) as mock:
        mock.return_value.status_code = 200
        mock.return_value.text = "ok"
        yield mock


@pytest.fixture
def mock_httpx_post_fail():
    """Mock httpx.AsyncClient.post 返回 500"""
    with patch("services.feishu_alert.httpx.AsyncClient.post", new_callable=AsyncMock) as mock:
        mock.return_value.status_code = 500
        mock.return_value.text = "Internal Server Error"
        yield mock


@pytest.fixture
def mock_httpx_get_healthy():
    """Mock httpx.AsyncClient.get 返回 200（服务健康）"""
    with patch("services.health_monitor.httpx.AsyncClient.get", new_callable=AsyncMock) as mock:
        mock.return_value.status_code = 200
        yield mock


@pytest.fixture
def mock_httpx_get_unhealthy():
    """Mock httpx.AsyncClient.get 返回 500（服务不健康）"""
    with patch("services.health_monitor.httpx.AsyncClient.get", new_callable=AsyncMock) as mock:
        mock.return_value.status_code = 500
        yield mock


@pytest.fixture
def mock_httpx_get_exception():
    """Mock httpx.AsyncClient.get 抛出异常（服务不可达）"""
    with patch("services.health_monitor.httpx.AsyncClient.get", new_callable=AsyncMock) as mock:
        mock.side_effect = Exception("Connection refused")
        yield mock


@pytest.fixture
def health_monitor_no_alert():
    """创建 HealthMonitor（无告警服务）"""
    from services.health_monitor import HealthMonitor
    return HealthMonitor(alert_service=None)


@pytest.fixture
def health_monitor_with_alert(alert_service):
    """创建 HealthMonitor（带告警服务）"""
    from services.health_monitor import HealthMonitor
    return HealthMonitor(alert_service=alert_service)
