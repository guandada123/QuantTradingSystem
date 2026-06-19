"""
性能测试 conftest — 检查 strategy-service 是否在线，否则跳过所有测试。
"""

import urllib.error
import urllib.request

import pytest

STRATEGY_URL = "http://localhost:8000"


def pytest_configure(config):
    """注册自定义标记"""
    config.addinivalue_line(
        "markers", "performance: 策略服务性能回归门禁，需要 strategy-service 运行"
    )


def pytest_collection_modifyitems(config, items):
    """收集阶段检查服务器可用性，若不在线则跳转所有测试"""
    try:
        urllib.request.urlopen(f"{STRATEGY_URL}/health", timeout=3)
    except (urllib.error.URLError, ConnectionError, OSError):
        for item in items:
            item.add_marker(pytest.mark.skip(reason="strategy-service 未运行，跳过性能测试"))
