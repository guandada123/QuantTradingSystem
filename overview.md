# 回测日报只跑1只股票(000001.SZ) 根因修复

## 问题现象
QTS 回测日报「股票综合排名」只有 000001.SZ 一只，其余 67 只全部缺失。

## 根因（3层）
1. **数据格式混用**：`daily_kline` 表 68 只股票里，1 只标准格式 `000001.SZ`，67 只非标格式 `SZ002636`/`SH603002`（前缀在前、无点号）
2. **代码解析 bug**：`fetch_kline_tencent` 对无点号码 `split(".")` 后整串当 suffix → 误判为北交所 `bj` → 拼出非法 URL `bjSZ002636` → 腾讯 API 请求失败 → 数据不足跳过
3. **SQLAlchemy 2.0 警告**（附带）：`_load_stock_pool_from_db` 裸 SQL 字符串抛异常 → 走兜底 `000001.SZ`

## 修复（A方案：代码层归一化，不动历史数据）
- `services/data_fetcher.py`：`fetch_kline_tencent` 加非标码归一化（`SZ002636`→`002636.SZ`）
- `services/report_service.py`：新增模块函数 `normalize_ts_code()`，`__init__` 和 `_load_stock_pool_from_db` 都过归一化
- `services/report_service.py`：SQL 用 `text()` 包裹，修复 SQLAlchemy 2.0 警告

## 验证结果
- DB 加载成功取到 **68 只**（不再走兜底），无点号残留 = 0
- 5 只非标码实测各拉到 **81 根 K 线**（至 2026-07-13），之前全失败的请求现在正常
- 腾讯 API URL 拼出 `sz002636`（正确）而非 `bjSZ002636`（非法）

## 下次回测日报
将自动扫描全部 68 只（归一化后），不再只有 000001.SZ。

## 补充：为什么只有 68 只（16:54 追问）
- `daily_kline` 本身是 **68 只小样本测试池**（2026-02-05 起，非全市场），不是数据缺失
- 真正全市场日线在 `daily_quote`（3521 只，2025-01-02 起，格式标准）和 `stock_pool`（3521 只）
- 进一步修复：`_load_stock_pool_from_db` 改为 **优先 `daily_quote`（全市场）> 回退 `daily_kline` > 兜底 000001.SZ`**
- 验证：回测池 **68 → 3495 只**（近 60 天有 ≥20 日数据的全市场标的），含茅台/海康，无格式残留
- 注：`daily_quote.trade_date` 是 date 类型，比较用 date 对象而非 isoformat 字符串

## 改动文件
- `/Users/guan/WorkBuddy/QuantTradingSystem/strategy-service/services/data_fetcher.py`
- `/Users/guan/WorkBuddy/QuantTradingSystem/strategy-service/services/report_service.py`
