"""
通达信行情数据提供者（基于 tdx-connector MCP）

通过 tdx-connector HTTP API 获取实时行情。
支持两种运行模式：
- docker: 连接 docker-compose 中的 tdx-connector 服务 (http://tdx-connector:8300)
- local: 连接本地 MCP 进程（开发环境）
"""

from datetime import datetime
import json
import logging
import os
import subprocess
from typing import Any

from shared.quote_provider.base import QuoteProvider

logger = logging.getLogger(__name__)


class TdxQuoteProvider(QuoteProvider):
    """基于通达信 MCP 的实现。

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
            elif isinstance(row, list | tuple):
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
        if "." in code:
            return code
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
