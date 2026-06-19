"""
AKShare 行情数据提供者

免 Token，纯 Python 实现，作为备选数据源。

内置三重防护：
1. 指数退避重试（瞬态网络抖动 <5s 自动恢复）
2. 全局断路器（连续 5 次失败后熔断 60s，降级到备用源）
3. safe_import（akshare 导入异常不影响服务稳定性）
"""

from collections.abc import Callable
from datetime import datetime
import logging
from typing import Any

from shared.quote_provider.base import QuoteProvider

logger = logging.getLogger(__name__)


class AKShareQuoteProvider(QuoteProvider):
    """基于 AKShare 的实现，免 Token。"""

    DEFAULT_INDEX_CODES = [
        "000001.SH",
        "399001.SZ",
        "399006.SZ",
        "000688.SH",
        "899050.BJ",
        "000300.SH",
        "000905.SH",
        "000852.SH",
    ]

    _RETRYABLE = (
        ConnectionError,
        TimeoutError,
        OSError,
    )

    @staticmethod
    def _get_ak() -> Any:
        """安全导入 akshare（带断路器保护）"""
        from shared.resilience import safe_import

        return safe_import("akshare")

    def _call_with_resilience(
        self,
        operation: str,
        func: Callable,
        *args: Any,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> Any:
        """统一的弹性调用入口。"""
        from shared.resilience import CircuitBreakerOpenError, get_circuit_breaker, retry

        breaker = get_circuit_breaker(
            "akshare",
            failure_threshold=5,
            recovery_timeout=60.0,
        )

        if breaker.is_open:
            raise CircuitBreakerOpenError(
                f"Circuit breaker 'akshare' is OPEN — AKShare calls blocked for {breaker.recovery_timeout}s"
            )

        try:
            return retry(
                func,
                *args,
                max_retries=max_retries,
                retryable_exceptions=self._RETRYABLE,
                **kwargs,
            )
        except self._RETRYABLE as e:
            breaker.record_failure()
            logger.error(f"AKShare {operation} 失败（已重试）: {e}")
            raise
        except Exception as e:
            breaker.record_failure()
            logger.error(f"AKShare {operation} 失败（非重试型）: {e}")
            raise
        else:
            breaker.record_success()

    # ---- 实时行情 ----

    def get_realtime_quote(self, ts_code: str) -> dict[str, Any]:
        try:
            ak = self._get_ak()
            if ak is None:
                return self._empty_quote(ts_code)

            code = ts_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")

            def _fetch():
                df = ak.stock_zh_a_spot_em()
                row = df[df["代码"] == code]
                if row.empty:
                    return None
                return row.iloc[0]

            row = self._call_with_resilience("get_realtime_quote", _fetch)
            if row is None:
                return self._empty_quote(ts_code)

            return {
                "ts_code": ts_code,
                "name": row.get("名称", ts_code),
                "price": float(row.get("最新价", 0)),
                "open": float(row.get("今开", 0)),
                "high": float(row.get("最高", 0)),
                "low": float(row.get("最低", 0)),
                "pre_close": float(row.get("昨收", 0)),
                "change": float(row.get("涨跌额", 0)),
                "pct_change": float(row.get("涨跌幅", 0)),
                "volume": int(float(row.get("成交量", 0))),
                "amount": float(row.get("成交额", 0)),
                "timestamp": datetime.now().isoformat(),
                "source": "akshare",
            }
        except Exception as e:
            if "CircuitBreakerOpenError" not in type(e).__name__:
                logger.error(f"AKShare 获取 {ts_code} 行情失败: {e}")
            return self._empty_quote(ts_code)

    def get_batch_realtime(self, ts_codes: list[str]) -> list[dict[str, Any]]:
        return [self.get_realtime_quote(c) for c in ts_codes]

    def get_index_realtime(self, index_codes: list[str] = None) -> list[dict[str, Any]]:
        try:
            ak = self._get_ak()
            if ak is None:
                return [self._empty_index(c) for c in (index_codes or self.DEFAULT_INDEX_CODES)]

            def _fetch():
                return ak.stock_zh_index_spot_em()

            df = self._call_with_resilience("get_index_realtime", _fetch)

            results = []
            for idx_code in index_codes or self.DEFAULT_INDEX_CODES:
                code = idx_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
                row = df[df["代码"] == code]
                if not row.empty:
                    r = row.iloc[0]
                    results.append(
                        {
                            "code": code,
                            "name": r.get("名称", idx_code),
                            "price": float(r.get("最新价", 0)),
                            "pct_change": float(r.get("涨跌幅", 0)),
                            "timestamp": datetime.now().isoformat(),
                            "source": "akshare",
                        }
                    )
                else:
                    results.append(self._empty_index(idx_code))
            return results
        except Exception as e:
            if "CircuitBreakerOpenError" not in type(e).__name__:
                logger.error(f"AKShare 获取指数行情失败: {e}")
            return [self._empty_index(c) for c in (index_codes or self.DEFAULT_INDEX_CODES)]

    def get_daily_kline(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            ak = self._get_ak()
            if ak is None:
                return []

            code = ts_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")

            def _fetch():
                return ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start_date or "19000101",
                    end_date=end_date or datetime.now().strftime("%Y%m%d"),
                    adjust="qfq",
                )

            df = self._call_with_resilience("get_daily_kline", _fetch, max_retries=2)
            df = df.tail(limit)
            result = []
            for _, row in df.iterrows():
                result.append(
                    {
                        "ts_code": ts_code,
                        "trade_date": str(row.get("日期", "")),
                        "open": float(row.get("开盘", 0)),
                        "high": float(row.get("最高", 0)),
                        "low": float(row.get("最低", 0)),
                        "close": float(row.get("收盘", 0)),
                        "volume": int(float(row.get("成交量", 0))),
                        "amount": float(row.get("成交额", 0)),
                        "source": "akshare",
                    }
                )
            return result
        except Exception as e:
            if "CircuitBreakerOpenError" not in type(e).__name__:
                logger.error(f"AKShare 获取 {ts_code} K线失败: {e}")
            return []

    def get_fundamental(self, ts_code: str) -> dict[str, Any]:
        try:
            ak = self._get_ak()
            if ak is None:
                return {}

            code = ts_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")

            def _fetch():
                return ak.stock_a_lg_indicator(symbol=code)

            df = self._call_with_resilience("get_fundamental", _fetch, max_retries=1)
            if df.empty:
                return {}
            row = df.iloc[0]
            return {
                "ts_code": ts_code,
                "pe_ttm": float(row.get("pe_ttm", 0)),
                "pb": float(row.get("pb", 0)),
                "total_mv": float(row.get("total_mv", 0)),
                "circ_mv": float(row.get("circ_mv", 0)),
            }
        except Exception as e:
            logger.warning("AKShare 获取估值数据失败 ts_code=%s: %s", ts_code, e)
            return {}

    def name(self) -> str:
        return "akshare"

    def _empty_quote(self, ts_code: str) -> dict[str, Any]:
        return {
            "ts_code": ts_code,
            "name": ts_code,
            "price": 0.0,
            "pct_change": 0.0,
            "volume": 0,
            "timestamp": datetime.now().isoformat(),
            "source": "akshare",
        }

    def _empty_index(self, code: str) -> dict[str, Any]:
        return {
            "code": code.split(".", maxsplit=1)[0],
            "name": code,
            "price": 0.0,
            "pct_change": 0.0,
            "timestamp": datetime.now().isoformat(),
            "source": "akshare",
        }
