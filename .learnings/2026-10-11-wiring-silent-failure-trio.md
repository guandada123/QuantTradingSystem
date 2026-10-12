# ✅已升级(2026-10-11)→R75 —— 接线类静默失效三连 —— 对象式 import / 字段名不存在 / 无认证端口

**日期**：2026-10-11（全项目审计）
**等级**：P1（功能从未执行、数据恒为 0、暴露面静默存在）
**类型**：silent-failure（接线错误三种典型形态）
**状态**：均已修复

---

## 形态一：对象式 import 一个**函数式仓库** → 功能从未执行

```python
# 修复前（jobs.py）
from repositories.account_repo import account_repo   # ← 模块里根本没有这个名字
positions = account_repo.get_positions()
```
`repositories/account_repo.py` 导出的是**函数** `get_positions(db, account_id)`。
结果：每个交易日 15:30 都 ImportError → 记一条 warning 后 `return` →
**AI 复盘自上线起从未真正执行过**。

> 🔴 同期证据：测试里有两例专门写 `_ar_mod.account_repo = mock_repo  # 绕开 import bug`
> —— **测试绕开了缺陷，就等于把缺陷冻结成契约**。修源码时必须同步迁移这些测试。

## 形态二：字段名不存在 → 数据恒为 0（无异常、无告警）

```python
p.get('pnl_pct', 0) * 100     # ← get_positions 返回的是 profit_loss_ratio
```
`dict.get(k, 0)` 对不存在的键**静默返回默认值** → 报告里每只股票盈亏都显示 `0.0%`。
> 判据：凡 `dict.get` 取**跨模块契约字段**，须对照产出方的真实键名；
> 消费端应 fail-loud（缺键即报错/告警），而不是给个「看起来正常」的 0。

## 形态三：端口绑定 0.0.0.0 + 无认证 = 暴露面静默存在

Redis（`requirepass` 空、`protected-mode no`）、PG 15432、QuestDB、RabbitMQ 全部
绑全接口。容器健康、CI 绿、没人报错 —— 直到有人问「这个端口谁能连」。

修复：13 处基础设施/监控端口统一收窄到 `127.0.0.1`（应用端口按需保留），
并在 docker-compose.yml 头部写下**端口绑定纪律**：
远程访问走 SSH 隧道 / Tailscale，禁止改回 0.0.0.0。

## 推广判据（三问）

1. **导入的东西真的存在吗？** 跨模块 import 的符号名须有测试或类型检查兜底
   ——「历史遗留注释写着"可能已废弃"」不是不查的理由。
2. **取的字段真的存在吗？** `dict.get` 默认值只能用于**可缺失字段**，
   契约字段缺失必须 fail-loud。
3. **这个端口/服务真的需要对外吗？** 默认最小暴露：基础设施一律回环，
   要远程就显式加隧道，让暴露成为**决定**而不是**默认**。
