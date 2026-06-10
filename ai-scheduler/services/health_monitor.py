"""
健康监控服务 - 定期检查所有微服务健康状态
"""
import httpx
import asyncio
import logging
from typing import Dict, Optional

from services.feishu_alert import HealthAlertService
from shared.middleware import get_trace_headers

logger = logging.getLogger(__name__)


class HealthMonitor:
    """服务健康监控器"""

    SERVICES = {
        "strategy-service": "http://strategy-service:8000/health",
        "execution-service": "http://execution-service:8001/health",
        "ai-scheduler": "http://localhost:8002/health",
    }

    def __init__(self, alert_service: Optional[HealthAlertService] = None):
        self.alert_service = alert_service
        self._previous_status: Dict[str, bool] = {}
        self._current_status: Dict[str, bool] = {}
        self._running = False

    async def check_service(self, name: str, url: str) -> bool:
        """检查单个服务健康状态"""
        try:
            async with httpx.AsyncClient(timeout=5, headers=get_trace_headers()) as client:
                resp = await client.get(url)
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"服务 {name} 健康检查失败: {e}")
            return False

    async def check_all(self) -> Dict[str, bool]:
        """检查所有服务健康状态"""
        results = {}
        for name, url in self.SERVICES.items():
            results[name] = await self.check_service(name, url)
        self._current_status = results
        return results

    async def run_monitoring_loop(self, interval: int = 300):
        """监控循环"""
        logger.info(f"健康监控启动，检查间隔: {interval}秒")
        while self._running:
            try:
                status = await self.check_all()
                logger.info(f"健康检查结果: {status}")

                # WebSocket 广播健康状态
                try:
                    from api.ws_scheduler import broadcast_health_update
                    asyncio.ensure_future(broadcast_health_update(status, all(status.values())))
                except Exception:
                    pass

                if self.alert_service:
                    # 检测状态变化
                    for name, is_healthy in status.items():
                        was_healthy = self._previous_status.get(name)

                        if was_healthy is not None:
                            # 服务从正常变为异常
                            if was_healthy and not is_healthy:
                                await self.alert_service.send_service_down(
                                    name, "健康检查失败，服务不可达"
                                )
                            # 服务从异常恢复正常
                            elif not was_healthy and is_healthy:
                                await self.alert_service.send_service_recovered(name)

                    self._previous_status = status.copy()

            except Exception as e:
                logger.error(f"健康监控循环异常: {e}")

            await asyncio.sleep(interval)

    async def start(self, interval: int = 300):
        """启动监控"""
        self._running = True
        asyncio.create_task(self.run_monitoring_loop(interval))
        logger.info("健康监控已启动")

    async def stop(self):
        """停止监控"""
        self._running = False
        logger.info("健康监控已停止")

    def get_status(self) -> Dict[str, bool]:
        """获取当前服务状态"""
        return self._current_status.copy()
