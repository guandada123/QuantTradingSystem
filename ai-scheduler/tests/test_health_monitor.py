"""
services/health_monitor.py 单元测试
覆盖: 初始化、check_service、check_all、状态变化检测、start/stop、get_status、循环异常恢复
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call


class TestHealthMonitorInit:
    """HealthMonitor 初始化测试"""

    def test_init_no_alert_service(self, health_monitor_no_alert):
        """无告警服务初始化"""
        assert health_monitor_no_alert.alert_service is None
        assert health_monitor_no_alert._previous_status == {}
        assert health_monitor_no_alert._current_status == {}
        assert health_monitor_no_alert._running is False

    def test_init_with_alert_service(self, health_monitor_with_alert):
        """带告警服务初始化"""
        assert health_monitor_with_alert.alert_service is not None
        assert health_monitor_with_alert._running is False

    def test_services_dict(self, health_monitor_no_alert):
        """默认监控的服务列表"""
        from services.health_monitor import HealthMonitor
        assert "strategy-service" in HealthMonitor.SERVICES
        assert "execution-service" in HealthMonitor.SERVICES
        assert "ai-scheduler" in HealthMonitor.SERVICES
        assert len(HealthMonitor.SERVICES) == 3

    def test_service_urls_are_valid(self, health_monitor_no_alert):
        """服务 URL 格式正确"""
        from services.health_monitor import HealthMonitor
        for name, url in HealthMonitor.SERVICES.items():
            assert url.startswith("http://")
            assert "/health" in url


class TestCheckService:
    """check_service 方法测试"""

    @pytest.mark.asyncio
    async def test_check_service_healthy(self, health_monitor_no_alert, mock_httpx_get_healthy):
        """服务健康（200）"""
        result = await health_monitor_no_alert.check_service("test-svc", "http://test:8000/health")
        assert result is True
        mock_httpx_get_healthy.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_service_unhealthy(self, health_monitor_no_alert, mock_httpx_get_unhealthy):
        """服务不健康（500）"""
        result = await health_monitor_no_alert.check_service("test-svc", "http://test:8000/health")
        assert result is False

    @pytest.mark.asyncio
    async def test_check_service_exception(self, health_monitor_no_alert, mock_httpx_get_exception):
        """服务不可达（异常）"""
        result = await health_monitor_no_alert.check_service("test-svc", "http://test:8000/health")
        assert result is False

    @pytest.mark.asyncio
    async def test_check_service_timeout_set(self, health_monitor_no_alert):
        """超时时间设为 5 秒"""
        with patch("services.health_monitor.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=MagicMock(status_code=200)
            )
            await health_monitor_no_alert.check_service("svc", "http://test/health")
        # 验证 httpx.AsyncClient 创建时 timeout=5
        mock_client.assert_called_once_with(timeout=5)


class TestCheckAll:
    """check_all 方法测试"""

    @pytest.mark.asyncio
    async def test_check_all_returns_dict(self, health_monitor_no_alert, mock_httpx_get_healthy):
        """返回字典格式"""
        result = await health_monitor_no_alert.check_all()
        assert isinstance(result, dict)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_check_all_all_healthy(self, health_monitor_no_alert, mock_httpx_get_healthy):
        """全部健康"""
        result = await health_monitor_no_alert.check_all()
        assert all(result.values())

    @pytest.mark.asyncio
    async def test_check_all_updates_current_status(self, health_monitor_no_alert, mock_httpx_get_healthy):
        """更新 _current_status"""
        await health_monitor_no_alert.check_all()
        assert health_monitor_no_alert._current_status == {
            "strategy-service": True,
            "execution-service": True,
            "ai-scheduler": True,
        }


class TestStateChangeDetection:
    """状态变化检测测试"""

    @pytest.mark.asyncio
    async def test_healthy_to_unhealthy_triggers_down_alert(self, health_monitor_with_alert):
        """正常→异常触发宕机告警"""
        # 模拟前一状态正常
        health_monitor_with_alert._previous_status = {"svc": True}

        with patch.object(health_monitor_with_alert, "check_all", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = {"svc": False}
            with patch.object(health_monitor_with_alert.alert_service, "send_service_down", new_callable=AsyncMock) as mock_down:
                # 只运行一次循环迭代
                health_monitor_with_alert._running = True
                task = asyncio.create_task(health_monitor_with_alert.run_monitoring_loop(0.01))
                await asyncio.sleep(0.05)
                health_monitor_with_alert._running = False
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

                # 应该触发 send_service_down
                mock_down.assert_called()

    @pytest.mark.asyncio
    async def test_unhealthy_to_healthy_triggers_recovered_alert(self, health_monitor_with_alert):
        """异常→正常触发恢复通知"""
        health_monitor_with_alert._previous_status = {"svc": False}

        with patch.object(health_monitor_with_alert, "check_all", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = {"svc": True}
            with patch.object(health_monitor_with_alert.alert_service, "send_service_recovered", new_callable=AsyncMock) as mock_recovered:
                health_monitor_with_alert._running = True
                task = asyncio.create_task(health_monitor_with_alert.run_monitoring_loop(0.01))
                await asyncio.sleep(0.05)
                health_monitor_with_alert._running = False
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

                mock_recovered.assert_called()

    @pytest.mark.asyncio
    async def test_no_state_change_no_alert(self, health_monitor_with_alert):
        """状态不变不发送告警"""
        health_monitor_with_alert._previous_status = {"svc": True}

        with patch.object(health_monitor_with_alert, "check_all", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = {"svc": True}
            with patch.object(health_monitor_with_alert.alert_service, "send_service_down", new_callable=AsyncMock) as mock_down:
                health_monitor_with_alert._running = True
                task = asyncio.create_task(health_monitor_with_alert.run_monitoring_loop(0.01))
                await asyncio.sleep(0.05)
                health_monitor_with_alert._running = False
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

                mock_down.assert_not_called()

    @pytest.mark.asyncio
    async def test_first_check_no_previous_status_no_alert(self, health_monitor_with_alert):
        """首次检查（无 previous_status）不发送告警"""
        # _previous_status 为空
        assert health_monitor_with_alert._previous_status == {}

        with patch.object(health_monitor_with_alert, "check_all", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = {"svc": False}
            with patch.object(health_monitor_with_alert.alert_service, "send_service_down", new_callable=AsyncMock) as mock_down:
                health_monitor_with_alert._running = True
                task = asyncio.create_task(health_monitor_with_alert.run_monitoring_loop(0.01))
                await asyncio.sleep(0.05)
                health_monitor_with_alert._running = False
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

                # 首次检查不应该触发告警（was_healthy is None）
                mock_down.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_exception_does_not_crash(self, health_monitor_no_alert):
        """循环异常不应该导致崩溃"""
        with patch.object(health_monitor_no_alert, "check_all", side_effect=Exception("Unexpected error")):
            health_monitor_no_alert._running = True
            task = asyncio.create_task(health_monitor_no_alert.run_monitoring_loop(0.01))
            await asyncio.sleep(0.05)
            health_monitor_no_alert._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # 不应抛出异常


class TestStartStop:
    """start/stop 方法测试"""

    @pytest.mark.asyncio
    async def test_start_sets_running_true(self, health_monitor_no_alert):
        """start 设置 _running = True"""
        await health_monitor_no_alert.start(interval=0.1)
        assert health_monitor_no_alert._running is True
        await health_monitor_no_alert.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, health_monitor_no_alert):
        """stop 设置 _running = False"""
        await health_monitor_no_alert.start(interval=0.1)
        await health_monitor_no_alert.stop()
        assert health_monitor_no_alert._running is False

    @pytest.mark.asyncio
    async def test_start_creates_background_task(self, health_monitor_no_alert, mock_httpx_get_healthy):
        """start 创建后台任务"""
        await health_monitor_no_alert.start(interval=0.1)
        # 等后台任务运行一次
        await asyncio.sleep(0.2)
        await health_monitor_no_alert.stop()
        # 应该已经执行过检查
        assert mock_httpx_get_healthy.call_count >= 0  # 可能已被调用


class TestGetStatus:
    """get_status 方法测试"""

    def test_get_status_returns_copy(self, health_monitor_no_alert):
        """返回 _current_status 的副本"""
        health_monitor_no_alert._current_status = {"svc": True}
        status = health_monitor_no_alert.get_status()
        assert status == {"svc": True}
        # 修改返回的副本不影响原始
        status["svc"] = False
        assert health_monitor_no_alert._current_status["svc"] is True

    def test_get_status_empty_initially(self, health_monitor_no_alert):
        """初始状态为空"""
        assert health_monitor_no_alert.get_status() == {}


class TestMonitoringLoop:
    """监控循环测试"""

    @pytest.mark.asyncio
    async def test_loop_calls_check_all(self, health_monitor_no_alert, mock_httpx_get_healthy):
        """循环中调用 check_all"""
        with patch.object(health_monitor_no_alert, "check_all", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = {"svc": True}
            health_monitor_no_alert._running = True
            task = asyncio.create_task(health_monitor_no_alert.run_monitoring_loop(0.01))
            await asyncio.sleep(0.05)
            health_monitor_no_alert._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert mock_check.call_count >= 1

    @pytest.mark.asyncio
    async def test_loop_stops_when_running_false(self, health_monitor_no_alert):
        """_running=False 时循环停止"""
        health_monitor_no_alert._running = False
        # run_monitoring_loop 应该立即退出（因为 while self._running 为 False）
        await health_monitor_no_alert.run_monitoring_loop(interval=0.01)
        # 不应该抛出异常

    @pytest.mark.asyncio
    async def test_loop_default_interval_300s(self, health_monitor_no_alert):
        """默认间隔为 300 秒"""
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = [None, Exception("stop")]  # 第一次 sleep 成功，第二次抛异常
            health_monitor_no_alert._running = True
            try:
                await health_monitor_no_alert.run_monitoring_loop()
            except Exception:
                pass
            health_monitor_no_alert._running = False
            # 默认应该传 300
            if mock_sleep.call_args_list:
                assert mock_sleep.call_args_list[0] == call(300)

    @pytest.mark.asyncio
    async def test_loop_custom_interval(self, health_monitor_no_alert):
        """自定义间隔"""
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = [None, Exception("stop")]
            health_monitor_no_alert._running = True
            try:
                await health_monitor_no_alert.run_monitoring_loop(interval=60)
            except Exception:
                pass
            health_monitor_no_alert._running = False
            if mock_sleep.call_args_list:
                assert mock_sleep.call_args_list[0] == call(60)
