# VPB 量价事件突破策略 — 开发完成

## 策略概述

**VPB (Volume-Price Event Breakout)** 是一个全新的量价事件突破策略，填补了现有策略体系中事件驱动 + 形态识别突破的缺口。

## 核心架构：双阶段确认

```
           ┌──────────────┐     ┌──────────────┐
           │  Stage 1     │     │  Stage 2     │
 行情数据 →│  事件检测     │ →   │  突破确认     │ → 信号
           │  - 成交量爆发  │     │  - 价格突破   │
           │  - 波动率扩张  │     │  - RSI过滤   │
           │  - 跳空异动    │     │  - 量确认    │
           └──────────────┘     └──────────────┘
```

## 信号规则

| 条件 | 买入 | 卖出 |
|------|------|------|
| 事件 | 容量激增/波动率扩张/跳空 | — |
| 突破 | 价格突破前N日最高价 | 跌破前N日最低价 |
| 日内 | 收盘在当日区间上半部 | — |
| RSI | < 超买线, > 下限 | > 趋势退出线 + 破均线 |
| 量确认 | 突破日放量（可选） | — |
| 动态止损 | — | ATR × 倍数 |
| 超时 | — | 最大持有天数 |

## 与现有策略的差异

| 维度 | 现有策略 | VPB |
|------|---------|-----|
| 触发逻辑 | 纯价格/指标 | **事件先行**：只有"有事发生"才交易 |
| 突破确认 | N日高点/低点 | 双阶段 + RSI + 成交量三重过滤 |
| 退出机制 | 反向信号 | ATR动态跟踪止损 + 持有期限 + RSI衰竭 |
| 假突破防护 | 无 | confirm_bars 确认窗口 |

## 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `strategy-service/services/signals.py` | 新增 `_signal_vpb()` + 注册 `_SIGNAL_DISPATCH` + 路由扩展 |
| `strategy-service/services/param_grids.py` | 新增 VPB 参数搜索空间（15个参数） |
| `strategy-service/models/enums.py` | 新增 `VPB = "vpb"` + 补全缺失的 VWM/BBR/ADX/OBV/VBM |
| `strategy-service/api/backtest_v2.py` | 更新 docstring 策略列表 |
| `scripts/multi_strategy_backtest.py` | 新增 VPB 测试配置条目 |

## 参数搜索空间

详情见 `param_grids.py`，核心参数：
- `event_lookback`: 事件检测周期 (15/20/30)
- `vol_surge_mult`: 容量激增倍数 (1.3/1.5/2.0)
- `breakout_lookback`: 突破检测周期 (10/15/20)
- `confirm_bars`: 确认天数 (0/1/2)
- `max_hold_days`: 最长持有 (10/15/20)
- `atr_mult_stop`: ATR 止损倍数 (1.5/2.0/2.5)
