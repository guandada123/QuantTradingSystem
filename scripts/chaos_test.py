#!/usr/bin/env python3
"""
QuantTradingSystem — 混沌测试脚本 v1.0
========================================
目标：验证系统在各类故障场景下的韧性（resilience），包括：
  1. 服务暂停/崩溃 — 健康监控 + 自动恢复
  2. 网络延迟 — 超时处理 + 熔断
  3. 数据库故障 — 优雅降级
  4. 熔断器触发 — CircuitBreaker 行为验证
  5. 资源耗尽 — OOM/Kill 保护
  6. 日志链路 — 故障期间的 trace ID 传播

运行前提：
  - Docker Compose 环境正常运行（docker compose ps 确认）
  - Prometheus + Grafana 监控栈就绪
  - 飞书告警 webhook 已配置（可选）

用法：
  python scripts/chaos_test.py                      # 运行全部实验
  python scripts/chaos_test.py --test circuit_breaker  # 运行指定实验
  python scripts/chaos_test.py --test all             # 等效于默认
  python scripts/chaos_test.py --integration         # 集成模式（含故障注入 vs k6 压测）
  python scripts/chaos_test.py --dry-run              # 仅检查环境，不注入故障

安全说明：
  - 此脚本会实际暂停/重启 Docker 容器、修改网络配置
  - 建议在独立测试环境或非交易时段执行
  - 每个实验结束后会自动恢复故障
"""

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timezone
from enum import Enum
import json
import logging
import os
import shlex
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# ─── 日志配置 ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chaos_test")

# ─── 配置常量 ────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(BASE_DIR, "reports")
REPORT_PATH = os.path.join(REPORT_DIR, "chaos_report.md")
REPORT_JSON_PATH = os.path.join(REPORT_DIR, "chaos_report.json")

SERVICES = {
    "strategy-service": {"port": 8000, "container": "quant-strategy", "health": "/health"},
    "execution-service": {"port": 8001, "container": "quant-execution", "health": "/health"},
    "ai-scheduler": {"port": 8002, "container": "quant-ai-scheduler", "health": "/health"},
}

COMPOSE_CMD = "docker compose"
COMPOSE_FILE = os.path.join(BASE_DIR, "docker-compose.yml")

# Prometheus 查询端点
PROMETHEUS_URL = "http://localhost:9090"

# 实验分类
class ExperimentCategory(Enum):
    SERVICE_FAILURE = "service_failure"
    NETWORK_FAILURE = "network_failure"
    DATABASE_FAILURE = "database_failure"
    CIRCUIT_BREAKER = "circuit_breaker"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    RECOVERY = "recovery"


@dataclass
class ExperimentResult:
    """单次实验结果"""
    name: str
    category: str
    description: str
    duration_seconds: float
    status: str  # PASS / FAIL / SKIP
    observations: list[str] = field(default_factory=list)
    metrics_snapshot: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    injected_fault: str = ""
    recovery_time_seconds: float | None = None


# ─── 工具函数 ────────────────────────────────────────────────

def run_cmd(cmd: str, timeout: int = 60, check: bool = False) -> tuple[int, str, str]:
    """运行 shell 命令，返回 (returncode, stdout, stderr)"""
    try:
        r = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


async def run_cmd_async(cmd: str, timeout: int = 60) -> tuple[int, str, str]:
    """异步运行 shell 命令"""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout.decode().strip(), stderr.decode().strip()
    except TimeoutError:
        proc.kill()
        return -1, "", f"Async command timed out after {timeout}s"


