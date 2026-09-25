# 配置写了三处，代码一处都不读 —— 「配置被无视」比「配置写错」更隐蔽

- 日期：2026-09-02（统一巡检中枢 run#65）
- 级别：P1（潜伏；当前 Docker 环境下因数值巧合而未暴露）
- 状态：已修复并部署（QTS `78c89058`，未 push）
- 影响面：`ai-scheduler` 健康监控；同型风险面覆盖**所有「有配置项但代码没读」的地方**

## 现象

`HealthMonitor.SERVICES` 硬编码三个探测地址：

```python
SERVICES = {
    "strategy-service":  "http://strategy-service:8000/health",
    "execution-service": "http://execution-service:8001/health",
    "ai-scheduler":      "http://localhost:8002/health",
}
```

而 `STRATEGY_SERVICE_URL` / `EXECUTION_SERVICE_URL` 在**三处**被显式配置：

| 配置源 | 值 |
|--------|-----|
| `docker-compose.yml`（ai-scheduler env） | `http://strategy-service:8000` |
| `k8s/configmap.yaml:42-43` | `http://strategy-service.quant-trading.svc.cluster.local:8000` |
| `helm/.../configmap.yaml:32-33` | 由 `serviceUrl` helper 生成 |

**三处配置，代码一处都不读。**

## 取证：金丝雀实验（这是本次定位的关键动作）

```bash
docker exec -e STRATEGY_SERVICE_URL=http://CANARY-SHOULD-BE-READ:9999 ... python -c "
  print(settings.STRATEGY_SERVICE_URL)          # http://CANARY-SHOULD-BE-READ:9999  ← 读到了
  print(HealthMonitor.SERVICES['strategy-service'])  # http://strategy-service:8000 ← 没跟
"
```

`settings` 读到了、组件没跟 → **配置被无视**，不是配置没注入。
这一步把「是不是 compose 没传变量」这类猜测一次性排除。

## 为什么一直没暴露

Docker 下硬编码值与 compose 注入值**恰好相同**，功能正常。
k8s 下短服务名经 search domain（`ndots:5`）也能解析，同样正常。

→ 它是**纯潜伏缺陷**：只要不改名、不换命名空间、不改用 FQDN，就永远不发病。

## 真实代价（不是"难看"，是"误导排查"）

一旦环境变化导致地址不匹配：
- 监控探测错误地址 → 持续判定 DOWN
- `HealthAlertService.send_service_down` → **每 5 分钟推一次飞书**
- 运维第一反应是去改 `EXECUTION_SERVICE_URL` 配置 → **改了没用**
- 于是要么误判成"服务真挂了"，要么误判成"配置不生效的 bug"，都查不到根因

**「改配置不生效」是运维最绝望的故障形态之一**，而它的成因往往就是根本没人读那个配置。

## 修复

```python
_SERVICE_URL_SETTINGS = {
    "strategy-service": "STRATEGY_SERVICE_URL",
    "execution-service": "EXECUTION_SERVICE_URL",
}

def _resolve_services(self) -> dict[str, str]:
    resolved = dict(self.SERVICES)          # 兜底默认值
    for name, attr in self._SERVICE_URL_SETTINGS.items():
        base = getattr(settings, attr, None)
        if base:
            resolved[name] = str(base).rstrip("/") + "/health"
    return resolved
```

`check_all()` 改用 `_resolve_services()`。保留 `SERVICES` 作为默认值注册表（兼容既有测试）。
`ai-scheduler` 自探测走容器回环，**不参与配置覆盖**——改名不会把自己的探测改坏。

## 验证

- 新增 5 用例；全量 **258 passed**
- **反向验证**（还原成无视配置的旧行为）→ **3 例失败**，证明测试有效非恒真
- 生产容器内金丝雀复验：注入 CANARY → 跟随配置（修复前恒为 False）
- 实测三服务均 `True`；重启后健康监控 300s 循环正常输出，401 锚点未移动

## ✅已升级(2026-09-06)（7 条）

1. **★ 「有配置项」不等于「配置项被读取」** —— 验收标准不是"配置写了"，
   而是"改配置后行为变了"。金丝雀实验（注入一个不可能的值，看组件跟不跟）
   是验证这一点最快的方法，10 秒出结果。
2. **★ 数值巧合会掩盖结构性缺陷** —— 硬编码与配置恰好相等时，
   系统表现完全正常，缺陷要等到环境变化才发病，届时排查成本极高。
   判断标准：**改一下配置，看有没有任何变化**。
3. **★ 「改配置不生效」优先怀疑代码根本没读** —— 而不是怀疑注入链路、
   环境变量优先级、pydantic 加载顺序。先做金丝雀实验，5 分钟定性。
4. **★ 同一个值在 N 处各写一遍，必有某处不读它** ——
   （run#62 已立过此条，本次是它的镜像面：上次是"各处写法不一致"，这次是"各处都写了但没人读"）
5. **★ 自探测地址不要纳入配置覆盖** —— 组件探测自己时，用回环地址最稳；
   让它跟随外部服务命名，等于给自己增加一个无谓的故障面。
6. **★ 默认值注册表与运行时解析要分开** —— 直接把 `SERVICES` 当运行值用，
   就会失去"配置优先"的能力；保留它做兜底、另加解析函数，改动小且向后兼容。
7. **★ 潜伏缺陷也值得修** —— 它当前不发病，但发病时必然在最坏的时机
   （环境迁移 / 故障排查中），且会主动误导排查方向。

## 关联

- 与 run#58 / run#62「跨容器探测写死 localhost」是同一族：那两次是**地址写错**，
  这次是**地址没读**。三者的共同根因是「服务地址无单一真源」。
- 全仓扫描结果：服务地址共 **6 处取值点 / 4 种解析方式**
  （`settings.*` / `os.getenv` / 硬编码字面量 / 模块级 `getattr` 冻结常量），
  默认值重复 5 遍。**本次只修了 ai-scheduler 一处，其余 5 处未动**，列为待办。
