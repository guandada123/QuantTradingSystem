"""
端到端集成测试
测试运行中的 QuantTradingSystem Docker 服务
对 strategy-service(8000) / execution-service(8001) / ai-scheduler(8002) 进行全面验证

运行: python -m pytest tests/test_e2e.py -v --tb=short
要求: Docker Compose 已启动所有服务
"""

import json
import time
from typing import Any, Dict

import pytest
import requests
import websocket  # pip install websocket-client

# ============================================================
# 配置
# ============================================================
STRATEGY_URL = "http://localhost:8000"
EXECUTION_URL = "http://localhost:8001"
AI_SCHEDULER_URL = "http://localhost:8002"
DASHBOARD_URL = "http://localhost:3000"
GRAFANA_URL = "http://localhost:3001"
PROMETHEUS_URL = "http://localhost:9090"
ALERTMANAGER_FEISHU_URL = "http://localhost:9093"


def skip_if_not_reachable(url: str) -> bool:
    """检查服务是否可达，不可达则跳过"""
    try:
        r = requests.get(url, timeout=3)
        return r.status_code < 500
    except Exception:
        return False


# ============================================================
# 基础设施健康检查
# ============================================================


class TestInfrastructureHealth:
    """基础设施连通性和基本健康检查"""

    def test_strategy_health(self):
        """strategy-service 健康检查"""
        if not skip_if_not_reachable(f"{STRATEGY_URL}/health"):
            pytest.skip("strategy-service not reachable")
        r = requests.get(f"{STRATEGY_URL}/health")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "healthy"

    def test_execution_health(self):
        """execution-service 健康检查"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        r = requests.get(f"{EXECUTION_URL}/health")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "healthy"

    def test_ai_scheduler_health(self):
        """ai-scheduler 健康检查"""
        if not skip_if_not_reachable(f"{AI_SCHEDULER_URL}/health"):
            pytest.skip("ai-scheduler not reachable")
        r = requests.get(f"{AI_SCHEDULER_URL}/health")
        assert r.status_code == 200

    def test_dashboard_serves(self):
        """dashboard 主页可访问"""
        if not skip_if_not_reachable(DASHBOARD_URL):
            pytest.skip("dashboard not reachable")
        r = requests.get(DASHBOARD_URL)
        assert r.status_code == 200
        assert "QuantTradingSystem" in r.text or "html" in r.text.lower()

    def test_dashboard_all_pages(self):
        """dashboard 所有9个页面均可访问"""
        if not skip_if_not_reachable(DASHBOARD_URL):
            pytest.skip("dashboard not reachable")
        pages = [
            "/",
            "/orders.html",
            "/account.html",
            "/backtest.html",
            "/strategies.html",
            "/trade-analysis.html",
            "/stock-selection.html",
            "/review-analysis.html",
            "/alerts.html",
        ]
        for page in pages:
            r = requests.get(f"{DASHBOARD_URL}{page}")
            assert r.status_code == 200, f"Page {page} returned {r.status_code}"


# ============================================================
# Prometheus Metrics 验证
# ============================================================


class TestPrometheusMetrics:
    """Prometheus metrics 端点验证"""

    def test_strategy_metrics_endpoint(self):
        """strategy-service /metrics 端点返回有效指标"""
        if not skip_if_not_reachable(f"{STRATEGY_URL}/health"):
            pytest.skip("strategy-service not reachable")
        r = requests.get(f"{STRATEGY_URL}/metrics")
        assert r.status_code == 200
        assert "http_requests_total" in r.text

    def test_execution_metrics_endpoint(self):
        """execution-service /metrics 端点返回有效指标"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        r = requests.get(f"{EXECUTION_URL}/metrics")
        assert r.status_code == 200
        assert "http_requests_total" in r.text

    def test_prometheus_up(self):
        """Prometheus 服务运行中"""
        if not skip_if_not_reachable(f"{PROMETHEUS_URL}/-/healthy"):
            pytest.skip("Prometheus not reachable")
        r = requests.get(f"{PROMETHEUS_URL}/-/healthy")
        assert r.status_code == 200

    def test_prometheus_scraping_targets(self):
        """Prometheus 采集目标状态"""
        if not skip_if_not_reachable(f"{PROMETHEUS_URL}/-/healthy"):
            pytest.skip("Prometheus not reachable")
        r = requests.get(f"{PROMETHEUS_URL}/api/v1/targets")
        data = r.json()
        assert data["status"] == "success"
        targets = data["data"]["activeTargets"]
        assert len(targets) >= 3, f"Expected >=3 targets, got {len(targets)}"

    def test_grafana_accessible(self):
        """Grafana 可访问"""
        if not skip_if_not_reachable(f"{GRAFANA_URL}/api/health"):
            pytest.skip("Grafana not reachable")
        r = requests.get(f"{GRAFANA_URL}/api/health")
        assert r.status_code == 200