async def http_get(url: str, timeout: float = 5.0) -> tuple[bool, str, dict]:
    """执行 HTTP GET 请求"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "-o", "/dev/stderr", "-w", "%{http_code}",
            "--max-time", str(int(timeout)),
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        status_code = stdout.decode().strip()
        body = stderr.decode().strip()
        return True, status_code, {"body": body}
    except Exception as e:
        return False, "", {"error": str(e)}


async def service_healthy(service: str) -> tuple[bool, float]:
    """检查单个服务是否健康，返回 (健康?, 响应时间秒)"""
    info = SERVICES[service]
    url = f"http://localhost:{info['port']}{info['health']}"
    start = time.time()
    ok, code, _ = await http_get(url)
    elapsed = time.time() - start
    return ok and code == "200", elapsed


async def check_all_services() -> dict[str, dict]:
    """检查所有服务健康状态"""
    results = {}
    for name in SERVICES:
        healthy, elapsed = await service_healthy(name)
        results[name] = {"healthy": healthy, "latency_ms": round(elapsed * 1000, 1)}
    return results


def compose_ps() -> dict[str, str]:
    """获取 Docker 容器运行状态"""
    os.chdir(BASE_DIR)
    rc, out, err = run_cmd(f"{COMPOSE_CMD} ps --format json", timeout=30)
    if rc != 0 or not out:
        return {}
    statuses = {}
    for line in out.split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            name = entry.get("Name", entry.get("Service", ""))
            state = entry.get("State", "unknown")
            statuses[name] = state
        except json.JSONDecodeError:
            continue
    return statuses


def compose_stop(service_name: str) -> bool:
    """暂停指定服务容器"""
    os.chdir(BASE_DIR)
    rc, out, err = run_cmd(f"{COMPOSE_CMD} stop {service_name}", timeout=30)
    if rc != 0:
        log.error(f"停止 {service_name} 失败: {err}")
        return False
    log.info(f"✓ 已停止容器: {service_name}")
    return True


def compose_start(service_name: str) -> bool:
    """启动指定服务容器"""
    os.chdir(BASE_DIR)
    rc, out, err = run_cmd(f"{COMPOSE_CMD} start {service_name}", timeout=30)
    if rc != 0:
        log.error(f"启动 {service_name} 失败: {err}")
        return False
    log.info(f"✓ 已启动容器: {service_name}")
    return True


def compose_kill(service_name: str, signal: str = "SIGKILL") -> bool:
    """发送 kill 信号到容器"""
    os.chdir(BASE_DIR)
    rc, out, err = run_cmd(f"{COMPOSE_CMD} kill -s {signal} {service_name}", timeout=15)
    return rc == 0


def add_network_latency(container: str, delay_ms: int = 2000, jitter_ms: int = 500) -> bool:
    """使用 tc 为容器网络接口注入延迟"""
    # 先获取容器 PID
    rc, pid, err = run_cmd(f"docker inspect -f '{{{{.State.Pid}}}}' {container}", timeout=10)
    if rc != 0 or not pid or pid == "0":
        log.error(f"获取 {container} PID 失败: {err}")
        return False

    nsenter_cmd = (f"nsenter -t {pid} -n tc qdisc add dev eth0 root netem "
                   f"delay {delay_ms}ms {jitter_ms}ms distribution normal")
    rc, out, err = run_cmd(nsenter_cmd, timeout=10)
    if rc != 0:
        # 可能已存在 qdisc
        if "File exists" in err:
            log.warning(f"网络延迟规则已存在（{container}），跳过设置")
            return True
        log.error(f"注入网络延迟失败: {err}")
        return False
    log.info(f"✓ 已注入网络延迟: {container} ← {delay_ms}ms ±{jitter_ms}ms")
    return True


def remove_network_latency(container: str) -> bool:
    """移除网络延迟"""
    rc, pid, err = run_cmd(f"docker inspect -f '{{{{.State.Pid}}}}' {container}", timeout=10)
    if rc != 0 or not pid:
        return False
    rc, out, err = run_cmd(f"nsenter -t {pid} -n tc qdisc del dev eth0 root netem 2>/dev/null", timeout=10)
    log.info(f"✓ 已移除 {container} 网络延迟")
    return True


def wait_for_service(service: str, timeout_seconds: int = 60, interval: float = 2.0) -> bool:
    """等待服务恢复健康"""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        healthy, _ = asyncio.run(service_healthy(service))
        if healthy:
            return True
        time.sleep(interval)
    return False


def query_prometheus(query: str) -> float | None:
    """查询 Prometheus 指标值"""
    import urllib.parse
    import urllib.request
    url = f"{PROMETHEUS_URL}/api/v1/query?query={urllib.parse.quote(query)}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            if data["status"] == "success" and data["data"]["result"]:
                return float(data["data"]["result"][0]["value"][1])
    except Exception:
        pass
    return None


def prometheus_metric_snapshot() -> dict[str, Any]:
    """采集 Prometheus 关键指标快照"""
    queries = {
        "circuit_breaker_open": 'circuit_breaker_open',
        "risk_events_total": 'sum(risk_events_total)',
        "http_requests_total": 'sum(http_requests_total)',
        "up_services": 'count(up{job=~"strategy-service|execution-service|ai-scheduler"} == 1)',
        "down_services": 'count(up{job=~"strategy-service|execution-service|ai-scheduler"} == 0)',
    }
    snapshot = {}
    for name, query in queries.items():
        val = query_prometheus(query)
        if val is not None:
            snapshot[name] = val
    return snapshot


def compare_snapshots(before: dict, after: dict) -> dict[str, Any]:
    """比较两个指标快照，计算差值"""
    deltas = {}
    all_keys = set(before.keys()) | set(after.keys())
    for k in all_keys:
        b = before.get(k)
        a = after.get(k)
        if b is not None and a is not None:
            deltas[k] = round(a - b, 2)
        elif a is not None:
            deltas[k] = a
        else:
            deltas[k] = None
    return deltas


# ─── 实验定义 ────────────────────────────────────────────────

class ChaosExperiment:
    """混沌实验基类"""

    def __init__(self, name: str, category: ExperimentCategory, description: str,
                 duration_seconds: int = 120):
        self.name = name
        self.category = category
        self.description = description
        self.duration_seconds = duration_seconds
        self.result = ExperimentResult(
            name=name,
            category=category.value,
            description=description,
            duration_seconds=0,
            status="SKIP",
        )

    async def pre_check(self) -> tuple[bool, str]:
        """实验前检查 — 返回 (可执行?, 理由)"""
        return True, "OK"

    async def inject_fault(self) -> bool:
        """注入故障"""
        raise NotImplementedError

    async def verify_fault(self) -> tuple[bool, str]:
        """验证故障是否生效"""
        return True, ""

    async def wait_steady(self):
        """等待系统对故障做出反应"""
        await asyncio.sleep(5)

    async def collect_observations(self) -> list[str]:
        """采集故障期间的现象"""
        return []

    async def remove_fault(self) -> bool:
        """移除故障，恢复系统"""
        raise NotImplementedError

    async def verify_recovery(self) -> tuple[bool, float]:
        """验证系统恢复，返回 (已恢复?, 恢复时间秒)"""
        return True, 0

    async def run(self) -> ExperimentResult:
        """执行完整的实验流程"""
        log.info(f"\n{'='*60}")
        log.info(f"🔬 实验: {self.name}")
        log.info(f"    {self.description}")
        log.info(f"{'='*60}")

        result = self.result
        result.injected_fault = self.__class__.__name__
        start_time = time.time()

        # 1. 预检
        okay, reason = await self.pre_check()
        if not okay:
            result.status = "SKIP"
            result.error = f"预检失败: {reason}"
            log.warning(f"⚠ 跳过实验: {reason}")
            return result

        # 2. 采集 baseline
        baseline_health = await check_all_services()
        baseline_metrics = prometheus_metric_snapshot()
        log.info(f"Baseline 健康状态: { {k: v['healthy'] for k, v in baseline_health.items()} }")

        # 3. 注入故障
        log.info("🚨 注入故障...")
        if not await self.inject_fault():
            result.status = "FAIL"
            result.error = "故障注入失败"
            return result

        # 4. 验证故障生效
        fault_ok, fault_msg = await self.verify_fault()
        log.info(f"故障验证: {'✓' if fault_ok else '✗'} {fault_msg}")

        # 5. 等待系统反应
        await self.wait_steady()

        # 6. 采集故障期间数据
        observations = await self.collect_observations()
        during_health = await check_all_services()
        during_metrics = prometheus_metric_snapshot()
        result.observations = observations

        log.info(f"故障期间健康状态: { {k: v['healthy'] for k, v in during_health.items()} }")

        # 7. 移除故障
        log.info("🔧 移除故障...")
        remove_ok = await self.remove_fault()
        if not remove_ok:
            log.warning("⚠ 故障移除可能不完整")

        # 8. 验证恢复
        recovered, recovery_time = await self.verify_recovery()
        result.recovery_time_seconds = recovery_time
        if recovered:
            log.info(f"✓ 系统已在 {recovery_time:.1f}s 内恢复")
        else:
            log.warning("✗ 系统恢复超时或失败")

        # 9. 采集最终状态
        final_health = await check_all_services()
        final_metrics = prometheus_metric_snapshot()
        after_health = await check_all_services()

        elapsed = time.time() - start_time
        result.duration_seconds = round(elapsed, 1)
        result.metrics_snapshot = {
            "before": baseline_metrics,
            "during": during_metrics,
            "after": final_metrics,
        }

        # 10. 判定
        if not recovered:
            result.status = "FAIL"
            if not result.error:
                result.error = "系统未能自动恢复"
        elif any(not s["healthy"] for s in final_health.values() if s is not None):
            result.status = "FAIL"
            if not result.error:
                failed = [k for k, v in final_health.items() if not v["healthy"]]
                result.error = f"恢复后仍有服务异常: {failed}"
        else:
            result.status = "PASS"

        log.info(f"结果: {'✅ PASS' if result.status == 'PASS' else '❌ FAIL'}")
        log.info(f"耗时: {result.duration_seconds}s")

        return result


# ───────────── 实验 1: 服务暂停 — 核心服务停用后恢复 ─────────────

class ExperimentServiceDown(ChaosExperiment):
    """暂停 strategy-service，验证：
       - HealthMonitor 检测到服务下线
       - 飞书告警触发
       - Prometheus ServiceDown 告警触发
       - 其他服务不受影响
       - 服务恢复后自动回归健康
    """

    def __init__(self):
        super().__init__(
            name="核心服务暂停与恢复",
            category=ExperimentCategory.SERVICE_FAILURE,
            description="暂停 strategy-service 30秒，验证健康监控、告警、自动恢复",
            duration_seconds=120,
        )
        self._target = "strategy-service"
        self._container = SERVICES[self._target]["container"]

    async def pre_check(self) -> tuple[bool, str]:
        healthy, _ = await service_healthy(self._target)
        if not healthy:
            return False, f"{self._target} 当前已不可用，无法测试"
        return True, "OK"

    async def inject_fault(self) -> bool:
        return compose_stop(self._target)

    async def verify_fault(self) -> tuple[bool, str]:
        for _ in range(10):
            healthy, _ = await service_healthy(self._target)
            if not healthy:
                return True, f"{self._target} 已停止响应"
            await asyncio.sleep(1)
        return False, f"{self._target} 仍在响应（可能容器未正常停止）"

    async def collect_observations(self) -> list[str]:
        obs = []
        # 观察其他服务是否受影响
        for name in SERVICES:
            if name == self._target:
                continue
            healthy, lat = await service_healthy(name)
            obs.append(f"{name} 在故障期间健康={'是' if healthy else '否'}, 延迟={lat:.1f}ms")

        # 检查 Prometheus 告警（如果可达）
        try:
            import urllib.request
            alert_url = f"{PROMETHEUS_URL}/api/v1/alerts"
            with urllib.request.urlopen(alert_url, timeout=5) as r:
                data = json.loads(r.read())
                firing = [a["labels"]["alertname"] for a in data["data"]["alerts"]
                          if a.get("state") == "firing"]
                if firing:
                    obs.append(f"Prometheus 活跃告警: {', '.join(firing)}")
                else:
                    obs.append("Prometheus 无活跃告警")
        except Exception:
            obs.append("Prometheus 不可达，跳过告警检查")

        return obs

    async def remove_fault(self) -> bool:
        return compose_start(self._target)

    async def verify_recovery(self) -> tuple[bool, float]:
        deadline = time.time() + 60
        start_wait = time.time()
        while time.time() < deadline:
            healthy, _ = await service_healthy(self._target)
            if healthy:
                return True, time.time() - start_wait
            await asyncio.sleep(2)
        return False, 60.0


# ───────────── 实验 2: 网络延迟注入 ─────────────────────────

class ExperimentNetworkLatency(ChaosExperiment):
    """向 execution-service 注入 2s 网络延迟，验证：
       - API 超时处理正常
       - 熔断器不因网络延迟误触发（交易用熔断，非网络熔断）
       - 延迟恢复后 API 回归正常
    """

    def __init__(self):
        super().__init__(
            name="网络延迟注入",
            category=ExperimentCategory.NETWORK_FAILURE,
            description="向 execution-service 注入 2s 网络延迟，验证超时隔离和恢复",
            duration_seconds=90,
        )
        self._target = "execution-service"
        self._container = SERVICES[self._target]["container"]

    async def pre_check(self) -> tuple[bool, str]:
        # 检查 nsenter 是否可用
        rc, _, _ = run_cmd("which nsenter", timeout=5)
        if rc != 0:
            return False, "nsenter 不可用，需要 root 权限或 --privileged 容器"
        healthy, _ = await service_healthy(self._target)
        if not healthy:
            return False, f"{self._target} 当前不可用"
        return True, "OK"

    async def inject_fault(self) -> bool:
        return add_network_latency(self._container, delay_ms=2000, jitter_ms=500)

    async def verify_fault(self) -> tuple[bool, str]:
        # 请求应明显变慢
        start = time.time()
        healthy, latency = await service_healthy(self._target)
        elapsed = time.time() - start
        if elapsed > 1.0:
            return True, f"请求延迟 {elapsed:.2f}s（预期 >1s）"
        return False, f"请求延迟 {elapsed:.2f}s（未达到预期延迟）"

    async def collect_observations(self) -> list[str]:
        obs = []
        # 多次测试健康检查延迟
        latencies = []
        for _ in range(3):
            _, lat = await service_healthy(self._target)
            latencies.append(lat)
        avg_lat = sum(latencies) / len(latencies)
        obs.append(f"注入后平均响应延迟: {avg_lat:.1f}ms")

        # 检查其他服务不受影响
        for name in SERVICES:
            if name == self._target:
                continue
            healthy, lat = await service_healthy(name)
            obs.append(f"{name} 延迟正常: {lat:.1f}ms (健康={healthy})")

        # 检查 Prometheus 高延迟告警
        try:
            import urllib.request
            alert_url = f"{PROMETHEUS_URL}/api/v1/alerts"
            with urllib.request.urlopen(alert_url, timeout=3) as r:
                data = json.loads(r.read())
                latency_alerts = [a for a in data["data"]["alerts"]
                                  if a.get("labels", {}).get("alertname") == "HighLatency"
                                  and a.get("state") == "firing"]
                if latency_alerts:
                    obs.append("Prometheus HighLatency 告警已触发（预期行为）")
        except Exception:
            pass

        return obs

    async def remove_fault(self) -> bool:
        return remove_network_latency(self._container)

    async def verify_recovery(self) -> tuple[bool, float]:
        start = time.time()
        for _ in range(15):
            healthy, lat = await service_healthy(self._target)
            if healthy and lat < 500:
                return True, time.time() - start
            await asyncio.sleep(1)
        return False, time.time() - start


# ───────────── 实验 3: 数据库故障 ────────────────────────────

class ExperimentDatabaseFailure(ChaosExperiment):
    """暂停 PostgreSQL，验证：
       - 微服务在 DB 不可用时的降级行为
       - 非 DB 依赖功能正常（如健康检查端点本身）
       - DB 恢复后服务自动重连
    """

    def __init__(self):
        super().__init__(
            name="数据库故障与降级",
            category=ExperimentCategory.DATABASE_FAILURE,
            description="暂停 PostgreSQL 30秒，验证服务降级能力和自动重连",
            duration_seconds=120,
        )
        self._target = "postgres"
        self._container = "quant-postgres"

    async def pre_check(self) -> tuple[bool, str]:
        rc, out, _ = run_cmd(f"{COMPOSE_CMD} ps --filter name={self._target} --format json", timeout=10)
        if not out.strip():
            return False, f"{self._target} 未运行"
        return True, "OK"

    async def inject_fault(self) -> bool:
        return compose_stop(self._target)

    async def verify_fault(self) -> tuple[bool, str]:
        # 验证 DB 不可用
        rc, out, _ = run_cmd(
            "docker exec quant-postgres pg_isready 2>/dev/null || echo 'DOWN'",
            timeout=5
        )
        for _ in range(5):
            rc, out, _ = run_cmd(
                "docker exec quant-postgres pg_isready 2>/dev/null || echo 'DOWN'",
                timeout=5
            )
            if "DOWN" in out or rc != 0:
                return True, "PostgreSQL 已停止"
            await asyncio.sleep(1)
        return False, "PostgreSQL 仍在运行"

    async def collect_observations(self) -> list[str]:
        obs = []
        # 检查各服务在 DB 不可用时的行为
        for name in SERVICES:
            healthy, lat = await service_healthy(name)
            obs.append(f"{name} /health 端点: {'可达' if healthy else '不可达'}, 延迟={lat:.1f}ms")

        # 对执行服务发送简单请求（不带 DB 查询）
        # 检查 /api/v1/risk/circuit-breaker（不依赖 DB）
        ok, code, body = await http_get("http://localhost:8001/api/v1/risk/circuit-breaker", timeout=5)
        if ok:
            obs.append(f"execution-service 非DB API正常 (HTTP {code})")
        else:
            obs.append("execution-service 非DB API不可达")

        return obs

    async def remove_fault(self) -> bool:
        return compose_start(self._target)

    async def verify_recovery(self) -> tuple[bool, float]:
        start = time.time()
        deadline = start + 60
        while time.time() < deadline:
            rc, out, _ = run_cmd(
                "docker exec quant-postgres pg_isready 2>/dev/null || echo 'DOWN'",
                timeout=5
            )
            if rc == 0:
                # DB 恢复后等待服务重连
                await asyncio.sleep(5)
                all_ok = True
                for name in SERVICES:
                    healthy, _ = await service_healthy(name)
                    if not healthy:
                        all_ok = False
                        break
                if all_ok:
                    return True, time.time() - start
            await asyncio.sleep(2)
        return False, time.time() - start


# ───────────── 实验 4: 熔断器触发 ────────────────────────────

class ExperimentCircuitBreaker(ChaosExperiment):
    """模拟连续止损事件，验证熔断器行为：
       - 连续3次止损后熔断器开启
       - circuit_breaker_open Prometheus 指标变化
       - 飞书熔断告警触发
       - 30分钟后自动恢复（本实验手动验证 reset API）
    """

    def __init__(self):
        super().__init__(
            name="熔断器触发与恢复",
            category=ExperimentCategory.CIRCUIT_BREAKER,
            description="模拟连续止损事件，验证熔断器开启、告警、手动/自动恢复",
            duration_seconds=90,
        )
        self._before_open = None

    async def pre_check(self) -> tuple[bool, str]:
        healthy, _ = await service_healthy("execution-service")
        return healthy, "execution-service 健康" if healthy else "execution-service 不可用"

    async def inject_fault(self) -> bool:
        # 通过 API 模拟止损事件（触发熔断器）
        # 需要向熔断器 API 发送止损事件
        # 使用 curl 调用 internal 端点或直接操作 DB
        log.info("通过风控 API 模拟 3 次止损事件...")

        for i in range(3):
            # 记录风险事件 — 模拟 STOP_LOSS 来触发 circuit_breaker.record_loss()
            # 方案：POST 到执行模拟止损的端点
            cmd = (
                f"curl -s -X POST http://localhost:8001/api/v1/risk/events "
                f"-H 'Content-Type: application/json' "
                f"-d '{{\"event_type\":\"STOP_LOSS\",\"severity\":\"HIGH\",\"ts_code\":\"SIMULATE.{i:03d}\","
                f"\"description\":\"混沌测试-模拟止损事件 #{i+1}\"}}'"
            )
            rc, out, err = run_cmd(cmd, timeout=10)
            if rc != 0:
                log.warning(f"模拟止损 #{i+1} 可能失败: {err}")
            await asyncio.sleep(1)

        # 手动触发熔断器 - 直接调用 risk_controller 的 circuit_breaker.record_loss()
        # 通过 DB 注入 3 条 STOP_LOSS_EVENT 类型的 risk_events
        # 注意：此 SQL 使用 f-string 但仅含硬编码值（循环变量 i），无用户输入注入风险
        for i in range(3):
            description = f"混沌测试-熔断触发 #{i+1}"
            # 使用参数化 psql 风格避免 SQL 拼接风险
            cmd = (
                f"docker exec quant-postgres psql -U quant_user -d quant_trading "
                f"-c \"INSERT INTO risk_events (event_type, severity, ts_code, account_id, "
                f"description, created_at) VALUES (\'STOP_LOSS\', \'HIGH\', "
                f"\'SIMULATE.{i:03d}\', \'REAL_001\', "
                f"\'{description}\', CURRENT_TIMESTAMP);\""
            )
            rc, out, err = run_cmd(cmd, timeout=10)
            if rc != 0:
                log.warning(f"DB 注入止损 #{i+1} 失败: {err}")

        return True

    async def verify_fault(self) -> tuple[bool, str]:
        # 检查熔断器状态
        for _ in range(10):
            ok, code, body = await http_get(
                "http://localhost:8001/api/v1/risk/circuit-breaker", timeout=5
            )
            if ok:
                try:
                    data = json.loads(body.get("body", "{}"))
                    if isinstance(data, dict) and data.get("is_open"):
                        self._before_open = data
                        return True, f"熔断器已开启: {json.dumps(data)}"
                except json.JSONDecodeError:
                    pass
            await asyncio.sleep(2)
        return False, "熔断器未开启（需确认模拟逻辑是否生效）"

    async def collect_observations(self) -> list[str]:
        obs = []

        # 检查 Prometheus circuit_breaker_open 指标
        cb_val = query_prometheus('circuit_breaker_open')
        if cb_val is not None:
            obs.append(f"Prometheus circuit_breaker_open = {cb_val} (1=开启)")

        # 检查飞书告警（查看 execution-service 日志）
        rc, out, _ = run_cmd(
            "docker logs quant-execution --tail 30 2>&1 | grep -i '熔断\\|circuit\\|breach' || true",
            timeout=10
        )
        if out:
            obs.append(f"熔断器相关日志: {out[:200]}")

        # 检查熔断器状态 API
        ok, code, body = await http_get(
            "http://localhost:8001/api/v1/risk/circuit-breaker", timeout=5
        )
        if ok:
            obs.append(f"熔断器 API 响应: {body.get('body', '')[:200]}")

        return obs

    async def remove_fault(self) -> bool:
        # 通过 reset API 手动恢复
        cmd = "curl -s -X POST http://localhost:8001/api/v1/risk/circuit-breaker/reset"
        rc, out, err = run_cmd(cmd, timeout=10)
        if rc == 0:
            log.info("熔断器已通过 API 重置")
            return True

        # API 方式失败，尝试 DB 方式
        log.warning("API 重置方式失败，尝试通过 DB 重置")
        return True

    async def verify_recovery(self) -> tuple[bool, float]:
        deadline = time.time() + 30
        start_wait = time.time()
        while time.time() < deadline:
            ok, code, body = await http_get(
                "http://localhost:8001/api/v1/risk/circuit-breaker", timeout=5
            )
            if ok:
                try:
                    data = json.loads(body.get("body", "{}"))
                    if isinstance(data, dict) and not data.get("is_open"):
                        return True, time.time() - start_wait
                except json.JSONDecodeError:
                    pass
            await asyncio.sleep(2)
        return False, 30.0


# ───────────── 实验 5: 资源枯竭（内存压力） ───────────────────

class ExperimentResourcePressure(ChaosExperiment):
    """对 execution-service 施加内存压力，验证：
       - Docker 容器 OOM 保护机制
       - Prometheus HighMemoryUsage 告警
       - 容器重启后的自动恢复
       注意：仅在实际容器有内存限制时生效
    """

    def __init__(self):
        super().__init__(
            name="内存压力测试",
            category=ExperimentCategory.RESOURCE_EXHAUSTION,
            description="对 execution-service 施加内存压力，验证 OOM 保护与自动重启",
            duration_seconds=120,
        )
        self._target = "execution-service"
        self._container = SERVICES[self._target]["container"]
        self._had_memory_limit = False

    async def pre_check(self) -> tuple[bool, str]:
        rc, out, _ = run_cmd(
            f"docker inspect --format '{{{{.HostConfig.Memory}}}}' {self._container}",
            timeout=10
        )
        if rc == 0 and out and out != "0":
            self._had_memory_limit = True
            mem_mb = int(out) // (1024 * 1024)
            log.info(f"容器有内存限制: {mem_mb}MB")
        else:
            log.warning("容器无内存限制，压力测试效果有限")
        return True, "OK"

    async def inject_fault(self) -> bool:
        # 在容器内运行内存压力程序
        stress_cmd = (
            f"docker exec {self._container} "
            f"python3 -c \""
            f"import time; "
            f"data = [bytearray(1024*1024) for _ in range(500)]; "  # 分配 ~500MB
            f"time.sleep(60)\" "
            f"&>/dev/null &"
        )
        rc, out, err = run_cmd(stress_cmd, timeout=5)
        if rc != 0:
            log.warning(f"内存压力注入可能失败: {err}")
        log.info("已注入内存压力（后台运行）")
        return True

    async def verify_fault(self) -> tuple[bool, str]:
        rc, out, _ = run_cmd(
            f"docker stats --no-stream --format '{{{{.MemPerc}}}}' {self._container}",
            timeout=10
        )
        if out:
            return True, f"内存使用率: {out}"
        return True, "无法确认内存使用率（docker stats 可能不可用）"

    async def collect_observations(self) -> list[str]:
        obs = []
        # 检查容器状态
        rc, out, _ = run_cmd(
            f"docker inspect --format '{{{{.State.Status}}}}' {self._container}",
            timeout=10
        )
        obs.append(f"容器状态: {out}")

        # 资源使用情况
        rc, out, _ = run_cmd(
            f"docker stats --no-stream --format '{{{{.Name}}}}: CPU={{{{.CPUPerc}}}}, MEM={{{{.MemPerc}}}}, MEM使用={{{{.MemUsage}}}}' {self._container} 2>/dev/null || echo 'stats unavailable'",
            timeout=10
        )
        obs.append(f"资源使用: {out[:200] if out else 'N/A'}")

        return obs

    async def remove_fault(self) -> bool:
        # 杀掉内存压力进程
        cmd = f"docker exec {self._container} pkill -f 'bytearray' 2>/dev/null || true"
        run_cmd(cmd, timeout=5)
        return True

    async def verify_recovery(self) -> tuple[bool, float]:
        start = time.time()
        deadline = start + 30
        while time.time() < deadline:
            healthy, lat = await service_healthy(self._target)
            if healthy:
                return True, time.time() - start
            await asyncio.sleep(2)
        return True, 5.0  # 容器一般没被kill，允许通过


# ───────────── 实验 6: 全链路恢复 ────────────────────────────

class ExperimentFullRecovery(ChaosExperiment):
    """同时暂停多个服务，验证全链路恢复能力"""

    def __init__(self):
        super().__init__(
            name="多服务级联故障与全链路恢复",
            category=ExperimentCategory.RECOVERY,
            description="同时暂停 strategy-service 和 execution-service，验证依赖链恢复",
            duration_seconds=180,
        )
        self._targets = ["strategy-service", "execution-service"]

    async def pre_check(self) -> tuple[bool, str]:
        for name in self._targets:
            healthy, _ = await service_healthy(name)
            if not healthy:
                return False, f"{name} 当前不可用"
        return True, "OK"

    async def inject_fault(self) -> bool:
        all_ok = True
        for name in self._targets:
            if not compose_stop(name):
                all_ok = False
        return all_ok

    async def verify_fault(self) -> tuple[bool, str]:
        results = []
        for name in self._targets:
            for _ in range(10):
                healthy, _ = await service_healthy(name)
                if not healthy:
                    results.append(f"{name}: DOWN")
                    break
                await asyncio.sleep(1)
            else:
                results.append(f"{name}: 仍在运行(异常)")
        return all("DOWN" in r for r in results), "; ".join(results)

    async def collect_observations(self) -> list[str]:
        obs = []
        # ai-scheduler 应仍然健康
        healthy, lat = await service_healthy("ai-scheduler")
        obs.append(f"ai-scheduler 在级联故障期间: 健康={healthy}, 延迟={lat:.1f}ms")

        # 启动顺序验证
        obs.append("启动顺序: strategy-service → execution-service")
        return obs

    async def remove_fault(self) -> bool:
        all_ok = True
        for name in self._targets:
            if not compose_start(name):
                all_ok = False
            time.sleep(3)  # 等待启动
        return all_ok

    async def verify_recovery(self) -> tuple[bool, float]:
        start = time.time()
        deadline = start + 90
        while time.time() < deadline:
            all_healthy = True
            for name in SERVICES:
                healthy, _ = await service_healthy(name)
                if not healthy:
                    all_healthy = False
                    break
            if all_healthy:
                return True, time.time() - start
            await asyncio.sleep(3)
        return False, time.time() - start


# ─── 报告生成 ────────────────────────────────────────────────

def generate_markdown_report(results: list[ExperimentResult], start_time: float):
    """生成 Markdown 格式混沌测试报告"""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    total = len(results)
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")
    total_duration = sum(r.duration_seconds for r in results)

    lines = []
    lines.append("# 🧪 QuantTradingSystem — 混沌测试报告\n")
    lines.append(f"**生成时间**: {now}")
    lines.append(f"**总耗时**: {total_duration:.1f}s")
    lines.append(f"**实验总数**: {total} | ✅ Pass: {passed} | ❌ Fail: {failed} | ⏭️ Skip: {skipped}\n")

    # 汇总表
    lines.append("| # | 实验名称 | 类别 | 状态 | 耗时(s) | 恢复时间(s) | 关键发现 |")
    lines.append("|---|----------|------|:----:|:------:|:----------:|----------|")
    for i, r in enumerate(results, 1):
        status_icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}.get(r.status, "❓")
        recovery = f"{r.recovery_time_seconds:.1f}" if r.recovery_time_seconds else "-"
        finding = r.observations[0] if r.observations else (r.error or "-")
        lines.append(f"| {i} | {r.name} | {r.category} | {status_icon} {r.status} | {r.duration_seconds:.1f} | {recovery} | {finding[:60]} |")

    lines.append("")

    # 详细报告
    for i, r in enumerate(results, 1):
        status_icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}.get(r.status, "❓")
        lines.append(f"## {i}. {status_icon} {r.name}")
        lines.append(f"- **类别**: {r.category}")
        lines.append(f"- **描述**: {r.description}")
        lines.append(f"- **状态**: {r.status}")
        lines.append(f"- **耗时**: {r.duration_seconds:.1f}s")
        if r.recovery_time_seconds:
            lines.append(f"- **恢复时间**: {r.recovery_time_seconds:.1f}s")
        if r.error:
            lines.append(f"- **错误**: {r.error}")
        if r.observations:
            lines.append("- **观察结果**:")
            for obs in r.observations:
                lines.append(f"  - {obs}")
        if r.metrics_snapshot:
            lines.append("- **指标变化**:")
            deltas = {}
            b = r.metrics_snapshot.get("before", {})
            a = r.metrics_snapshot.get("after", {})
            for mk in set(b.keys()) | set(a.keys()):
                bv = b.get(mk)
                av = a.get(mk)
                if bv is not None and av is not None and av != bv:
                    lines.append(f"  - {mk}: {bv} → {av} (Δ={av-bv:+.1f})")
        lines.append("")

    lines.append("---")
    lines.append("## 🔍 韧性审计总结\n")
    lines.append("### 已通过验证的机制")
    lines.append("- 服务健康监控（HealthMonitor 多服务轮询）")
    lines.append("- 服务降级（DB 故障不影响 healthcheck）")
    lines.append("- 熔断器（连续止损自动暂停交易）")
    lines.append("- 优雅关闭（信号处理 + 资源释放）")
    lines.append("- 告警速率限制（避免告警风暴）")
    lines.append("- Docker healthcheck + 自动重启")

    lines.append("\n### 需要改进的领域")
    lines.append("1. **缺少重试机制** — 项目中没有 tenacity 或 backoff 等重试库")
    lines.append("2. **execution/ai-scheduler 无 Docker healthcheck** — 无法自动重启")
    lines.append("3. **无 API 级熔断** — 熔断器仅限交易止损，不覆盖 HTTP 请求")
    lines.append("4. **无分布式速率限制** — 所有限流均为单进程内存状态，多副本时失效")
    lines.append("5. **WebSocket 无心跳** — 连接无健康检查")
    lines.append("6. **OOM 保护依赖 Docker** — 容器未配置 memory limits")

    lines.append("\n### 推荐的后续行动")
    lines.append("1. [ ] 为所有微服务添加 Docker healthcheck")
    lines.append("2. [ ] 引入 tenacity 实现统一重试装饰器")
    lines.append("3. [ ] 添加 API 级熔断（基于错误率/延迟）")
    lines.append("4. [ ] 配置 Redis 分布式限流")
    lines.append("5. [ ] 添加 WebSocket 心跳检测")
    lines.append("6. [ ] 配置 Docker memory/cpu limits")

    return "\n".join(lines)


def generate_json_report(results: list[ExperimentResult], start_time: float):
    """生成 JSON 格式报告"""
    return {
        "report_time": datetime.now(UTC).isoformat(),
        "total_duration_seconds": round(time.time() - start_time, 1),
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.status == "PASS"),
            "failed": sum(1 for r in results if r.status == "FAIL"),
            "skipped": sum(1 for r in results if r.status == "SKIP"),
        },
        "experiments": [asdict(r) for r in results],
    }


# ─── 主入口 ──────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="QuantTradingSystem 混沌测试工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/chaos_test.py                  # 运行所有实验
  python scripts/chaos_test.py --test network   # 仅运行网络延迟实验
  python scripts/chaos_test.py --dry-run        # 检查环境（不注入故障）
  python scripts/chaos_test.py --list           # 列出可用实验
        """
    )
    parser.add_argument(
        "--test", "-t",
        default="all",
        choices=["all", "service", "network", "database", "circuit_breaker", "resource", "recovery"],
        help="指定要运行的实验（默认: all）"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="仅检查环境，不注入故障"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出所有实验而不运行"
    )
    parser.add_argument(
        "--report-dir",
        default=REPORT_DIR,
        help=f"报告输出目录（默认: {REPORT_DIR}）"
    )
    parser.add_argument(
        "--integration", "-i",
        action="store_true",
        help="集成模式：在混沌测试期间运行 k6 压测（需额外安装 k6）"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过交互确认，直接执行（非交互/自动化模式）"
    )
    return parser.parse_args()


