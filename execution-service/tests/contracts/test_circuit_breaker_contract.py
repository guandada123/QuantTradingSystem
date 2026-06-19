"""
熔断器状态机契约测试 v1.0

验证 CircuitBreaker 的核心行为契约：
1. TestInitContract — 初始状态全部闭合，计数器归零
2. TestOpenContract — 连续止损次数达到阈值后自动断开
3. TestCooldownContract — 冷却期自动恢复交易
4. TestProfitResetContract — 盈利记录重置止损计数
5. TestResetContract — 手动重置恢复初始状态
6. TestIdempotentContract — NOP 操作的幂等性

不依赖任何外部服务，直接测试 services.risk_controller.CircuitBreaker。
"""

import time
from datetime import datetime

import pytest

from services.risk_controller import CircuitBreaker


# =========================================================================
# 1. 初始状态合约
# =========================================================================


class TestInitContract:
    """契约：新实例必须处于 CLOSED 状态，计数器为零"""

    def test_is_allowed_by_default(self):
        """初始状态下 is_allowed() 返回 True"""
        cb = CircuitBreaker()
        assert cb.is_allowed() is True

    def test_is_open_false_by_default(self):
        """初始状态下 is_open 为 False"""
        cb = CircuitBreaker()
        assert cb._is_open is False

    def test_consecutive_losses_zero(self):
        """初始状态下 consecutive_losses 为 0"""
        cb = CircuitBreaker()
        assert cb._consecutive_losses == 0

    def test_status_contract(self):
        """status 属性必须包含全部关键字段"""
        cb = CircuitBreaker()
        s = cb.status
        assert "is_open" in s
        assert "consecutive_losses" in s
        assert "opened_at" in s
        assert "cooldown_remaining_minutes" in s
        assert s["is_open"] is False
        assert s["consecutive_losses"] == 0
        assert s["opened_at"] is None
        assert s["cooldown_remaining_minutes"] == 0

    def test_default_parameters_stored(self):
        """默认参数正确存储"""
        cb = CircuitBreaker()
        assert cb.max_consecutive_losses == 3
        assert cb.cooldown_minutes == 30

    def test_custom_parameters_stored(self):
        """自定义参数正确存储"""
        cb = CircuitBreaker(max_consecutive_losses=5, cooldown_minutes=60)
        assert cb.max_consecutive_losses == 5
        assert cb.cooldown_minutes == 60

    def test_opened_at_none_when_closed(self):
        """闭合状态下 opened_at 为 None"""
        cb = CircuitBreaker()
        assert cb._opened_at is None


# =========================================================================
# 2. 熔断触发合约
# =========================================================================


class TestOpenContract:
    """契约：连续止损达到阈值后自动断开"""

    def test_one_loss_does_not_open(self):
        """一次止损不会打开熔断器"""
        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb.record_loss()
        assert cb._is_open is False
        assert cb.is_allowed() is True

    def test_two_losses_still_closed(self):
        """两次止损仍不会打开熔断器"""
        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb.record_loss()
        cb.record_loss()
        assert cb._is_open is False

    def test_three_losses_opens_breaker(self):
        """三次止损打开熔断器"""
        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb.record_loss()
        cb.record_loss()
        cb.record_loss()
        assert cb._is_open is True

    def test_fourth_loss_stays_open(self):
        """超过阈值后继续记录损失，熔断器保持打开"""
        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        for _ in range(5):
            cb.record_loss()
        assert cb._is_open is True
        assert cb._consecutive_losses == 5

    def test_breaker_open_blocks_trading(self):
        """熔断器打开后 is_allowed() 返回 False"""
        cb = CircuitBreaker(max_consecutive_losses=2, cooldown_minutes=30)
        cb.record_loss()
        cb.record_loss()
        assert cb.is_allowed() is False

    def test_opened_at_set_on_trigger(self):
        """熔断触发时 opened_at 被设置为当前时间"""
        cb = CircuitBreaker(max_consecutive_losses=2, cooldown_minutes=30)
        before = datetime.now()
        cb.record_loss()
        cb.record_loss()
        after = datetime.now()
        assert cb._opened_at is not None
        assert before <= cb._opened_at <= after

    def test_status_reflects_open_state(self):
        """status 属性反映打开状态"""
        cb = CircuitBreaker(max_consecutive_losses=2, cooldown_minutes=30)
        cb.record_loss()
        cb.record_loss()
        s = cb.status
        assert s["is_open"] is True
        assert s["consecutive_losses"] == 2
        assert s["opened_at"] is not None
        assert s["cooldown_remaining_minutes"] > 0

    @pytest.fixture
    def single_loss_cb(self):
        """恰好一次损失的熔断器（阈值=1 的边界）"""
        cb = CircuitBreaker(max_consecutive_losses=1, cooldown_minutes=30)
        cb.record_loss()
        return cb

    def test_boundary_min_losses(self, single_loss_cb):
        """max_consecutive_losses=1 时一次损失即触发"""
        assert single_loss_cb._is_open is True
        assert single_loss_cb.is_allowed() is False

    def test_boundary_max_losses_zero(self):
        """max_consecutive_losses=0 时永远触发（极端边界）"""
        cb = CircuitBreaker(max_consecutive_losses=0, cooldown_minutes=30)
        cb.record_loss()
        assert cb._is_open is True


