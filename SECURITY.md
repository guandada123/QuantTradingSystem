# Security Policy

## 历史凭据声明（Important）

本仓库的提交历史中**曾包含一个真实的 Tushare API Token**，位置：

```
data/fetch_data.py   行 26   提交 dff27b6f 及若干后续提交
```

泄漏形态为「环境变量默认值兜底」：

```python
os.environ.get("ts_token", "<真实 Token>")
```

它看起来像在正确使用环境变量，但把真值写成了 fallback，环境变量缺失时会静默使用硬编码值。

**该 Token 已于 2026-10-23 于 Tushare 个人中心重置，旧值已实测失效**（调用返回 `您的token不对，请确认`）。

因此：如果你在历史提交中看到这串字符，**它已经不能用于任何用途**，请勿尝试使用，也无需再做轮换。

> 为什么保留历史而不改写：仓库曾短暂处于 public 状态，改写历史无法收回已产生的副本，且需 force push 影响所有 clone。以「失效 + 显式声明」处理，风险等价而代价更低。

## 当前状态

| 项 | 状态 |
|---|---|
| 仓库可见性 | private |
| `.env` 等含凭据的文件 | `.gitignore` 排除，历史上从未提交 |
| `.env.example` | 仅占位符，与真实值无重合 |
| 凭据存储 | `.env` 权限 `600` |
| 密钥扫描 | `security-scan.yml` 的 `secret-scan` job（注意：该项为观测，不阻塞合并） |

## 报告漏洞

本仓库为个人项目，无公开漏洞奖励计划。如发现安全问题，请直接通过仓库所有者联系，**不要**提交公开 issue。

## 给未来维护者的三条

1. **判断凭据是否生效，不能只看接口是否返回数据。** 本项目有降级链，主源失败会自动换下一个源，功能看起来完全正常。要确认改的是哪条路径，看能区分路径的特征字段（如 Tushare 的 `ps_ttm` 有值，腾讯兜底恒为 `None`）。
2. **`docker restart` 不会重新读取 `.env`。** 环境变量在容器创建时注入，改配置后必须 `docker compose up -d --force-recreate <service>`。
3. **`except Exception` 会吞掉代码缺陷。** 降级链里已对 `AttributeError` / `NameError` / `UnboundLocalError` 做上抛处理（见 `data_service.py::PROGRAMMING_ERRORS`），新增类似的容错代码时请沿用这一约定。
