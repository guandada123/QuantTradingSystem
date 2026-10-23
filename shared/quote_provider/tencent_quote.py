"""腾讯行情估值兜底源（qt.gtimg.cn）

为什么需要这个模块（2026-10-23 实测结论）：
- Tushare ``daily_basic`` 在 2000 积分档被限流至 1 次/小时，当天首次之后全部失败；
- AKShare 新版已移除 ``stock_a_lg_indicator``，``AKShareQuoteProvider.get_fundamental``
  恒抛 AttributeError；
- 二者叠加导致 ``/stock/{ts_code}`` 的估值字段长期返回空。

腾讯该接口免鉴权、无频次限制、单只查询体积小（约 1KB），适合作为最后一道兜底。

字段契约（2026-10-23 实测 600519.SH / 000001.SZ，响应共 88 字段）：
    [39] 市盈率 TTM    [44] 流通市值(亿元)
    [45] 总市值(亿元)  [46] 市净率

单位换算：腾讯为亿元，Tushare 为万元，故 ×10000。若下游按万元解读，两源可互换。
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={symbol}"
TENCENT_MIN_FIELDS = 47
IDX_PE_TTM = 39
IDX_CIRC_MV = 44
IDX_TOTAL_MV = 45
IDX_PB = 46
YI_TO_WAN = 10000.0

_MARKET_PREFIX = {"SH": "sh", "SZ": "sz", "BJ": "bj"}


def to_tencent_symbol(ts_code: str) -> str:
    """600519.SH → sh600519；000001.SZ → sz000001"""
    code, _, market = (ts_code or "").partition(".")
    prefix = _MARKET_PREFIX.get(market.upper(), "sh")
    return f"{prefix}{code}"


def _to_float(raw: str) -> float | None:
    """字段 → 浮点；缺失/非数值返回 None。

    2026-10-23：原返回 0.0，导致同一响应里出现两种空值约定（`ps_ttm` 用 None 表示未知，
    pe/pb/市值用 0.0）。下游无法区分「值真的是 0」与「字段没拿到」，
    例如 total_mv=0 若参与市值加权会静默拉低权重。现统一为 None。
    """
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _yi_to_wan(value: float | None) -> float | None:
    """亿元 → 万元；None 透传（不能对 None 做乘法）"""
    return None if value is None else value * YI_TO_WAN


def fetch_fundamental(ts_code: str, timeout: float = 5.0) -> dict[str, Any]:
    """取单只标的估值，失败一律返回 {}（不抛异常，由调用方决定是否继续降级）"""
    symbol = to_tencent_symbol(ts_code)
    try:
        resp = requests.get(TENCENT_QUOTE_URL.format(symbol=symbol), timeout=timeout)
        resp.encoding = "gbk"
        if resp.status_code != 200:
            logger.warning("腾讯估值接口非 200 ts_code=%s status=%s", ts_code, resp.status_code)
            return {}
        parts = resp.text.split('="')
        if len(parts) < 2:
            logger.warning("腾讯估值接口响应格式异常 ts_code=%s", ts_code)
            return {}
        fields = parts[1].rstrip('";\n').split("~")
    except Exception as e:
        logger.warning("腾讯估值接口异常 ts_code=%s: %s", ts_code, e)
        return {}

    if len(fields) < TENCENT_MIN_FIELDS:
        logger.warning(
            "腾讯估值接口字段数不足 ts_code=%s fields=%d < %d，疑似字段布局变更",
            ts_code,
            len(fields),
            TENCENT_MIN_FIELDS,
        )
        return {}

    return {
        "ts_code": ts_code,
        "pe_ttm": _to_float(fields[IDX_PE_TTM]),
        "pb": _to_float(fields[IDX_PB]),
        # 腾讯不提供市销率。此前写 0.0，下游会把「无数据」误读成「PS=0」，
        # 与 Tushare 路径（有真实 PS）语义冲突 → 统一用 None 表示未知。
        "ps_ttm": None,
        "total_mv": _yi_to_wan(_to_float(fields[IDX_TOTAL_MV])),
        "circ_mv": _yi_to_wan(_to_float(fields[IDX_CIRC_MV])),
    }
