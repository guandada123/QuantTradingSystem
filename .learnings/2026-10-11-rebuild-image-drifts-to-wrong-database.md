# ✅已升级(2026-10-11)→R70 —— 重建镜像 = 依赖漂移 → 静默降级 → **服务对着错误的库读写**（四层掩蔽）

**日期**：2026-10-11（全项目审计当日，重建 strategy 镜像后暴露）
**等级**：P0（服务实际读写 SQLite 而非生产 PG；健康检查/接口全部"正常"）
**类型**：silent-failure（依赖漂移 + 裸 except 降级 + 下游类型错）
**状态**：已修复（显式驱动 + 降级留证 + URL 归一化），并新增回归测试

---

## 1. 事故链（四层掩蔽，每层都"看起来正常"）

```
① 重建镜像：Dockerfile 用 pip 解析（非 uv.lock）
   → SQLAlchemy 由「2.x 早期」漂到 2.1.4
② SQLAlchemy 2.1 起 `postgresql://` 的默认 DBAPI = psycopg(v3)
   而镜像只装 psycopg2-binary → create_engine 抛 ModuleNotFoundError('psycopg')
③ 被 `except Exception:` 吞掉，只留一行「PostgreSQL不可用，回退到SQLite内存数据库」
   （连异常类型都不打）→ **服务从此对着 sqlite:///./quant_trading.db 读写**
④ 下游再崩一次：SELECT MAX(updated_at) 是 SQL 表达式，SQLAlchemy 不套用列类型
   → SQLite 的 TEXT 列返回 **str** → to_beijing(str) 抛
   「'str' object has no attribute 'tzinfo'」，被 run_loop 的 except 吞成每 5 分钟一条日志
```

**全程红灯只有一个**：一行与根因无关的 tzinfo 报错。容器 healthy、/health 200、接口可用。

## 2. 实测证据

- `docker exec quant-strategy python -c "create_engine(os.environ['DATABASE_URL'])"`
  → `ModuleNotFoundError: No module named 'psycopg'`（URL 是 `postgresql://…`）
- 驱动盘点：psycopg2 2.9.13 ✅ / psycopg(v3) ❌ / SQLAlchemy 2.1.4
- 回退后的自证：`_probe_latest` 报 `(sqlite3.OperationalError) no such table: minute_quote_metadata`
  —— 巡检在查 SQLite（生产数据全在 PG）
- 修复后：`daily_quote rows: 3149380`（PG）· data-quality 评分 100/100 / 通过 7/7

## 3. 判据

1. **显式声明外部依赖的具体实现**，不要依赖框架默认：
   `postgresql+psycopg2://` 优于 `postgresql://`（SQLAlchemy 2.1 改了默认）。
2. **降级必须留证**：`except Exception:` 后只报「不可用」= 把根因埋掉。
   至少 `exc_info=True` + `type(e).__name__`；能 fail-fast 就别降级
   （本例中「回退到另一个数据库」根本不是降级，是**换了一个事实来源**）。
3. **重建镜像属于高危操作**：健康检查只证明"进程活着"，必须另做
   **数据面验证**（"能否读到已知行数/已知表"），否则等于「容器健康 ≠ 可重新部署」的第二次兑现。
4. **构建应锁定依赖**：Dockerfile 用 pip 自由解析 → 每次重建都是一次未受控升级。

## 4. 同族

- 「容器健康 ≠ 可重新部署」（基础镜像/依赖刷新会引爆陈旧假设）
- 「框架级成功 ≠ 真实产出」（fallback 让框架"成功"，事实来源已错）
- 「本地全绿 ≠ CI 会绿」的镜像版：**旧镜像全绿 ≠ 重建后全绿**
