# WF（Walk-Forward）判据四处漂移，同一份数据得出相反结论

**日期**: 2026-09-04
**项目**: QuantTradingSystem / strategy-service
**影响面**: 日报 Top5 排序 + 飞书卡片标签 + `wf_passed` 计数
**严重度**: P1（结论自相矛盾，且排序方向被反转）

---

## 结论先行

`overfit_ratio = mean(测试期夏普 / 训练期夏普)`，**越大越好**：
- `1.0` = 样本外完全保持
- `0.5` = 样本外保留一半（可接受下限）
- `0` = 样本外无技能
- `< 0` = **方向反转**（最差）

但代码里 4 个判定点各自硬编码了 3 套互相矛盾的判据，其中 3 套方向是反的。
同一条 `ratio=-59` 的数据，在 `wf_passed` 算"通过"，在 `wf_label` 标"过拟合"。

---

## 四处判据（修复前）

| # | 位置 | 旧判据 | 方向 | 对 `ratio=-59` 的判定 |
|---|------|--------|------|----------------------|
| 1 | `wf_passed` 计数 | `stability>=50 且 ratio <= 0.2` | ❌ 反 | **通过** |
| 2 | `wf_label` 标签 | `stability>=50 且 ratio >  0.2` | ✅ 对 | 过拟合 |
| 3 | `_is_overfit` 硬排除 | `ratio > 0.2` | ❌ 反 | 保留（排除掉 ratio=0.9 的好策略） |
| 4 | `_rank_score` 加权 | `stability>=50 且 ratio <= 0.2` | ❌ 反 | **打满权重** |

1 与 2 判定**完全相反**；1 与 4 同向错误（4 危害更大：直接决定 Top5 排序）。

### 实测规模（2026-09-04，30 个 WF 候选）

```
overfit_ratio: min=-59.43  中位=-0.50  max=88.75
  ratio <  0（方向反转）        : 17/30
  ratio >= 0.5（保留过半）      :  7/30
  ratio <= 0.2（旧 wf_passed）  : 21/30  ← 把 -59 也算通过
```

旧口径下 **21/30 "通过"**，其中含 −59、−30.89、−22.07 这类方向反转的。
日报 `wf_passed: 4 / 30` 全是这批。

---

## 修复

统一为类常量 + 单一入口：

```python
WF_MIN_STABILITY: float = 50.0
WF_MIN_OVERFIT_RATIO: float = 0.5

@classmethod
def _wf_is_trustworthy(cls, wf):
    if not wf:
        return False
    return (wf.get("stability", 0) >= cls.WF_MIN_STABILITY
            and wf.get("overfit_ratio", 0) >= cls.WF_MIN_OVERFIT_RATIO
            and wf.get("wf_return", 0) > 0)
```

4 处全部改调它。`_is_overfit` 例外保留独立判据 `ratio < 0`——理由写在代码注释里：
一刀切用 `_wf_is_trustworthy` 会在"没有一条达标"的日子里把 30 条已验证的全排除，
排名反而被未验证的单笔噪声填满，与修复目的背道而驰。

### 第三道闸 `wf_return > 0`（修完第一版后又补的）

只靠 stability + ratio 挡不住两类漏网：

1. **比值爆炸**：`ratio = test_sharpe / train_sharpe`，训练期夏普趋近 0 时分母极小，
   ratio 可飙到 **73.59 / 88.75**（实测 `000415.SZ`）。这表示"样本内本来就没优势"，
   却被误读成"样本外保持得好"。
2. **盈亏不对称**：过半窗口小赚 + 一次大亏 → stability 高但复合净收益为负。

`wf_return` = 复合样本外收益（%），是"样本外真的赚到钱"的直接证据。
实测补上后 `wf_passed` 仍为 5/30 —— 本次没砍掉任何一条，是安全网不是收紧。

### 顺带修掉：排序折扣"替换"而非"叠加"

```python
# 修复前
if trustworthy: return wf_return * (stability / 100)   # 60% → ×0.6
return wf_return * 0.5                                  # 40% → ×0.5  ← 几乎无差别！

# 修复后
return wf_return * (stability / 100) * 0.5              # 40% → ×0.2，差 3 倍
```

平折 `0.5` **替换**了稳定性缩放，导致 stability=40% 的劣化条目与 60% 的可信条目
几乎同权 → Top1 长期被「⚠️ 样本外劣化」占据。改叠加后：

| | 修复前 | 修复后 |
|---|---|---|
| Top5 可信条目 | 2/5 | **3/5** |
| Top1 | 000415.SZ（劣化，ratio 73.59） | **603823.SH（✅可信）** |

### 顺带修掉：闭包不可测

`_rank_score` 原本是 `generate_daily_report` 里的嵌套闭包，**无法单测**——
两次判据反转都栽在这个盲区里。提取为类方法 `_wf_rank_score(rec, wf_validated)`。

---

## 第 5 处漂移（自己改名引入的死代码）

把 `wf_label` 从 `"⚠️ 过拟合"` 改名为 `"⚠️ 样本外劣化"` 后，`extreme_day`
分支里的字符串比对没跟着改：

