"""
限流中间件 — 转发到根目录 shared/rate_limiter.py 的完整令牌桶实现

P0 安全修复：不再支持 RATE_LIMIT_ENABLED=false 空操作降级。
限流为基础安全控制，应始终强制执行。如需本地调试宽松限流，
可在本地 .env 设置 max_requests 为更大值而非彻底关闭。
"""

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# 导入根目录的完整令牌桶实现（始终启用，不再支持空操作降级）
_THIS_DIR = Path(__file__).resolve().parent
_QTS_ROOT = _THIS_DIR.parent.parent
_ROOT_RATE_LIMITER = str(_QTS_ROOT / "shared" / "rate_limiter.py")

import importlib.util

spec = importlib.util.spec_from_file_location("shared.rate_limiter_impl", _ROOT_RATE_LIMITER)
assert spec is not None, "rate_limiter_impl module spec not found"
_root_module = importlib.util.module_from_spec(spec)
_root_module.__package__ = "shared"
sys.modules["shared.rate_limiter_impl"] = _root_module
spec.loader.exec_module(_root_module)

RateLimitMiddleware = _root_module.RateLimitMiddleware
logger.info("限流中间件已加载（始终启用，P0 安全修复）")
