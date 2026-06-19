"""
告警工具 — 统一 fire-and-forget 协程调度

替代分散在 order_manager.py / risk_controller.py 的重复 _fire_alert() 实现。
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_ALERT_TIMEOUT_SECONDS = 5.0


async def _alert_with_timeout(coro):
    """执行告警协程，带超时保护防止飞书挂起时协程永悬"""
    try:
        await asyncio.wait_for(coro, timeout=_ALERT_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.debug(f"告警发送超时({_ALERT_TIMEOUT_SECONDS}s)，已丢弃")
    except Exception as e:
        logger.debug(f"告警发送异常: {e}")


def fire_alert(coro):
    """
    安全地在事件循环中调度告警协程（fire-and-forget，带超时保护）。

    Python 3.12+ 兼容:
      - 已有运行中事件循环 → create_task（避免 get_event_loop() 废弃警告）
      - 无运行中事件循环 → asyncio.run()
    """
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            asyncio.ensure_future(_alert_with_timeout(coro))
            return
    except RuntimeError:
        pass  # 没有运行中的事件循环
    asyncio.run(_alert_with_timeout(coro))
