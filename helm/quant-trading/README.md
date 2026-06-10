# QuantTradingSystem Helm Chart

## 快速开始

```bash
# 开发环境安装
helm install quant-trading ./helm/quant-trading \
  -f helm/quant-trading/ci/values-dev.yaml \
  --set secrets.deepseekApiKey=sk-xxx \
  --set secrets.feishuWebhook=https://open.feishu.cn/...

# 生产环境安装
helm install quant-trading ./helm/quant-trading \
  -f helm/quant-trading/ci/values-prod.yaml \
  --set secrets.deepseekApiKey=sk-xxx \
  --set ingress.host=quant.example.com

# 升级
helm upgrade quant-trading ./helm/quant-trading

# 卸载
helm uninstall quant-trading

# 渲染模板（调试）
helm template quant-trading ./helm/quant-trading -f helm/quant-trading/ci/values-dev.yaml
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `global.environment` | 部署环境 | `dev` |
| `global.imageRegistry` | 镜像仓库 | `ghcr.io/quant-trading` |
| `strategyService.replicas` | 策略服务副本数 | `2` |
| `executionService.replicas` | 执行服务副本数 | `2` |
| `aiScheduler.replicas` | AI调度器副本数 | `2` |
| `secrets.*` | API 密钥等敏感配置 | 空（部署时注入） |

## 环境覆盖

- `values.yaml` — 默认值
- `ci/values-dev.yaml` — 开发环境（降低资源、关闭 ELK）
- `ci/values-prod.yaml` — 生产环境（高可用、TLS）

## 包含资源

- Namespace + RBAC (ServiceAccount, Role, RoleBinding)
- ConfigMap + Secret
- 微服务: strategy-service, execution-service, ai-scheduler (Deployment + Service + HPA + PDB)
- Dashboard (Nginx + 静态前端)
- 基础设施: PostgreSQL, Redis, RabbitMQ
- 监控: Prometheus, Grafana
- 网络: Ingress + NetworkPolicy (Zero-Trust)
- 资源管控: ResourceQuota + LimitRange
