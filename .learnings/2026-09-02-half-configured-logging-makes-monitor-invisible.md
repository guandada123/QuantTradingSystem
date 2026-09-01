# 日志只配了一半：structlog 可用时 INFO 级全部静默丢失

- **日期**：2026-09-02（统一巡检中枢 run#64）
- **等级**：P1
- **影响面**：`ai-scheduler` 服务 INFO 日志连续 **59 天零输出**；健康监控「是否还在跑」无法验证
- **状态**：已修复并部署（`shared/logging_config.py` + 7 条回归用例）

---

## 1. 现象

巡检中枢第 16 项全绿，但排查 `EXECUTION_SERVICE_URL` 散落问题时顺手看了一眼 `quant-ai-scheduler` 的日志，发现三件反常事：

| 观察 | 数字 |
|---|---|
| 容器日志总行数 | 28,955 行（横跨 06-26 → 09-02） |
| 业务 INFO 日志（启动横幅 / 调度 / 健康检查结果） | **0 条** |
| 业务 WARNING 日志（健康检查失败） | 37 条，**最后一条停在 2026-07-05T00:38Z** |
| uvicorn 访问日志 | 正常、实时 |

一个每 300 秒打一次汇总日志的健康监控，59 天里一条汇总都没有 —— 但同一批代码里的 WARNING 却能出来。

## 2. 根因

`shared/logging_config.py::configure_logging()` 有两个分支，**行为不对等**：

```python
try:
    import structlog
    structlog.configure(...)          # ← 只配「渲染器」
    # 没有 root handler，没有 root level
except ImportError:
    logging.setLoggerClass(_StructuredLogger)
    root.handlers.clear()
    root.addHandler(handler)          # ← 降级分支才配「输出通道」
    root.setLevel(INFO)
```

`structlog` **只负责把日志渲染成字符串**，真正写出去的仍是标准 logging。structlog 可用时 root 既无 handler 也无 level，于是：

> 业务 logger → propagate 到 root → root 无 handler → 落到 `logging.lastResort`（阈值 **WARNING**）→ **INFO 级全部丢弃**。

容器内实测（修复前）：`root.level = WARNING | handlers = []`。

**触发条件是纯依赖漂移**：`ai-scheduler` 容器装了 structlog 26.1.0，`strategy-service` / `execution-service` 没装。而 structlog **未在任何 requirements 中声明**，是传递依赖偶然装上的。

## 3. 真实后果（比数字难看严重得多）

1. **「装了监控」≠「看得见监控」**。HealthMonitor 实际一直在正常运行（修复后 16ms 内就打出 `健康检查结果: {...}`），但它的输出被吞了 59 天。本次排查为了确认「循环到底死没死」绕了很大一圈 —— 而答案一直都在，只是没人能看见。
2. **启动横幅消失** → 无法从日志确认服务重启过、配置是否生效（这次排查里我一度被「日志停在 07-05」误导，以为容器僵死）。
3. **WARNING 能出、INFO 不能出，是最坏的组合**：系统看起来「有日志、有监控」，故障时才出声，健康时完全静默 —— 恰好无法证明自己活着。

## 4. 修复

`shared/logging_config.py`：

- 抽出 `_install_root_handler(service_name, level, json_output)`，**structlog 分支与降级分支统一调用**
- 新增 `_PassthroughJsonFormatter`：structlog 已渲染成 JSON 的记录原样透传，避免「JSON 包 JSON」让 ELK 无法解析字段；原生 logging 记录照常 JSON 化
- 新增 `_ExcludeLoggerFilter`：挂在 handler 上跳过 `uvicorn*`（uvicorn 自带 handler，否则每条访问日志打印两遍）

> 为什么用 **handler Filter 而不是 `logger.propagate = False`**：uvicorn 启动时会执行 `logging.config.dictConfig()`，
> 而 `DictConfigurator.configure_logger()` 对未显式声明 `propagate` 的 logger **重置回 True**，
> 在 `configure_logging()` 里设的 propagate 会被覆盖掉。Filter 挂在 handler 上不受影响。

## 5. 验证（三层）

| 层 | 结果 |
|---|---|
| 容器内实测（structlog 26.1.0 分支） | `root.level = INFO / handlers=['StreamHandler']`，INFO 与 structlog INFO 全部可见，格式为单行 JSON 未二次编码，uvicorn 访问日志正常且无重复 |
| **反向验证** | 把 `_install_root_handler(...)` 换回 `pass` → 新增 3 个核心用例 + 2 个存量用例**共 5 个失败**，失败信息 `err='WARN-MUST-SURVIVE\n'` 正是旧行为走 `lastResort` 到 stderr 的铁证 |
| 生产重启验证 | 59 天来首次出现 `🤖 AI调度器启动中...` / `健康监控启动，检查间隔: 300秒` / **`健康检查结果: {'strategy-service': True, 'execution-service': True, 'ai-scheduler': True}`**（启动后 16ms） |

回归：`shared/` 318 passed（基线 311 + 新增 7，完全吻合）；ruff + ruff-format 全绿。

## 6. 待办（未擅自处理）

- structlog **仍未在任何 requirements 中声明**。修复后两个分支行为一致，风险已收敛；但「某个传递依赖装上了就换一条代码路径」这件事本身还在，建议显式声明或显式移除，把依赖变成决定而非巧合。
- `ai-scheduler/services/health_monitor.py::SERVICES` 仍是**硬编码类属性**，不读 `settings.STRATEGY_SERVICE_URL` / `EXECUTION_SERVICE_URL`。compose 下服务名恰好一致所以没爆；k8s configmap 里是 `*.quant-trading.svc.cluster.local:8001` → **部署到 k8s 必然全 DOWN**。属已知待办⑬。

---

## ★ 升级候选（复用写法）

1. **「配了日志」不等于「日志能出去」。日志链路 = 渲染器 + 输出通道，只配一半等于没配，且不会报错。** 验收要问「INFO 级能不能打到 stdout」，不是「有没有调用 configure」。
2. **一个模块有 structlog / 非 structlog 两条分支时，必须验证两条分支的输出行为一致。** 分支越多，未配对的那条越容易漏。判定标准：两个分支都跑同一组「level 可见性」断言。
3. **依赖漂移会静默改变代码路径。** structlog 没写进 requirements，装上就换分支。凡「try import X / except ImportError」型兼容代码，X 的存在与否是**运行时事实**而非**配置决定** —— 要么显式声明依赖，要么保证两条路径行为一致（本次选了后者）。
4. **`logging.lastResort` 是静默杀手**：root 无 handler 时它兜底，阈值 WARNING，输出到 stderr。表现是「WARNING 能出、INFO 不能出」——这种「部分可见」比全不可见更容易被误认为正常。
5. **判断「一个循环/监控是否还活着」，先确认它的输出通道是通的。** 本次为了确认 HealthMonitor 存活绕了一大圈，而它其实一直在跑 —— 输出被吞会让「健康的监控」和「死掉的监控」长得一模一样。
6. **能自我证明存活的系统才可信**：健康检查类组件必须留下「我跑过了」的痕迹（且该痕迹要能被看见），否则「静默」与「死亡」无法区分。
7. **改 `logger.propagate` 前先确认有没有 `dictConfig` 会重置它。** uvicorn 启动时必然重置。挂在 handler 上的 Filter 不受 dictConfig 影响，是更稳的位置。
8. **「日志停在某个日期」不等于服务死了。** 本次一度被「日志停在 07-05」误导；容器 Up 12 days 与日志停在 59 天前并存，是因为输出通道坏了而非进程停了。判定存活要用 API 探活，不要只用日志新鲜度。
