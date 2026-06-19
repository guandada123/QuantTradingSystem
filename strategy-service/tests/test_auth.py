"""
shared/auth.py 认证模块单元测试

覆盖：
- JWT Token 创建与验证 (create_access_token / verify_access_token)
- FastAPI Dependencies (get_current_user / get_current_service / get_optional_user / require_role)
- 错误处理（无效/过期 Token、无凭证、角色不匹配）
- API Key 认证（SHA-256 常量时间比较）
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
import sys
import time

# ── 导入路径修复 ──────────────────────────────────────────────
# conftest.py 已统一处理 shared/ 路径。只需将 service 目录加入路径。
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# ─────────────────────────────────────────────────────────────

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from jose import JWTError, jwt
import pytest

# 被测试模块 — conftest 已确保 import shared 指向正确路径
from shared.auth import (
    User,
    create_access_token,
    get_current_service,
    get_current_user,
    get_optional_user,
    require_role,
    verify_access_token,
)

# ============================================================
#  Token 创建与验证（直接函数调用）
# ============================================================


class TestTokenCreation:
    """JWT Token 创建和验证"""

    def test_create_and_verify_default(self):
        """默认参数创建并验证"""
        token = create_access_token(subject="user001")
        assert isinstance(token, str)
        assert len(token) > 20

        data = verify_access_token(token)
        assert data.sub == "user001"
        assert data.role == "user"

    def test_create_with_role_admin(self):
        """管理员角色"""
        token = create_access_token(subject="admin001", role="admin")
        data = verify_access_token(token)
        assert data.sub == "admin001"
        assert data.role == "admin"

    def test_create_with_role_service(self):
        """服务角色"""
        token = create_access_token(subject="svc-ingestion", role="service")
        data = verify_access_token(token)
        assert data.sub == "svc-ingestion"
        assert data.role == "service"

    def test_create_with_custom_expiry(self):
        """自定义过期时间"""
        token = create_access_token(subject="user001", expires_delta=timedelta(hours=1))
        data = verify_access_token(token)
        assert data.sub == "user001"

    def test_create_with_extra_claims(self):
        """额外自定义声明"""
        token = create_access_token(
            subject="user001",
            extra_claims={"scope": "read_only", "tenant": "default"},
        )
        # verify_access_token 不返回额外声明，但 token 应包含
        payload = jwt.decode(
            token,
            os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-production"),
            algorithms=[os.environ.get("JWT_ALGORITHM", "HS256")],
        )
        assert payload["scope"] == "read_only"
        assert payload["tenant"] == "default"

    def test_token_contains_iat_and_exp(self):
        """Token 包含 iat 和 exp 声明"""
        token = create_access_token(subject="user001")
        payload = jwt.decode(
            token,
            os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-production"),
            algorithms=[os.environ.get("JWT_ALGORITHM", "HS256")],
        )
        assert "iat" in payload
        assert "exp" in payload
        assert payload["exp"] > payload["iat"]

    def test_multiple_tokens_different(self):
        """连续创建的 Token 应不同（含 iat）"""
        token1 = create_access_token(subject="user001")
        time.sleep(1.5)  # 跨越秒边界确保 iat 不同（jwt.encode 将 iat 截断为整秒）
        token2 = create_access_token(subject="user001")
        assert token1 != token2


class TestTokenVerification:
    """Token 验证错误处理"""

    def test_verify_invalid_token_raises(self):
        """无效 Token → HTTPException 401"""
        with pytest.raises(HTTPException) as exc:
            verify_access_token("invalid.jwt.token")
        assert exc.value.status_code == 401
        assert "Invalid or expired token" in exc.value.detail

    def test_verify_expired_token_raises(self):
        """已过期 Token → HTTPException 401"""
        token = create_access_token(
            subject="user001",
            expires_delta=timedelta(seconds=-1),  # 过去
        )
        with pytest.raises(HTTPException) as exc:
            verify_access_token(token)
        assert exc.value.status_code == 401

    def test_verify_wrong_secret_raises(self):
        """使用不同密钥签名的 Token → 验证失败"""
        wrong_token = jwt.encode(
            {"sub": "user001", "role": "user"},
            "wrong-secret",
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            verify_access_token(wrong_token)
        assert exc.value.status_code == 401

    def test_verify_missing_sub_raises(self):
        """缺少 subject 的 Token → HTTPException 401"""
        bad_token = jwt.encode(
            {"role": "user", "exp": datetime.now(UTC) + timedelta(hours=1)},
            os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-production"),
            algorithm=os.environ.get("JWT_ALGORITHM", "HS256"),
        )
        with pytest.raises(HTTPException) as exc:
            verify_access_token(bad_token)
        assert exc.value.status_code == 401
        assert "missing subject" in exc.value.detail.lower()

    def test_verify_empty_token_raises(self):
        """空 Token → HTTPException 401"""
        with pytest.raises(HTTPException):
            verify_access_token("")

    def test_verify_malformed_token_raises(self):
        """畸形 Token → HTTPException 401"""
        with pytest.raises(HTTPException):
            verify_access_token("not-a-jwt-at-all")


# ============================================================
#  FastAPI Dependencies — 通过 TestClient 测试
# ============================================================


def _make_test_app(**kwargs) -> FastAPI:
    """创建一个测试用 FastAPI 应用，注入 auth 依赖。"""
    app = FastAPI()

    @app.get("/protected")
    async def protected_endpoint(user: User = Depends(get_current_user)):
        return {"user_id": user.id, "role": user.role}

    @app.get("/service-only")
    async def service_endpoint(user: User = Depends(get_current_service)):
        return {"user_id": user.id, "role": user.role}

    @app.get("/optional-auth")
    async def optional_endpoint(user: User | None = Depends(get_optional_user)):
        if user:
            return {"user_id": user.id, "role": user.role, "authenticated": True}
        return {"authenticated": False}

    @app.get("/admin-only")
    async def admin_endpoint(user: User = Depends(require_role("admin"))):
        return {"user_id": user.id, "role": user.role}

    return app


class TestGetCurrentUser:
    """get_current_user 依赖测试"""

    def setup_method(self):
        self.app = _make_test_app()
        self.client = TestClient(self.app)

    def test_valid_bearer_token(self):
        """有效 Bearer Token → 正常返回用户信息"""
        token = create_access_token(subject="user001", role="user")
        resp = self.client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user001"
        assert data["role"] == "user"

    def test_admin_bearer_token(self):
        """管理员 Token"""
        token = create_access_token(subject="admin001", role="admin")
        resp = self.client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "admin001"
        assert resp.json()["role"] == "admin"

    def test_no_credentials(self):
        """无凭证 → 401"""
        resp = self.client.get("/protected")
        assert resp.status_code == 401

    def test_expired_token(self):
        """过期 Token → 401"""
        token = create_access_token(
            subject="user001",
            expires_delta=timedelta(seconds=-1),
        )
        resp = self.client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_invalid_token_format(self):
        """格式错误 → 401"""
        resp = self.client.get("/protected", headers={"Authorization": "Bearer not-a-token"})
        assert resp.status_code == 401

    def test_wrong_auth_scheme(self):
        """非 Bearer 方案 → 401（auto_error=True 时报错）"""
        resp = self.client.get("/protected", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        # HTTPBearer(auto_error=False) — 不会自行报错，但 get_current_user 会
        assert resp.status_code == 401

    def test_token_with_service_role(self):
        """service 角色的 Token 也可通过 get_current_user（不做角色过滤）"""
        token = create_access_token(subject="svc-ingestion", role="service")
        resp = self.client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "service"


class TestGetOptionalUser:
    """get_optional_user 依赖测试"""

    def setup_method(self):
        self.app = _make_test_app()
        self.client = TestClient(self.app)

    def test_with_valid_token(self):
        """有效 Token → 返回用户"""
        token = create_access_token(subject="guest001")
        resp = self.client.get("/optional-auth", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user_id"] == "guest001"

    def test_without_token(self):
        """无 Token → 返回 None"""
        resp = self.client.get("/optional-auth")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_with_expired_token(self):
        """过期 Token → 返回 None（不抛出异常）"""
        token = create_access_token(
            subject="guest001",
            expires_delta=timedelta(seconds=-1),
        )
        resp = self.client.get("/optional-auth", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_with_invalid_token(self):
        """无效 Token → 返回 None"""
        resp = self.client.get(
            "/optional-auth",
            headers={"Authorization": "Bearer definitely.invalid.token"},
        )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False


class TestRequireRole:
    """require_role 依赖测试"""

    def setup_method(self):
        self.app = _make_test_app()
        self.client = TestClient(self.app)

    def test_admin_role_allowed(self):
        """admin 角色访问 admin-only → 200"""
        token = create_access_token(subject="root", role="admin")
        resp = self.client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_user_role_denied(self):
        """user 角色访问 admin-only → 403"""
        token = create_access_token(subject="user001", role="user")
        resp = self.client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"].lower()

    def test_service_role_denied(self):
        """service 角色访问 admin-only → 403"""
        token = create_access_token(subject="svc", role="service")
        resp = self.client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_no_token_denied(self):
        """无 Token → require_role 内部调用 get_current_user → 401"""
        resp = self.client.get("/admin-only")
        assert resp.status_code == 401


# ============================================================
#  API Key 认证测试
# ============================================================


class TestAPIKeyAuth:
    """API Key 方式认证（通过 get_current_service）"""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        """设置测试用 API Key"""
        monkeypatch.setenv("API_KEYS", "test-key-1,test-key-2")
        # 重载模块使 _API_KEYS 生效
        import importlib

        import shared.auth as auth_module

        importlib.reload(auth_module)
        # 重新导入更新后的模块
        global get_current_service, get_current_user, verify_access_token, create_access_token
        from shared.auth import (
            User,
            create_access_token,
            get_current_service,
            get_current_user,
            require_role,
            verify_access_token,
        )

        yield

        # 清理
        monkeypatch.delenv("API_KEYS", raising=False)
        importlib.reload(auth_module)

    def setup_method(self):
        self.app = _make_test_app()
        self.client = TestClient(self.app)

    def test_valid_api_key_service_only(self):
        """有效 API Key → 200"""
        resp = self.client.get("/service-only", headers={"X-API-Key": "test-key-1"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "internal_service"
        assert resp.json()["role"] == "service"

    def test_valid_api_key_second_key(self):
        """第二个 API Key → 200"""
        resp = self.client.get("/service-only", headers={"X-API-Key": "test-key-2"})
        assert resp.status_code == 200

    def test_invalid_api_key(self):
        """无效 API Key → 401"""
        resp = self.client.get("/service-only", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    def test_missing_api_key(self):
        """无 API Key → 401"""
        resp = self.client.get("/service-only")
        assert resp.status_code == 401

    def test_valid_api_key_also_works_for_get_current_user(self):
        """API Key 也可以通过 get_current_user（双模式）"""
        resp = self.client.get("/protected", headers={"X-API-Key": "test-key-1"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "api_service"
        assert resp.json()["role"] == "service"

    def test_invalid_api_key_get_current_user(self):
        """无效 API Key 在 get_current_user 中 → 401"""
        resp = self.client.get("/protected", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_api_key_requires_configured(self):
        """未配置 API_KEYS 时 → 500"""
        from unittest.mock import patch

        import shared.auth as auth_mod

        with patch.object(auth_mod, "_API_KEYS", set()):
            # patch 后无需 reload，get_current_service 运行时读取模块级的 _API_KEYS
            from shared.auth import get_current_service

            app = FastAPI()

            @app.get("/svc-only")
            async def svc_endpoint(user=Depends(get_current_service)):
                return {"ok": True}

            client = TestClient(app)
            resp = client.get("/svc-only", headers={"X-API-Key": "test-key-1"})
            assert resp.status_code == 500


# ============================================================
#  安全边界测试
# ============================================================


class TestSecurityBoundaries:
    """安全相关边界测试"""

    def test_minimal_subject(self, monkeypatch):
        """极短的 subject"""
        token = create_access_token(subject="a")
        data = verify_access_token(token)
        assert data.sub == "a"

    def test_long_subject(self, monkeypatch):
        """超长 subject"""
        long_sub = "x" * 1000
        token = create_access_token(subject=long_sub)
        data = verify_access_token(token)
        assert data.sub == long_sub

    def test_special_chars_in_subject(self, monkeypatch):
        """subject 包含特殊字符"""
        token = create_access_token(subject="user@company.com|123")
        data = verify_access_token(token)
        assert data.sub == "user@company.com|123"

    def test_role_case_sensitivity(self, monkeypatch):
        """角色大小写敏感"""
        token = create_access_token(subject="admin001", role="Admin")
        data = verify_access_token(token)
        assert data.role == "Admin"  # 不做大小写归一化

    def test_get_current_service_no_api_keys_configured(self, monkeypatch):
        """API_KEYS 为空时抛 500"""
        import importlib

        import shared.auth

        monkeypatch.setenv("API_KEYS", "")
        importlib.reload(shared.auth)
        from shared.auth import get_current_service

        # 创建一个新 app 使用 reload 后的依赖
        app = FastAPI()

        @app.get("/svc")
        async def svc_endpoint(user=Depends(get_current_service)):
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/svc", headers={"X-API-Key": "any-key"})
        assert resp.status_code == 500
