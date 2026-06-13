"""
JWT + API Key 认证模块。

两种认证方式：
1. JWT Bearer Token（终端用户 / 外部调用）
2. API Key（服务间内部调用，X-API-Key header）

Usage:
    from shared.auth import get_current_user, get_current_service

    @router.get("/orders")
    async def list_orders(user=Depends(get_current_user)):
        ...

    # 服务间调用
    @router.post("/internal/signal")
    async def internal_signal(service=Depends(get_current_service)):
        ...

配置通过环境变量：
    JWT_SECRET_KEY        — JWT 签名密钥（生产环境使用 openssl rand -hex 32 生成）
    JWT_ALGORITHM         — 签名算法（默认 HS256）
    JWT_EXPIRE_MINUTES    — Token 过期时间（默认 60 分钟）
    API_KEYS              — 逗号分隔的 API Key 列表（用于服务间认证）
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import os
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import (
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from jose import JWTError, jwt
from pydantic import BaseModel

# ============================================================
#  Configuration
# ============================================================

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-production")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

# 逗号分隔的 API Key 列表（服务间调用认证）
_API_KEYS_RAW = os.environ.get("API_KEYS", "")
_API_KEYS = {k.strip() for k in _API_KEYS_RAW.split(",") if k.strip()}


# ============================================================
#  Data Models
# ============================================================


class TokenData(BaseModel):
    """JWT Token 载荷."""

    sub: str  # 用户 ID / 服务名
    role: str = "user"  # "admin" | "user" | "service"
    exp: datetime | None = None


class User(BaseModel):
    """认证用户."""

    id: str
    role: str = "user"


# ============================================================
#  JWT Token Operations
# ============================================================


def create_access_token(
    subject: str,
    role: str = "user",
    expires_delta: timedelta | None = None,
    extra_claims: dict | None = None,
) -> str:
    """创建 JWT access token.

    Args:
        subject: 用户 ID 或服务名
        role: 角色（admin / user / service）
        expires_delta: 过期时间偏移（默认使用 JWT_EXPIRE_MINUTES）
        extra_claims: 额外自定义声明

    Returns:
        签名的 JWT token 字符串
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=JWT_EXPIRE_MINUTES)

    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + expires_delta,
        **(extra_claims or {}),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_access_token(token: str) -> TokenData:
    """验证并解码 JWT token.

    Args:
        token: JWT token 字符串

    Returns:
        TokenData 解码后的载荷

    Raises:
        HTTPException 401: Token 无效或过期
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        sub: str | None = payload.get("sub")
        role: str = payload.get("role", "user")

        if sub is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return TokenData(sub=sub, role=role, exp=None)

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


# ============================================================
#  Security Schemes
# ============================================================

_bearer_scheme = HTTPBearer(auto_error=False)
_api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


# ============================================================
#  FastAPI Dependencies (FastAPI 0.95+ Annotated style)
# ============================================================


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_bearer_scheme),
    ] = None,
    api_key: Annotated[
        str | None,
        Security(_api_key_scheme),
    ] = None,
) -> User:
    """FastAPI Dependency: 获取当前认证用户。

    支持 JWT Bearer Token 和 API Key 两种方式。
    在路由中注入以强制认证：

        @router.get("/orders")
        async def list_orders(user: User = Depends(get_current_user)):
            ...

    Raises:
        HTTPException 401: 未认证
    """
    # JWT Bearer Token
    if credentials and credentials.credentials:
        token_data = verify_access_token(credentials.credentials)
        return User(id=token_data.sub, role=token_data.role)

    # API Key
    if api_key and _API_KEYS:
        # 用 SHA-256 做常量时间比较防时序攻击
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        for stored in _API_KEYS:
            stored_hash = hashlib.sha256(stored.encode()).hexdigest()
            if key_hash == stored_hash:
                return User(id="api_service", role="service")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide Bearer token or X-API-Key header.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_service(
    api_key: Annotated[
        str | None,
        Security(_api_key_scheme),
    ] = None,
) -> User:
    """FastAPI Dependency: 仅允许服务间 API Key 认证。

    用于内部服务调用的端点保护。

    Raises:
        HTTPException 401: 未提供有效的 API Key
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Service authentication required. Provide X-API-Key header.",
        )

    if not _API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API_KEYS not configured on server",
        )

    # 常量时间比较
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    for stored in _API_KEYS:
        stored_hash = hashlib.sha256(stored.encode()).hexdigest()
        if key_hash == stored_hash:
            return User(id="internal_service", role="service")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API Key",
    )


async def get_optional_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_bearer_scheme),
    ] = None,
) -> User | None:
    """FastAPI Dependency: 可选认证（不强制要求）。

    用于既需要支持登录用户也需要支持未登录访问的端点。
    返回 None 表示未认证。
    """
    if credentials and credentials.credentials:
        try:
            token_data = verify_access_token(credentials.credentials)
            return User(id=token_data.sub, role=token_data.role)
        except HTTPException:
            pass
    return None


# ============================================================
#  Role-Based Access Control
# ============================================================


def require_role(required_role: str):
    """工厂函数：创建角色检查依赖。

    Usage:
        @router.delete("/users/{user_id}")
        async def delete_user(user: User = Depends(require_role("admin"))):
            ...
    """

    async def _check_role(user: User = Depends(get_current_user)) -> User:
        if user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{required_role}' required, got '{user.role}'",
            )
        return user

    return _check_role
