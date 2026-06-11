# 根因分析：2026-06-11 strategy-service 重复宕机

**报告状态**: 最终  
**分析时间**: 2026-06-12 07:02 GMT+8

---

## 事件时间线

```
14:01:37  🔴 AkShare 数据源异常 — RemoteDisconnected
14:02:09  🔴 strategy-service 宕机 — 健康检查失败
14:02:12  🔴 AkShare 数据源再次异常
14:03:21  🔴 AkShare 数据源第三次异常
         ... 服务自动恢复（K8s 重启 Pod）...
21:37:30  🔴 strategy-service 再次宕机（盘后处理时）
         ... 再次自动恢复 ...
```

## 根因诊断

### 因果关系链

```
AkShare RemoteDisconnected (14:01:37)
  │
  ▼
strategy-service 调用 AkShare 时捕获异常
  │
  ├─ ❌ 未正确处理 — 异常向上传播
  │     │
  │     ├─ worker 进程崩溃 / 事件循环阻塞
  │     │
  │     └─ /health 端点无响应 (14:02:09)
  │           │
  │           └─ K8s livenessProbe 超时 → Pod 被 Kill → 自动重启
  │
  └─ 21:37 盘后处理时再次触发（AkShare 负载高/限流）
        └─ 同样的崩溃 → 恢复循环
```

### 确认的根因

**直接原因**: AkShare HTTP 连接被远端强制关闭（`RemoteDisconnected`），strategy-service 未正确处理，导致服务崩溃。

**根本原因**: strategy-service 缺少对外部数据源的三层防护：

1. ❌ **重试机制** — 未对瞬态网络错误进行指数退避重试
2. ❌ **断路器** — 外部数据源连续失败后未自动降级到备用源
3. ❌ **健康检查解耦** — `/health` 端点可能间接受数据采集模块异常影响

---

## 修复方案

### P0（立即）：AkShare 调用加防护

```python
# strategy-service/services/data_provider.py

import asyncio

async def fetch_akshare_data_with_retry(
    func, *args, max_retries: int = 3, **kwargs
):
    """带指数退避的 AkShare 调用"""
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except (ConnectionError, RemoteDisconnected, TimeoutError) as e:
            if attempt == max_retries - 1:
                logger.error("akshare_call_exhausted", error=str(e))
                raise
            wait = 2 ** attempt
            logger.warning("akshare_retry", attempt=attempt, wait=wait)
            await asyncio.sleep(wait)
```

### P1（本周）：添加断路器 + 数据源降级

```python
# strategy-service/services/data_provider.py

class DataProviderWithFallback:
    """多数据源降级：AkShare → 腾讯财经 → 通达信"""

    def __init__(self):
        self.akshare_breaker = CircuitBreaker(failure_threshold=5)

    async def get_realtime_quote(self, ts_code: str):
        try:
            return await self.akshare_breaker.call(
                akshare.stock_zh_a_spot_em
            )
        except CircuitBreakerOpenError:
            logger.warning("akshare_circuit_open — falling back to tencent")
            return await tencent_get_quote(ts_code)  # 备用数据源
```

### P2（本月）：健康检查端点解耦

```python
# strategy-service/main.py

@app.get("/health")
async def health_check():
    """健康检查 — 不依赖外部数据源"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "dependencies": {
            "database": await check_db(),
            "redis": await check_redis(),
            # 外部数据源不检查！故障不应影响服务可用性
        }
    }
```

---

## 防止复发

| 措施 | 效果 |
|------|------|
| AkShare 重试 + 指数退避 | 瞬态网络抖动（<5s）不再导致崩溃 |
| 数据源降级（AkShare→腾讯→通达信） | 单源故障不中断行情服务 |
| 断路器 | 连续故障后自动隔离，避免重复尝试耗尽资源 |
| /health 端点解耦 | 数据源故障不影响 K8s 健康检查判定 |
| Chaos test: `network-test` 场景 | CI 中验证多数据源降级链路 |

---

## 监控增强

```yaml
# monitoring/slo_alerts.yml 添加
- alert: AkShareErrorRate
  expr: rate(akshare_errors_total[5m]) > 0.1
  labels:
    severity: warning
  annotations:
    summary: "AkShare 错误率超过 10%"
```

---

*关联 ADR-004: 连接器分阶段集成策略*  
*关联 best-practices: 错误处理模式*
