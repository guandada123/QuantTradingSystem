# ADR-001: 使用 pydantic-settings 统一配置管理

## 状态
已采纳（2026-06-12）

## 背景
QTS 项目配置分散在：
1. `.env` 文件（本地开发）
2. `k8s/configmap.yaml`（K8s 部署）
3. `docker-compose.yml` 环境变量（Docker 部署）

三处可能存在不同步，且 K8s Secrets 全部为空，生产部署会静默失败。

## 决策
1. **单一配置来源**：所有配置通过 `core/config.py` 的 pydantic-settings `Settings` 类加载
2. **启动时强制校验**：`validate_startup()` 方法在 lifespan 中调用，非空必填项被拒绝
3. **K8s Secrets 使用 Sealed Secrets**：加密后的 secret 提交 Git，集群内自动解密

## 后果
- 正向：启动时即可发现配置错误，不会静默失效
- 正向：三层配置合并逻辑清晰（代码默认 → .env → K8s env）
- 正向：Sealed Secrets 可安全提交到 Git
- 负向：需要运维在集群中安装 Sealed Secrets Controller

## 配置校验规则
- 至少一个 AI API 密钥不能为空
- 数据库密码不能为空
- 更多规则可在 `validate_startup()` 中添加
