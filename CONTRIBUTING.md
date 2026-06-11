# 贡献指南 — QuantTradingSystem

> 团队协作规范 · 代码评审流程 · 分支策略

---

## 快速上手

```bash
# 1. 克隆仓库
git clone <repo-url>
cd QuantTradingSystem

# 2. 安装工具链
pip install -e ".[dev]"

# 3. 安装 pre-commit hooks（提交前自动检查）
pre-commit install

# 4. 运行完整检查
ruff check . && ruff format --check .
mypy strategy-service/ execution-service/ ai-scheduler/
pytest
```

---

## 分支策略

```
main          ← 生产就绪代码，受保护
  ├── develop ← 集成分支
  │   ├── feat/<name>      ← 新功能
  │   ├── fix/<issue-id>   ← Bug 修复
  │   ├── refactor/<name>  ← 重构
  │   └── docs/<name>      ← 文档
  └── release/vX.Y.Z      ← 发布分支
```

**规则**：
- `main` 分支禁止直接推送，必须通过 PR 合并
- 功能分支从 `develop` 切出，合并回 `develop`
- 上线时 `develop` → `main`（打 tag）
- 分支命名：`feat/`、`fix/`、`refactor/`、`docs/`、`test/`、`chore/`

---

## Git 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>(<scope>): <subject>

[optional body]
[optional footer]
```

**Type** 类型：

| Type | 含义 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(strategy): 添加双均线金叉策略` |
| `fix` | Bug 修复 | `fix(execution): 修复 MiniQMT 断连重试逻辑` |
| `refactor` | 重构（无功能变更） | `refactor(core): 提取公共数据模型到 shared 包` |
| `test` | 测试 | `test(ai-scheduler): 增加模型选择算法单元测试` |
| `docs` | 文档 | `docs(readme): 更新部署文档` |
| `chore` | 杂务（依赖、CI） | `chore(deps): 升级 FastAPI 到 0.115` |
| `perf` | 性能优化 | `perf(backtest): 向量化回测循环` |
| `security` | 安全修复 | `security(api): 修复 JWT 密钥泄露` |

**Scope** 范围：

| Scope | 对应服务/模块 |
|-------|-------------|
| `strategy` | strategy-service |
| `execution` | execution-service |
| `ai-scheduler` | ai-scheduler |
| `k8s` | Kubernetes 配置 |
| `ci` | CI/CD 流水线 |
| `monitoring` | 监控/日志 |
| `docs` | 文档 |

---

## 代码评审流程

### 提交 PR 前自查

在创建 PR 前，确认以下全部通过：

- [ ] `ruff check .` — 零 lint 错误
- [ ] `ruff format --check .` — 格式正确
- [ ] `mypy --strict <service>/` — 类型检查通过
- [ ] `pytest` — 所有测试通过
- [ ] 测试覆盖率 ≥ 80%（新增代码）
- [ ] 敏感信息无硬编码（密钥走环境变量 / K8s Secret）
- [ ] 错误处理完整（无裸 `except:`）

### 评审者检查清单

- [ ] 代码逻辑正确，无死代码
- [ ] 测试覆盖了 happy path + 边界 + 错误处理
- [ ] 类型注解完整（`mypy --strict` 通过）
- [ ] 错误信息清晰可操作
- [ ] 关键路径有结构化日志
- [ ] 无安全漏洞（`bandit` 通过）
- [ ] 文档同步更新

### 评审标准

| 严重度 | 含义 | 处理方式 |
|:--:|------|----------|
| 🔴 | 必须修改 | PR 不可合并，必须修复 |
| 🟡 | 建议修改 | 推荐修复，不阻塞合并 |
| 🟢 | 建议/好评 | 无需修改，仅供参考 |

---

## 代码规范

### Python

严格遵循 `ruff.toml` 中定义的规则集。核心要点：