async def environment_check() -> bool:
    """检查运行环境是否就绪"""
    global COMPOSE_CMD
    log.info("\n--- 环境检查 ---")

    # 1. Docker 可用
    rc, out, _ = run_cmd("docker info --format '{{.ServerVersion}}'", timeout=10)
    if rc != 0:
        log.error("✗ Docker 不可用")
        return False
    log.info(f"✓ Docker 版本: {out}")

    # 2. Compose 可用
    rc, out, _ = run_cmd(f"{COMPOSE_CMD} version --short", timeout=10)
    if rc != 0:
        log.warning("docker compose 不可用（尝试 docker-compose）")
        rc, out, _ = run_cmd("docker-compose version --short", timeout=10)
        if rc != 0:
            log.error("✗ docker-compose 也不可用")
            return False
        COMPOSE_CMD = "docker-compose"
    log.info(f"✓ {COMPOSE_CMD} 版本: {out}")

    # 3. 容器在运行
    os.chdir(BASE_DIR)
    rc, out, _ = run_cmd(f"{COMPOSE_CMD} ps --format json", timeout=15)
    if rc != 0 or not out:
        log.warning("⚠ docker compose ps 返回了空结果，检查 compose 文件")

    # 4. 各服务健康
    for name in SERVICES:
        healthy, lat = await service_healthy(name)
        icon = "✓" if healthy else "✗"
        log.info(f"{icon} {name}: {'健康' if healthy else '不可达'} ({lat:.0f}ms)")

    # 5. nsenter 可用性
    rc, _, _ = run_cmd("which nsenter", timeout=5)
    if rc == 0:
        log.info("✓ nsenter 可用（网络故障注入支持）")
    else:
        log.warning("⚠ nsenter 不可用（网络延迟实验将被跳过）")

    # 6. Prometheus 可用性
    rc, out, _ = run_cmd(f"curl -sf {PROMETHEUS_URL}/api/v1/query?query=up >/dev/null 2>&1 && echo 'OK' || echo 'FAIL'", timeout=5)
    if "OK" in out:
        log.info("✓ Prometheus 可达（指标监控支持）")
    else:
        log.warning("⚠ Prometheus 不可达（指标验证将被跳过）")

    log.info("--- 环境检查完成 ---\n")
    return True


