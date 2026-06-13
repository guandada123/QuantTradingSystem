"""shared/graceful_shutdown.py 单元测试 — 信号处理 + 请求排空"""

from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.graceful_shutdown import (
    _shutdown_flag,
    decrement_active,
    get_active_count,
    increment_active,
    is_shutting_down,
    register_shutdown_callback,
)


class TestShutdownFlag:
    def setup_method(self):
        _shutdown_flag.clear()

    def test_initially_not_shutting_down(self):
        assert is_shutting_down() is False

    def test_flag_set_triggers_shutdown(self):
        _shutdown_flag.set()
        assert is_shutting_down() is True

    def test_flag_clear_resets(self):
        _shutdown_flag.set()
        _shutdown_flag.clear()
        assert is_shutting_down() is False


class TestActiveRequests:
    def setup_method(self):
        import shared.graceful_shutdown as gs

        gs._active_requests = 0

    def test_increment_and_decrement(self):
        increment_active()
        assert get_active_count() == 1
        increment_active()
        assert get_active_count() == 2
        decrement_active()
        assert get_active_count() == 1
        decrement_active()
        assert get_active_count() == 0

    def test_concurrent_increment(self):
        """并发增减不丢失计数"""
        import shared.graceful_shutdown as gs

        gs._active_requests = 0
        threads = []
        for _ in range(50):
            t = threading.Thread(target=increment_active)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        assert get_active_count() == 50

        threads = []
        for _ in range(50):
            t = threading.Thread(target=decrement_active)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        assert get_active_count() == 0


class TestShutdownCallbacks:
    def test_register_callback(self):
        results = []

        def my_cleanup():
            results.append("cleaned")

        register_shutdown_callback(my_cleanup)
        # 回调已注册（不自动执行，需 lifespan 退出时调用）
        from shared.graceful_shutdown import _shutdown_callbacks

        assert my_cleanup in _shutdown_callbacks
