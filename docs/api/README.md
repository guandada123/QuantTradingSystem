# QuantTradingSystem — 统一 API 文档

## 文件结构
```
docs/api/
  ├── index.html                  # 聚合门户，含 3 个 swagger-ui 实例
  ├── strategy-service.json       # 策略研究服务 OpenAPI 3.0 (46 端点)
  ├── execution-service.json      # 交易执行服务 OpenAPI 3.0 (23 端点)
  └── ai-scheduler.json           # AI 调度器 OpenAPI 3.0 (10 端点)

dashboard/api-docs.html           # 前端已有 swagger-ui 页面（增强后支持静态回退）

scripts/generate_openapi_specs.py # 自动从运行服务拉取 spec
```

## 3 服务路由统计

| 服务 | 版本 | 端点 | 模块 | 标签 |
|------|------|:----:|:----:|------|
| strategy-service | 2.0.0 | 46 | 11 | 股票/信号/回测/AI/账户/交易/调度/策略/执行/配置 |
| execution-service | 1.1.0 | 23 | 3 | 订单/持仓/风控 |
| ai-scheduler | 1.0.0 | 10 | 1 | 系统/调度任务 |
| **合计** | — | **79** | **15** | |

## 访问方式

### 本地 Nginx 开发模式
打开浏览器访问 `http://localhost:3000/api-docs.html`

### Docker 环境
```bash
docker-compose up -d dashboard
```
然后访问 `http://localhost:3000/api-docs.html`

### 静态文件浏览
直接用浏览器打开 `docs/api/index.html` 即可离线查看所有 API 文档。

## 更新 specs（微服务 API 变更后）
```bash
# 自动从运行中的 3 个服务拉取最新 OpenAPI 规范
python3 scripts/generate_openapi_specs.py
```
