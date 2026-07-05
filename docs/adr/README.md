# 架构决策记录 (ADR)

本目录记录 QuantTradingSystem 项目的关键架构决策。每篇 ADR 遵循：

- **标题**: 简短描述决策内容
- **状态**: 已采纳 / 已提议 / 已废弃
- **日期**: 决策日期
- **背景**: 为什么需要做决策
- **决策**: 我们选择了什么
- **后果**: 正面和负面后果

| 编号 | 标题 | 状态 |
|------|------|:--:|
| [001](001-microservices-architecture.md) | 微服务架构选型 | ✅ 已采纳 |
| [002](002-fastapi-celery-choice.md) | FastAPI + Celery 技术栈 | ✅ 已采纳 |
| [003](003-miniqmt-selection.md) | MiniQMT 券商接口选型 | ✅ 已采纳 |
| [004](004-connector-staged-integration.md) | 连接器分阶段集成策略 | ✅ 已采纳 |
| [005](005-unified-dependency-management.md) | 统一依赖与锁文件管理 | ✅ 已采纳 |
| [006](006-dist-build-and-ci-gate.md) | Dashboard 构建流水线与 CI 门 | ✅ 已采纳 |
