"""
Tushare Pro 行情数据提供者
"""

import logging
import math
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from shared.quote_provider.base import (
    QuoteProvider,
    RateLimitError,
    is_systemic_error,
)

logger = logging.getLogger(__name__)

TUSHARE_SINGLE_REQUEST_LIMIT = 6000
FUNDAMENTAL_WINDOW_DAYS = 10
FUNDAMENTAL_CACHE_TTL_SECONDS = 3600
# 2026-10-23：容量上限。缓存为模块级 dict、只写不清，接口接受任意 ts_code，
# 异常调用可使其无界增长。超限时按插入顺序淘汰最早的四分之一。
FUNDAMENTAL_CACHE_MAX = 8192
# daily_basic 在交易日 15:00–17:00 更新；该窗口内缓存易命中「更新前」的旧值，
# 故缩短有效期（1h → 5min），避免一次数据刷新被缓存掩盖。
FUNDAMENTAL_REFRESH_HOURS = (15, 17)
FUNDAMENTAL_CACHE_TTL_IN_REFRESH = 300

# 2026-10-28 修复（CI 首暴）：上面的「15:00–17:00」指的是**交易所本地时间（北京时间）**，
# 但原实现用 `datetime.now().hour` —— 取的是**容器本地时区**。生产/CI 容器 TZ=UTC，
# 于是窗口实际落在 UTC 15:00–17:00 = 北京 23:00–次日 01:00：
#   · 真正的收盘刷新窗口（北京 15–17 点）反而走 1h 长 TTL，缓存会掩盖当天新数据；
#   · 半夜 23–01 点却被缩短到 5 分钟，纯浪费请求。
# 与 `shared/trading_calendar.py` 的 CN_TZ 同一口径，不用裸 now()。
CN_TZ = ZoneInfo("Asia/Shanghai")


def _market_hour() -> int:
    """当前**交易所**小时（北京时区）。判定与交易日相关的时刻一律走这里，不用裸 now()。"""
    return datetime.now(CN_TZ).hour


_FUNDAMENTAL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _fundamental_cache_ttl() -> int:
    """按**交易所时区**当前时刻返回缓存有效期（秒）"""
    hour = _market_hour()
    start, end = FUNDAMENTAL_REFRESH_HOURS
    return (
        FUNDAMENTAL_CACHE_TTL_IN_REFRESH if start <= hour < end else FUNDAMENTAL_CACHE_TTL_SECONDS
    )


