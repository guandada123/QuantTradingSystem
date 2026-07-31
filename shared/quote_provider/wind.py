"""
Wind 万得行情数据提供者

利用 Wind AIFin Market CLI 提供实时行情、K线、指数和基本面数据。

依赖:
  - Node.js (npx/node)
  - Wind MCP Skill: ~/.agents/skills/wind-mcp-skill/scripts/cli.mjs
  - Wind API Key: ~/.wind-aifinmarket/config

Docker 兼容:
  - 环境变量 WIND_CLI_PATH 可覆盖 CLI 路径（如挂载到容器内的位置）
  - 环境变量 WIND_AVAILABLE=0 可强制禁用 Wind（即使 CLI 文件存在）

配置: 在容器环境变量设置 QTS_DATA_SOURCE=wind 生效。
"""

import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from shared.quote_provider.base import QuoteProvider

logger = logging.getLogger(__name__)

WIND_CLI = Path(
    os.environ.get(
        "WIND_CLI_PATH",
        str(Path.home() / ".agents" / "skills" / "wind-mcp-skill" / "scripts" / "cli.mjs"),
    )
)

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


def _wind_available() -> bool:
    """Wind CLI 可用且未被环境变量禁用。"""
    if os.environ.get("WIND_AVAILABLE", "1") == "0":
        return False
    return WIND_CLI.exists()


