# 🚑 QTS 运行手册（Runbook）

快速故障处理指南。遇到问题按优先级排查。

---

## 1. 服务启动失败

### 症状
- `docker-compose up` 后某容器反复重启
- `docker ps` 显示某容器为 `restarting`

### 排查步骤
```bash
# 查看容器日志
docker compose logs <service-name> --tail=50

# 常见原因
# - .venv 不存在 → 运行 make setup
# - 数据库未就绪 → 检查 postgres/redis 容器是否先启动
# - 端口冲突 → lsof -i :<port>
```

### 修复
```bash
# 重建服务
docker compose build <service-name>
docker compose up -d <service-name>

# 强制重启
docker compose restart <service-name>
```

---

## 2. 数据库连接失败

### 症状
- 日志显示 `could not connect to server`
- API 返回 503

### 排查
```bash
# 检查数据库容器
docker compose ps postgres redis questdb

# 测试连接
docker compose exec postgres pg_isready -U quant
```

### 修复
```bash
# 重启数据库
docker compose restart postgres

# 重建数据卷（⚠️ 会丢失数据！）
docker compose down -v && docker compose up -d postgres
```

---

## 3. Dashboard 页面加载空白

### 排查
```bash
# 检查 dist 是否最新
cd dashboard && bash build.sh

# 检查 Nginx 配置
docker compose logs dashboard

# 浏览器 F12 → Console/Network 查看具体错误
```

### 常见原因
- dist/ 被源码覆盖 → 重新执行 `build.sh`
- Nginx 配置错误 → 检查 `dashboard/nginx.conf`
- CSP 阻止内联脚本 → 检查浏览器 Console

---

## 4. 策略回测卡住

### 症状
- 回测长时间无进度
- API `/backtest/status` 返回 running 但不动

### 排查
```bash
# 查看 strategy-service 资源
docker stats strategy-service

# 查看队列积压
docker compose exec rabbitmq rabbitmqctl list_queues
```

### 修复
```bash
# 重启 strategy-service
docker compose restart strategy-service

# 清空回测队列（⚠️）
docker compose exec rabbitmq rabbitmqctl purge_queue backtest
```

---

## 5. AI 调度器响应超时

### 症状
- ai-scheduler 日志显示 `HTTP 429` 或 `timeout`
- 飞书无推送

### 排查
```bash
# 检查 API 配额
docker compose logs ai-scheduler --tail=30

# 检查 DeepSeek 余额
curl https://api.deepseek.com/dashboard/billing  # 需 API Key
```

### 应急
- 自动触发 Fallback 链（deepseek → catrouter）
- 如全部失败，降低任务并发数

---

## 6. 磁盘空间不足（< 500MB）

### 检查
```bash
# 查看 Docker 占用
docker system df

# 查看日志占用
du -sh logs/*

# 清理
docker system prune -af --volumes  # ⚠️ 会删除所有停止的容器
```

### 定期维护
```bash
make clean  # 清理构建缓存
```

---

## 7. CI 构建失败

### 常见原因
- lint 失败：`make lint` 本地先通过
- 测试失败：`make test` 本地先通过
- Gitleaks: 检查是否有 API Key 泄漏到 git

### 修复
```bash
# lint 自动修复
ruff check . --fix

# 重新提交
git add -A && /commit "fix: ..."
```

---

## 8. Flink/Streaming 服务异常

### 症状
- 实时计算延迟增加
- 数据积压

### 排查
```bash
# 检查 Flink 任务状态
docker compose exec flink-jobmanager flink list

# 查看积压
docker compose exec rabbitmq rabbitmqctl list_queues | grep realtime
```