```python
# ✅ 正确：有类型注解、有文档字符串、错误处理完整
from typing import Any

def calculate_position_size(
    capital: float,
    price: float,
    max_risk_pct: float = 0.05,
) -> int:
    """Calculate the maximum position size based on risk parameters.

    Args:
        capital: Available capital in CNY.
        price: Current stock price.
        max_risk_pct: Maximum risk per position as decimal (default 5%).

    Returns:
        Number of shares to buy.

    Raises:
        ValueError: If capital or price is non-positive.
    """
    if capital <= 0 or price <= 0:
        raise ValueError("Capital and price must be positive")
    max_loss = capital * max_risk_pct
    return int(max_loss / price // 100 * 100)  # Round to lot size


# ❌ 禁止：裸 except、无类型注解、无文档
def calc_pos(cap, prc):
    try:
        return int(cap * 0.05 / prc)
    except:
        return 0
```

### 禁止的代码模式

| 禁止 | 原因 | 正确做法 |
|------|------|----------|
| `except:` / `except Exception:` | 吞掉所有异常 | 指定具体异常类型 |
| `print()` 用于日志 | 无级别、无格式化 | `logger.info/warning/error` |
| 硬编码密钥/密码 | 安全风险 | 环境变量 / K8s Secret |
| 大段注释掉的代码 | 代码腐化 | Git 历史回溯 |
| `TODO` 无负责人/日期 | 永远不会做 | `# TODO(@name, 2026-06-15): ...` |
| `from module import *` | 命名空间污染 | 显式导入或用 `__all__` |

### 结构化日志规范

```python
import structlog

logger = structlog.get_logger(__name__)

# ✅ 使用结构化日志，携带上下文
logger.info(
    "order_placed",
    order_id=order.id,
    ts_code=order.ts_code,
    quantity=order.quantity,
    price=order.price,
    trace_id=request.headers.get("X-Trace-ID"),
)

# ❌ 不要用 f-string 做日志
logger.info(f"Order {order.id} placed")  # 无法按字段搜索
```

---

## 项目结构约定

```
QuantTradingSystem/
├── strategy-service/        # 策略研究服务
│   ├── api/                 # FastAPI 路由
│   ├── core/                # 核心业务逻辑
│   ├── services/            # 外部服务集成
│   ├── models/              # 数据模型 (Pydantic/ORM)
│   └── tests/               # 单元测试
├── execution-service/       # 交易执行服务
│   ├── api/
│   ├── core/
│   ├── services/
│   └── tests/
├── ai-scheduler/            # AI 模型调度
│   ├── api/
│   ├── core/
│   └── tests/
├── shared/                  # 跨服务共享代码
│   ├── models.py            # 共享数据模型
│   ├── exceptions.py        # 共享异常
│   └── utils.py             # 工具函数
├── monitoring/              # 监控配置
├── k8s/                     # Kubernetes 部署
├── tests/                   # 集成测试 / E2E 测试
└── docs/                    # 文档
```

### 添加新模块的步骤

1. 在对应服务的目录下创建 `core/your_module.py` 或 `api/your_module.py`
2. 创建 `tests/test_your_module.py`
3. 运行 `ruff check .` 和 `pytest` 确保通过
4. 如果新增了 API 路由，在 `api/__init__.py` 中注册
5. 如果新增了外部依赖，更新 `pyproject.toml`

---

## 常见问题

### Q: `mypy` 报类型错误但我确定代码是对的？

```python
# 如果确实是已知安全的操作，使用 # type: ignore[reason]
result = some_dynamic_call()  # type: ignore[no-untyped-call]  # 第三方库无 stubs
```

### Q: 测试中想绕过某些 ruff 规则？

在 `ruff.toml` 的 `[lint.per-file-ignores]` 中为 `tests/**/*.py` 配置例外。

### Q: 如何在本地运行整个 CI 流水线？

```bash
pre-commit run --all-files  # Lint + Format + Type Check + Security
pytest                      # Unit Tests
docker compose up -d        # Integration / E2E
pytest tests/test_e2e.py
```