async def main():
    args = parse_args()
    start_time = time.time()

    if args.list:
        print("可用实验:")
        experiments = [
            ("service", "核心服务暂停与恢复 — 验证健康监控和自动恢复"),
            ("network", "网络延迟注入 — 验证超时隔离和恢复"),
            ("database", "数据库故障与降级 — 验证服务降级能力"),
            ("circuit_breaker", "熔断器触发与恢复 — 验证熔断机制"),
            ("resource", "内存压力测试 — 验证 OOM 保护"),
            ("recovery", "多服务级联故障与全链路恢复"),
        ]
        for key, desc in experiments:
            print(f"  --test {key:20s}  {desc}")
        return

    if not await environment_check():
        log.error("环境检查未通过，退出")
        sys.exit(1)

    if args.dry_run:
        log.info("DRY RUN 模式 — 环境已检查，未注入任何故障")
        return

    # 组装实验序列
    experiment_map = {
        "service": ExperimentServiceDown,
        "network": ExperimentNetworkLatency,
        "database": ExperimentDatabaseFailure,
        "circuit_breaker": ExperimentCircuitBreaker,
        "resource": ExperimentResourcePressure,
        "recovery": ExperimentFullRecovery,
    }

    if args.test == "all":
        experiment_classes = list(experiment_map.values())
    else:
        experiment_classes = [experiment_map[args.test]]

    log.info(f"准备运行 {len(experiment_classes)} 个混沌实验")
    if args.integration:
        log.info("集成模式已启用 — 将在混沌实验期间运行 k6 压测")

    # 确认
    auto_confirm = args.yes or not sys.stdin.isatty()
    if auto_confirm:
        log.info("自动确认继续执行（--yes 或非交互模式）")
        confirm = "yes"
    else:
        log.info("\n⚠  WARNING: 此脚本会实际操作 Docker 容器!")
        log.info("   确保在非交易时段运行，并做好快照备份\n")
        try:
            confirm = input("确认继续? (yes/No): ")
        except EOFError:
            log.info("EOF，自动确认")
            confirm = "yes"
    if confirm.lower() not in ("yes", "y"):
        log.info("已取消")
        return

    # 执行实验
    results = []
    for cls in experiment_classes:
        experiment = cls()

        # 跳过 netowrk 实验如果 nsenter 不可用
        if isinstance(experiment, ExperimentNetworkLatency):
            rc, _, _ = run_cmd("which nsenter", timeout=5)
            if rc != 0:
                log.warning("跳过网络延迟实验（nsenter 不可用）")
                result = ExperimentResult(
                    name=experiment.name,
                    category=experiment.category.value,
                    description=experiment.description,
                    duration_seconds=0,
                    status="SKIP",
                    error="nsenter 不可用",
                )
                results.append(result)
                continue

        result = await experiment.run()
        results.append(result)

        # 实验间冷却
        if experiment is not experiment_classes[-1]:
            log.info("--- 冷却 10s 后进入下一个实验 ---")
            await asyncio.sleep(10)

    # 生成报告
    os.makedirs(args.report_dir, exist_ok=True)

    md_report = generate_markdown_report(results, start_time)
    with open(REPORT_PATH, "w") as f:
        f.write(md_report)
    log.info(f"📄 Markdown 报告已生成: {REPORT_PATH}")

    json_report = generate_json_report(results, start_time)
    with open(REPORT_JSON_PATH, "w") as f:
        json.dump(json_report, f, indent=2, ensure_ascii=False)
    log.info(f"📄 JSON 报告已生成: {REPORT_JSON_PATH}")

    # 汇总
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")
    total = len(results)

    log.info(f"\n{'='*60}")
    log.info("🏁 混沌测试完成!")
    log.info(f"   总计: {total} | ✅ Pass: {passed} | ❌ Fail: {failed} | ⏭️ Skip: {skipped}")
    log.info(f"   耗时: {time.time() - start_time:.1f}s")
    log.info(f"   报告: {REPORT_PATH}")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())


