# VPB v2.2 退出机制优化 + Walk-Forward 参数验证 完成报告

## 完成内容

### A) 退出机制优化（`signals.py`）

**核心问题**：VPB 胜率不错（40-50%）但盈亏比 < 1.0 → 平均亏损 > 平均盈利 → 总收益为负

**根因**：原版 ATR 固定止损基于入场价，不随价格上涨上移 → 盈利单回吐变亏损

**修复方案**（退出优先级从高到低）：
1. **固定止盈**（`take_profit_pct=15%`）— 达到目标即锁定利润
2. **最高点回撤止损**（`trailing_stop_pct=6%`）— 从持仓期间最高价偏移 6% 退出，锁定纸面利润
3. **ATR 硬止损**（保留）— 防跳空/极端波动，作为地板保护
4. **趋势反转**（保留）— 跌破前 N 日最低价
5. **最大持有天数**（保留）
6. **RSI 动量衰竭**（保留）

### B) Walk-Forward 参数验证

在 600570.SH 和 600519.SH 上运行 Walk-Forward 分析（126天训练/42天测试/42天步长），搜参范围包括 5 个关键参数（324组合）。

**关键发现**：
- 参数偏好跨窗口一致性高 → 低过拟合（ω=0.80）
- 最优参数偏好：4% trailing / 10% take profit / 最短 breakout lookback（10天）
- 但过紧参数（4% trail）在高波动标的（恒生电子）上表现不佳

**最终推荐**：6% trail + 15% take profit（平衡稳健，3/3 标的改善）

## 回测对比结果

| 标的 | 旧退出 | 新退出(v2.2) | 改善 |
|------|--------|-------------|------|
| 贵州茅台 | -5.18% (0.31) | **+0.13%** (1.08) | **+5.31pp** ✅ |
| 恒生电子 | -3.45% (0.68) | **+1.45%** (1.19) | **+4.90pp** ✅ |
| 五粮液 | -4.14% (0.17) | -2.70% (0.35) | +1.44pp 🟡 |

## 修改的文件

| 文件 | 变更 |
|------|------|
| `strategy-service/services/signals.py` | 退出逻辑重构：trailing stop + take profit + ATR硬止损 |
| `strategy-service/services/param_grids.py` | vpb 参数网格扩展（3个新参数） |
| `scripts/multi_strategy_backtest.py` | VPB 默认参数更新 |

## 新增文件

| 文件 | 用途 |
|------|------|
| `scripts/vpb_exit_comparison.py` | 旧退出 vs 新退出的 4 配置 × 4 标的对比 |
| `scripts/vpb_optimized_verification.py` | Walk-Forward 参数验证 |
| `scripts/vpb_final_recommendation.py` | 最终推荐参数验证 |
