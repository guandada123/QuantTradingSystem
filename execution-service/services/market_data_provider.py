"""
行情数据源适配器 — 为高级风控规则提供实时市场数据。
基于 westock-mcp + 腾讯行情接口，计算 ATR、涨跌停统计、行业指数等。

Usage:
    from market_data_provider import MarketDataProvider
    provider = MarketDataProvider()
    data = await provider.fetch_market_data("sh600584")
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 缓存目录
CACHE_DIR = Path(os.path.dirname(os.path.dirname(__file__))) / "shared" / "claw_data" / "cache"
CACHE_TTL_MINUTES = 5  # 行情缓存5分钟有效


class MarketDataProvider:
    """行情数据提供器，封装 ATR、行业指数、涨跌停统计等"""

    def __init__(self, use_mcp: bool = True):
        self.use_mcp = use_mcp
        self.cache_dir = CACHE_DIR

    def _cache_key(self, symbol: str, data_type: str) -> str:
        return f"{data_type}_{symbol}"

    def _cache_get(self, key: str) -> dict | None:
        try:
            path = self.cache_dir / f"{key}.json"
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                age = (
                    datetime.now() - datetime.fromisoformat(data.get("ts", "2000-01-01T00:00:00"))
                ).total_seconds()
                if age < CACHE_TTL_MINUTES * 60:
                    return data.get("value")
        except Exception:
            pass
        return None

    def _cache_set(self, key: str, value: dict):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with open(self.cache_dir / f"{key}.json", "w") as f:
                json.dump({"ts": datetime.now().isoformat(), "value": value}, f, ensure_ascii=False)
        except Exception:
            pass

    async def fetch_market_data(self, symbol: str) -> dict[str, Any]:
        """获取完整的市场数据包"""
        # 检查缓存
        cache_key = self._cache_key(symbol, "market_data")
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        result = {}

        # 1. ATR (14) — 基于日K计算
        atr_data = await self._compute_atr(symbol)
        if atr_data:
            result["atr"] = atr_data["atr"]
            result["avg_volume"] = atr_data.get("avg_volume")
            result["ma20"] = atr_data.get("ma20")
            result["high_20d"] = atr_data.get("high_20d")
            result["low_20d"] = atr_data.get("low_20d")
            result["rsi"] = atr_data.get("rsi")

        # 2. 个股当日涨跌
        try:
            today_data = await self._fetch_today_quote(symbol)
            if today_data:
                result["stock_drop_pct"] = today_data.get("change_percent", 0) / 100
                result["current_price"] = today_data.get("price", 0)
        except Exception:
            pass

        # 3. 行业指数 & 涨跌停统计（从同花顺/东财）
        try:
            market_stats = await self._fetch_market_stats()
            if market_stats:
                result["sector_drop_pct"] = market_stats.get("sector_drop_pct", 0)
                result["limit_down_up_ratio"] = market_stats.get("limit_down_up_ratio", 0)
                result["total_limit_down"] = market_stats.get("total_limit_down", 0)
                result["total_limit_up"] = market_stats.get("total_limit_up", 0)
        except Exception:
            pass

        self._cache_set(cache_key, result)
        return result

    async def _compute_atr(self, symbol: str, period: int = 14) -> dict | None:
        """基于日K线计算 ATR、MA20、RSI"""
        try:
            # 使用 westock-mcp or Fallback
            klines = await self._fetch_kline(symbol, period * 2)
            if not klines or len(klines) < period:
                return None

            tr_values = []
            closes = []
            highs = []
            lows = []

            for i in range(1, len(klines)):
                high = float(klines[i].get("high", 0))
                low = float(klines[i].get("low", 0))
                prev_close = float(klines[i - 1].get("close", 0))
                close = float(klines[i].get("close", 0))

                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                tr_values.append(tr)
                closes.append(close)
                highs.append(high)
                lows.append(low)

            if len(tr_values) < period:
                return None

            atr = sum(tr_values[-period:]) / period
            ma20 = sum(closes[-min(20, len(closes)) :]) / min(20, len(closes))
            high_20d = max(highs[-min(20, len(highs)) :])
            low_20d = min(lows[-min(20, len(lows)) :])

            # RSI(14)
            gains = sum(max(c - closes[i - 1], 0) for i, c in enumerate(closes[-14:], 1) if i > 0)
            losses = sum(max(closes[i - 1] - c, 0) for i, c in enumerate(closes[-14:], 1) if i > 0)
            rs = gains / losses if losses > 0 else 100
            rsi = 100 - (100 / (1 + rs))

            return {
                "atr": round(atr, 2),
                "ma20": round(ma20, 2),
                "high_20d": round(high_20d, 2),
                "low_20d": round(low_20d, 2),
                "rsi": round(rsi, 1),
                "avg_volume": round(
                    sum(float(k.get("volume", 0)) for k in klines[-period:]) / period
                ),
            }
        except Exception as e:
            logger.warning(f"ATR compute failed for {symbol}: {e}")
            return None

    async def _fetch_kline(self, symbol: str, limit: int = 30) -> list:
        """获取日K线数据 — 优先 westock-mcp，fallback 腾讯"""
        # Fallback: 腾讯行情接口
        try:
            import httpx

            # Parse symbol code
            code = symbol.replace("sh", "").replace("sz", "")
            market = "1" if symbol.startswith("sh") else "0"
            url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,,,{limit},qfq"
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url)
                data = resp.json()
                klines = data.get("data", {}).get(f"{market}{code}", {}).get("qfqday", []) or []
                if not klines:
                    klines = data.get("data", {}).get(f"{market}{code}", {}).get("day", []) or []
                return [
                    {
                        "date": k[0],
                        "open": k[1],
                        "close": k[2],
                        "high": k[3],
                        "low": k[4],
                        "volume": k[5],
                    }
                    for k in klines
                ]
        except Exception:
            return []

    async def _fetch_today_quote(self, symbol: str) -> dict | None:
        """获取当日行情"""
        try:
            import httpx

            code = symbol.replace("sh", "").replace("sz", "")
            market = "1" if symbol.startswith("sh") else "0"
            url = f"http://qt.gtimg.cn/q={market}{code}"
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url)
                text = resp.text
                if "~" not in text:
                    return None
                parts = text.split("~")
                if len(parts) > 32:
                    return {
                        "price": float(parts[3]),
                        "prev_close": float(parts[4]),
                        "open": float(parts[5]),
                        "volume": int(parts[6]),
                        "high": float(parts[33]),
                        "low": float(parts[34]),
                        "change_percent": float(parts[32]),
                    }
        except Exception:
            pass
        return None

    async def _fetch_market_stats(self) -> dict | None:
        """获取市场涨跌停统计和行业指数数据"""
        try:
            # 从腾讯获取大盘统计
            import httpx

            async with httpx.AsyncClient(timeout=5) as client:
                # 上证指数
                resp = await client.get("http://qt.gtimg.cn/q=sh000001")
                text = resp.text
                sector_drop = 0
                if "~" in text:
                    parts = text.split("~")
                    if len(parts) > 32:
                        sector_drop = float(parts[32]) / 100

                # 获取涨跌停数量（东财接口）
                resp2 = await client.get(
                    "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5000&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f2,f3"
                )
                if resp2.status_code == 200:
                    data = resp2.json()
                    if data.get("data") and data["data"].get("diff"):
                        items = data["data"]["diff"]
                        limit_up = sum(1 for i in items if i.get("f3", 0) >= 9.9)
                        limit_down = sum(1 for i in items if i.get("f3", 0) <= -9.9)
                        ratio = limit_down / max(limit_up, 1)
                        return {
                            "sector_drop_pct": sector_drop,
                            "limit_down_up_ratio": round(ratio, 2),
                            "total_limit_down": limit_down,
                            "total_limit_up": limit_up,
                        }
        except Exception:
            pass
        return None


# 便捷函数 — 供 daily_risk_monitor 使用
async def get_market_data_for_symbol(symbol: str) -> dict[str, Any]:
    """获取单个标的的市场数据"""
    provider = MarketDataProvider()
    return await provider.fetch_market_data(symbol)
