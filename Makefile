# QuantTradingSystem — Makefile
# ===============================
# 用法:
#   make test            — 运行所有服务测试
#   make test-strategy   — 仅运行 strategy-service 测试
#   make test-execution  — 仅运行 execution-service 测试
#   make test-scheduler  — 仅运行 ai-scheduler 测试
#   make test-coverage   — 运行所有测试 + 覆盖率报告
#   make lint            — ruff 代码检查
#   make lint-check      — ruff 格式检查 (只检查不修改)
#   make type-check      — mypy 类型检查
#   make security        — bandit 安全扫描
#   make fix             — ruff 自动修复代码 & 格式
#   make check-all       — 完整检查: lint → type-check → test → security
#   make test-contract   — 运行合约测试 (strategy-service)
#   make test-quote-provider — 运行行情提供商测试
#   make build           — 构建 dashboard 前端
#   make build-check     — 构建 + 验证 dist/ 与源码同步
#   make ci              — CI 流水线: lint → unit-test → contract-test → build
#   make install-deps    — 安装所有服务依赖
#   make install-dev     — 安装 dev 依赖 (ruff, mypy, bandit, pre-commit)
#   make precommit-install — 安装 pre-commit git hooks
#   make start           — 通过 docker-compose 启动所有服务
#   make clean           — 清理 .pyc / __pycache__ / .coverage
#   make help            — 列出所有目标
#
# 要求: macOS + zsh, 每个服务有独立的 .venv 虚拟环境

PROJECT_DIR := /Users/guan/WorkBuddy/QuantTradingSystem
SERVICES    := strategy-service execution-service ai-scheduler
PYTHON      := $(PROJECT_DIR)/.venv/bin/python

STRATEGY_PYTHON  := $(PROJECT_DIR)/strategy-service/.venv/bin/python
EXECUTION_PYTHON := $(PROJECT_DIR)/execution-service/.venv/bin/python
SCHEDULER_PYTHON := $(PROJECT_DIR)/ai-scheduler/.venv/bin/python

# 检查 dev 工具是否存在
RUFF     := $(PROJECT_DIR)/.venv/bin/ruff
MYPY     := $(PROJECT_DIR)/.venv/bin/mypy
BANDIT   := $(PROJECT_DIR)/.venv/bin/bandit
PRECOMMIT := $(PROJECT_DIR)/.venv/bin/pre-commit

.PHONY: test test-strategy test-execution test-scheduler test-coverage test-contract test-quote-provider build build-check ci lint lint-check type-check security security-headers-check fix check-all check-deploy install-deps install-dev precommit-install start clean help

# ─── 测试 ───────────────────────────────────────────────────────────────────────

test: test-strategy test-execution test-scheduler  ## 运行所有服务测试

test-strategy:  ## 运行 strategy-service 测试（跳过 test_quote_provider.py）
	cd $(PROJECT_DIR)/strategy-service && \
	$(STRATEGY_PYTHON) -m pytest tests/ -v --tb=short \
		--ignore=tests/test_quote_provider.py

test-execution:  ## 运行 execution-service 测试
	cd $(PROJECT_DIR)/execution-service && \
	$(EXECUTION_PYTHON) -m pytest tests/ -v --tb=short

test-scheduler:  ## 运行 ai-scheduler 测试
	cd $(PROJECT_DIR)/ai-scheduler && \
	$(SCHEDULER_PYTHON) -m pytest tests/ -v --tb=short

test-coverage:  ## 运行所有测试并生成合并覆盖率报告
	@cd $(PROJECT_DIR)/strategy-service && \
		$(STRATEGY_PYTHON) -m pytest tests/ -v --tb=short \
		--ignore=tests/test_quote_provider.py \
		--cov=. --cov-report=term-missing
	@cd $(PROJECT_DIR)/execution-service && \
		$(EXECUTION_PYTHON) -m pytest tests/ -v --tb=short \
		--cov=. --cov-report=term-missing
	@cd $(PROJECT_DIR)/ai-scheduler && \
		$(SCHEDULER_PYTHON) -m pytest tests/ -v --tb=short \
		--cov=. --cov-report=term-missing

test-contract:  ## 运行合约测试 (strategy-service contracts/)
	cd $(PROJECT_DIR)/strategy-service && \
	$(STRATEGY_PYTHON) -m pytest tests/contracts/ -v --tb=short

test-quote-provider:  ## 运行行情提供商测试
	cd $(PROJECT_DIR)/strategy-service && \
	$(STRATEGY_PYTHON) -m pytest tests/test_quote_provider.py -v --tb=short

# ─── 构建 ────────────────────────────────────────────────────────────────────────

build:  ## 构建 dashboard 前端 (build.sh)
	cd $(PROJECT_DIR)/dashboard && ./build.sh
	@echo "✅ dashboard build 完成"

build-check: build  ## 构建 + 验证 dist/ 与源码同步
	@cd $(PROJECT_DIR) && \
		git diff --stat -- dashboard/dist/ 2>/dev/null | grep -q . && \
		(echo "❌ dist/ 与源码不同步，请重新构建!" && exit 1) || \
		echo "✅ dist/ 与源码同步"

# ─── CI 流水线 ─────────────────────────────────────────────────────────────────

ci: lint lint-check test test-contract build  ## CI 流水线: lint → unit-test → contract-test → build
	@echo "🎉 CI 流水线全部通过"

# ─── 代码检查 ──────────────────────────────────────────────────────────────────

lint:  ## ruff 代码检查
	$(RUFF) check $(PROJECT_DIR)
	@echo "✅ ruff lint 通过"

lint-check:  ## ruff 格式检查 (只检查不修改)
	$(RUFF) format --check $(PROJECT_DIR)
	@echo "✅ ruff format 通过"

