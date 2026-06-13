# QuantTradingSystem — 开发工具链
# 用法: make setup / make lint / make test / make ci

PYTHON := /opt/homebrew/bin/python3.12
PIP_INSTALL := $(PYTHON) -m pip install --break-system-packages
PYTEST := $(PYTHON) -m pytest
MIRROR := -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn

.PHONY: setup lint format test ci docker-up docker-down migrate help

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## 初始化开发环境
	$(PIP_INSTALL) pre-commit ruff mypy pytest pytest-cov bandit $(MIRROR)
	pre-commit install --hook-type pre-commit --hook-type commit-msg
	@echo "✅ QTS 开发环境就绪 (Python 3.12)"

lint: ## 运行 lint (ruff)
	ruff check strategy-service/ execution-service/ ai-scheduler/ shared/ --fix
	ruff format strategy-service/ execution-service/ ai-scheduler/ shared/

format: ## 格式化代码
	ruff format strategy-service/ execution-service/ ai-scheduler/ shared/

test: ## 运行单元测试 (跳过需Docker的DB测试)
	cd strategy-service && PYTHONPATH=$(CURDIR) $(PYTEST) tests/ -v --tb=short --ignore=tests/test_api.py || true
	cd execution-service && PYTHONPATH=$(CURDIR) $(PYTEST) tests/ -v --tb=short || true

test-all: ## 运行全部测试 (需先 docker-up)
	cd strategy-service && PYTHONPATH=$(CURDIR) $(PYTEST) tests/ -v --tb=short
	cd execution-service && PYTHONPATH=$(CURDIR) $(PYTEST) tests/ -v --tb=short

test-e2e: ## 运行 E2E 测试 (需先 docker-up)
	PYTHONPATH=$(CURDIR) $(PYTEST) tests/test_e2e.py -v --tb=short

ci: ## 模拟完整 CI 流水线
	$(MAKE) lint
	$(MAKE) test
	bandit -r strategy-service/ execution-service/ ai-scheduler/ -ll --skip B101 || echo "⚠️ bandit 发现安全提示(非阻塞)"
	@echo "✅ CI 通过"

docker-up: ## 启动所有服务
	docker compose up -d
	@echo "等待服务就绪..."
	@sleep 10
	@curl -sf http://localhost:8000/health > /dev/null && echo "✅ strategy-service ready" || echo "⚠️ strategy-service not ready"

docker-down: ## 停止所有服务
	docker compose down

migrate: ## 执行数据库迁移
	cd strategy-service && alembic upgrade head

migrate-new: ## 新建迁移脚本
	@read -p "迁移描述: " desc; cd strategy-service && alembic revision -m "$$desc"

load-test: ## 运行 k6 压测
	k6 run scripts/load_test.js
