"""
健康监控服务 - 定期检查所有微服务健康状态
"""

import asyncio
import logging
from typing import cast

import httpx
from core.config import settings

from services.feishu_alert import HealthAlertService
from shared.middleware import get_trace_headers

logger = logging.getLogger(__name__)

# 后台任务强引用（2026-10-17 修复，RUF006）
# asyncio 只保存 task 的弱引用：ensure_future/create_task 的返回值若不持有，
# 任务可能在首个 await 之前就被 GC 回收 —— 轻则「健康状态 WebSocket 广播静默丢失」，
# 重则 start() 里的监控主循环被回收，健康监控静默停摆且无任何日志。
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn_background(coro) -> asyncio.Task:
    """创建后台任务并持强引用，完成后自动移除。"""
    # cast 说明：ensure_future(协程) 运行时必返 Task，但 typeshed 声明为 Future[_T]
    # （mypy 报 no-any-return）——入参 coro 无类型标注，返回值被推断为 Any。
    task = cast(asyncio.Task, asyncio.ensure_future(coro))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


def _probe_timeout() -> float:
    """单次探活超时（秒）：读配置，缺失/非法/非正数一律回落到 10s。"""
    raw = getattr(settings, "HEALTH_CHECK_TIMEOUT", 10.0)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 10.0
    return value if value > 0 else 10.0


def _probe_retries() -> int:
    """单拍内失败重试次数：缺失/非法/负数一律回落到 1（= 一拍最多探两次）。"""
    raw = getattr(settings, "HEALTH_CHECK_RETRIES", 1)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return value if value >= 0 else 1


def _retry_delay() -> float:
    """重试间隔（秒）：缺失/非法/负数一律回落到 2s。"""
    raw = getattr(settings, "HEALTH_CHECK_RETRY_DELAY", 2.0)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 2.0
    return value if value >= 0 else 2.0


class HealthMonitor:
    """服务健康监控器"""

    # 兜底默认值。实际探测地址以 _resolve_services() 为准（会先读配置）。
    SERVICES = {
        "strategy-service": "http://strategy-service:8000/health",
        "execution-service": "http://execution-service:8001/health",
        # 自探测走容器内网回环，与 compose/helm/k8s 的服务命名解耦，不参与配置覆盖
        "ai-scheduler": "http://localhost:8002/health",
    }

    # 探测地址的配置来源：settings 字段名 → 覆盖哪个服务的 base url
    _SERVICE_URL_SETTINGS = {
        "strategy-service": "STRATEGY_SERVICE_URL",
        "execution-service": "EXECUTION_SERVICE_URL",
    }

    def _resolve_services(self) -> dict[str, str]:
        """解析实际探测地址：优先读配置，缺省才用 SERVICES 兜底。

        2026-09-02 修复（巡检中枢 run#65）：此前 check_all() 直接用硬编码的 SERVICES，
        docker-compose / k8s configmap / helm values **三处**配置的 STRATEGY_SERVICE_URL、
        EXECUTION_SERVICE_URL 全部被无视 —— 金丝雀实验（注入 CANARY 地址）证实 settings
        读到了而 HealthMonitor 没跟。Docker 下两者数值恰好相同才没暴露；一旦改名、
        换命名空间或改用 FQDN，监控就会探测错误地址并持续误报 DOWN，而运维按配置排查
        永远查不出问题（改配置不生效）。
        """
        resolved = dict(self.SERVICES)
        for name, attr in self._SERVICE_URL_SETTINGS.items():
            base = getattr(settings, attr, None)
            if base:
                resolved[name] = str(base).rstrip("/") + "/health"
        return resolved

    def __init__(self, alert_service: HealthAlertService | None = None):
        self.alert_service = alert_service
        self._previous_status: dict[str, bool] = {}
        self._current_status: dict[str, bool] = {}
        self._running = False
        # 监控主循环任务：持强引用防 GC（见模块级 _BACKGROUND_TASKS 说明）
        self._monitor_task: asyncio.Task | None = None

    async def check_service(self, name: str, url: str) -> bool:
        """检查单个服务健康状态（拍内失败会重试，两次都失败才算不健康）。

        2026-11-24 加固（T-INS-0d116c2f5c2e）：此前单次 5s 超时即返回 False，任何一次探测
        抖动都会被上一拍基线放大成「🚨 服务宕机」，下一拍又「✅ 服务恢复」—— 两个多月 50+
        次「宕机」里没有一次伴随容器重启。现在改为：同一拍内失败后按 HEALTH_CHECK_RETRY_DELAY
        间隔重试 HEALTH_CHECK_RETRIES 次（默认 1 次），全部失败才判这一拍不健康；单次超时
        改由 HEALTH_CHECK_TIMEOUT 配置（默认 10s）。边沿触发（只在状态翻转时推送）不变。
        """
        timeout = _probe_timeout()
        attempts = _probe_retries() + 1
        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout, headers=get_trace_headers()
                ) as client:
                    resp = await client.get(url)
                # httpx 在此被视作 Any → 显式 bool 才符合 `-> bool`
                if bool(resp.status_code == 200):
                    return True
                logger.warning(
                    f"服务 {name} 健康检查返回 {resp.status_code}"
                    f"（第 {attempt}/{attempts} 次，timeout={timeout}s）"
                )
            except Exception as e:
                logger.warning(
                    f"服务 {name} 健康检查失败（第 {attempt}/{attempts} 次，timeout={timeout}s）: {e}"
                )
            if attempt < attempts:
                delay = _retry_delay()
                if delay > 0:
                    await asyncio.sleep(delay)
        return False

    async def check_all(self) -> dict[str, bool]:
        """检查所有服务健康状态（探测地址先读配置，见 _resolve_services）"""
        results = {}
        for name, url in self._resolve_services().items():
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

                    _spawn_background(broadcast_health_update(status, all(status.values())))
                except Exception:
                    logger.debug("健康状态 WebSocket 广播失败（非关键）")

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
        # 监控主循环必须持强引用：这是本服务的核心循环，
        # 若被 GC 会表现为「健康监控静默停摆、无任何日志」（RUF006）
        self._monitor_task = _spawn_background(self.run_monitoring_loop(interval))
        logger.info("健康监控已启动")

    async def stop(self):
        """停止监控"""
        self._running = False
        # 主循环会在 sleep 后自行退出（_running=False），无需强杀
        self._monitor_task = None
        logger.info("健康监控已停止")

    def get_status(self) -> dict[str, bool]:
        """获取当前服务状态"""
        return self._current_status.copy()
