# ═══════════════════════════════════════════════════════
# QuantTradingSystem — ai-scheduler
# 构建命令: docker build -f ai-scheduler/Dockerfile -t quant-ai-scheduler .
# 构建上下文: 项目根目录（以支持 shared/ 包和 pyproject.toml）
# ═══════════════════════════════════════════════════════

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Step 1: 复制依赖配置（利用 Docker 多层缓存） ──
COPY pyproject.toml .

# ── Step 2: 复制 shared 包（作为 quant-trading-system 的子包安装） ──
COPY shared/ ./shared/

# ── Step 3: 安装项目依赖（仅 ai-scheduler + shared，通过 pyproject.toml 统一管理） ──
# 依赖一致性校验（2026-10-11 加）：与 strategy-service 同一背景 ——
# 该服务同样用**不带版本**的 `pip install -e ".[extras]"`，重建时会自由解析最新依赖。
# （2026-10-11 实测：strategy-service 因此把 SQLAlchemy 漂到 2.1 → 服务静默改用 SQLite。）
# pip check 只能拦住"版本互相冲突"，拦不住"悄悄升级"；**根治办法是锁版本**
# （参见 strategy-service/requirements.pinned.txt 的做法：从已验证镜像导出 pinned 列表）。
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[ai-scheduler,shared]"
    && pip check

# ── Step 4: 复制 ai-scheduler 代码（最后一步，变更最频繁的层放最后） ──
COPY ai-scheduler/ ./ai-scheduler/

WORKDIR /app/ai-scheduler

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')"

# 非 root 用户运行（安全加固）
RUN groupadd -r appuser && useradd -r -g appuser appuser && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
