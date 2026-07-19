# QuantTradingSystem 项目文档索引

> 生成日期：2026-07-10
> 用途：修改代码前先查此索引，保持架构一致、风格统一、避免冲突

---

## 快速决策树

```
要做什么？                   先查什么？
─────────────────────────────────────────────────
理解整体架构                 → docs/ARCHITECTURE.md
搞清楚服务端口和模块位置      → docs/ARCHITECTURE.md
查数据库表结构                → .workbuddy/memory/PROJECT_MEMORY.md
查AI模型选择                 → .workbuddy/memory/PROJECT_MEMORY.md
写代码要保持风格              → .workbuddy/docs/best-practices/python-style.md
写测试                       → .workbuddy/docs/best-practices/testing-guide.md
处理异常                     → .workbuddy/docs/best-practices/error-handling.md
安全审查                     → .workbuddy/docs/best-practices/security-checklist.md
理解为什么这么设计            → docs/adr/001 ~ 006
部署/运维                    → docs/RUNBOOK.md
排查生产问题                  → docs/incident-response/
查API端点                    → docs/api/README.md
```

---

## 文档总览

### 架构与设计

| 文档 | 路径 | 说明 |
|------|------|------|
| 项目架构文档 | `docs/ARCHITECTURE.md` | 125行，系统总览、3个微服务详解、数据流、监控栈、测试矩阵、部署拓扑 |
| 项目记忆 | `.workbuddy/memory/PROJECT_MEMORY.md` | 241行，架构图、服务细节、数据库设计、Web前端、技术决策、风险、成功标准 |
| 运行手册 | `docs/RUNBOOK.md` | 故障处理指南 |

### 架构决策记录 (ADR)

| 文档 | 路径 | 决策内容 |
|------|------|---------|
| ADR-001 | `docs/adr/001-microservices-architecture.md` | 微服务架构选型 |
| ADR-002 | `docs/adr/002-fastapi-celery-choice.md` | FastAPI + Celery 技术栈 |
| ADR-003 | `docs/adr/003-miniqmt-selection.md` | MiniQMT 券商接口选型 |
| ADR-004 | `docs/adr/004-connector-staged-integration.md` | 连接器分阶段集成策略 |
| ADR-005 | `docs/adr/005-unified-dependency-management.md` | 统一依赖与锁文件管理 |
| ADR-006 | `docs/adr/006-dist-build-and-ci-gate.md` | Dashboard 构建流水线与 CI 门 |

### 最佳实践

| 文档 | 路径 | 说明 |
|------|------|------|
| Python风格指南 | `.workbuddy/docs/best-practices/python-style.md` | 命名规范、代码风格、模块组织 |
| 测试指南 | `.workbuddy/docs/best-practices/testing-guide.md` | 测试编写规范、Mock策略 |
| 异常处理 | `.workbuddy/docs/best-practices/error-handling.md` | 异常处理规范、错误码体系 |
| 安全清单 | `.workbuddy/docs/best-practices/security-checklist.md` | 安全检查项 |

### API 文档

| 文档 | 路径 |
|------|------|
| API文档索引 | `docs/api/README.md` |
| Swagger UI | `docs/api/index.html` |
| strategy-service OpenAPI | `docs/api/strategy-service.json` |
| execution-service OpenAPI | `docs/api/execution-service.json` |
| ai-scheduler OpenAPI | `docs/api/ai-scheduler.json` |

---

## 关键速查

### 三个微服务

| 服务 | 端口 | 端口Docker | 职责 | 核心文件 |
|------|:----:|:---------:|------|---------|
| strategy-service | 8000 | 8008 | 策略研究、数据聚合、回测、API网关 | `api/`, `services/`, `services/backtest/` |
| execution-service | 8001 | 8009 | 订单管理、风控、MiniQMT | `services/risk_controller.py` 等 |
| ai-scheduler | 8002 | 8010 | AI调度、定时任务、WebSocket | `services/scheduler.py` 等 |

### 数据库

| 数据库 | 端口 | 用途 |
|--------|:---:|------|
| PostgreSQL | 5432 | 关系数据（股票池、行情、订单、持仓等7张表） |
| Redis | 6379 | 缓存/队列 |
| QuestDB | 8812 | 时序数据（分钟K线、Tick） |
| RabbitMQ | 5672 | 消息队列（服务间异步通信） |

### 监控栈

```
服务 Metrics → Prometheus:9090 → Grafana:3001（3个Dashboard）
            → Alertmanager-Feishu:9093 → 飞书告警

服务日志 → Logstash:5044 → Elasticsearch:9200 → Kibana:5601
```

### 测试覆盖

| 层级 | 位置 | 数量 |
|------|------|:---:|
| shared 单元测试 | `shared/tests/` | 39 |
| strategy 单元测试 | `strategy-service/tests/` | ~50 |
| execution 单元测试 | `execution-service/tests/` | ~15 |
| ai-scheduler 单元测试 | `ai-scheduler/tests/` | ~9 |
| E2E 测试 | `tests/test_e2e.py` | ~20 |

---

## 修改代码前的必查清单

- [ ] 我改了哪个服务？（strategy:8000 / execution:8001 / ai-scheduler:8002）
- [ ] 我遵循了 `best-practices/python-style.md` 的命名规范？
- [ ] 我遵循了 `best-practices/error-handling.md` 的异常处理规范？
- [ ] 我改了数据表结构？（需要同步更新 DDL 和 Alembic 迁移）
- [ ] 我改了API？（需要更新 OpenAPI 文档和测试）
- [ ] 我加了新依赖？（需要更新 `pyproject.toml` 和锁文件）
- [ ] 测试覆盖率没降？现有 133 个测试
