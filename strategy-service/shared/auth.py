"""
认证模块 — 条件启用 JWT/API Key 认证

行为由环境变量 AUTH_ENABLED 控制：
  - AUTH_ENABLED=false（默认）: 返回 dev-user（向后兼容）
  - AUTH_ENABLED=true: 转发到根目录 shared/auth.py 的完整 JWT 认证

远程部署时必须设置：
  export AUTH_ENABLED=true
  export JWT_SECRET_KEY=$(openssl rand -hex 32)
  export API_KEYS="service-key-1,service-key-2"
"""

import importlib.util
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() in ("true", "1", "yes")

# 模块加载时打印一次状态（不在每次请求时重复）
if _AUTH_ENABLED:
    logger.info("JWT 认证已启用（AUTH_ENABLED=true）")
else:
    logger.info("认证未启用（AUTH_ENABLED=false），所有端点公开访问——本地使用无需设置")

# 预加载根认证模块（仅在启用时加载一次）
_ROOT_AUTH_MODULE = None
if _AUTH_ENABLED:
    _THIS_DIR = Path(__file__).resolve().parent
    _QTS_ROOT = _THIS_DIR.parent.parent
    _ROOT_AUTH = str(_QTS_ROOT / "shared" / "auth.py")

    spec = importlib.util.spec_from_file_location("shared.auth_impl", _ROOT_AUTH)
    if spec:
        _ROOT_AUTH_MODULE = importlib.util.module_from_spec(spec)
        _ROOT_AUTH_MODULE.__package__ = "shared"
        sys.modules["shared.auth_impl"] = _ROOT_AUTH_MODULE
        assert spec.loader is not None, "auth_impl module spec has no loader"
        spec.loader.exec_module(_ROOT_AUTH_MODULE)
        logger.info("JWT 认证模块已加载（AUTH_ENABLED=true）")


async def get_current_user():
    """FastAPI Dependency: 获取当前认证用户。

    当 AUTH_ENABLED=false 时返回开发用户。
    当 AUTH_ENABLED=true 时转发到根 shared/auth.py 的完整 JWT 认证。
    """
    if not _AUTH_ENABLED:
        return {"id": "dev-user", "name": "Developer"}

    if _ROOT_AUTH_MODULE is None:
        logger.critical(
            "认证模块加载失败且 AUTH_ENABLED=true，拒绝所有请求（P0 安全修复：不再降级为 dev-user）"
        )
        from fastapi import HTTPException
        from starlette.status import HTTP_503_SERVICE_UNAVAILABLE

        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证服务不可用",
        )

    return await _ROOT_AUTH_MODULE.get_current_user()
