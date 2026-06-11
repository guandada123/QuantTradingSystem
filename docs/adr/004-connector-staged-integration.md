# ADR-004: 连接器分阶段集成策略

**状态**: ✅ 已采纳  
**日期**: 2026-06-10  
**决策者**: QuantTradingSystem 团队

---

## 背景

MiniQMT (xtquant SDK) 的集成面临几个现实约束：

1. **环境依赖**: xtquant 需要同花顺 QMT 客户端已安装（仅 Windows），开发环境（macOS/Linux）无法直接运行
2. **开发效率**: 在真实 MiniQMT 环境下调试，每个周期包括：启动客户端 → 登录 → 下达测试订单 → 撤单 → 检查结果，约3-5分钟一轮
3. **风险控制**: 直接在实盘/MinQMT模拟盘上调试代码，可能产生意外的真实订单
4. **团队并行**: 多个开发者不能同时连接同一个 MiniQMT 实例

---

## 决策

**采用三阶段分步集成策略：**

```
Phase 1: 存根模式（开发期）
    Connector.simulate = True
    buy() → {"success": True, "order_id": "SIM_..."}
    └─ 所有操作返回模拟响应，不调用 xtquant

Phase 2: 本地对接（联调期）
    Connector.simulate = False
    buy() → xttrader.order_stock(...)
    └─ 在 Windows 开发机上连接 MiniQMT，验证 API 参数正确性

Phase 3: 生产运行（实盘期）
    Connector.simulate = False
    └─ 在 Windows 生产机上运行 execution-service，连接真实券商账户
```

### 存根模式设计

```python
class MiniQMTConnector:
    _SIMULATE_FLAG = True  # 默认模拟模式

    def __init__(self, simulate: bool | None = None):
        # 优先级：显式传入 > 类标志 > xtquant 是否可导入
        self._simulate = (
            simulate if simulate is not None
            else self._SIMULATE_FLAG
        )
        if not self._simulate:
            self._simulate = not self._can_import_xtquant()
```

**关键设计原则**:
- 存根与真实 API **接口完全一致**，Phase 1 的代码无需修改即可迁移到 Phase 3
- `health_check()` 方法区分 "simulate" / "live" 状态，监控系统可知当前模式
- 环境变量 `MINIQMT_SIMULATE=true` 强制模拟模式（CI/测试环境）

---

## 后果

### ✅ 正面

1. **团队并行开发不受限**: macOS/Linux 开发者无需 Windows 环境即可编写和测试交易逻辑
2. **零风险开发**: Phase 1 不会产生任何真实订单
3. **CI 可运行**: GitHub Actions (Ubuntu) 可运行完整的 MiniQMT 单元测试（32 个测试用例）
4. **平滑迁移**: 接口一致性保证 Phase 1→Phase 3 无需重构

### ❌ 负面

1. **存根覆盖率差距**: 存根返回固定响应，无法模拟 xtquant 的真实错误场景（如网络超时、订单拒绝）
2. **集成测试延迟**: 真实 MiniQMT 的边界行为（如部分成交、市场关闭拒绝订单）只能在 Phase 2 测试
3. **两套代码路径的心理模型**: 开发者需要理解 simulate/live 两种模式的差异

### ⚖️ 权衡

直接写真实 xtquant 对接代码（跳过 Phase 1）是可行的，但会阻塞非 Windows 环境开发者的工作。
三阶段策略增加 20% 的代码量（存根逻辑），但换来了团队并行开发能力。

---

## 当前阶段

**Phase 2 (本地对接)** — v2 connector 已实现完整的 xtquant 集成代码。

| 操作 | 状态 |
|------|:--:|
| connect() / disconnect() | ✅ |
| buy() / sell() | ✅ |
| cancel_order() | ✅ |
| get_positions() | ✅ |
| get_account_info() | ✅ |
| get_orders() | ✅ |
| 回调驱动状态追踪 (_TradingCallback) | ✅ |
| 模拟模式优雅降级 | ✅ |
| async context manager | ✅ |
| 单元测试 (32 cases) | ✅ |

**待 Phase 3**: Windows 生产机上已安装 QMT 客户端，运行 `export MINIQMT_SIMULATE=false` 后启动 execution-service。

---

## 参考

- xtquant SDK 文档: [http://dict.thinktrader.net/nativeApi/xtquant.html](http://dict.thinktrader.net/nativeApi/xtquant.html)
- MiniQMT Connector 代码: `execution-service/services/miniqmt_connector.py`
- MiniQMT 测试: `execution-service/tests/test_miniqmt_connector.py`