# =========================================================================
# 3. 冷却恢复合约
# =========================================================================


class TestCooldownContract:
    """契约：冷却期结束后自动恢复交易"""

    def test_cooldown_expires_auto_recovery(self):
        """冷却到期后 is_allowed() 自动恢复为 True"""
        cb = CircuitBreaker(max_consecutive_losses=1, cooldown_minutes=0.001)  # 极短冷却
        cb.record_loss()
        assert cb.is_allowed() is False  # 刚触发，冷却尚未开始

        # 这里我们只能验证逻辑：冷却时间为 0 时，经过足够时间后应恢复
        # 但由于时间不可控，我们通过 _opened_at 模拟时间推移来验证
        # 真正的冷却测试在 test_cooldown_elapsed_recovery 中

    def test_cooldown_elapsed_recovery(self):
        """冷却时间已过，is_allowed() 返回 True，内部状态重置"""
        cb = CircuitBreaker(max_consecutive_losses=1, cooldown_minutes=0.001)
        cb.record_loss()
        cb.is_allowed()  # 第一次调用：仍可能处于冷却期

        # 模拟冷却已过：将 _opened_at 设置为很久以前
        import datetime as dt
        cb._opened_at = dt.datetime.now() - dt.timedelta(hours=1)

        # 此时 is_allowed() 应返回 True，并自动恢复
        assert cb.is_allowed() is True
        assert cb._is_open is False
        assert cb._consecutive_losses == 0
        assert cb._opened_at is None

    def test_recovery_resets_status(self):
        """恢复后 status 显示闭合"""
        cb = CircuitBreaker(max_consecutive_losses=1, cooldown_minutes=0.001)
        cb.record_loss()
        cb._opened_at = datetime.now()  # 立即冷却
        cb.is_allowed()  # 触发检查

        # 手动推进时间：模拟冷却到期
        import datetime as dt
        cb._opened_at = dt.datetime.now() - dt.timedelta(hours=2)
        cb.is_allowed()

        s = cb.status
        assert s["is_open"] is False
        assert s["consecutive_losses"] == 0
        assert s["cooldown_remaining_minutes"] == 0

    def test_no_negative_cooldown(self):
        """冷却剩余时间不为负数"""
        cb = CircuitBreaker(max_consecutive_losses=1, cooldown_minutes=10)
        cb.record_loss()
        s = cb.status
        assert s["cooldown_remaining_minutes"] >= 0

    def test_zero_cooldown_instant_recovery(self):
        """cooldown_minutes=0 时立即恢复"""
        cb = CircuitBreaker(max_consecutive_losses=1, cooldown_minutes=0)
        cb.record_loss()
        # 即便是 0 冷却，第一次调用 is_allowed 时因为 elapsed=0 < cooldown=0
        # elapsed >= cooldown → False（0 >= 0 为 True），所以允许交易
        assert cb.is_allowed() is True
        assert cb._is_open is False


# =========================================================================
# 4. 盈利重置合约
# =========================================================================