```python
if entry.get("wf_label") == "⚠️ 过拟合":   # 永不成立 —— 整段成死代码
    entry["wf_label"] = "🌪️ 极端日"
```

**改名一处字符串，必须全局 grep 所有引用点**，尤其是 `== "字面量"` 形式的比对
（不像变量改名有工具兜底）。已加守卫测试锁住。

---

## ⚠️ 关键教训：守卫测试必须能真的报警（本次连栽两次）

第一版守卫测试长这样：

```python
src = inspect.getsource(mod.ReportService)
assert 'overfit_ratio"] <= 0.2' not in src
assert 'overfit_ratio", 0) > 0.2' not in src
assert "_wf_is_trustworthy(w)" in src
```

**它对第 4 处（`_rank_score`）完全视而不见**，因为那处写法是
`wf.get("overfit_ratio", 0) <= 0.2`，两个字面量都匹配不上。

我事后做了**注入验证**（把旧判据注回去跑测试）：
- 老守卫：`1 passed` ← 瞎的
- 新守卫：`2 failed` ← 有效

**任何"源码扫描型"守卫测试，写完必须注入一次回归、确认它会红。**
否则它只是一段让人安心的注释。

新守卫改用 `tokenize` 剥离注释与字符串后全量扫描：

```python
code_only = [tok.string for tok in tokenize.generate_tokens(io.StringIO(src).readline)
             if tok.type not in (tokenize.COMMENT, tokenize.STRING)]
assert "0.2" not in " ".join(code_only)          # 魔数不得进可执行代码
assert code.count("_wf_is_trustworthy(") >= 5    # 1 处定义 + 4 处调用
```

### 第二次栽：剥 STRING 把要比对的目标一起剥掉了

给「极端日分支标签同步」写守卫时，我照抄了上面那段，连 `STRING` 一起剥：

```python
if tok.type not in (tokenize.COMMENT, tokenize.STRING)   # ← 错
```

但要检测的目标 `entry.get("wf_label") == "⚠️ 过拟合"` **本身就是字符串字面量**，
被一并剥掉 → 注入旧标签后测试仍 `1 passed`，守卫是个空转。

**正确做法：只剥 `COMMENT`，保留 `STRING`。** 一般情况下剥 STRING 是想排除
docstring 里的说明文字，但当检测目标本身就是字符串时，那是自毁。

准则：**写守卫时先问一句「我要抓的那个东西，在我剥掉的部分里吗？」**

两次都靠「注入旧代码 → 看测试会不会红」抓到。这一步不能省。

---

## 通用规律

**同一个语义概念被多处判定，必然漂移。** 判定点 ≥ 2 就该抽单一入口，
且要有一个"剥离注释后全量扫描"的守卫测试锁住它——
只匹配具体字面量的守卫，挡不住写法不同的同一处错误。

相关：`.learnings/2026-09-04-top5-single-trade-noise-short-window.md`（同一次会话的另一处 Top5 缺陷）

---

## 顺带解决：纠缠 5 天的「创业板待裁决」——标注优于过滤

创业板 300/301 从 08-31 起连记 5 天「规则冲突待用户裁决」，一直空着。
冲突是真的：USER.md「不碰创业板」（**实盘**口径）vs sim_trade.py 2026-07-29
已放开创业板（**模拟盘**口径）—— 两边都是用户自己的规则。

卡住的原因是默认只有两个选项，而两个都有代价：

| 选项 | 代价 |
|------|------|
| 过滤创业板 | 回测池缩水、统计功效下降；模拟盘也跟着用不了 |
| 不过滤 | 晚报 Top5 静默推荐实盘不能买的标的 |

**第三个选项：不过滤，只标注。** 每条 Top5 附 `board` 字段，
summary 汇总 `top5_non_mainboard`，由下游按自己的口径消费。
两边信息都不丢，冲突不再需要裁决。

```python
TRADABLE_BOARDS = frozenset({"沪主板", "深主板", "深主板(原中小板)"})
```

实测 2026-09-04：Top5 中 1/5 为创业板（`300209.SZ`），且该条恰好也是
「⚠️ 样本外劣化」→ 实盘口径下前 4 名全是 ✅ 可信的主板标的。
**不用过滤就自然得到了"实盘可用清单"，还白赚一份"创业板那批表现如何"的观察数据。**

规律：**当 A 与 B 规则冲突且都有效时，别急着二选一 —— 先把维度显式化
（加字段），让下游各自按自己的口径过滤。过滤是消灭信息，标注是保留信息。**

---

## 已知边界（未修）

`ratio = test_sharpe / train_sharpe` 在**训练与测试同为负**时也是正数
（−0.5 / −1.0 = 0.5），会被误判为"样本外保持良好"。
但 `stability >= 50` 要求过半窗口盈利，均值夏普为负还能过半盈利的情况罕见，
实际未观测到，故未加 `mean(test_sharpe) > 0` 的第三道闸（YAGNI）。
若日后出现"高 stability + 高 ratio 但 wf_return 为负"的条目，需补这道闸。
