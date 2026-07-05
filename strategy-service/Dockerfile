# ═══════════════════════════════════════════════════════
# QuantTradingSystem — strategy-service
# Multi-stage build: ~60% smaller image, faster deploys
# ═══════════════════════════════════════════════════════

# ──── Stage 1: Builder ────
FROM python:3.12-slim AS builder

WORKDIR /build

# 安装编译工具（仅在 builder 中使用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make curl \
    && rm -rf /var/lib/apt/lists/*

# ═══════════════════════════════════════════════════════
# TA-Lib C library — 架构自动检测（同时支持 amd64 / arm64 / i386）
# ═══════════════════════════════════════════════════════
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
        amd64)  URL="https://github.com/TA-Lib/ta-lib/releases/download/v0.6.4/ta-lib_0.6.4_amd64.deb" ;; \
        arm64)  URL="https://github.com/TA-Lib/ta-lib/releases/download/v0.6.4/ta-lib_0.6.4_arm64.deb" ;; \
        i386)   URL="https://github.com/TA-Lib/ta-lib/releases/download/v0.6.4/ta-lib_0.6.4_i386.deb" ;; \
        *)      echo "Unsupported architecture: $ARCH" && exit 1 ;; \
    esac && \
    echo "Detected arch: $ARCH, downloading TA-Lib from: $URL" && \
    curl -fsSL "$URL" -o /tmp/ta-lib.deb && \
    dpkg -i /tmp/ta-lib.deb && \
    rm -f /tmp/ta-lib.deb && \
    ldconfig

# 提取 TA-Lib 共享库（创建下划线 symlink 兼容链接器）
RUN mkdir -p /ta-lib-output && \
    for f in /usr/lib/libta-lib*; do \
        if [ -e "$f" ]; then \
            base=$(basename "$f" | sed 's/libta-lib/libta_lib/'); \
            ln -sf "$f" "/usr/lib/$base"; \
            cp -P "/usr/lib/$base" /ta-lib-output/; \
        fi; \
    done && \
    ldconfig && \
    echo "=== TA-Lib libs ===" && ls -la /ta-lib-output/

# 安装 Python 依赖到虚拟环境（便于整体拷贝）
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ta-lib Python 包需 numpy 1.x
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple 'numpy==1.26.2' \
    && pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple setuptools wheel \
    && CFLAGS="-Wno-error=incompatible-pointer-types" pip install --no-cache-dir --no-build-isolation -i https://pypi.tuna.tsinghua.edu.cn/simple 'ta-lib==0.4.28'

# 安装业务依赖（全量 strategy+shared，来自 pyproject.toml）
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    fastapi uvicorn pydantic pydantic-settings \
    sqlalchemy asyncpg redis psycopg2-binary \
    pymongo pandas numpy requests python-multipart apscheduler httpx \
    prometheus-client websockets python-jose aiohttp \
    python-dotenv cachetools scikit-learn openai anthropic \
    backtrader akshare tushare quantstats vectorbt pandas-ta technical \
    dashscope pyyaml


# ──── Stage 2: Runtime ────
FROM python:3.12-slim AS runtime

WORKDIR /app

# 仅安装运行时系统库（无编译工具）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 拷贝 TA-Lib 共享库（自动适配架构）
COPY --from=builder /ta-lib-output/* /usr/lib/
RUN ldconfig

# 从 builder 拷贝完整的 Python 虚拟环境
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 拷贝源码（最后一步，变更最频繁的层放最后）
COPY . .

# 非 root 用户运行（安全加固）
RUN useradd --create-home --no-log-init appuser
USER appuser

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