class TestProfitResetContract:
    """契约：盈利记录重置止损计数"""

    def test_profit_resets_counter(self):
        """record_profit() 将 consecutive_losses 重置为 0"""
        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb.record_loss()
        cb.record_loss()
        assert cb._consecutive_losses == 2
        cb.record_profit()
        assert cb._consecutive_losses == 0

    def test_profit_keeps_breaker_open(self):
        """profit 记录不关闭已打开的熔断器（冷却期满才恢复）"""
        cb = CircuitBreaker(max_consecutive_losses=2, cooldown_minutes=30)
        cb.record_loss()
        cb.record_loss()
        assert cb._is_open is True
        cb.record_profit()
        # 虽然计数器归零，但熔断器仍为打开状态
        assert cb._is_open is True

    def test_profit_does_not_reset_opened_at(self):
        """profit 记录不清除 opened_at"""
        cb = CircuitBreaker(max_consecutive_losses=2, cooldown_minutes=30)
        cb.record_loss()
        cb.record_loss()
        opened = cb._opened_at
        assert opened is not None
        cb.record_profit()
        assert cb._opened_at is opened  # 引用不变

    def test_multiple_profits_idempotent(self):
        """多次 record_profit() 幂等"""
        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb.record_profit()
        cb.record_profit()
        cb.record_profit()
        assert cb._consecutive_losses == 0


# =========================================================================
# 5. 手动重置合约
# =========================================================================


class TestResetContract:
    """契约：reset() 恢复初始状态"""

    def test_reset_from_open(self):
        """从打开状态重置后全部归零"""
        cb = CircuitBreaker(max_consecutive_losses=2, cooldown_minutes=30)
        cb.record_loss()
        cb.record_loss()
        assert cb._is_open is True

        cb.reset()
        assert cb._is_open is False
        assert cb._consecutive_losses == 0
        assert cb._opened_at is None

    def test_reset_from_closed(self):
        """从闭合状态重置后仍维持闭合"""
        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb.reset()
        assert cb._is_open is False
        assert cb._consecutive_losses == 0
        assert cb._opened_at is None

    def test_reset_recovery(self):
        """reset() 后 is_allowed() 返回 True"""
        cb = CircuitBreaker(max_consecutive_losses=2, cooldown_minutes=30)
        cb.record_loss()
        cb.record_loss()
        assert cb.is_allowed() is False

        cb.reset()
        assert cb.is_allowed() is True

    def test_reset_twice_idempotent(self):
        """两次 reset() 幂等"""
        cb = CircuitBreaker(max_consecutive_losses=2, cooldown_minutes=30)
        cb.reset()
        cb.reset()
        assert cb._is_open is False
        assert cb._consecutive_losses == 0

    def test_reset_after_cooldown_idempotent(self):
        """冷却期后 reset 仍有效"""
        cb = CircuitBreaker(max_consecutive_losses=1, cooldown_minutes=0.001)
        cb.record_loss()
        import datetime as dt
        cb._opened_at = dt.datetime.now() - dt.timedelta(hours=1)
        cb.is_allowed()  # 自动恢复

        cb.reset()
        assert cb._is_open is False


# =========================================================================
# 6. 幂等性合约
# =========================================================================


class TestIdempotentContract:
    """契约：重复 NOP 操作不影响状态"""

    def test_record_loss_from_zero(self):
        """从零开始记录一次损失"""
        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        cb.record_loss()
        assert cb._consecutive_losses == 1

    def test_record_loss_overflow(self):
        """损失计数超过阈值时熔断器保持打开"""
        cb = CircuitBreaker(max_consecutive_losses=2, cooldown_minutes=30)
        cb.record_loss()
        cb.record_loss()
        cb.record_loss()  # 第三次
        assert cb._is_open is True
        # 熔断器打开后不受额外损失影响（is_open 保持 True）
        # 但计数器会继续增长
        assert cb._consecutive_losses == 3

    def test_is_allowed_does_not_mutate_state(self):
        """is_allowed() 是只读操作，不应该改变内部状态（除非冷却到期自动恢复）"""
        cb = CircuitBreaker(max_consecutive_losses=3, cooldown_minutes=30)
        before = cb._consecutive_losses
        cb.is_allowed()
        assert cb._consecutive_losses == before