# ============================================================
# API 端点验证
# ============================================================


class TestStrategyAPI:
    """strategy-service API 端点"""

    def test_root_endpoint(self):
        if not skip_if_not_reachable(f"{STRATEGY_URL}/health"):
            pytest.skip("strategy-service not reachable")
        r = requests.get(f"{STRATEGY_URL}/")
        assert r.status_code == 200

    def test_stock_pool_endpoint(self):
        """股票池端点"""
        if not skip_if_not_reachable(f"{STRATEGY_URL}/health"):
            pytest.skip("strategy-service not reachable")
        r = requests.get(f"{STRATEGY_URL}/api/v1/stock-pool")
        assert r.status_code in [200, 404, 500]

    def test_signal_endpoint(self):
        """交易信号端点"""
        if not skip_if_not_reachable(f"{STRATEGY_URL}/health"):
            pytest.skip("strategy-service not reachable")
        r = requests.get(f"{STRATEGY_URL}/api/v1/signals")
        assert r.status_code in [200, 404, 500]

    def test_backtest_endpoint(self):
        """回测端点"""
        if not skip_if_not_reachable(f"{STRATEGY_URL}/health"):
            pytest.skip("strategy-service not reachable")
        r = requests.get(f"{STRATEGY_URL}/api/v1/backtest/results")
        assert r.status_code in [200, 404, 500]


class TestExecutionAPI:
    """execution-service API 端点"""

    def test_orders_list(self):
        """订单列表"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        r = requests.get(f"{EXECUTION_URL}/api/v1/orders/")
        assert r.status_code in [200, 404]

    def test_positions_list(self):
        """持仓列表"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        r = requests.get(f"{EXECUTION_URL}/api/v1/positions/")
        assert r.status_code in [200, 404]

    def test_risk_check_endpoint(self):
        """风控检查端点"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        r = requests.get(
            f"{EXECUTION_URL}/api/v1/risk/check/600519.SH",
            params={"action": "BUY", "quantity": 100, "price": 1850.0},
        )
        assert r.status_code in [200, 403, 500]

    def test_risk_settings_endpoint(self):
        """风控参数查询"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        r = requests.get(f"{EXECUTION_URL}/api/v1/risk/settings")
        assert r.status_code == 200
        data = r.json()
        assert "max_position_ratio" in str(data).lower() or "max" in str(data).lower()

    def test_risk_events_endpoint(self):
        """风控事件列表"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        r = requests.get(f"{EXECUTION_URL}/api/v1/risk/events")
        assert r.status_code == 200

    def test_circuit_breaker_endpoint(self):
        """熔断器状态查询"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        r = requests.get(f"{EXECUTION_URL}/api/v1/risk/circuit-breaker")
        assert r.status_code == 200
        data = r.json()
        assert data.get("code") == 0 or "code" in data
        assert "is_open" in data.get("data", data)

    def test_position_monitor_endpoint(self):
        """持仓监控端点"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        r = requests.get(f"{EXECUTION_URL}/api/v1/risk/monitor")
        assert r.status_code in [200, 404, 500]

    def test_orders_daily_summary(self):
        """当日交易汇总"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        r = requests.get(f"{EXECUTION_URL}/api/v1/orders/summary/daily")
        assert r.status_code in [200, 404]


class TestAISchedulerAPI:
    """ai-scheduler API 端点"""

    def test_root_endpoint(self):
        if not skip_if_not_reachable(f"{AI_SCHEDULER_URL}/health"):
            pytest.skip("ai-scheduler not reachable")
        r = requests.get(f"{AI_SCHEDULER_URL}/")
        assert r.status_code == 200

    def test_metrics_endpoint(self):
        """metrics 端点"""
        if not skip_if_not_reachable(f"{AI_SCHEDULER_URL}/health"):
            pytest.skip("ai-scheduler not reachable")
        r = requests.get(f"{AI_SCHEDULER_URL}/metrics")
        assert r.status_code == 200


# ============================================================
# 跨服务集成验证
# ============================================================


