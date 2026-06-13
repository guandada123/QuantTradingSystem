# Changelog

## [2026-06-13] Phase 11: CI 修复 + 开发工具链完善

### pyproject.toml 修复
- `[dependency-groups]` → `[project.optional-dependencies]`
- 修复 `pip install -e ".[strategy,...]"` 在标准 pip 下的兼容性

### CI
- shared/ 已纳入 test matrix 和 type-check (已在之前版本配置)

### 开发体验
- Makefile: 添加 test-cov/type-check 目标
- README: 添加 CI badge

## [2026-06-13] 全维度代码质量优化

### 安全加固
- ES xpack.security.enabled + 密码保护
- Grafana 默认密码 → 环境变量 ${GRAFANA_ADMIN_PASSWORD}
- 数据库/RabbitMQ 密码 → 环境变量化
- .env.example 提供安全默认值

### 共享模块 (shared/)
- risk_config.py: 15个风控参数统一 dataclass + 环境变量覆盖
- logging_config.py: structlog 结构化日志 + 请求追踪
- rate_limiter.py: 令牌桶限流 (按IP/白名单/429+Retry-After)
- health.py: /health + /ready 标准化探针 (K8s/Docker适配)
- graceful_shutdown.py: SIGTERM排空 + 清理回调 + K8s preStop
- metrics.py: Prometheus /metrics (Counter/Histogram/Gauge) + 自动采集中间件

### 数据库迁移
- Alembic 框架引入 (alembic.ini + env.py)
- 3个迁移版本 (001基线 + 002_v2.1 + 003_v2.2) + 回滚支持
- models/migration.py 标记 DEPRECATED

### Docker
- strategy-service/Dockerfile: 多阶段构建 (builder → runtime)
- 镜像体积 -60%, 非root用户, HEALTHCHECK 30s间隔

### 质量基础设施
- ruff 格式化 (89文件)
- pre-commit hooks (ruff + conventional commits)
- Dependabot 依赖自动更新

### 测试
- 74个测试通过 (strategy-service 单元 + 集成)
- test_quote_provider: 96% 覆盖率
- test_ai_scheduler: 100% 覆盖率

### 开发体验
- Makefile: make setup/lint/test/ci/migrate/docker-up/load-test
- Python 3.12 标准化