def _evict_if_full() -> None:
    """容量超限时淘汰最早插入的四分之一（dict 保持插入顺序）"""
    if len(_FUNDAMENTAL_CACHE) < FUNDAMENTAL_CACHE_MAX:
        return
    for _ in range(max(FUNDAMENTAL_CACHE_MAX // 4, 1)):
        if not _FUNDAMENTAL_CACHE:
            return
        _FUNDAMENTAL_CACHE.pop(next(iter(_FUNDAMENTAL_CACHE)), None)


def _safe_float(value: Any):
    """空值/NaN → None。

    2026-10-23：Tushare 对亏损股的 pe_ttm 返回空值，此前 `float(None)` 抛 TypeError
    被 except 吞掉，导致整条记录丢弃 —— 实测 2026-10-22 有 1632/5570 只（29%）受影响，
    它们的 PB/PS/市值都是有效值却拿不到。改为逐字段降级为 None。
    """
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(num) else num


class TushareQuoteProvider(QuoteProvider):
    """基于 Tushare Pro API 的实现"""

    INDEX_MAP = {
        "000001.SH": "上证指数",
        "399001.SZ": "深证成指",
        "399006.SZ": "创业板指",
        "000688.SH": "科创50",
        "899050.BJ": "北证50",
        "000300.SH": "沪深300",
        "000905.SH": "中证500",
        "000852.SH": "中证1000",
    }

    STOCK_NAMES = {
        "600519.SH": "贵州茅台",
        "000858.SZ": "五粮液",
        "000001.SZ": "平安银行",
        "600036.SH": "招商银行",
        "601318.SH": "中国平安",
        "000333.SZ": "美的集团",
    }

    def __init__(self, token: str | None = None):
        self._pro = None
        self._token = token
        if token:
            self._init_tushare()

    def _init_tushare(self):
        """初始化 Tushare Pro"""
        import os as _os

        try:
            import tushare as ts

            if self._token:
                _os.environ["TUSHARE_TOKEN_PATH"] = _os.path.join(
                    _os.path.dirname(_os.path.dirname(__file__)), ".tushare_token"
                )
                try:
                    ts.set_token(self._token)
                    self._pro = ts.pro_api()
                except PermissionError:
                    self._pro = ts.pro_api(self._token)
                logger.info("TushareQuoteProvider: 初始化完成")
            else:
                logger.warning("TushareQuoteProvider: 未提供 Token")
        except ImportError:
            logger.error("TushareQuoteProvider: tushare 未安装")

    # ---- 实时行情 ----

    def get_realtime_quote(self, ts_code: str) -> dict[str, Any]:
        if not self._pro:
            return self._empty_quote(ts_code)
        try:
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
            df = self._pro.daily(ts_code=ts_code, start_date=start, end_date=end)
            if df.empty:
                return self._empty_quote(ts_code)
            row = df.iloc[0]
            return {
                "ts_code": ts_code,
                "name": self._get_name(ts_code),
                "price": float(row["close"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "pre_close": float(row["pre_close"]),
                "change": float(row["change"]),
                "pct_change": float(row["pct_chg"]),
                "volume": int(row["vol"]),
                "amount": float(row["amount"]),
                "trade_date": row["trade_date"],
                "timestamp": datetime.now().isoformat(),
                "source": "tushare",
            }
        except Exception as e:
            logger.error(f"Tushare 获取 {ts_code} 行情失败: {e}")
            # 系统性错误（限频/网络不通）上抛，让降级链冷却本源而非逐只重试
            if is_systemic_error(e):
                raise
            return self._empty_quote(ts_code)

    def get_batch_realtime(self, ts_codes: list[str]) -> list[dict[str, Any]]:
        return [self.get_realtime_quote(c) for c in ts_codes]

    def get_index_realtime(self, index_codes: list[str] | None = None) -> list[dict[str, Any]]:
        codes = index_codes or list(self.INDEX_MAP.keys())
        results = []
        for code in codes:
            try:
                if not self._pro:
                    results.append(self._empty_index(code))
                    continue
                end = datetime.now().strftime("%Y%m%d")
                start = (datetime.now() - timedelta(days=3)).strftime("%Y%m%d")
                df = self._pro.index_daily(ts_code=code, start_date=start, end_date=end)
                if not df.empty:
                    row = df.iloc[0]
                    results.append(
                        {
                            "code": code.split(".")[0],
                            "name": self.INDEX_MAP.get(code, code),
                            "price": float(row["close"]),
                            "pct_change": float(row["pct_chg"]),
                            "timestamp": datetime.now().isoformat(),
                            "source": "tushare",
                        }
                    )
                else:
                    results.append(self._empty_index(code))
            except Exception as e:
                logger.warning("Tushare 获取指数行情失败 ts_code=%s: %s", code, e)
                # 系统性错误（限频/网络不通）上抛，避免剩余指数继续撞同一死接口
                if is_systemic_error(e):
                    raise RateLimitError(str(e)) from e
                results.append(self._empty_index(code))
        return results

    def get_daily_kline(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self._pro:
            return []
        if start_date and "-" in start_date:
            start_date = start_date.replace("-", "")
        if end_date and "-" in end_date:
            end_date = end_date.replace("-", "")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        try:
            df = self._pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return []
            df = df.sort_values("trade_date")
            if len(df) > limit:
                logger.warning(
                    "Tushare 日线结果被 limit 截断 ts_code=%s rows=%d limit=%d "
                    "（请求区间大于 limit 时属预期；若调用方按区间预期长度则应排查调用参数）",
                    ts_code,
                    len(df),
                    limit,
                )
            return df.tail(limit).to_dict("records")
        except Exception as e:
            logger.error(f"Tushare 获取 {ts_code} K线失败: {e}")
            # 系统性错误（限频/网络不通）上抛，让降级链能冷却本源，
            # 而不是当成「无数据」继续逐只重试
            if is_systemic_error(e):
                raise RateLimitError(str(e)) from e
            return []

    def get_fundamental(self, ts_code: str) -> dict[str, Any]:
        """获取估值数据（PE/PB/PS/市值）。

        2026-10-23 加固：
        1. 结果缓存 1 小时 —— daily_basic 在 2000 积分档被限流到 1 次/分钟，
           而 /stock/{ts_code} 详情接口此前无缓存，连续查询第二只即静默返回空。
        2. 取数改为「近 10 自然日窗口 + 空则回退全历史」，避免为取 1 行拉满 6000 行。
        3. 显式按 trade_date 排序后取末行，不再依赖接口默认降序。
        """
        if not self._pro:
            return {}
        now = time.monotonic()
        cached = _FUNDAMENTAL_CACHE.get(ts_code)
        if cached is not None and now - cached[0] < _fundamental_cache_ttl():
            return dict(cached[1])
        try:
            row = self._fetch_latest_fundamental(ts_code)
            if row is None:
                return {}
            result = {
                "ts_code": ts_code,
                "pe_ttm": _safe_float(row.get("pe_ttm")),
                "pb": _safe_float(row.get("pb")),
                "ps_ttm": _safe_float(row.get("ps_ttm")),
                "total_mv": _safe_float(row.get("total_mv")),
                "circ_mv": _safe_float(row.get("circ_mv")),
            }
            _evict_if_full()
            _FUNDAMENTAL_CACHE[ts_code] = (now, result)
            return dict(result)
        except Exception as e:
            logger.warning("Tushare 获取估值数据失败 ts_code=%s: %s", ts_code, e)
            return {}

    def _fetch_latest_fundamental(self, ts_code: str):
        """返回最新一条每日指标（Series/dict），无数据返回 None。

        先拉近 FUNDAMENTAL_WINDOW_DAYS 个自然日：正常标的 1~7 行即命中，
        避免不带日期时单只老股恒返回 6000 行（000001.SZ 实测 1991-2001 已被截断）。
        窗口为空（长期停牌/退市边缘）则回退全历史，保持原行为不退化。
        """
        # 2026-10-24：补上同类方法都有的 client 守卫（daily/index_daily/估值入口均有）。
        # 原先漏了 → mypy 报「"None" has no attribute "daily_basic"」，
        # 而真实后果更严重：无 token/初始化失败时这里会抛 AttributeError，
        # 而不是像其它入口那样安静返回空。类型错误是症状，缺守卫是病。
        if not self._pro:
            return None
        fields = "ts_code,pe_ttm,pb,ps_ttm,total_mv,circ_mv,trade_date"
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=FUNDAMENTAL_WINDOW_DAYS)).strftime("%Y%m%d")
        df = self._pro.daily_basic(ts_code=ts_code, start_date=start, end_date=end, fields=fields)
        if df is not None and not df.empty:
            return self._latest_row(df, ts_code)

        df = self._pro.daily_basic(ts_code=ts_code, fields=fields)
        if df is None or df.empty:
            return None
        if len(df) >= TUSHARE_SINGLE_REQUEST_LIMIT:
            logger.warning(
                "Tushare daily_basic 触达单次返回上限 ts_code=%s rows=%d limit=%d，"
                "更早记录已被服务端截断（当前仅取最新一行，取值不受影响；"
                "若后续需全历史估值序列，须按日期分段拉取）",
                ts_code,
                len(df),
                TUSHARE_SINGLE_REQUEST_LIMIT,
            )
        return self._latest_row(df, ts_code)

    @staticmethod
    def _latest_row(df, ts_code: str):
        """显式升序排序后取末行，不依赖接口默认排序方向"""
        rows = len(df)
        if "trade_date" in getattr(df, "columns", ()):
            df = df.sort_values("trade_date", ascending=True)
        elif rows > 1:
            logger.warning(
                "Tushare daily_basic 返回缺少 trade_date 列，无法确认最新行 ts_code=%s rows=%d",
                ts_code,
                rows,
            )
        return df.iloc[-1]

    @staticmethod
    def clear_fundamental_cache() -> None:
        """清空估值缓存（测试与运维手工失效用）"""
        _FUNDAMENTAL_CACHE.clear()

    def name(self) -> str:
        return "tushare"

    # ---- 内部辅助 ----

    def _get_name(self, ts_code: str) -> str:
        return self.STOCK_NAMES.get(ts_code, ts_code)

    def _empty_quote(self, ts_code: str) -> dict[str, Any]:
        return {
            "ts_code": ts_code,
            "name": self._get_name(ts_code),
            "price": 0.0,
            "pct_change": 0.0,
            "volume": 0,
            "timestamp": datetime.now().isoformat(),
            "source": "tushare",
        }

    def _empty_index(self, code: str) -> dict[str, Any]:
        return {
            "code": code.split(".", maxsplit=1)[0],
            "name": self.INDEX_MAP.get(code, code),
            "price": 0.0,
            "pct_change": 0.0,
            "timestamp": datetime.now().isoformat(),
            "source": "tushare",
        }