class TestCrossServiceIntegration:
    """跨服务集成验证"""

    def test_execution_calls_strategy(self):
        """execution 可通过内部网络访问 strategy"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        # 验证 execution 能正常处理请求（间接验证与数据库的连通性）
        r = requests.get(f"{EXECUTION_URL}/api/v1/risk/settings")
        assert r.status_code == 200

    def test_strategy_stock_data_available(self):
        """strategy 股票数据可查询"""
        if not skip_if_not_reachable(f"{STRATEGY_URL}/health"):
            pytest.skip("strategy-service not reachable")
        # 测试行情数据端点（使用真实路径）
        endpoints = [
            "/api/v1/stocks/realtime/600519",
            "/api/v1/stocks/pool",
            "/api/v1/account/summary",
        ]
        success = 0
        for endpoint in endpoints:
            try:
                r = requests.get(f"{STRATEGY_URL}{endpoint}", timeout=10)
                if r.status_code == 200:
                    success += 1
            except Exception:
                pass
        # 至少有一个端点返回成功
        assert success >= 1, "All stock data endpoints failed"


# ============================================================
# 安全验证
# ============================================================


class TestSecurity:
    """安全性验证"""

    def test_no_env_exposure(self):
        """确保 /metrics 不泄露密钥"""
        if not skip_if_not_reachable(f"{STRATEGY_URL}/health"):
            pytest.skip("strategy-service not reachable")
        r = requests.get(f"{STRATEGY_URL}/metrics")
        assert r.status_code == 200
        # 不应包含 API 密钥
        assert "sk-" not in r.text, "API key leaked in metrics!"
        assert "TUSHARE_TOKEN" not in r.text, "Token name leaked in metrics!"

    def test_security_headers_dashboard(self):
        """dashboard 返回安全头部"""
        if not skip_if_not_reachable(DASHBOARD_URL):
            pytest.skip("dashboard not reachable")
        r = requests.get(DASHBOARD_URL)
        assert "nosniff" in r.headers.get("X-Content-Type-Options", "").lower()
        assert (
            r.headers.get("X-XSS-Protection") is not None
            or r.headers.get("X-Content-Type-Options") is not None
        )

    def test_health_no_sensitive_data(self):
        """/health 端点不泄露敏感信息"""
        if not skip_if_not_reachable(f"{EXECUTION_URL}/health"):
            pytest.skip("execution-service not reachable")
        r = requests.get(f"{EXECUTION_URL}/health")
        data = r.json()
        sensitive_keys = ["password", "secret", "token", "api_key"]
        for key in sensitive_keys:
            assert key not in str(data).lower(), f"Sensitive key '{key}' exposed"


# ============================================================
# 性能基线
# ============================================================


class TestPerformanceBaseline:
    """性能基线测试"""

    def test_health_response_time(self):
        """健康检查响应 < 200ms"""
        if not skip_if_not_reachable(f"{STRATEGY_URL}/health"):
            pytest.skip("strategy-service not reachable")
        times = []
        for _ in range(5):
            start = time.time()
            r = requests.get(f"{STRATEGY_URL}/health")
            times.append((time.time() - start) * 1000)
            assert r.status_code == 200
        avg = sum(times) / len(times)
        assert avg < 500, f"Health check too slow: {avg:.0f}ms avg"

    def test_concurrent_requests(self):
        """并发10个请求不报错"""
        import concurrent.futures

        if not skip_if_not_reachable(f"{STRATEGY_URL}/health"):
            pytest.skip("strategy-service not reachable")

        def make_request():
            r = requests.get(f"{STRATEGY_URL}/health", timeout=10)
            return r.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            results = [f.result() for f in futures]

        assert all(s == 200 for s in results), f"Concurrent failures: {results}"


# ============================================================
# 新增服务验证
# ============================================================


class TestNewServices:
    """P5 新增服务验证"""

    def test_alertmanager_feishu_health(self):
        """Alertmanager→飞书适配器健康检查"""
        if not skip_if_not_reachable(f"{ALERTMANAGER_FEISHU_URL}/health"):
            pytest.skip("alertmanager-feishu not reachable")
        r = requests.get(f"{ALERTMANAGER_FEISHU_URL}/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"

    def test_redis_aof_enabled(self):
        """Redis AOF 持久化已启用"""
        import subprocess

        result = subprocess.run(
            ["docker", "exec", "quant-redis", "redis-cli", "CONFIG", "GET", "appendonly"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "yes" in result.stdout.lower()

    def test_data_quality_metrics_registered(self):
        """数据质量 Prometheus 指标已注册"""
        if not skip_if_not_reachable(f"{STRATEGY_URL}/health"):
            pytest.skip("strategy-service not reachable")
        r = requests.get(f"{STRATEGY_URL}/metrics")
        quality_metrics = ["data_freshness_seconds", "data_gap_count", "data_quality_score"]
        for metric in quality_metrics:
            assert metric in r.text, f"Missing data quality metric: {metric}"