type-check:  ## mypy 类型检查（所有服务 + shared）
	$(MYPY) $(PROJECT_DIR)/strategy-service --strict --ignore-missing-imports --explicit-package-bases
	$(MYPY) $(PROJECT_DIR)/execution-service --strict --ignore-missing-imports --explicit-package-bases
	$(MYPY) $(PROJECT_DIR)/ai-scheduler --strict --ignore-missing-imports --explicit-package-bases
	$(MYPY) $(PROJECT_DIR)/shared --strict --ignore-missing-imports --explicit-package-bases
	@echo "✅ type-check 通过"

security:  ## bandit 安全扫描
	$(BANDIT) -c $(PROJECT_DIR)/pyproject.toml -r $(PROJECT_DIR)/strategy-service $(PROJECT_DIR)/execution-service $(PROJECT_DIR)/ai-scheduler
	@echo "✅ security 通过"

security-headers-check:  ## 验证 nginx.conf 包含必要的安全响应头
	@echo "=== 安全头检查 ==="
	@for nginx_conf in $(PROJECT_DIR)/monitoring/nginx.conf $(PROJECT_DIR)/dashboard/nginx.conf; do \
		echo "检查 $$nginx_conf ..."; \
		! grep -q "server_tokens off" $$nginx_conf && echo "❌ $$nginx_conf: 缺少 server_tokens off" && exit 1 || true; \
		! grep -q "X-Frame-Options" $$nginx_conf && echo "❌ $$nginx_conf: 缺少 X-Frame-Options" && exit 1 || true; \
		! grep -q "X-Content-Type-Options" $$nginx_conf && echo "❌ $$nginx_conf: 缺少 X-Content-Type-Options" && exit 1 || true; \
		! grep -q "Referrer-Policy" $$nginx_conf && echo "❌ $$nginx_conf: 缺少 Referrer-Policy" && exit 1 || true; \
		! grep -q "Permissions-Policy" $$nginx_conf && echo "❌ $$nginx_conf: 缺少 Permissions-Policy" && exit 1 || true; \
		! grep -q "Content-Security-Policy" $$nginx_conf && echo "❌ $$nginx_conf: 缺少 Content-Security-Policy" && exit 1 || true; \
		echo "  ✅ 安全头检查通过"; \
	done
	@echo "✅ 所有 nginx 安全头检查通过"

fix:  ## ruff 自动修复代码 & 格式
	$(RUFF) check --fix $(PROJECT_DIR)
	$(RUFF) format $(PROJECT_DIR)
	@echo "✅ fix 完成"

check-all: lint lint-check type-check test security security-headers-check  ## 完整检查: lint → type-check → test → security → headers
	@echo "🎉 check-all 全部通过"

# ─── 依赖管理 ──────────────────────────────────────────────────────────────────

install-deps:  ## 安装所有服务依赖
	@for svc in $(SERVICES); do \
		echo "==> 安装 $$svc 依赖..."; \
		cd $(PROJECT_DIR)/$$svc && .venv/bin/pip install -q -r requirements.txt; \
	done
	@echo "所有服务依赖安装完成。"

install-dev:  ## 安装 dev 依赖 (ruff, mypy, bandit, pre-commit)
	cd $(PROJECT_DIR) && $(PYTHON) -m pip install -e ".[dev]"
	@echo "✅ dev 依赖安装完成。"

precommit-install:  ## 安装 pre-commit git hooks
	$(PRECOMMIT) install
	@echo "✅ pre-commit hooks 已安装。"

# ─── 启动服务 ──────────────────────────────────────────────────────────────────

start:  ## 通过 docker-compose 启动所有服务
	cd $(PROJECT_DIR) && docker compose up -d
	@echo "等待服务就绪..."
	@sleep 15
	@for port in 8000 8001 8002 3000; do \
		curl -sf http://localhost:$$port/health > /dev/null 2>&1 \
			&& echo "  端口 $$port 就绪" \
			|| echo "  端口 $$port 未就绪"; \
	done

# ─── 清理 ──────────────────────────────────────────────────────────────────────

clean:  ## 清理 Python 缓存与覆盖率文件
	find $(PROJECT_DIR) -type f -name '*.pyc' -delete
	find $(PROJECT_DIR) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find $(PROJECT_DIR) -type f -name '.coverage' -delete
	find $(PROJECT_DIR) -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
	@echo "清理完成。"

# ─── 部署前检查 ──────────────────────────────────────────────────────────────────

check-deploy:  ## 部署前安全检查（密钥泄露 / 开发配置遗留）
	@echo "=== 部署前安全检查 ==="
	@! grep -r "dev-secret-change-in-production" $(PROJECT_DIR)/strategy-service \
		$(PROJECT_DIR)/execution-service $(PROJECT_DIR)/ai-scheduler \
		--include="*.py" 2>/dev/null && echo "✅ dev-secret 未在生产代码中出现" \
		|| (echo "❌ dev-secret 残留！禁止部署" && exit 1)
	@! grep -r "sk-" $(PROJECT_DIR)/shared --include="*.py" 2>/dev/null | grep -v "test_\|#\|os.environ\|getenv" && echo "✅ 无硬编码 API key" \
		|| (echo "❌ 检测到硬编码 API key！禁止部署" && exit 1)
	@! grep -r "CHANGE_ME\|your-" $(PROJECT_DIR)/k8s --include="*.yaml" 2>/dev/null && echo "✅ K8s 配置无占位符残留" \
		|| (echo "❌ K8s 配置有占位符未替换！" && exit 1)
	@echo "=== 部署前检查通过 ==="

# ─── 帮助 ──────────────────────────────────────────────────────────────────────

help:  ## 列出所有目标
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
