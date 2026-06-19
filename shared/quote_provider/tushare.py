"""
Tushare Pro 行情数据提供者
"""

from datetime import datetime, timedelta
import logging
from typing import Any

from shared.quote_provider.base import QuoteProvider

logger = logging.getLogger(__name__)


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
            return self._empty_quote(ts_code)

    def get_batch_realtime(self, ts_codes: list[str]) -> list[dict[str, Any]]:
        return [self.get_realtime_quote(c) for c in ts_codes]

    def get_index_realtime(self, index_codes: list[str] = None) -> list[dict[str, Any]]:
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
            return df.tail(limit).to_dict("records")
        except Exception as e:
            logger.error(f"Tushare 获取 {ts_code} K线失败: {e}")
            return []

    def get_fundamental(self, ts_code: str) -> dict[str, Any]:
        if not self._pro:
            return {}
        try:
            df = self._pro.daily_basic(
                ts_code=ts_code, fields="ts_code,pe_ttm,pb,ps_ttm,total_mv,circ_mv"
            )
            if df.empty:
                return {}
            row = df.iloc[0]
            return {
                "ts_code": ts_code,
                "pe_ttm": float(row["pe_ttm"]),
                "pb": float(row["pb"]),
                "ps_ttm": float(row["ps_ttm"]),
                "total_mv": float(row["total_mv"]),
                "circ_mv": float(row["circ_mv"]),
            }
        except Exception as e:
            logger.warning("Tushare 获取估值数据失败 ts_code=%s: %s", ts_code, e)
            return {}

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
