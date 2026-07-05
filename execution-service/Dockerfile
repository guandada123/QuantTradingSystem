# ═══════════════════════════════════════════════════════
# QuantTradingSystem — execution-service
# 构建命令: docker build -f execution-service/Dockerfile -t quant-execution .
# 构建上下文: 项目根目录（以支持 shared/ 包和 pyproject.toml）
# ═══════════════════════════════════════════════════════

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Step 1: 复制依赖配置（利用 Docker 多层缓存） ──
COPY pyproject.toml .

# ── Step 2: 复制 shared 包（作为 quant-trading-system 的子包安装） ──
COPY shared/ ./shared/

# ── Step 3: 安装项目依赖（仅 execution + shared，通过 pyproject.toml 统一管理） ──
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[execution,shared]"

# ── Step 4: 复制 execution-service 代码（最后一步，变更最频繁的层放最后） ──
COPY execution-service/ ./execution-service/

WORKDIR /app/execution-service

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

# 非 root 用户运行（安全加固）
RUN groupadd -r appuser && useradd -r -g appuser appuser && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
