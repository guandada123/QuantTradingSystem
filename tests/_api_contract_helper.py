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

import os

import pytest
import requests

AUTH_HEADERS: dict[str, str] = {}
_jwt = os.environ.get("QTS_JWT", "").strip()
_key = (os.environ.get("QTS_API_KEY") or os.environ.get("API_KEYS", "").split(",")[0]).strip()
if _jwt:
    AUTH_HEADERS["Authorization"] = f"Bearer {_jwt}"
elif _key:
    AUTH_HEADERS["X-API-Key"] = _key

_SKIP_MSG = (
    "需要凭据：服务端鉴权已启用。设 QTS_JWT 或 QTS_API_KEY 后重跑"
    "（有凭据时 401 仍会判失败，不会掩盖真问题）"
)


def _guard(resp: requests.Response) -> requests.Response:
    if resp.status_code == 401 and not AUTH_HEADERS:
        pytest.skip(_SKIP_MSG)
    return resp


def api_get(url: str, timeout: int = 10, **kwargs) -> requests.Response:
    """**kwargs 透传**（params 等）—— 2026-10-12：曾因子集形参漏 params 导致 TypeError。"""
    return _guard(requests.get(url, headers=AUTH_HEADERS, timeout=timeout, **kwargs))


def api_post(
    url: str, *, json: dict | None = None, timeout: int = 15, **kwargs
) -> requests.Response:
    return _guard(requests.post(url, json=json, headers=AUTH_HEADERS, timeout=timeout, **kwargs))
