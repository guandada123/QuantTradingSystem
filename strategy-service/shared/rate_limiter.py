"""
限流中间件 — 转发到根目录 shared/rate_limiter.py 的完整令牌桶实现

保留为转发层以保持 imports 兼容（from shared.rate_limiter import RateLimitMiddleware），
同时使 RATE_LIMIT_ENABLED 环境变量可在此层控制限流开关。
"""

import logging
import os
import sys
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# 限流是否启用（默认启用）
_RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")

if not _RATE_LIMIT_ENABLED:
    logger.warning("限流已通过 RATE_LIMIT_ENABLED=false 禁用")

    # 导出空操作的中间件
    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            return await call_next(request)
else:
    # 通过路径导入根目录的完整令牌桶实现
    _THIS_DIR = Path(__file__).resolve().parent
    _QTS_ROOT = _THIS_DIR.parent.parent
    _ROOT_RATE_LIMITER = str(_QTS_ROOT / "shared" / "rate_limiter.py")

    import importlib.util

    spec = importlib.util.spec_from_file_location("shared.rate_limiter_impl", _ROOT_RATE_LIMITER)
    _root_module = importlib.util.module_from_spec(spec)
    _root_module.__package__ = "shared"
    sys.modules["shared.rate_limiter_impl"] = _root_module
    spec.loader.exec_module(_root_module)

    # 导出根模块的 RateLimitMiddleware
    RateLimitMiddleware = _root_module.RateLimitMiddleware
