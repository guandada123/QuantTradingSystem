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
# 2026-10-11 收尾：改为 **pip constraints 锁版本** ——
#   `constraints.txt` 由"已验证镜像的 pip freeze"导出，`-c` 只约束版本、不新增依赖；
#   解析冲突会**直接构建失败**（好过像 strategy 那样静默漂移到另一个数据库）。
#   ⚠️ 同时修掉上一版引入的语法错误：`&& pip check` 原先换行但**缺续行符 `\\`**，
#      会被 Dockerfile 解析成未知指令 → 该镜像当时根本无法构建。
COPY ai-scheduler/constraints.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
        -c constraints.txt -e ".[ai-scheduler,shared]" \
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