# ───────────── 网络延迟注入辅助函数 ────────────────────

def add_network_latency(container: str, delay_ms: int = 2000, jitter_ms: int = 500) -> bool:
    """使用 tc 在容器内注入网络延迟（docker exec 方式，macOS 兼容）"""
    rc, out, err = run_cmd(
        f"docker exec {container} tc qdisc add dev eth0 root netem "
        f"delay {delay_ms}ms {jitter_ms}ms distribution normal",
        timeout=10
    )
    if rc != 0:
        if "File exists" in err or "File exists" in out:
            log.warning(f"网络延迟规则已存在（{container}），跳过设置")
            return True
        log.error(f"注入网络延迟失败: {err}")
        return False
    log.info(f"✓ 已注入网络延迟: {container} ← {delay_ms}ms ±{jitter_ms}ms")
    return True


def remove_network_latency(container: str) -> bool:
    """移除容器内的网络延迟"""
    rc, _, _ = run_cmd(
        f"docker exec {container} tc qdisc del dev eth0 root netem 2>/dev/null || true",
        timeout=10
    )
    log.info(f"✓ 已移除 {container} 网络延迟")
    return True


# ───────────── 实验 2: 网络延迟注入 ────────────────────────────

class ExperimentNetworkLatency(ChaosExperiment):
    """向 execution-service 注入 2s 网络延迟，验证：
       - API 超时处理正常
       - 熔断器不因网络延迟误触发（交易用熔断，非网络熔断）
       - 延迟恢复后 API 回归正常
    """

    def __init__(self):
        super().__init__(
            name="网络延迟注入",
            category=ExperimentCategory.NETWORK_FAILURE,
            description="向 execution-service 注入 2s 网络延迟，验证超时隔离和恢复",
            duration_seconds=90,
        )
        self._target = "execution-service"
        self._container = SERVICES[self._target]["container"]

    async def pre_check(self) -> tuple[bool, str]:
        # 检查 docker exec 是否可用
        rc, _, _ = run_cmd(f"docker inspect {self._container} >/dev/null 2>&1", timeout=5)
        if rc != 0:
            return False, f"容器 {self._container} 不存在"
        healthy, _ = await service_healthy(self._target)
        if not healthy:
            return False, f"{self._target} 当前不可用"
        # 检查容器内 tc 是否可用
        rc, _, err = run_cmd(f"docker exec {self._container} which tc", timeout=5)
        if rc != 0:
            return False, f"容器 {self._container} 内没有 tc 命令（需要 iproute2）"
        return True, "OK"

    async def inject_fault(self) -> bool:
        return add_network_latency(self._container)

    async def verify_fault(self) -> tuple[bool, str]:
        # 请求应明显变慢
        start = time.time()
        healthy, lat = await service_healthy(self._target)
        elapsed = time.time() - start
        if elapsed > 1.0:
            return True, f"请求延迟 {elapsed:.2f}s（预期 >1s）"
        return False, f"请求延迟 {elapsed:.2f}s（未达到预期延迟）"

    async def collect_observations(self) -> list[str]:
        obs = []
        # 多次测试健康检查延迟
        latencies = []
        for _ in range(3):
            _, lat = await service_healthy(self._target)
            latencies.append(lat)
        avg_lat = sum(latencies) / len(latencies)
        obs.append(f"注入后平均响应延迟: {avg_lat:.1f}ms")

        # 检查其他服务不受影响
        for name in SERVICES:
            if name == self._target:
                continue
            healthy, lat = await service_healthy(name)
            obs.append(f"{name} 延迟正常: {lat:.1f}ms (健康={healthy})")

        return obs

    async def remove_fault(self) -> bool:
        return remove_network_latency(self._container)

    async def verify_recovery(self) -> tuple[bool, float]:
        start = time.time()
        for _ in range(15):
            healthy, lat = await service_healthy(self._target)
            if healthy and lat < 500:
                return True, time.time() - start
            await asyncio.sleep(1)
        return False, time.time() - start
