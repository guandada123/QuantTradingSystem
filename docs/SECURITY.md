# QTS 安全漏洞跟踪

> 最后更新: 2026-06-12

## 扫描配置

```bash
safety check --full-report
pip-audit
bandit -c pyproject.toml -r strategy-service/ execution-service/ ai-scheduler/
```

## 已知风险类别

### 高优先级（需立即修复）

| # | 组件 | 风险 | 修复方案 |
|---|------|------|----------|
| 1 | `celery<5.4.0` | CVE-2024-xxxx 任务注入 | 升级 `celery>=5.4.0` ✅ 已处理 |
| 2 | `tushare` HTTP 明文 | 数据传输未加密 | 仅用于公开行情数据，无需修复 |
| 3 | `akshare` 依赖链 | 东方财富非官方API | 已添加断路器+降级保护 ✅ |

### 中优先级（按计划修复）

| # | 组件 | 风险 | 计划 |
|---|------|------|------|
| 4 | `aio-pika<9.5.0` | RabbitMQ 连接未TLS | 添加 `amqps://` 支持 |
| 5 | `python-jose` 仓库 | jose→jwcrypto迁移中 | 监控迁移进度，适时切换 |

### 已缓解

| # | 措施 | 缓解效果 |
|---|------|----------|
| 1 | pyproject.toml 版本上限 `"<N.0"` | 防止意外升级到破坏性主版本 |
| 2 | shared/resilience.py 断路器 | 外部API故障隔离 |
| 3 | K8s NetworkPolicy | Pod间最小权限通信 |
| 4 | nginx CSP + HSTS 框架 | XSS/XSRF攻击面最小化 |
| 5 | JWT `python-jose[cryptography]` | 强加密后端（非pycrypto） |

## 审计频率

- **每周**: `safety check` 自动扫描（`.github/workflows/security-scan.yml`）
- **每月**: 人工审查 `bandit` 报告 + Secret 扫描
- **每次部署**: 安全检查清单（`best-practices/security-checklist.md`）
