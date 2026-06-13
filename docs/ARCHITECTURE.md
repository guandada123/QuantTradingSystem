# QuantTradingSystem 架构文档

## 系统总览

```
                         ┌──────────────────┐
                         │   Web 前端        │
                         │   Nginx:3000      │
                         │   Vue3+ECharts    │
                         └────────┬─────────┘
                                  │ /api/v1/*
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
        ▼                         ▼                         ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│ strategy-svc  │◄────►│ execution-svc │◄────►│ ai-scheduler  │
│ :8000         │AMQP  │ :8001         │      │ :8002         │
│ 策略研究      │      │ 交易执行      │      │ AI调度        │
└───┬───┬───┬───┘      └───────┬───────┘      └───────┬───────┘
    │   │   │                  │                      │
    ▼   ▼   ▼                  ▼                      ▼
┌──────┐ ┌───┐ ┌──────┐  ┌──────────┐        ┌──────────────┐
│PG/TD │ │RDS│ │QstDB │  │RabbitMQ  │        │DeepSeek API  │
│:5432 │ │6379│ │:8812 │  │:5672     │        │(外部)        │
└──────┘ └───┘ └──────┘  └──────────┘        └──────────────┘
```

## 微服务详解

### strategy-service (端口 8000)
**职责**: 策略研究、数据聚合、回测引擎、API 网关

| 模块 | 路径 | 说明 |
|------|------|------|
| API 路由 | `api/` | 14个路由模块, 25+ 端点 |
| 数据服务 | `services/data_service.py` | 多数据源适配 (TDX/Tushare/AKShare) |
| 回测引擎 | `services/backtest/` | V1 + V2 回测引擎 |
| AI 分析 | `services/multi_agent.py` | DeepSeek 多智能体分析 |
| Stock Insight | `api/stock_insight.py` | 多因子选股集成 |
| 飞书告警 | `services/feishu_alert.py` | 信号推送/告警通知 |

**依赖**: PostgreSQL, Redis, QuestDB, RabbitMQ

### execution-service (端口 8001)
**职责**: 订单管理、风险控制、MiniQMT 接口

| 模块 | 说明 |
|------|------|
| 订单管理 | 限价单/市价单提交与跟踪 |
| 风险控制 | 仓位限制、止损检查 |
| MiniQMT | QMT 交易接口适配 |

**依赖**: PostgreSQL, RabbitMQ

### ai-scheduler (端口 8002)
**职责**: AI 模型调度、定时任务、WebSocket 推送

| 模块 | 说明 |
|------|------|
| 模型调度 | Flash/Pro 按需切换, 成本优化 |
| 定时任务 | APScheduler 市场扫描/日终报告 |
| WebSocket | 实时行情推送 (3s 间隔) |

**依赖**: strategy-service, execution-service, DeepSeek API

## 数据流

```
Tushare/TDX/AKShare ──► DataService ──► API ──► Dashboard
                                   │
                                   ▼
                              PostgreSQL (持久化)
                                   │
                                   ▼
                              QuestDB (时序)
                                   │
                                   ▼
                              Redis (缓存)
```

## 监控栈

```
服务 Metrics ──► Prometheus (:9090) ──► Grafana (:3001)
           │                              ├─ quant-trading
           │                              ├─ trading-metrics
           │                              └─ system-overview
           │
           └──► Alertmanager-Feishu (:9093) ──► 飞书群
```

## 日志栈 (ELK)

```
服务日志 ──► Logstash (:5044) ──► Elasticsearch (:9200) ──► Kibana (:5601)
```

## 测试矩阵

| 层级 | 位置 | 数量 | CI |
|------|------|------|-----|
| shared 单元 | `shared/tests/` | 39 | ✅ |
| strategy 单元 | `strategy-service/tests/` | ~50 | ✅ |
| execution 单元 | `execution-service/tests/` | ~15 | ✅ |
| ai-scheduler 单元 | `ai-scheduler/tests/` | ~9 | ✅ |
| E2E | `tests/test_e2e.py` | ~20 | ✅ (Docker) |
| 安全扫描 | CI bandit+safety | - | ✅ |

## 部署拓扑

| 环境 | 方式 | 文件 |
|------|------|------|
| 本地开发 | `make docker-up` | `docker-compose.yml` (14容器) |
| K8s 集群 | `k8s/deploy.sh` | `k8s/` (75资源, 21文件) |
| Python | Python 3.12 | `pyproject.toml` |

## 关键设计决策

1. **多数据源容灾**: TDX → Tushare → AKShare 降级链
2. **多阶段 Docker**: strategy-service 用 builder→runtime 减 60% 体积
3. **令牌桶限流**: 按 IP 隔离, 白名单支持, 429+Retry-After
4. **优雅关闭**: SIGTERM 排空 + 清理回调, K8s preStop 适配
5. **AI 模型调度**: Flash(轻量任务) / Pro(分析任务) 按需切换
6. **数据库迁移**: Alembic 3版本 + 回滚, 旧 migration.py 已废弃
