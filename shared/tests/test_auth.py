"""shared/auth.py 单元测试 — JWT 纯函数 + 数据模型"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException, status
from jose import jwt
import pytest

# ⚠️ auth.py 在导入时会检查 JWT_SECRET_KEY 和 ENV。
# 测试环境默认为 development，所以不会 raise RuntimeError。
from shared.auth import (
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    TokenData,
    User,
    create_access_token,
    require_role,
    verify_access_token,
)

# ============================================================
#  TokenData 模型测试
# ============================================================


class TestTokenData:
    """JWT 载荷 Pydantic 模型"""

    def test_default_role(self):
        td = TokenData(sub="user1")
        assert td.sub == "user1"
        assert td.role == "user"
        assert td.exp is None

    def test_with_role(self):
        td = TokenData(sub="admin1", role="admin")
        assert td.role == "admin"

    def test_with_exp(self):
        exp = datetime.now(UTC)
        td = TokenData(sub="user1", exp=exp)
        assert td.exp is exp


# ============================================================
#  User 模型测试
# ============================================================


class TestUser:
    def test_default_role(self):
        user = User(id="u1")
        assert user.id == "u1"
        assert user.role == "user"

    def test_with_role(self):
        user = User(id="admin1", role="admin")
        assert user.role == "admin"


# ============================================================
#  create_access_token & verify_access_token 测试
# ============================================================


class TestCreateAndVerifyToken:
    """JWT token 创建与验证的集成测试"""

    def test_create_and_verify(self):
        token = create_access_token(subject="user-001", role="user")
        assert isinstance(token, str)
        data = verify_access_token(token)
        assert data.sub == "user-001"
        assert data.role == "user"

    def test_admin_role(self):
        token = create_access_token(subject="admin-001", role="admin")
        data = verify_access_token(token)
        assert data.sub == "admin-001"
        assert data.role == "admin"

    def test_custom_expiry(self):
        expires = timedelta(hours=1)
        token = create_access_token(subject="user-002", role="user", expires_delta=expires)
        data = verify_access_token(token)
        assert data.sub == "user-002"

    def test_extra_claims(self):
        token = create_access_token(
            subject="user-003",
            role="user",
            extra_claims={"scope": "read_only", "tenant": "acme"},
        )
        # 解码查看 extra claims
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        assert payload["scope"] == "read_only"
        assert payload["tenant"] == "acme"

    def test_invalid_token_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            verify_access_token("invalid.token.here")
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    def test_tampered_token_raises(self):
        token = create_access_token(subject="user-001")
        tampered = token + "x"
        with pytest.raises(HTTPException) as exc_info:
            verify_access_token(tampered)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    def test_expired_token_raises(self):
        """过期 token 应被拒绝"""
        expires = timedelta(seconds=-1)  # 已经过期
        token = create_access_token(subject="user-001", role="user", expires_delta=expires)
        with pytest.raises(HTTPException) as exc_info:
            verify_access_token(token)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    def test_token_contains_iat(self):
        token = create_access_token(subject="user-001")
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        assert "iat" in payload
        assert "exp" in payload

    def test_missing_subject_raises(self):
        """payload 中没有 sub 字段时抛出 401"""
        # 手动构造一个无 sub 的 token
        payload = {"role": "user", "exp": datetime.now(UTC) + timedelta(hours=1)}
        token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            verify_access_token(token)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "missing subject" in exc_info.value.detail.lower()


# ============================================================
#  require_role 测试（不含 FastAPI 依赖注入）
# ============================================================


class TestRequireRole:
    """require_role 工厂函数的 inner _check_role 测试"""

    @pytest.mark.asyncio
    async def test_matching_role_passes(self):
        """角色匹配时正常返回 User"""
        check = require_role("admin")
        # 手动构造一个 User，绕过 FastAPI Depends
        user = User(id="admin1", role="admin")
        result = await check(user)
        assert result.id == "admin1"
        assert result.role == "admin"

    @pytest.mark.asyncio
    async def test_wrong_role_raises_403(self):
        """角色不匹配时抛出 403"""
        check = require_role("admin")
        user = User(id="user1", role="user")
        with pytest.raises(HTTPException) as exc_info:
            await check(user)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# ============================================================
#  生产安全校验测试
# ============================================================


class TestProductionSecurityCheck:
    """非开发环境使用默认 JWT_SECRET_KEY 时抛出 RuntimeError"""

    def test_default_key_in_production_raises(self):
        """模拟 ENV=production 且使用默认密钥时抛异常"""
        with patch.dict(
            "os.environ",
            {"ENV": "production", "JWT_SECRET_KEY": "dev-secret-change-in-production"},
            clear=False,
        ):
            # 需要重新加载 auth 模块触发检查
            import importlib

            import shared.auth as auth_mod

            with pytest.raises(RuntimeError, match="JWT_SECRET_KEY must be set"):
                importlib.reload(auth_mod)

    def test_custom_key_in_production_passes(self):
        """模拟 ENV=production 且使用自定义密钥时正常"""
        with patch.dict(
            "os.environ",
            {
                "ENV": "production",
                "JWT_SECRET_KEY": "my-strong-random-secret-key-12345678",
            },
            clear=False,
        ):
            import importlib

            import shared.auth as auth_mod

            # 不应抛出异常
            importlib.reload(auth_mod)

    def test_default_key_in_development_passes(self):
        """开发环境使用默认密钥时正常"""
        import importlib

        import shared.auth as auth_mod

        # 默认 ENV=development，不应抛异常
        importlib.reload(auth_mod)
