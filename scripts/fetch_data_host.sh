#!/bin/bash
# fetch_data_host.sh — 在quant-strategy容器内执行数据拉取
# 用法: bash scripts/fetch_data_host.sh
# 由 Marvis Bridge 调度

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="quant-strategy"

# 检查容器是否运行
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "[ERROR] 容器 ${CONTAINER} 未运行"
    echo "请先启动: cd ${PROJECT_DIR} && docker compose up -d"
    exit 1
fi

echo "[$(date)] 在容器 ${CONTAINER} 中执行 fetch_data.py..."

docker exec ${CONTAINER} python3 /app/data/fetch_data.py

EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date)] ✅ 数据拉取成功"
else
    echo "[$(date)] ❌ 数据拉取失败 (exit=$EXIT_CODE)"
fi

exit $EXIT_CODE
