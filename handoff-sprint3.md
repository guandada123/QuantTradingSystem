# Sprint 2 → Sprint 3 交接文档

> 生成时间: 2026-06-16 22:19
> 项目: QuantTradingSystem (QTS v2.0)
> Git: 已推送至 GitHub

---

## ✅ Sprint 2 — 全部完成

| # | 任务 | 状态 |
|---|---|---|
| P1-ARCH-02 | 拆分 God Class (1098→778行) | ✅ |
| P2-PERF-03 | 引擎复用 + 缓存 TTL | ✅ |
| P2-PERF-05 | backtest_details JSON 压缩存储 | ✅ |
| P2-ARCH-05 | Walk-Forward 参数网格 API 化 | ✅ |
| P3-PERF-06 | 突破策略单调队列 O(n) 优化 | ✅ |
| Phase 5 | 精简 backtest_engine_v2.py 协调层 | ✅ |
| Phase 6 | 全量验证 | ✅ |

---

## 📊 当前项目状态

### 测试覆盖
- **strategy-service**: 233 tests / ~61% 覆盖
- **execution-service**: ~78% 覆盖
- **ai-scheduler**: ~97% 覆盖
- **全量 CI**: 75 K8s 资源 0 错误

### 架构现状

```
strategy-service/
├── api/backtest_v2.py        ← Walk-Forward API 化完成
├── services/
│   ├── backtest_engine_v2.py ← 778 行（精简后）
│   ├── signals.py            ← 单调队列 O(n) 优化完成
│   ├── performance_calc.py   ← 绩效计算（独立模块）
│   ├── trade_executor.py     ← 交易执行（独立模块）
│   ├── param_grids.py        ← 参数网格（独立模块）
│   └── indicators.py
├── repositories/
│   └── walkforward_repo.py   ← WF 结果持久化
├── models/models.py          ← WalkForwardResult ORM
└── tests/
    ├── test_backtest_engine_v2.py    ← 100 tests
    ├── test_backtest_api_v2.py       ← API 测试
    ├── test_backtest_repo_integration.py ← 持久化测试
    ├── test_repositories.py
    ├── test_backtest_integration.py
    └── test_backtest.py
```

---

## 🔴 待办清单（Sprint 3 候选）

### P0 — 阻塞项

| # | 问题 | 文件 | 说明 |
|---|---|---|---|
| 1 | **全量测试收集失败** | `tests/test_quote_provider.py` | `AKShareQuoteProvider` 已重构为工厂模式，测试未同步 |
| 2 | **全量测试收集失败** | `tests/test_miniqmt_connector.py` | 缺失 `connector` fixture |
| 3 | **WebSocket 测试挂起** | `tests/test_ws_handler.py` | 被动循环无异步测试框架 |
| 4 | **shared 导入歧义** | 顶层 + strategy-service 各有 `shared/` | 需统一 PYTHONPATH |

### P1 — 高优先级（God Class 候选）

| # | 文件 | 行数 | 优先级原因 |
|---|---|---|---|
| 5 | **`multi_agent.py`** | **32,511 行** | 最大单体文件，5 个 TODO 占位 |
| 6 | **`backtest_service.py`** | **25,342 行** | 代理密度高，大量业务逻辑内联 |
| 7 | **`stock_insight_engine.py`** | **25,772 行** | 未经过重构审计 |
| 8 | **`scheduler_service.py`** | **17,750 行** | 调度逻辑密集未拆分 |
| 9 | **`data_service.py`** | **20,376 行** | 数据服务层未审计 |

### P2 — 服务间协调

| # | 项目 | 说明 |
|---|---|---|
| 10 | **execution-service 系统性重构** | risk_controller/feishu_alert 未统一审计 |
| 11 | **服务间契约测试** | strategy↔execution↔scheduler API 兼容性无自动化 |
| 12 | **灾备** | PG 主从 / Redis Sentinel / 跨区域 — 全部 pending |

### P3 — 生产就绪

| # | 项目 | 来源 |
|---|---|---|
| 13 | MiniQMT 实盘对接 | production-readiness.md |
| 14 | Sealed Secrets / External Secrets | production-readiness.md |
| 15 | PodSecurityStandards restricted | production-readiness.md |
| 16 | OPA/Gatekeeper 准入控制 | production-readiness.md |
| 17 | 镜像签名 (Cosign) | production-readiness.md |
| 18 | 审计日志收集 | production-readiness.md |

### P4 — 前端/dashboard

| # | 项目 | 说明 |
|---|---|---|
| 19 | 8 个 HTML 页面 | 纯静态、无 SPA、有 .bak 残留 |
| 20 | 主题切换 | ❌ 无 light/dark |
| 21 | API URL 硬编码 | `localhost:8000` 多处 |
| 22 | Nginx 缓存策略 | 未优化 |

---

## 🎯 建议 Sprint 3 顺序

1. **修复 P0 测试收集错误**（半日）— `test_quote_provider.py` + `test_miniqmt_connector.py` + `test_ws_handler.py`
2. **`multi_agent.py` 拆分**（2日）— 32K 行最大单体
3. **`backtest_service.py` 精简**（1日）— 25K 行 God Class 候选
4. **服务间契约测试**（1日）— API 兼容性自动化
5. **前端现代化**（2日）— 主题切换、URL 动态化、CSP

---

## 🔧 测试运行命令

```bash
# 全量（注意 PYTHONPATH）
cd /Users/guan/WorkBuddy/QuantTradingSystem
PYTHONPATH="/Users/guan/WorkBuddy/QuantTradingSystem" \
/Users/guan/.workbuddy/binaries/python/envs/default/bin/python \
-m pytest strategy-service/tests/ -v --tb=no

# 引擎专项
PYTHONPATH="/Users/guan/WorkBuddy/QuantTradingSystem" \
/Users/guan/.workbuddy/binaries/python/envs/default/bin/python \
-m pytest strategy-service/tests/test_backtest_engine_v2.py -v

# 全量相关（跳过已知 P0 故障文件）
PYTHONPATH="/Users/guan/WorkBuddy/QuantTradingSystem" \
/Users/guan/.workbuddy/binaries/python/envs/default/bin/python \
-m pytest strategy-service/tests/test_backtest_engine_v2.py \
  strategy-service/tests/test_backtest.py \
  strategy-service/tests/test_backtest_api_v2.py \
  strategy-service/tests/test_repositories.py \
  strategy-service/tests/test_backtest_integration.py \
  strategy-service/tests/test_backtest_repo_integration.py -v
```
