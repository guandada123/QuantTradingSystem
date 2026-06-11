# ADR-002: FastAPI + Celery 技术栈选择

**状态**: ✅ 已采纳  
**日期**: 2026-06-05  
**决策者**: QuantTradingSystem 团队

---

## 背景

需要为微服务选择 Web 框架和异步任务框架。备选方案：

| 方案 | Web框架 | 异步任务 |
|------|---------|----------|
| A | Django + DRF | Celery |
| B | FastAPI | Celery |
| C | FastAPI | 自建 asyncio Queue |
| D | Flask | RQ (Redis Queue) |

核心需求：
- 高并发 API（回测查询、实时行情推送）
- 内置 OpenAPI 文档生成（降低团队协作成本）
- 异步非阻塞 IO（LLM API 调用、飞书 Webhook）
- 定时任务调度（每日选股、每周复盘）

---

## 决策

**采用 FastAPI + Celery（方案 B）。**

```python
# FastAPI: 自动生成 OpenAPI 文档、请求验证、异步支持
@app.get("/api/v1/signals")
async def get_signals(ts_code: str, limit: int = 50):
    ...

# Celery: 后台回测任务、定时策略扫描
@celery_app.task
def run_backtest(strategy_id: str, ts_code: str, start: str, end: str):
    ...
```

### 选型理由

| 评估维度 | FastAPI | Django/DRF | Flask |
|----------|:--:|:--:|:--:|
| 异步原生支持 | ✅ async/await | ⚠️ 3.x 后支持 | ❌ WSGI |
| OpenAPI 自动生成 | ✅ 内置 | ⚠️ drf-spectacular | ❌ 需插件 |
| 请求验证 (Pydantic) | ✅ 内置 | ⚠️ Serializer | ❌ 需插件 |
| 学习曲线 | 低 | 中 | 低 |
| 生态成熟度 | 成熟 | 最成熟 | 成熟 |
| 性能 (req/s) | ~25,000 | ~8,000 | ~10,000 |

**Celery 选择理由**（vs RQ / asyncio Queue）：

| 特性 | Celery | RQ | asyncio Queue |
|------|:--:|:--:|:--:|
| 任务持久化 | ✅ RabbitMQ/Redis | ✅ Redis | ❌ 内存 |
| 定时调度 (beat) | ✅ celery-beat | ⚠️ rq-scheduler | ❌ 需自建 |
| 重试机制 | ✅ 内置指数退避 | ⚠️ 手动 | ❌ 需自建 |
| 监控面板 | ✅ Flower | ⚠️ rq-dashboard | ❌ 无 |
| 社区活跃度 | ⭐ 24k | ⭐ 9k | N/A |

---

## 后果

### ✅ 正面

1. **OpenAPI 文档零成本**: 写完路由即获得 Swagger UI（`/docs`），团队无需维护独立 API 文档
2. **Pydantic 类型安全**: `pip install mypy` 后可实现端到端类型检查（请求 → 业务逻辑 → 数据库）
3. **Celery Beat 定时调度**: 每日选股、每周复盘无需外部 cron，一条 `celery-beat` schedule 即可
4. **Flower 监控面板**: 实时查看回测任务队列长度、失败率、执行时间

### ❌ 负面

1. **Celery 依赖重量级**: 需要 RabbitMQ（≈300MB 内存）或 Redis
2. **调试异步任务困难**: Celery Worker 异常不会反映在 API 响应中，需要额外日志追踪
3. **Pydantic v2 迁移成本**: v1 → v2 API 变更需要团队适应期

### ⚖️ 权衡

方案 C（自建 asyncio Queue）更轻量但无持久化和重试。A股交易日只有 4 小时，回测任务不能因重启丢失。Celery 的持久化 + 自动重试机制对金融系统是必要的。

Django 的 ORM、Admin、Auth 等功能强大，但本项目已设计了自己的 ORM 抽象层和 JWT 认证，不需要 Django 的 "batteries-included" 重量。

---

## 替代方案

### 被否决的方案

1. **Django + DRF**: 功能强大但太重。Django ORM 的 Migration 系统对高频率模型变更（交易系统频繁增加指标字段）造成摩擦
2. **Flask + RQ**: Flask 缺少原生异步支持和请求验证，需要大量插件组装；RQ 缺少 celery-beat 等效的定时调度
3. **gRPC**: 微服务间通信性能更好，但调试成本高（需要 protobuf 编译 + grpcurl），学习曲线陡峭，不适合 3 人小团队
