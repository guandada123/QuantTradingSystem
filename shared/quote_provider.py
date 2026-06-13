"""
统一行情数据提供者接口 v1.0

定义 QuoteProvider ABC，支持 Tushare、通达信、AKShare 数据源切换。
使用工厂模式 + 配置驱动，运行时动态切换。

数据源切换策略：
- tdx（通达信）：主数据源，延迟最低，通过 tdx-connector MCP 获取
- tushare：备用数据源，日线/基本面为主
- akshare：第二备用，纯 Python 实现，无需 Token
"""

import abc
from collections.abc import Callable
from datetime import datetime, timedelta
import json
import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 1. QuoteProvider 抽象基类
# ──────────────────────────────────────────────


class QuoteProvider(abc.ABC):
    """行情数据提供者抽象接口"""

    @abc.abstractmethod
    def get_realtime_quote(self, ts_code: str) -> dict[str, Any]:
        """获取单只股票实时行情"""
        ...

    @abc.abstractmethod
    def get_batch_realtime(self, ts_codes: list[str]) -> list[dict[str, Any]]:
        """批量获取多只股票实时行情"""
        ...

    @abc.abstractmethod
    def get_index_realtime(self, index_codes: list[str] = None) -> list[dict[str, Any]]:
        """获取核心指数行情"""
        ...

    @abc.abstractmethod
    def get_daily_kline(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取日K线数据"""
        ...

    @abc.abstractmethod
    def get_fundamental(self, ts_code: str) -> dict[str, Any]:
        """获取基本面数据（PE/PB/市值等）"""
        ...

    def name(self) -> str:
        """返回数据源名称"""
        return self.__class__.__name__


# ──────────────────────────────────────────────
# 2. Tushare 实现（现有封装）
# ──────────────────────────────────────────────


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
                logger.warning("Tushare 获取指数行情失败 ts_code=%s: %s", ts_code, e)
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


# ──────────────────────────────────────────────
# 3. 通达信实现（基于 tdx-connector MCP）
# ──────────────────────────────────────────────


class TdxQuoteProvider(QuoteProvider):
    """
    基于通达信 MCP 的实现。

    通过 tdx-connector HTTP API 获取实时行情。
    支持两种运行模式：
    - docker: 连接 docker-compose 中的 tdx-connector 服务 (http://tdx-connector:8300)
    - local: 连接本地 MCP 进程（开发环境）

    代码规范转换：通达信使用纯数字代码 + 市场后缀（如 000001.SZ），
    与 Tushare 的 ts_code 一致，无需额外转换。
    """

    INDEX_CODES = {
        "000001.SH": "上证指数",
        "399001.SZ": "深证成指",
        "399006.SZ": "创业板指",
        "000688.SH": "科创50",
        "899050.BJ": "北证50",
        "000300.SH": "沪深300",
        "000905.SH": "中证500",
        "000852.SH": "中证1000",
    }

    def __init__(
        self,
        api_url: str | None = None,
        mcp_cmd: str | None = None,
    ):
        """
        Args:
            api_url: tdx-connector HTTP API 地址（docker 环境）
            mcp_cmd: MCP 进程启动命令（local 开发环境）
        """
        self._api_url = api_url or os.getenv("TDX_CONNECTOR_URL", "")
        self._mcp_cmd = mcp_cmd or os.getenv("TDX_MCP_CMD", "")
        self._mcp_process = None
        self._ready = bool(self._api_url) or bool(self._mcp_cmd)

        if not self._ready:
            logger.warning("TdxQuoteProvider: 未配置 API URL 或 MCP 命令，将返回空数据")
        else:
            logger.info(f"TdxQuoteProvider: 初始化完成 (api_url={self._api_url or 'none'})")

    # ---- 实时行情 ----

    def get_realtime_quote(self, ts_code: str) -> dict[str, Any]:
        """获取单只股票实时行情"""
        result = self._call_mcp(
            "get_quotes",
            {
                "codes": [ts_code],
                "fields": [
                    "code",
                    "name",
                    "price",
                    "open",
                    "high",
                    "low",
                    "pre_close",
                    "change",
                    "pct_change",
                    "volume",
                    "amount",
                ],
            },
        )
        if result and len(result) > 0:
            return self._format_quote(ts_code, result[0])
        return self._empty_quote(ts_code)

    def get_batch_realtime(self, ts_codes: list[str]) -> list[dict[str, Any]]:
        """批量获取多只股票实时行情"""
        result = self._call_mcp(
            "get_quotes",
            {
                "codes": ts_codes,
                "fields": [
                    "code",
                    "name",
                    "price",
                    "open",
                    "high",
                    "low",
                    "pre_close",
                    "change",
                    "pct_change",
                    "volume",
                    "amount",
                ],
            },
        )
        if not result:
            return [self._empty_quote(c) for c in ts_codes]
        quote_map = {self._normalize_code(r.get("code", "")): r for r in result}
        return [self._format_quote(c, quote_map.get(self._normalize_code(c), {})) for c in ts_codes]

    def get_index_realtime(self, index_codes: list[str] = None) -> list[dict[str, Any]]:
        """获取指数行情"""
        codes = index_codes or list(self.INDEX_CODES.keys())
        result = self._call_mcp(
            "get_quotes",
            {
                "codes": codes,
                "fields": ["code", "name", "price", "pct_change"],
            },
        )
        if not result:
            return [self._empty_index(c) for c in codes]
        quote_map = {self._normalize_code(r.get("code", "")): r for r in result}
        return [
            {
                "code": c.split(".")[0],
                "name": self.INDEX_CODES.get(c, c),
                "price": float(quote_map.get(self._normalize_code(c), {}).get("price", 0)),
                "pct_change": float(
                    quote_map.get(self._normalize_code(c), {}).get("pct_change", 0)
                ),
                "timestamp": datetime.now().isoformat(),
                "source": "tdx",
            }
            for c in codes
        ]

    def get_daily_kline(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取日K线"""
        result = self._call_mcp(
            "get_kline",
            {
                "code": ts_code,
                "period": "day",
                "count": limit,
            },
        )
        if not result:
            return []
        # tdx K线返回格式：[date, open, high, low, close, volume, amount]
        formatted = []
        for row in result:
            if isinstance(row, dict):
                formatted.append(
                    {
                        "ts_code": ts_code,
                        "trade_date": str(row.get("date", "")),
                        "open": float(row.get("open", 0)),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "close": float(row.get("close", 0)),
                        "volume": int(row.get("volume", 0)),
                        "amount": float(row.get("amount", 0)),
                        "source": "tdx",
                    }
                )
            elif isinstance(row, (list, tuple)):
                formatted.append(
                    {
                        "ts_code": ts_code,
                        "trade_date": str(row[0]) if len(row) > 0 else "",
                        "open": float(row[1]) if len(row) > 1 else 0,
                        "high": float(row[2]) if len(row) > 2 else 0,
                        "low": float(row[3]) if len(row) > 3 else 0,
                        "close": float(row[4]) if len(row) > 4 else 0,
                        "volume": int(row[5]) if len(row) > 5 else 0,
                        "amount": float(row[6]) if len(row) > 6 else 0,
                        "source": "tdx",
                    }
                )
        return formatted[-limit:]

    def get_fundamental(self, ts_code: str) -> dict[str, Any]:
        """获取基本面数据（通过 tdx_indicator_select 或 tdx_api_data）"""
        result = self._call_mcp(
            "get_indicators",
            {
                "code": ts_code,
                "indicators": ["pe_ttm", "pb", "total_mv", "circ_mv"],
            },
        )
        if not result:
            return {}
        return {
            "ts_code": ts_code,
            "pe_ttm": float(result.get("pe_ttm", 0)),
            "pb": float(result.get("pb", 0)),
            "ps_ttm": float(result.get("ps_ttm", 0)),
            "total_mv": float(result.get("total_mv", 0)),
            "circ_mv": float(result.get("circ_mv", 0)),
        }

    def name(self) -> str:
        return "tdx"

    # ---- 内部方法 ----

    def _call_mcp(self, action: str, params: dict) -> Any:
        """
        调用 tdx-connector MCP。
        优先尝试 HTTP API，失败后降级到子进程调用。
        """
        # 策略 1：HTTP API（Docker 环境）
        if self._api_url:
            try:
                import httpx

                resp = httpx.post(
                    f"{self._api_url.rstrip('/')}/mcp/{action}",
                    json=params,
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    return resp.json().get("data", resp.json())
                logger.warning(f"tdx HTTP API 返回 {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.warning(f"tdx HTTP API 调用失败: {e}")

        # 策略 2：子进程 MCP（本地开发环境）
        if self._mcp_cmd:
            try:
                cmd = self._mcp_cmd.split()
                input_data = json.dumps({"action": action, "params": params})
                proc = subprocess.run(
                    cmd,
                    input=input_data,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if proc.returncode == 0 and proc.stdout:
                    return json.loads(proc.stdout)
                logger.warning(f"tdx MCP 子进程返回空: {proc.stderr[:200]}")
            except Exception as e:
                logger.warning(f"tdx MCP 子进程失败: {e}")

        return None

    def _normalize_code(self, code: str) -> str:
        """规范化证券代码"""
        code = code.strip().upper()
        # 如果已有市场后缀，直接返回
        if "." in code:
            return code
        # 根据前缀推断市场
        if code.startswith("6") or code.startswith("9"):
            return f"{code}.SH"
        if code.startswith("0") or code.startswith("3") or code.startswith("2"):
            return f"{code}.SZ"
        if code.startswith("4") or code.startswith("8"):
            return f"{code}.BJ"
        return code

    def _format_quote(self, ts_code: str, raw: dict) -> dict[str, Any]:
        """格式化行情数据"""
        return {
            "ts_code": ts_code,
            "name": raw.get("name", ts_code),
            "price": float(raw.get("price", 0)),
            "open": float(raw.get("open", 0)),
            "high": float(raw.get("high", 0)),
            "low": float(raw.get("low", 0)),
            "pre_close": float(raw.get("pre_close", 0)),
            "change": float(raw.get("change", 0)),
            "pct_change": float(raw.get("pct_change", 0)),
            "volume": int(raw.get("volume", 0)),
            "amount": float(raw.get("amount", 0)),
            "trade_date": raw.get("trade_date", datetime.now().strftime("%Y%m%d")),
            "timestamp": datetime.now().isoformat(),
            "source": "tdx",
        }

    def _empty_quote(self, ts_code: str) -> dict[str, Any]:
        return {
            "ts_code": ts_code,
            "name": ts_code,
            "price": 0.0,
            "pct_change": 0.0,
            "volume": 0,
            "timestamp": datetime.now().isoformat(),
            "source": "tdx",
        }

    def _empty_index(self, code: str) -> dict[str, Any]:
        return {
            "code": code.split(".", maxsplit=1)[0],
            "name": self.INDEX_CODES.get(code, code),
            "price": 0.0,
            "pct_change": 0.0,
            "timestamp": datetime.now().isoformat(),
            "source": "tdx",
        }


# ──────────────────────────────────────────────
# 4. AKShare 实现（备选，纯 Python）
# ──────────────────────────────────────────────


class AKShareQuoteProvider(QuoteProvider):
    """基于 AKShare 的实现，免 Token。

    内置三重防护：
    1. 指数退避重试（瞬态网络抖动 <5s 自动恢复）
    2. 全局断路器（连续 5 次失败后熔断 60s，降级到备用源）
    3. safe_import（akshare 导入异常不影响服务稳定性）
    """

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

    # 可重试的网络级异常
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
        """统一的弹性调用入口。

        - 断路器打开时抛出 CircuitBreakerOpenError → 调用方降级
        - 瞬态网络错误自动重试
        - 重试耗尽时记录错误并抛出

        Args:
            operation: 操作名（用于日志）
            func: 被调用的同步函数
            max_retries: 最大重试次数
        """
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
            # CircuitBreakerOpenError 和非重试型异常统一记录
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
            logger.warning("Tushare 获取估值数据失败 ts_code=%s: %s", ts_code, e)
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


# ──────────────────────────────────────────────
# 5. 工厂类
# ──────────────────────────────────────────────


class QuoteProviderFactory:
    """行情数据提供者工厂"""

    REGISTRY = {
        "tushare": TushareQuoteProvider,
        "tdx": TdxQuoteProvider,
        "akshare": AKShareQuoteProvider,
    }

    def __init__(self, default_source: str = "tushare", **kwargs):
        self._default_source = default_source
        self._kwargs = kwargs
        self._instances: dict[str, QuoteProvider] = {}

    def get_provider(self, source: str | None = None) -> QuoteProvider:
        """获取指定或默认的数据提供者"""
        source = source or self._default_source
        if source not in self._instances:
            cls = self.REGISTRY.get(source)
            if not cls:
                logger.warning(f"未知数据源 '{source}'，使用 tushare 回退")
                cls = TushareQuoteProvider
            logger.info(f"QuoteProviderFactory: 创建 {source} 提供者")
            self._instances[source] = cls(**self._kwargs.get(source, {}))
        return self._instances[source]

    def set_default_source(self, source: str):
        """动态切换默认数据源"""
        if source not in self.REGISTRY:
            logger.warning(f"未知数据源 '{source}'，忽略切换")
            return
        self._default_source = source
        logger.info(f"QuoteProviderFactory: 默认数据源切换为 {source}")

    @property
    def default(self) -> QuoteProvider:
        return self.get_provider()

    @classmethod
    def register(cls, name: str, provider_cls) -> None:
        """注册自定义提供者"""
        cls.REGISTRY[name] = provider_cls


# 全局工厂实例（延迟初始化）
_factory: QuoteProviderFactory | None = None


def get_quote_provider(source: str | None = None) -> QuoteProvider:
    """获取全局行情提供者"""
    global _factory
    if _factory is None:
        _factory = QuoteProviderFactory(
            default_source=os.getenv("QTS_DATA_SOURCE", "tushare"),
            tdx={"api_url": os.getenv("TDX_CONNECTOR_URL", "")},
            tushare={"token": os.getenv("TUSHARE_TOKEN", "")},
        )
    return _factory.get_provider(source)


def set_data_source(source: str):
    """全局切换数据源"""
    global _factory
    if _factory is None:
        _factory = QuoteProviderFactory(default_source=source)
    else:
        _factory.set_default_source(source)
