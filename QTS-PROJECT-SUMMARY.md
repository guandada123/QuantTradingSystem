# QuantTradingSystem (QTS) — 项目总结文档

> **版本**: v0.2.0 | **最后更新**: 2026-06-19 | **许可**: MIT

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术架构](#2-技术架构)
3. [核心功能模块](#3-核心功能模块)
4. [前端 Dashboard](#4-前端-dashboard)
5. [基础设施与部署](#5-基础设施与部署)
6. [CI/CD 流水线](#6-cicd-流水线)
7. [安全加固](#7-安全加固)
8. [开发指南](#8-开发指南)
9. [使用指南](#9-使用指南)
10. [测试体系](#10-测试体系)
11. [监控与可观测性](#11-监控与可观测性)
12. [质量审计与优化历程](#12-质量审计与优化历程)
13. [未来规划](#13-未来规划)
14. [附录](#14-附录)

---

## 1. 项目概述

### 1.1 简介

**QuantTradingSystem (QTS)** 是一套基于微服务架构的 AI 驱动 A 股量化交易系统，覆盖从数据采集、策略研究、AI 分析到交易执行的全流程。系统集成 DeepSeek 多智能体分析引擎、Tushare/AKShare 实时行情、自研回测引擎和 Web 端仪表盘。

### 1.2 核心能力

| 能力 | 描述 |
|------|------|
| **数据聚合** | 多数据源并行接入（Tushare、AKShare、通达信、东方财富），自动质量监控 |
| **策略回测** | 5 种内置策略（双均线、趋势跟踪、均值回归、动量突破、组合策略），支持参数优化 |
| **AI 智能分析** | 多 Agent 辩论式分析（DeepSeek V4 Pro/Flash），覆盖基本面/技术面/情绪面 |
| **AI 全市场选股** | 多因子评分 + LLM 评估，自动筛选优质标的 |
| **交易执行** | 订单管理、智能路由、止盈止损、风险控制（仓位限制/熔断器） |
| **实时监控** | WebSocket 实时行情推送（每 3 秒指数广播）、Prometheus 指标、飞书告警 |

### 1.3 项目规模

| 维度 | 数据 |
|------|------|
| 总代码行数 | ~55,350 Python + 4,836 JS + 2,116 CSS + 3,715 HTML |
| 配置文件 | 1,665 行 Shell + 10,141 行 YAML |
| 文件总数 | 353 个 |
| 测试文件 | 50+ 测试文件，2,478 行测试代码 |
| Docker 容器 | 14 个（3 微服务 + 前端 + 10 基础设施） |
| K8s 资源 | 75 个，21 个 YAML 文件 |
| CI 工作流 | 4 个 GitHub Actions |
| Makefile 目标 | 25+ 个 |

---

## 2. 技术架构

### 2.1 系统架构总览

```
                              ┌──────────────────┐
                              │   Web 前端        │
                              │ Nginx :3000       │
                              │ Vue3 + ECharts    │
                              └────────┬──────────┘
                                       │ /api/v1/*
         ┌─────────────────────────────┼──────────────────────────┐
         │                             │                          │
         ▼                             ▼                          ▼
 ┌───────────────┐          ┌───────────────┐          ┌──────────────────┐
 │ strategy-svc  │◄──AMQP──►│ execution-svc │◄────────►│  ai-scheduler    │
 │ :8000         │          │ :8001         │  HTTP    │ :8002            │
 │ 策略研究服务   │          │ 交易执行服务   │          │ AI 调度服务      │
 └───┬───┬───┬───┘          └───────┬───────┘          └──────┬───────────┘
     │   │   │                      │                         │
     ▼   ▼   ▼                      ▼                         ▼
 ┌──────┐┌───┐┌──────┐    ┌──────────────┐         ┌──────────────────┐
 │PG/TD ││RDS││QstDB │    │  RabbitMQ    │         │  DeepSeek / Kimi │
 │:5432 ││6379││:8812 │    │ :5672        │         │  GLM / MiniMax   │
 └──────┘└───┘└──────┘    └──────────────┘         └──────────────────┘
```

### 2.2 微服务详解

#### 2.2.1 strategy-service（端口 8000）— 策略研究服务

**职责**: 策略研究、数据聚合、回测引擎、API 网关

| 模块 | 路径 | 说明 |
|------|------|------|
| API 路由 | `api/` | 14 个路由模块，25+ API 端点 |
| 数据服务 | `services/data_service.py` | 多数据源适配（TDX/Tushare/AKShare），含数据质量监控 |
| 回测引擎 | `services/backtest_engine_v2.py` | V2 增强引擎，支持 5 种策略 |
| AI 分析 | `services/multi_agent/` | 5 个 Agent 辩论式分析（技术/基本面/情绪/风险/综合） |
| Stock Insight | `services/stock_insight_engine/` | 多因子选股引擎（6 个子模块） |
| 指标计算 | `services/indicators.py` | TA-Lib + pandas_ta 技术指标 |
| 调度器 | `services/scheduler/` | APScheduler 定时任务 |
| 数据访问 | `repositories/` | 7 个 Repository（Repository 模式） |

**代码量**: ~29,800 行 Python

**API 端点**（25+）:

| 分组 | 端点 | 说明 |
|------|------|------|
| 健康 | `GET /health`, `GET /metrics` | 健康检查、Prometheus 指标 |
| 📈 股票数据 | `GET /api/v1/stocks/pool` | 股票池列表 |
| | `GET /api/v1/stocks/realtime/{code}` | 个股实时行情 |
| | `GET /api/v1/stocks/index/realtime` | 指数实时行情（上证/深证/创业板） |
| | `GET /api/v1/stocks/kline/{code}` | K 线数据 |
| | `GET /api/v1/stocks/f10/{code}` | F10 基本面 |
| 🤖 AI 分析 | `POST /api/v1/ai/analyze` | 多智能体分析（5 Agent 辩论） |
| | `POST /api/v1/ai/scan` | AI 全市场选股 |
| 📊 回测 | `POST /api/v1/backtest/run` | 策略回测 |
| | `GET /api/v1/backtest/strategies` | 策略列表 |
| | `GET /api/v1/backtest/history` | 回测历史 |
| 💰 账户 | `GET /api/v1/account/summary` | 账户概要 |
| | `GET /api/v1/account/positions` | 持仓列表 |
| 📋 交易信号 | `GET /api/v1/signals` | 交易信号 |
| 💬 WebSocket | `ws://localhost:8000/ws` | 实时行情推送（每 3 秒） |

---

#### 2.2.2 execution-service（端口 8001）— 交易执行服务

**职责**: 订单管理、风险控制、MiniQMT 接口

| 模块 | 说明 |
|------|------|
| 订单管理 | `services/order_manager.py` — 限价单/市价单提交与跟踪 |
| 订单验证 | `services/order_validator.py` — 订单参数校验 |
| 止损管理 | `services/order_stop.py` — 停损单自动管理 |
| 持仓管理 | `services/position_manager.py` — 持仓查询/更新/平仓 |
| 风险控制 | `services/risk_controller.py` — 仓位限制、止损、熔断器 |
| MiniQMT | `services/miniqmt_connector.py` — 同花顺 MiniQMT 交易接口适配 |
| 飞书告警 | `services/feishu_alert.py` — 交易事件通知 |
| WebSocket | `api/ws_execution.py` — 订单/持仓实时推送 |

**API 端点**:

| 端点 | 说明 |
|------|------|
| `GET /health`, `GET /metrics` | 健康/指标 |
| `GET /api/v1/orders` | 订单列表 |
| `POST /api/v1/orders` | 创建订单 |
| `DELETE /api/v1/orders/{id}` | 撤单 |
| `GET /api/v1/positions` | 持仓列表 |
| `GET /api/v1/risk/check/{ts_code}` | 风控检查 |
| `GET /api/v1/risk/circuit-breaker` | 熔断器状态 |
| `POST /api/v1/risk/reset-circuit-breaker` | 重置熔断器 |
| `WebSocket /ws/execution` | 订单/风险实时推送 |

**代码量**: ~10,500 行 Python

---

#### 2.2.3 ai-scheduler（端口 8002）— AI 调度服务

**职责**: AI 任务调度、健康监控、LLM 客户端

| 模块 | 说明 |
|------|------|
| 任务调度 | `services/task_scheduler.py` — APScheduler 定时任务 |
| LLM 客户端 | `services/llm_client.py` — DeepSeek API 调用 |
| 策略客户端 | `services/strategy_client.py` — strategy-service HTTP 客户端 |
| 健康监控 | `services/health_monitor.py` — 各服务健康状态 |

**API 端点**:

| 端点 | 说明 |
|------|------|
| `GET /health`, `GET /metrics` | 健康/指标 |
| `POST /api/v1/scheduler/scan` | 触发选股扫描 |
| `POST /api/v1/scheduler/review` | 触发每日复盘 |
| `POST /api/v1/scheduler/predict` | 触发市场预测 |
| `GET /api/v1/scheduler/tasks` | 任务状态列表 |
| `GET /api/v1/health-monitor/status` | 各服务健康状态 |
| `WebSocket /ws/scheduler` | 任务/健康状态推送 |

**代码量**: ~5,000 行 Python

---

### 2.3 shared 公共模块

| 模块 | 文件 | 说明 |
|------|------|------|
| 认证 | `auth.py` | JWT + API Key 双重认证 |
| 健康探针 | `health.py` | `/health` (liveness) + `/ready` (readiness) |
| 中间件 | `middleware.py` | Trace ID 跨服务链路追踪 + 响应脱敏 |
| 限流 | `rate_limiter.py` | 令牌桶限流，按 IP 隔离，60 请求/分钟 |
| 指标 | `metrics.py` | 轻量 Prometheus 指标 |
| Redis | `redis_client.py` | Redis 客户端工厂（支持 Sentinel 高可用） |
| 弹性 | `resilience.py` | 重试 + 断路器 + 降级模式 |
| 风控配置 | `risk_config.py` | 15 个风控参数统一配置 |
| WS 协议 | `ws_protocol.py` | WebSocket 标准化消息格式 |
| 日志 | `logging_config.py` | structlog 结构化日志 + ContextVar trace_id |
| 异常 | `exceptions.py` | 共享异常定义 |
| 优雅关闭 | `graceful_shutdown.py` | SIGTERM/SIGINT 处理器 |
| 行情提供商 | `quote_provider/` | 接口抽象 + 3 个实现（tushare/tdx/akshare）+ 工厂 |

**代码量**: ~3,800 行 Python

### 2.4 数据流架构

```
外部数据源                             内部服务间通信
Tushare ──┐                     strategy-service ←──AMQP──→ execution-service
AKShare ──┼──► DataService ──►  (回测/信号/分析)            (订单/风控)
通达信  ──┘                            ↕ HTTP                  ↕ HTTP
                                   ai-scheduler ──────────► DeepSeek API
                                      (调度/监控)              (LLM)
                                         │
                                    ┌────┴────┐
                                    │ 飞书告警 │
                                    └─────────┘
```

### 2.5 架构设计决策（ADR）

| 决策 | 选择 | 替代方案 | 原因 |
|------|------|---------|------|
| ADR-001 | 微服务架构 | 单体应用 | 独立部署/扩展，故障隔离 |
| ADR-002 | FastAPI + APScheduler | Celery | 原生 asyncio 支持，减少依赖复杂度 |
| ADR-003 | MiniQMT | 券商 API/同花顺标准版 | 合规且低成本，低延迟 |
| ADR-004 | 分阶段连接器集成 | 一步到位 | 安全回退：模拟层 → 沙箱 → 实盘 |

---

## 3. 核心功能模块

### 3.1 多数据源聚合

- **Tushare**: 基础行情、财务数据、资金流向
- **AKShare**: 实时行情、龙虎榜、板块资金
- **通达信**: K 线数据、技术指标、板块成分
- **自动质量监控**: 5 分钟间隔后台任务，检测数据异常/缺失

### 3.2 回测引擎（V2）

| 策略名称 | 类型 | 说明 |
|---------|------|------|
| 双均线金叉 (MA Cross) | 趋势跟踪 | 快线上穿慢线买入，下穿卖出 |
| 趋势跟踪 (Trend) | 趋势跟踪 | ADX + EMA 确认趋势方向 |
| 均值回归 (Mean Reversion) | 震荡策略 | RSI 超买超卖 + Bollinger 区间 |
| 动量突破 (Breakout) | 突破策略 | N 日高点突破 + 成交量确认 |
| 组合策略 (COMBO) | 综合策略 | 多策略加权融合 |

**回测产出**:
- 收益率曲线、夏普比率、最大回撤、胜率
- 交易明细热力图、月度收益分布
- Walk-Forward 分析、参数敏感性测试

### 3.3 AI 多智能体分析

系统使用 **5 个 Agent 辩论式分析**，每个 Agent 负责独立分析视角：

| Agent | 角色 | 分析维度 |
|-------|------|---------|
| Technical Analyst | 技术分析师 | K 线形态、技术指标、趋势判断 |
| Fundamental Analyst | 基本面分析师 | 财务数据、估值水平、行业地位 |
| Sentiment Analyst | 情绪分析师 | 新闻舆情、市场情绪、资金流向 |
| Risk Manager | 风险官 | 风险评估、仓位建议、止损策略 |
| Portfolio Manager | 投资经理 | 综合裁定、输出最终投资建议 |

### 3.4 AI 全市场选股（Stock Insight）

多因子选股引擎，结合 LLM 评估：

```
股票池(全市场/A股)
    │
    ├── 过滤层: PE/PB/市值/ST/涨跌幅
    │
    ├── 因子评分: 动量/价值/质量/情绪/技术(6因子)
    │
    ├── 惩罚层: 上涨缩量/业绩变脸/异常波动
    │
    └── LLM 评估: DeepSeek 综合分析 → 最终排名
```

### 3.5 交易执行

- **订单类型**: 限价单、市价单、止损单
- **智能路由**: 根据市场环境自动选择最优执行路径
- **风险控制**: 仓位比例限制（默认 30%/只）、最大持仓数（默认 3）、止损（默认 8%）、止盈（默认 30%）、日亏损上限（默认 5%）
- **熔断器**: 连续失败自动熔断，周期性半开探测恢复
- **MiniQMT 集成**: 同花顺 MiniQMT 实盘接口

### 3.6 AI 模型调度

| 任务 | 推荐模型 | 成本系数 |
|------|---------|---------|
| 数据清洗/指标计算 | DeepSeek-V4-Flash | 0.06x |
| 新闻情绪分析 | DeepSeek-V3.2 | 0.29x |
| 多智能体辩论/模式识别 | DeepSeek-V4-Pro | 0.16x |
| 策略优化 | GLM-5.1 | 1.06x |

---

## 4. 前端 Dashboard

### 4.1 技术栈

| 技术 | 用途 |
|------|------|
| **Vue 3** (CDN) | SPA 单页应用框架 |
| **ECharts 5** | 交互式图表（K 线、热力图、曲线） |
| **WebSocket** | 实时行情推送 |
| **Inter + JetBrains Mono** | 品牌字体 |
| **Nginx** | 反向代理 + 静态文件服务 |
| **design-tokens.css** | 设计令牌系统 |
| **CSP Nonce** | 内容安全策略 |

### 4.2 页面清单（10 页）

| 页面 | 文件 | 大小 | 核心功能 |
|------|------|------|---------|
| 🏠 **主入口** | `index.html` | 6.5K | SPA 路由、CSP 安全头、Service Worker |
| 💰 **账户展示** | `account.html` | 9.5K | 资产概览、持仓列表、盈亏曲线（ECharts） |
| 📝 **交易下单** | `orders.html` | 11.2K | 快速下单、方向切换（买/卖）、持仓操作 |
| 📊 **回测分析** | `backtest.html` | 23.8K | 策略参数配置、回测执行、绩效图表、热力图 |
| 🎯 **策略管理** | `strategies.html` | 14.6K | 策略卡片浏览、创建、对比 |
| 🔍 **交易分析** | `trade-analysis.html` | 9.0K | 指标卡片、胜率统计、盈亏分布 |
| 📋 **复盘分析** | `review-analysis.html` | 12.2K | AI 日/周复盘报告、风险标注 |
| 🔎 **选股报告** | `stock-selection.html` | 8.5K | AI 选股结果、多因子评分展示 |
| 🔔 **告警管理** | `alerts.html` | 11.5K | 告警规则配置、历史告警、状态切换 |
| 📚 **API 文档** | `api-docs.html` | 3.4K | 多服务 Swagger 集成标签页 |

### 4.3 设计系统

**配色方案**:

| 层级 | 色彩 |
|------|------|
| 品牌色 | 紫色系（#534AB7 → #7F77DD） |
| A 股方向 | 🟢 绿跌 🔴 红涨（A 股惯例） |
| 语义色 | 成功绿、错误红、警告橙、信息蓝 |

**主题模式**: 支持 **Light / Dark / System** 三模式切换，过渡平滑。

**排版**:

| 变量 | 值 |
|------|------|
| 正文字体 | Inter, -apple-system, PingFang SC |
| 等宽字体 | JetBrains Mono, SF Mono, Fira Code |
| 字号比例 | 12px → 30px（8 级，基 14px） |
| 字重 | 400 / 500 仅用两档 |
| 行高 | 1.25 / 1.5 / 1.625 |

**间距 & 圆角**:

| 层级 | 值 |
|------|------|
| 基础单位 | 4px |
| 间距等级 | 4/8/12/16/20/24/32/40/48px |
| 圆角等级 | 6px / 8px / 12px / 16px / 9999px |

### 4.4 交互优化

| 特性 | 说明 |
|------|------|
| 磁吸 Hover | 鼠标悬停时卡片微幅追踪光标位置 + 3% 放大 |
| 入场动画 | 页面切换时内容 fade-in + translateY(10px) 交错入场 |
| 玻璃卡片 | `backdrop-filter: blur(28px)` + 半透明边框 |
| 骨架屏 | 内容加载前显示脉冲动画占位 |
| 空状态 | 各页面无数据时显示友好空状态提示 |
| 卡片 Hover | 11 种卡片统一 `translateY(-2px)` + 主题自适应阴影 |

### 4.5 构建产物

| 文件 | 原始 | 压缩后 | 节省 |
|------|------|--------|------|
| style.css | 69KB | 53KB | -22.6% |
| app.js | 28KB | 15KB | -46.8% |
| app.spa.js | 116KB | 88KB | -24.3% |
| index.html | 6.4KB | 5.7KB | -11.5% |

---

## 5. 基础设施与部署

### 5.1 Docker Compose（14 容器）

| 容器 | 镜像 | 端口 | 资源配置 |
|------|------|------|---------|
| **strategy-service** | 自定义（多阶段构建） | 8000 | 512MB, HEALTHCHECK |
| **execution-service** | 自定义（slim） | 8001 | 512MB, NET_ADMIN |
| **ai-scheduler** | 自定义（slim） | 8002 | 512MB |
| **dashboard** | nginx:alpine | 3000 | 反向代理 + 静态文件 |
| **postgres** | timescaledb:pg15 | 15432 | TimescaleDB 扩展 |
| **redis** | redis:7-alpine | 6379 | 512MB, allkeys-lru |
| **questdb** | questdb:latest | 8812/9000 | 时序数据，行情 7 天 TTL |
| **rabbitmq** | 3-management-alpine | 5672/15672 | 消息队列 |
| **prometheus** | prom:latest | 9090 | 15 秒抓取间隔 |
| **grafana** | grafana:latest | 3001 | 3 个预置仪表盘 |
| **alertmanager-feishu** | 自定义 | 9093 | 告警转飞书 |
| **elasticsearch** | 8.11.0 | 9200 | 1GB heap, 密码保护 |
| **logstash** | 8.11.0 | 5044/9600 | 日志管道 |
| **kibana** | 8.11.0 | 5601 | 日志可视化 |

**Profile 分组**:

```bash
# 启动微服务（3个）
docker compose --profile microservices up -d

# 启动基础设施（数据库/缓存/队列）
docker compose --profile infra up -d

# 启动监控（Prometheus/Grafana/ELK）
docker compose --profile monitoring up -d

# 启动前端
docker compose --profile web up -d

# 一键全部启动
docker compose --profile "*" up -d
```

### 5.2 Kubernetes 部署（21 YAML 文件）

| 资源 | 类型 | 副本 | 说明 |
|------|------|------|------|
| strategy-service | Deployment + Service + HPA | 2 | 自动扩缩容 |
| execution-service | Deployment + Service | 1 | 交易执行 |
| ai-scheduler | Deployment + Service | 1 | AI 调度 |
| dashboard | Deployment + Service | 1 | 前端 |
| postgres | StatefulSet + PVC | 1 | TimescaleDB |
| redis | StatefulSet | 1 | 缓存 |
| questdb | StatefulSet | 1 | 时序 |
| rabbitmq | StatefulSet | 1 | 队列 |
| elasticsearch | StatefulSet | 1 | 日志 |
| prometheus | Deployment | 1 | 监控 |
| grafana | Deployment | 1 | 可视化 |

**额外配置**: Ingress（path-based routing）、NetworkPolicy、RBAC、PodDisruptionBudget、ResourceQuota

### 5.3 Helm Chart

```bash
helm/quant-trading/
├── Chart.yaml
├── values.yaml
├── ci/
│   ├── values-dev.yaml
│   └── values-prod.yaml
└── templates/
    ├── _helpers.tpl
    ├── _microservice.tpl
    ├── configmap.yaml
    ├── ingress.yaml
    ├── namespace.yaml
    ├── network-policy.yaml
    ├── rbac.yaml
    ├── resource-quota.yaml
    ├── secrets.yaml
    └── services.yaml
```

### 5.4 环境变量配置

多 Profile 系统，按优先级加载：

```
.env               — 基础配置（可提交 Git，非敏感默认值）
.env.local         — 本地覆盖（不提交 Git，存放实际密钥）  ← 最高优先级
.env.development   — 开发环境（可提交 Git）
.env.production    — 生产环境（不提交 Git，真实密钥+域名）
```

**关键变量类别**:

| 类别 | 变量 | 来源 |
|------|------|------|
| 📊 数据源 | TUSHARE_TOKEN, AKSHARE_ENABLED, QTS_DATA_SOURCE | tushare.pro |
| 🤖 AI 模型 | DEEPSEEK_API_KEY, GLM_API_KEY, KIMI_API_KEY, MINIMAX_API_KEY | 各平台 |
| 💹 交易终端 | MINIQMT_USER, MINIQMT_PASSWORD | 同花顺 |
| 🔔 通知 | FEISHU_WEBHOOK | 飞书机器人 |
| ⚙️ 风控 | MAX_POSITION_RATIO, STOP_LOSS_RATIO, MAX_DAILY_LOSS | — |
| 🔐 认证 | JWT_SECRET_KEY, API_KEYS | `openssl rand -hex 32` |

---

## 6. CI/CD 流水线

### 6.1 GitHub Actions（4 个工作流）

```
PR/Push to main
    │
    ├── pre-commit ──► ruff lint ──► ruff format
    │
    ├── lint ──► ruff check + ruff format --check
    │
    ├── type-check ──► mypy (4个矩阵: strategy/execution/ai-scheduler/shared)
    │
    ├── unit-test ──► pytest (4个矩阵, 覆盖率≥65%/30%)
    │      │
    │      └── e2e-test ──► docker compose up + pytest test_e2e.py
    │
    ├── contract-test ──► pytest tests/contracts/
    │
    ├── build-check ──► ./build.sh + git diff dist/ 验证同步
    │
    └── git tag v* ──► security-scan ──► Docker 构建推送 GHCR
         (每周一)           │
                      bandit + safety + gitleaks
```

| 工作流 | 触发 | 阶段 |
|--------|------|------|
| **ci.yml** | PR/推送 main | 工程审核 Kit |
| **test.yml** | PR/推送 main | Lint → TypeCheck → UnitTest(4矩阵) → Contract → BuildCheck → E2E |
| **build.yml** | git tag v* | 构建 4 个 Docker 镜像 → 推送 GHCR |
| **security-scan.yml** | 每周一 + 代码变更 | safety(依赖) + bandit(代码) + gitleaks(密钥) |

### 6.2 Makefile（25+ 目标）

| 目标 | 说明 |
|------|------|
| `make test` | 运行所有服务测试 |
| `make test-strategy` | strategy-service 测试 |
| `make test-execution` | execution-service 测试 |
| `make test-scheduler` | ai-scheduler 测试 |
| `make test-coverage` | 所有测试 + 合并覆盖率 |
| `make test-contract` | 合约测试 |
| `make lint` | ruff 检查 |
| `make lint-check` | ruff 格式检查 |
| `make type-check` | mypy 类型检查（4 矩阵） |
| `make security` | bandit 安全扫描 |
| `make fix` | ruff 自动修复 + 格式化 |
| `make check-all` | 完整检查链 |
| `make build` | dashboard 前端构建 |
| `make build-check` | 构建 + 同步验证 |
| `make ci` | 完整 CI 流水线 |
| `make start` | docker-compose 启动 |
| `make check-deploy` | 部署前安全检查 |

### 6.3 代码质量工具链

| 工具 | 用途 | 规则 |
|------|------|------|
| **ruff** | Python 代码检查 + 格式化 | 50+ 规则（pycodestyle/pyflakes/isort/pylint/bandit 等） |
| **mypy** | 静态类型检查 | `--strict` 模式 |
| **pre-commit** | 提交前自动检查 | ruff + trailing-whitespace + check-yaml + detect-private-key |
| **bandit** | 安全漏洞扫描 | 排除 B101/B105/B603 |
| **gitleaks** | Git 密钥泄露检测 | 配置 `.gitleaks.toml` |

---

## 7. 安全加固

### 7.1 认证与授权

| 机制 | 说明 |
|------|------|
| **JWT** | 终端用户认证，Bearer Token |
| **API Key** | 服务间认证，X-API-Key 头部 |
| **双机制并行** | 核心端点同时验证 JWT + API Key |

### 7.2 Web 安全

| 措施 | 头/配置 | 值 |
|------|---------|-----|
| CSP | Content-Security-Policy | Nonce 策略，限制 script-src/style-src |
| 点击劫持 | X-Frame-Options | DENY |
| MIME 嗅探 | X-Content-Type-Options | nosniff |
| 引荐来源 | Referrer-Policy | strict-origin-when-cross-origin |
| 权限 | Permissions-Policy | 限制摄像头/麦克风/地理位置 |
| 服务版本 | server_tokens | off |

### 7.3 数据安全

| 措施 | 说明 |
|------|------|
| 响应脱敏 | 自动脱敏 API Key / Token / Secret / Password |
| 密钥扫描 | pre-commit `detect-private-key` hook + CI gitleaks |
| 限流 | 令牌桶算法，60 请求/分钟，429 + Retry-After |
| Trace ID | 跨服务链路追踪，请求唯一标识 |

### 7.4 基础设施安全

| 措施 | 说明 |
|------|------|
| 非 root 用户 | 所有自定义 Dockerfile 以非 root 运行 |
| 密码环境变量化 | ES/Grafana/DB/RabbitMQ 密码均通过环境变量注入 |
| .env 分层 | 密钥存放 `.env.local`（不提交 Git） |
| K8s Secret | K8s 部署通过 Secret 管理敏感信息 |
| NetworkPolicy | 服务间网络隔离 |

---

## 8. 开发指南

### 8.1 本地开发环境

```bash
# 1. 克隆并进入项目
git clone <repo-url>
cd QuantTradingSystem

# 2. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖（按需安装对应分组）
pip install -e ".[strategy,dev]"        # 策略服务 + 开发工具
pip install -e ".[execution,dev]"       # 执行服务 + 开发工具
pip install -e ".[ai-scheduler,dev]"    # AI 调度 + 开发工具

# 4. 安装 pre-commit hooks
pre-commit install
```

> **注意**: `pyproject.toml` 为统一依赖管理入口，各子目录的 `requirements.txt` 已废弃。

### 8.2 开发流程

```
1. 从 develop 切出功能分支
   git checkout -b feat/my-feature develop

2. 开发 → 提交
   git commit -m "feat(scope): 描述"

3. 运行完整检查
   make check-all

4. 推送 + 创建 PR
   git push origin feat/my-feature
   # → GitHub → Create PR
```

### 8.3 分支策略

```
main          ← 生产就绪代码（受保护）
  └── develop ← 集成分支
      ├── feat/<name>          新功能
      ├── fix/<issue-id>       Bug 修复
      ├── refactor/<name>      重构
      └── docs/<name>          文档
```

### 8.4 Git 提交规范

使用 **Conventional Commits** 格式：

```
<type>(<scope>): <subject>

[optional body]
[optional footer]
```

**Type**:

| Type | 含义 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(strategy): 添加双均线金叉策略` |
| `fix` | Bug 修复 | `fix(execution): 修复 MiniQMT 断连重试逻辑` |
| `refactor` | 重构 | `refactor(core): 提取公共数据模型到 shared 包` |
| `test` | 测试 | `test(ai-scheduler): 增加模型选择算法单元测试` |
| `docs` | 文档 | `docs(readme): 更新部署文档` |
| `chore` | 杂务 | `chore(deps): 升级 FastAPI 到 0.115` |
| `perf` | 性能优化 | `perf(backtest): 向量化回测循环` |
| `security` | 安全修复 | `security(api): 修复 JWT 密钥泄露` |

**Scope**:

| Scope | 对应 |
|-------|------|
| `strategy` | strategy-service |
| `execution` | execution-service |
| `ai-scheduler` | ai-scheduler |
| `k8s` | Kubernetes 配置 |
| `ci` | CI/CD 流水线 |
| `monitoring` | 监控/日志 |
| `docs` | 文档 |

---

## 9. 使用指南

### 9.1 快速启动

```bash
# 方式一：Docker Compose 一键启动（推荐）
docker compose --profile microservices --profile web --profile infra up -d

# 方式二：本地开发模式（仅启动 dependency）

# 启动策略服务
cd strategy-service && source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 启动前端（另一个终端）
cd dashboard && python3 -m http.server 3000

# 或使用 Nginx（推荐，自动代理 API + WebSocket）
brew install nginx
nginx -c /path/to/monitoring/nginx-local.conf
```

### 9.2 访问入口

| 服务 | URL | 说明 |
|------|-----|------|
| Dashboard | http://localhost:3000 | Web 前端 |
| Strategy API | http://localhost:8000/docs | Swagger 文档 |
| Execution API | http://localhost:8001/docs | Swagger 文档 |
| AI Scheduler | http://localhost:8002/docs | Swagger 文档 |
| Prometheus | http://localhost:9090 | 指标查询 |
| Grafana | http://localhost:3001 | 仪表盘（默认密码 admin） |
| Kibana | http://localhost:5601 | 日志搜索 |
| RabbitMQ | http://localhost:15672 | 消息队列管理（quant_user/quant_pass） |

### 9.3 调试常用命令

```bash
# 查看微服务日志
docker compose logs -f strategy-service

# 进入交互式检查
docker exec -it quant-strategy python -c "from shared.health import health; print(health())"

# 运行完整测试
make ci

# 运行单个服务测试
make test-strategy

# 部署前安全检查
make check-deploy

# 清理 Python 缓存
make clean
```

### 9.4 日常操作流程

**盘前准备**:
1. 确保所有服务运行正常（`make start`)
2. 检查数据源连通性（`curl localhost:8000/health`）
3. 查看 AI 选股结果（Dashboard → 选股报告）

**盘中监控**:
1. Dashboard 实时行情（指数每 3 秒自动刷新）
2. 关注 AI 信号推送（Dashboard → 策略管理）
3. 飞书告警监控交易执行状态

**盘后复盘**:
1. Dashboard → 复盘分析，查看 AI 日/周复盘
2. 策略效果评估（Dashboard → 回测分析）
3. 调整参数/策略（Dashboard → 策略管理）

---

## 10. 测试体系

### 10.1 测试覆盖范围

| 层级 | 位置 | 数量 | 说明 |
|------|------|------|------|
| 单元测试 | 各服务 `tests/` | 50+ 测试 | 核心业务逻辑全覆盖 |
| 合约测试 | `strategy-service/tests/contracts/` | 5+ 测试 | RiskController/CircuitBreaker 接口契约 |
| 集成测试 | `strategy-service/tests/` | 10+ 测试 | 数据库/外部服务集成 |
| 端到端测试 | `tests/test_e2e.py` | 5+ 测试 | 完整业务流程 |
| Quote Provider | `tests/test_quote_provider.py` | 专测 | 行情接口 96% 覆盖率 |

### 10.2 测试工具

| 工具 | 用途 |
|------|------|
| pytest | 测试框架 |
| pytest-cov | 覆盖率报告 |
| pytest-asyncio | 异步测试支持 |
| pytest-mock | Mock 支持 |
| pytest-xdist | 并行测试 |

### 10.3 覆盖率目标

| 服务 | 当前 | 目标 |
|------|------|------|
| strategy-service | ≥65% | ≥80% |
| execution-service | ≥65% | ≥80% |
| ai-scheduler | 100% | 维持 |
| shared | ≥30% | ≥50% |
| **合并** | **≥70%** | **≥80%** |

---

## 11. 监控与可观测性

### 11.1 Prometheus 指标

**策略服务**（20+ 指标）:

| 指标 | 类型 | 标签 |
|------|------|------|
| `trading_orders_total` | Counter | direction, status |
| `trading_positions_count` | Gauge | — |
| `trading_pnl_total` | Gauge | — |
| `trading_risk_events_total` | Counter | type, severity |
| `ai_calls_total` | Counter | model, agent |
| `ws_connections_active` | Gauge | — |

**执行服务**:

| 指标 | 类型 | 说明 |
|------|------|------|
| `orders_total` | Counter | 按方向/状态统计 |
| `positions_count` | Gauge | 当前持仓数 |
| `risk_events_total` | Counter | 风控事件 |
| `circuit_breaker_open` | Gauge | 熔断器状态 |

### 11.2 Grafana 仪表盘

| 仪表盘 | 内容 |
|--------|------|
| **Quant Trading Overview** | 交易信号、持仓、PnL、AI 调用 |
| **Trading Metrics** | 订单量、盈亏分布、风险事件 |
| **System Overview** | 服务健康、资源使用、延迟 |

### 11.3 ELK 日志栈

- **Logstash** 管道聚合所有微服务日志
- **Elasticsearch** 全文索引，7 天留存
- **Kibana** 日志搜索 + 可视化

### 11.4 告警体系

| 告警规则 | 级别 | 渠道 |
|----------|------|------|
| ServiceDown | 🔴 Critical | 飞书 → Alertmanager |
| ServiceFlapping | 🟡 Warning | 飞书 |
| HighErrorRate | 🟡 Warning | 飞书 |
| HighLatency | 🟡 Warning | 飞书 |
| SLO 违规 | 🟡 Warning | 飞书 |

---

## 12. 质量审计与优化历程

### 12.1 总体统计

| 任务 | 状态 | 数量 |
|------|------|------|
| 规划任务 | ✅ 全部完成 | 53 项 |
| P0 修复 | ✅ 全部完成 | 8 项 |
| P1 修复 | ✅ 全部完成 | 30 项 |
| CI 修复 | ✅ 全部通过 | ruff check + format 双绿 |

### 12.2 优化阶段

```
Phase 1: P0 硬伤修复（Dashboard 前/后端）
   ├── HTML 标签错配、脚本加载顺序
   ├── API 双前缀、服务响应格式不一致
   ├── 飞书 webhook 依赖、health API 返回值
   └── QTS 前端 UI 优化（中文标签/热图间距/双栏布局）

Phase 2: 架构重构
   ├── DataService → Repository 模式
   ├── QuoteProvider 抽象接口（tushare/tdx/akshare）
   ├── 统一异常/结构化日志
   ├── Execution 模块拆分
   └── shared 公共模块抽取

Phase 3: Dashboard 前端全面优化
   ├── Inter 字体 + design-tokens CSS 变量系统
   ├── 骨架屏、空状态、入场动画
   ├── 磁吸 hover 微交互
   ├── 11 种卡片统一 hover 动效
   └── 全线硬编码 hex 颜色清零

Phase 4: 测试增强
   ├── DataService 测试
   ├── Contract 测试（RiskController/CircuitBreaker）
   ├── Scheduler 弹性测试
   └── Pydantic v2 兼容修复

Phase 5: 安全加固
   ├── CSP Nonce 实现
   ├── Nginx 安全头检查（5 个头）
   ├── Bandit/Secret 扫描 CI
   └── 38 项安全修复

Phase 6: CI/CD 流水线
   ├── Makefile 25+ 目标
   ├── GitHub Actions 4 个工作流
   ├── ruff + mypy + bandit + gitleaks 工具链
   └── 构建产物同步验证
```

### 12.3 关键修复亮点

| 问题类型 | 修复措施 | 影响 |
|---------|---------|------|
| 硬编码颜色 | → CSS 变量 / `color-mix()` | 100+ 处 hex 清零 |
| 硬编码阴影 | → 主题自适应 `color-mix(in srgb, var(--color-XX))` | 所有卡片 hover 阴影可随主题自动切换 |
| 字体缺失 | → Inter + JetBrains Mono 全局注入 | 10 个 HTML 页面统一品牌字体 |
| 主题切换 | → Light/Dark/System 三模式 + CSP Nonce | 各浏览器/系统偏好完美适配 |
| 无数据状态 | → 骨架屏 + 空状态提示 | 各页面加载/空状态友好展示 |

---

## 13. 未来规划

### 13.1 短期（下一迭代）

| 事项 | 优先级 | 预估 |
|------|--------|------|
| 补充 `stock_insight_engine` 测试（当前 8% 覆盖率） | P1 | 4h |
| 补充 `scheduler_service` 测试（当前 13% 覆盖率） | P1 | 3h |
| 合并覆盖率提高到 ≥80% | P1 | 上述完成后 |
| Walk-Forward 回测报告样式优化 | P2 | 2h |
| 交易分析页面增加更多 ECharts 图表 | P2 | 3h |

### 13.2 中期

| 事项 | 说明 |
|------|------|
| 实盘交易上线 | MiniQMT 实盘 → 沙箱 → 真金交易 |
| 策略市场扩展 | 新增 5+ 策略模板，社区贡献机制 |
| 风险模型深化 | VaR、CVaR 风险度量，压力测试 |
| 多账户支持 | 模拟盘 + 实盘并行管理 |
| 港股/美股扩展 | 多市场覆盖 |

### 13.3 长期愿景

| 方向 | 目标 |
|------|------|
| 深度学习策略 | LSTM/Transformer 用于价格预测 |
| 强化学习 | RL 自动策略优化 |
| 社交情绪集成 | 雪球/微博/推特情绪因子 |
| 策略自动化 | 策略自发现、自适应参数 |
| 社区版 | 开源策略分享、回测结果公开 |

---

## 14. 附录

### A. 目录结构速查

```
QuantTradingSystem/
├── strategy-service/     # 策略研究服务（FastAPI）
│   ├── api/              # 路由（14模块，25+端点）
│   ├── core/             # 核心配置
│   ├── services/         # 业务逻辑（25+模块）
│   │   ├── multi_agent/  # AI 多智能体系统
│   │   ├── stock_insight_engine/  # 多因子选股
│   │   └── scheduler/    # APScheduler 调度器
│   ├── models/           # 数据模型
│   ├── repositories/     # 数据访问层（7 repo）
│   ├── tests/            # 测试
│   └── Dockerfile        # 多阶段构建
│
├── execution-service/    # 交易执行服务（FastAPI）
│   ├── api/              # 订单/持仓/风控路由
│   ├── services/         # 订单/持仓/风控/MiniQMT
│   └── tests/            # 测试（15+ 文件）
│
├── ai-scheduler/         # AI 调度服务（FastAPI）
│   ├── api/              # 调度/任务路由
│   ├── services/         # 调度/LLM/健康监控
│   └── tests/            # 9 个测试文件
│
├── shared/               # 公共模块（~3.8K 行）
│   ├── auth.py           # 认证
│   ├── health.py         # 健康探针
│   ├── middleware.py     # Trace ID + 脱敏
│   ├── rate_limiter.py   # 限流
│   ├── metrics.py        # 指标
│   ├── resilience.py     # 弹性模式
│   └── quote_provider/   # 行情提供商抽象
│
├── dashboard/            # Web 前端
│   ├── index.html        # 主入口（SPA）
│   ├── account.html      # 账户展示
│   ├── orders.html       # 交易下单
│   ├── backtest.html     # 回测分析
│   ├── strategies.html   # 策略管理
│   ├── trade-analysis.html # 交易分析
│   ├── review-analysis.html # 复盘分析
│   ├── stock-selection.html # 选股报告
│   ├── alerts.html       # 告警管理
│   ├── api-docs.html     # API 文档
│   ├── design-tokens.css # 设计令牌系统
│   ├── style.css         # 主样式（~2,300 行）
│   ├── app.js            # SPA 框架（~2,600 行）
│   ├── app.spa.js        # 页面脚本合集（~2,200 行）
│   └── build.sh          # 前端构建脚本
│
├── docs/                 # 文档
│   ├── ARCHITECTURE.md   # 架构文档
│   ├── ADR-*.md          # 架构决策记录（4 份）
│   ├── api-coverage.md   # API 覆盖
│   └── security-*        # 安全文档
│
├── k8s/                  # Kubernetes（21 YAML）
├── helm/                 # Helm Chart
├── monitoring/           # 监控配置
│   ├── prometheus.yml    # 抓取 + 告警规则
│   ├── alert_rules.yml   # 告警规则
│   ├── slo_alerts.yml    # SLO 告警
│   ├── grafana/          # Grafana 仪表盘
│   └── logstash/         # Logstash 管道
│
├── config/               # 基础设施配置
├── scripts/              # 运维/分析脚本
├── tests/                # E2E 测试
├── reports/              # 回测/混沌工程报告
├── data/                 # 数据目录
├── output/               # 输出目录
│
├── Makefile              # 25+ 自动化目标
├── docker-compose.yml    # 14 容器编排
├── pyproject.toml        # 统一依赖管理
├── ruff.toml             # Ruff 规则（50+）
└── .env.example          # 环境变量模板
```

### B. 技术栈清单

| 类别 | 技术 | 版本 |
|------|------|------|
| **后端框架** | FastAPI | ≥0.115.0 |
| **异步服务器** | Uvicorn | ≥0.34.0 |
| **数据库（关系）** | PostgreSQL + TimescaleDB | PG15 |
| **数据库（时序）** | QuestDB | latest |
| **缓存** | Redis | 7-alpine |
| **消息队列** | RabbitMQ | 3-management-alpine |
| **ORM** | SQLAlchemy (async) | ≥2.0.36 |
| **数据科学** | pandas / numpy / scikit-learn | latest |
| **技术指标** | TA-Lib / pandas_ta | ≥0.6.0 |
| **回测框架** | backtrader / vectorbt | ≥1.9.78 / ≥0.28.0 |
| **AI 模型** | OpenAI / Anthropic / DashScope SDK | multiple |
| **前端框架** | Vue 3 (CDN) | 3 |
| **图表** | ECharts | 5 |
| **容器编排** | Docker Compose + Kubernetes | — |
| **监控** | Prometheus + Grafana + ELK | latest |
| **CI/CD** | GitHub Actions | — |
| **代码质量** | ruff / mypy / pre-commit / bandit | latest |

### C. Prometheus 指标完整清单

```
# 策略服务
trading_orders_total{direction,status}
trading_positions_count
trading_pnl_total
trading_risk_events_total{type,severity}
ai_calls_total{model,agent}
ws_connections_active
http_requests_total{method,endpoint,status}
http_request_duration_seconds{method,endpoint}

# 执行服务
orders_total{direction,type,status}
orders_pending_count
positions_count
risk_events_total{type,severity}
circuit_breaker_open
miniqmt_connection_status

# AI 调度
scheduler_tasks_total{service,type}
task_duration_seconds
service_health_status{service}
service_uptime_seconds
feishu_alerts_total{level}
```

### D. 法律声明

> ⚠️ **风险提示**: 本系统仅供学习和研究使用。量化交易涉及重大风险，过往表现不代表未来收益。使用本系统进行实盘交易前，请确保:
> 1. 充分理解量化交易的风险
> 2. 已通过模拟盘充分验证策略
> 3. 设置合理的风控参数
> 4. 遵守相关法律法规

---

*本文档由 QTS 项目团队维护，最后更新于 2026-06-19。*