def _call_cli(server_type: str, tool_name: str, params: dict, timeout: int = 15) -> dict | None:
    """调用 Wind CLI，返回 {columns, rows} 或 None。"""
    if not _wind_available():
        return None
    try:
        params_json = json.dumps(params, ensure_ascii=False)
        r = subprocess.run(
            ["node", str(WIND_CLI), "call", server_type, tool_name, params_json],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WIND_CLI.parent.parent),
        )
        if r.returncode != 0:
            return None
        payload = json.loads(r.stdout)
        text_payload = payload.get("content", [{}])[0].get("text", "")
        if not text_payload:
            return None
        data = json.loads(text_payload)
        raw = data.get("data", {})
        if not raw:
            return None

        # analytics_data 嵌套格式
        if isinstance(raw, dict) and "data" in raw and isinstance(raw["data"], list):
            raw = raw["data"][0] if raw["data"] else {}

        return {
            "columns": [c["name"] for c in raw.get("columns", [])],
            "rows": raw.get("rows", []),
        }
    except (json.JSONDecodeError, subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug("Wind CLI 调用失败 %s.%s: %s", server_type, tool_name, e)
        return None


def _to_float(v) -> float | None:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _to_int(v) -> int | None:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _ts_code_to_wind(ts_code: str) -> str:
    """将 ts_code 转为 Wind 标准码（QTS 用 .SH/.SZ 格式，Wind 也用同样格式）"""
    code = ts_code.strip()
    if "." not in code:
        if code.startswith(("6", "9")):
            return f"{code}.SH"
        elif code.startswith(("0", "3")):
            return f"{code}.SZ"
        elif code.startswith(("8", "4")):
            return f"{code}.BJ"
        return code
    return code


def _plain_code(ts_code: str) -> str:
    """去后缀: 600519.SH → 600519"""
    return ts_code.partition(".")[0]


class WindQuoteProvider(QuoteProvider):
    """基于 Wind 万得的数据提供者。

    注：Docker 容器内需挂载 Wind CLI 目录，否则自动降级为空响应。
    """

    def __init__(self):
        self._available = _wind_available()
        if self._available:
            logger.info("WindQuoteProvider: Wind CLI 可用")
        else:
            logger.warning("WindQuoteProvider: Wind CLI 不可用，将返回空数据")

    def _empty_quote(self, ts_code: str) -> dict[str, Any]:
        return {
            "ts_code": ts_code,
            "name": ts_code,
            "price": 0.0,
            "pct_change": 0.0,
            "volume": 0,
            "timestamp": datetime.now().isoformat(),
            "source": "wind",
        }

    def _empty_index(self, code: str) -> dict[str, Any]:
        return {
            "code": _plain_code(code),
            "name": code,
            "price": 0.0,
            "pct_change": 0.0,
            "timestamp": datetime.now().isoformat(),
            "source": "wind",
        }

    # ---- 实时行情 ----

    def get_realtime_quote(self, ts_code: str) -> dict[str, Any]:
        if not self._available:
            return self._empty_quote(ts_code)
        try:
            wcode = _ts_code_to_wind(ts_code)
            # 用 get_stock_price_indicators 获取价格+涨跌幅
            result = _call_cli(
                "stock_data",
                "get_stock_price_indicators",
                {"windcode": wcode, "indexes": "最新成交价,涨跌幅"},
                timeout=10,
            )
            if result and result["rows"]:
                row = result["rows"][0]
                price = _to_float(row[0]) if len(row) > 0 else None
                pct = _to_float(row[1]) if len(row) > 1 else None
                return {
                    "ts_code": ts_code,
                    "name": ts_code,
                    "price": price or 0.0,
                    "pct_change": pct or 0.0,
                    "volume": 0,
                    "timestamp": datetime.now().isoformat(),
                    "source": "wind",
                }
            # 降级：get_stock_quote 获取更多字段
            result2 = _call_cli(
                "stock_data",
                "get_stock_quote",
                {"windcode": wcode},
                timeout=10,
            )
            if result2 and result2["rows"]:
                row = result2["rows"][0]
                return {
                    "ts_code": ts_code,
                    "name": ts_code,
                    "price": _to_float(row[2]) if len(row) > 2 else 0.0,
                    "open": _to_float(row[1]) if len(row) > 1 else None,
                    "high": _to_float(row[3]) if len(row) > 3 else None,
                    "low": _to_float(row[4]) if len(row) > 4 else None,
                    "volume": _to_int(row[6]) if len(row) > 6 else 0,
                    "amount": _to_float(row[5]) if len(row) > 5 else None,
                    "timestamp": datetime.now().isoformat(),
                    "source": "wind",
                }
        except Exception as e:
            logger.warning("Wind 获取 %s 行情失败: %s", ts_code, e)
        return self._empty_quote(ts_code)

    def get_batch_realtime(self, ts_codes: list[str]) -> list[dict[str, Any]]:
        """批量获取实时行情（Wind 不支持批量，串行调用）"""
        return [self.get_realtime_quote(c) for c in ts_codes]

    # ---- 指数行情 ----

    def get_index_realtime(self, index_codes: list[str] = None) -> list[dict[str, Any]]:
        if not self._available:
            return [self._empty_index(c) for c in (index_codes or DEFAULT_INDEX_CODES)]
        codes = index_codes or DEFAULT_INDEX_CODES
        results = []
        for idx in codes:
            try:
                wcode = _ts_code_to_wind(idx)
                # 用 get_index_price_indicators 获取涨跌幅
                result = _call_cli(
                    "index_data",
                    "get_index_price_indicators",
                    {"windcode": wcode, "indexes": "最新成交价,涨跌幅"},
                    timeout=10,
                )
                if result and result["rows"]:
                    row = result["rows"][0]
                    results.append(
                        {
                            "code": _plain_code(idx),
                            "name": _plain_code(idx),
                            "price": _to_float(row[0]) or 0.0,
                            "pct_change": _to_float(row[1]) or 0.0,
                            "timestamp": datetime.now().isoformat(),
                            "source": "wind",
                        }
                    )
                else:
                    results.append(self._empty_index(idx))
            except Exception:
                results.append(self._empty_index(idx))
        return results

    # ---- K线数据 ----

    def get_daily_kline(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self._available:
            return []
        try:
            wcode = _ts_code_to_wind(ts_code)
            end = end_date or datetime.now().strftime("%Y%m%d")
            # 保守推算 begin_date（按 1.5 倍窗口）
            if start_date:
                begin = start_date
            else:
                # 估算 limit 天前
                from datetime import timedelta

                begin_dt = datetime.now() - timedelta(days=int(limit * 1.5))
                begin = begin_dt.strftime("%Y%m%d")

            result = _call_cli(
                "stock_data",
                "get_stock_kline",
                {"windcode": wcode, "kline": "日K", "begin_date": begin, "end_date": end},
                timeout=15,
            )
            if result and result["rows"]:
                rows = result["rows"]
                cols = result["columns"]
                # 转为字典列表
                dict_rows = [dict(zip(cols, row)) for row in rows]
                # 取最后 limit 条
                dict_rows = dict_rows[-limit:]
                out = []
                for r in dict_rows:
                    out.append(
                        {
                            "ts_code": ts_code,
                            "trade_date": str(r.get("TIME", ""))[:10],
                            "open": _to_float(r.get("OPEN", 0)) or 0.0,
                            "high": _to_float(r.get("HIGH", 0)) or 0.0,
                            "low": _to_float(r.get("LOW", 0)) or 0.0,
                            "close": _to_float(r.get("MATCH", 0)) or 0.0,
                            "volume": _to_int(r.get("VOL", 0)) or 0,
                            "amount": _to_float(r.get("AMOUNT", 0)) or 0.0,
                            "source": "wind",
                        }
                    )
                return out
        except Exception as e:
            logger.warning("Wind 获取 %s K线失败: %s", ts_code, e)
        return []

    # ---- 基本面 ----

    def get_fundamental(self, ts_code: str) -> dict[str, Any]:
        if not self._available:
            return {}
        try:
            wcode = _ts_code_to_wind(ts_code)
            result = _call_cli(
                "stock_data",
                "get_stock_price_indicators",
                {"windcode": wcode, "indexes": "最新成交价,涨跌幅,市盈率,市净率,总市值"},
                timeout=15,
            )
            if result and result["rows"]:
                row = result["rows"][0]
                cols = result["columns"]
                rdict = dict(zip(cols, row))
                return {
                    "ts_code": ts_code,
                    "pe_ttm": _to_float(rdict.get("市盈率(TTM)", rdict.get("市盈率", 0))) or 0.0,
                    "pb": _to_float(rdict.get("市净率", 0)) or 0.0,
                    "total_mv": _to_float(rdict.get("总市值2", rdict.get("总市值", 0))) or 0.0,
                    "circ_mv": 0.0,
                }
        except Exception as e:
            logger.warning("Wind 获取 %s 基本面失败: %s", ts_code, e)
        return {}

    def name(self) -> str:
        return "wind"
