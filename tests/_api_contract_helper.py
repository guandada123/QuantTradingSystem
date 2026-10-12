"""契约/E2E 测试的**带凭据请求**helper（2026-10-12）。

## 背景
strategy-service 已启用鉴权（JWT + `X-API-Key`），而契约/性能/E2E 测试此前**裸请求** →
一律 401 → 一批用例长期"假红"（既不反映服务故障，也没人真跑）。

## 约定
- 凭据**从环境读**（不写进代码）：`QTS_JWT`（用户态）或 `QTS_API_KEY` / `API_KEYS`（服务间）。
- **无凭据时遇 401 → skip（附原因）**：skip ≠ 通过，也不伪装失败。
- **有凭据时 401 仍判失败**（不掩盖真问题）；非 401 的契约不符照常失败。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

import pytest
import requests

# 服务端 shared/auth.py 的 dev 默认密钥。**非 dev 环境下服务端会拒绝以它启动**
# （`if _ENV not in (dev…) and JWT_SECRET_KEY == _JWT_DEV_DEFAULT: raise`），
# 故用它自签的令牌**只可能在 dev 生效** —— 不构成生产后门。
_DEV_SECRET = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-production")


def _b64(obj: dict) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )


def mint_dev_token(role: str = "user", subject: str = "contract-test", ttl: int = 1800) -> str:
    """自签 dev 令牌（**纯标准库** HS256，不依赖 python-jose）。"""
    now = int(time.time())
    signing_input = (
        f"{_b64({'alg': 'HS256', 'typ': 'JWT'})}."
        f"{_b64({'sub': subject, 'role': role, 'iat': now, 'exp': now + ttl})}"
    )
    sig = (
        base64.urlsafe_b64encode(
            hmac.new(_DEV_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    return f"{signing_input}.{sig}"


def _build_headers() -> tuple[dict[str, str], bool]:
    """返回 (headers, 是否用的自动 dev 令牌)。显式凭据优先。"""
    jwt = os.environ.get("QTS_JWT", "").strip()
    key = (os.environ.get("QTS_API_KEY") or os.environ.get("API_KEYS", "").split(",")[0]).strip()
    if jwt:
        return {"Authorization": f"Bearer {jwt}"}, False
    if key:
        return {"X-API-Key": key}, False
    return {"Authorization": f"Bearer {mint_dev_token()}"}, True


AUTH_HEADERS, _USING_DEV_TOKEN = _build_headers()

_SKIP_MSG = (
    "401 且当前环境不接受可用凭据：显式设 QTS_JWT（用户态令牌）或 QTS_API_KEY 后重跑"
    "；dev 环境本应接受自动签发的 dev 令牌（若这里是 CI/生产，请为该环境配只读凭据）"
)


def _guard(resp: requests.Response) -> requests.Response:
    """401 的处理**分两种**：自动 dev 令牌被拒 → skip（环境所限，非代码问题）；
    **显式凭据仍 401 → 判失败**（凭据无效或过期，是真问题，不能掩盖）。"""
    if resp.status_code == 401 and _USING_DEV_TOKEN:
        pytest.skip(_SKIP_MSG)
    return resp


def api_get(url: str, timeout: int = 10, **kwargs) -> requests.Response:
    """**kwargs 透传**（params 等）—— 2026-10-12：曾因子集形参漏 params 导致 TypeError。"""
    return _guard(requests.get(url, headers=AUTH_HEADERS, timeout=timeout, **kwargs))


def api_post(
    url: str, *, json: dict | None = None, timeout: int = 15, **kwargs
) -> requests.Response:
    return _guard(requests.post(url, json=json, headers=AUTH_HEADERS, timeout=timeout, **kwargs))
