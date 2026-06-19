# QuantTradingSystem - A股量化交易系统

[![Test & Lint](https://github.com/guandada123/QuantTradingSystem/actions/workflows/test.yml/badge.svg)](https://github.com/guandada123/QuantTradingSystem/actions/workflows/test.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)]()

基于微服务架构的AI驱动A股量化交易系统，集成DeepSeek多智能体分析、Tushare实时行情、回测引擎和Web端仪表盘。

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│  QuantTradingSystem V2.0                            │
├─────────────────────────────────────────────────────┤
│  策略研究服务 (FastAPI)         交易执行服务          │
│  ├─ Tushare/AKShare数据源      ├─ MiniQMT接口       │
│  ├─ 5种回测策略                ├─ 订单管理           │
│  ├─ DeepSeek AI多智能体分析     └─ 风险控制           │
│  ├─ AI模型智能调度器                                 │
│  └─ WebSocket实时推送                                │
├─────────────────────────────────────────────────────┤
│  Web前端 (Vue3+ECharts+Nginx)                       │
│  ├─ 账户展示 / 交易分析 / AI选股 / 每日复盘          │
│  └─ 实时指数行情 (每3秒推送)                         │
├─────────────────────────────────────────────────────┤
│  基础设施 (Docker Compose)                          │
│  PostgreSQL/QuestDB/Redis/RabbitMQ/ELK/Prometheus   │
└─────────────────────────────────────────────────────┘
```

## 快速启动

### 策略服务（必须）
```bash
cd strategy-service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```
访问 http://localhost:8000/docs 查看API文档

### 前端（可选）
```bash
cd dashboard
python3 -m http.server 3000
```
访问 http://localhost:3000

### Nginx托管（推荐，需先安装nginx）
```bash
brew install nginx
nginx -c /path/to/monitoring/nginx-local.conf
```
访问 http://localhost:3000（自动代理API和WebSocket）

## 环境变量

复制 `.env.example` 为 `.env`，填入密钥：

| 变量 | 说明 | 获取地址 |
|------|------|---------|
| TUSHARE_TOKEN | A股行情数据 | https://tushare.pro |
| DEEPSEEK_API_KEY | AI分析模型 | https://platform.deepseek.com |
| FEISHU_WEBHOOK | 飞书告警通知 | 飞书群机器人 |

## API端点（共25个）

| 分组 | 端点 | 说明 |
|------|------|------|
| 📈 股票数据 | `GET /api/v1/stocks/realtime/{code}` | 个股实时行情 |
| | `GET /api/v1/stocks/index/realtime` | 指数实时行情 |
| 🤖 AI分析 | `POST /api/v1/ai/analyze/{ts_code}` | 多智能体分析 |
| | `POST /api/v1/ai/scan` | AI全市场选股 |
| | `GET /api/v1/ai/models` | AI模型列表 |
| 📊 回测 | `POST /api/v1/backtest/run` | 策略回测 |
| | `GET /api/v1/backtest/strategies` | 策略列表 |
| 💰 账户 | `GET /api/v1/account/summary` | 账户概要 |
| | `GET /api/v1/account/positions` | 持仓列表 |
| 📋 交易 | `GET /api/v1/trades/stats` | 交易统计 |
| 💬 WebSocket | `ws://localhost:8000/ws` | 实时行情推送 |

## AI模型调度

系统根据任务复杂度自动选择Flash或Pro模型，降低使用成本：

| 任务 | 模型 | 成本系数 |
|------|------|---------|
| 数据清洗/指标计算 | Deepseek-V4-Flash | 0.06x |
| 新闻情绪分析 | DeepSeek-V3.2 | 0.29x |
| 多智能体辩论/模式识别 | Deepseek-V4-Pro | 0.16x |
| 策略优化 | GLM-5.1 | 1.06x |

## 测试

```bash
cd strategy-service
pytest tests/ -v          # 50个测试用例
```

## 技术栈

- **后端**: Python 3.9+ / FastAPI / Uvicorn
- **数据**: Tushare / AKShare / 通达信
- **AI**: DeepSeek / Kimi / GLM / MiniMax
- **前端**: HTML5 / Vue3 / ECharts / WebSocket
- **部署**: Docker / Docker Compose / Nginx
- **监控**: Prometheus / Grafana / ELK Stack
