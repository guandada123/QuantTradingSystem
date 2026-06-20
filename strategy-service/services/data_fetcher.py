"""
多源数据获取模块
支持多源降级策略（腾讯财经 → 东方财富 → DataService），
内置进程级内存缓存（TTLCache）和文件缓存。

负责：
- K线历史行情获取（腾讯财经 API，最稳定，无需 Token）
- 东方财富 K 线获取（HTTPS 备份源）
- 多源降级获取逻辑
- 基准指数数据获取（腾讯 + AKShare 兜底）
"""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
import os
import time
from typing import List, Optional
import urllib.request

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# 进程内共享内存缓存（所有 DataFetcher 实例共享）
_mem_cache: TTLCache = TTLCache(maxsize=256, ttl=3600)

# 缓存 TTL 默认值
_default_cache_ttl: int = 86400  # 1 天


# ============================================================
# 缓存工具函数
# ============================================================


def _mem_cache_key(prefix: str, ts_code: str, start_date: str, end_date: str) -> str:
    """生成内存缓存键"""
    sd = start_date.replace("-", "")
    ed = end_date.replace("-", "")
    return f"{prefix}:{ts_code}:{sd}:{ed}"


def _get_cache_ttl() -> int:
    """获取缓存 TTL（秒），优先从 settings 读取"""
    try:
        from core.config import settings

        return settings.CACHE_TTL_SECONDS
    except (ImportError, AttributeError):
        return _default_cache_ttl


def _cache_dir() -> str:
    """获取缓存目录路径"""
    d = os.path.join(os.path.dirname(__file__), ".cache")
    os.makedirs(d, exist_ok=True)
    return d


# ============================================================
# 腾讯财经 K 线 API（HTTP，最稳定，无需 Token）
# ============================================================

_TENCENT_BASE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def fetch_kline_tencent(ts_code: str, start_date: str, end_date: str) -> list[dict]:
    """通过腾讯财经 API 获取历史K线（最稳定，有本地缓存）

    Args:
        ts_code: 股票代码（如 000001.SZ）
        start_date: 起始日期 YYYYMMDD 或 YYYY-MM-DD
        end_date: 结束日期 YYYYMMDD 或 YYYY-MM-DD

    Returns:
        K线数据列表 [{trade_date, open, close, high, low, vol, amount}, ...]
    """
    start_clean = start_date.replace("-", "")
    end_clean = end_date.replace("-", "")

    # === L1 内存缓存 ===
    mem_key = _mem_cache_key("tx", ts_code, start_clean, end_clean)
    cached = _mem_cache.get(mem_key)
    if cached is not None:
        logger.debug("MemCache HIT: tx:%s [%s~%s]", ts_code, start_clean, end_clean)
        return cached

    # 腾讯API需要 YYYY-MM-DD 格式
    start_fmt = f"{start_clean[:4]}-{start_clean[4:6]}-{start_clean[6:8]}"
    end_fmt = f"{end_clean[:4]}-{end_clean[4:6]}-{end_clean[6:8]}"

    symbol = ts_code.split(".", maxsplit=1)[0]
    suffix = ts_code.rsplit(".", maxsplit=1)[-1].upper() if "." in ts_code else "SZ"
    market_prefix = "sz" if suffix == "SZ" else "sh" if suffix == "SH" else "bj"
    code = f"{market_prefix}{symbol}"

    # 文件缓存（带 TTL 检查）
    cache_dir = _cache_dir()
    cache_file = os.path.join(cache_dir, f"tx_{symbol}_{start_clean}_{end_clean}.json")
    cache_ttl = _get_cache_ttl()

    try:
        if os.path.exists(cache_file):
            age = time.time() - os.path.getmtime(cache_file)
            if age < cache_ttl:
                with open(cache_file, encoding="utf-8") as f:
                    data = json.load(f)
                # 预热内存缓存
                _mem_cache[mem_key] = data
                return data
            else:
                logger.debug(
                    "缓存过期，重新获取: %s (age=%.0fs > ttl=%ds)", cache_file, age, cache_ttl
                )
    except Exception:
        logger.debug("腾讯K线: 缓存读取失败，跳过", cache_file=str(cache_file))

    url = f"{_TENCENT_BASE}?param={code},day,{start_fmt},{end_fmt},500,qfq"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
    )

    data = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                break
        except Exception:
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))

    if data and data.get("code") == 0:
        stock_data = data.get("data", {}).get(code, {})
        qfq_key = "qfqday"
        rows = stock_data.get(qfq_key, [])
        if not rows:
            rows = stock_data.get("day", [])

        if rows:
            klines = []
            for row in rows:
                try:
                    klines.append(
                        {
                            "trade_date": str(row[0]),
                            "open": float(row[1]),
                            "close": float(row[2]),
                            "high": float(row[3]),
                            "low": float(row[4]),
                            "vol": int(float(row[5])),
                            "amount": 0.0,
                        }
                    )
                except (IndexError, ValueError, TypeError) as e:
                    logger.warning("腾讯K线行解析失败: %s，数据: %s", e, row)
                    continue

            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(klines, f, ensure_ascii=False)
            except Exception:
                logger.debug("腾讯K线: 缓存写入失败", cache_file=cache_file)

            logger.info(f"Tencent: {ts_code} 获取 {len(klines)} 条K线")
            _mem_cache[mem_key] = klines
            return klines

    return []


# ============================================================
# 东方财富 K 线 API（HTTPS，备份源）
# ============================================================

_EASTMONEY_BASE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

# 向后兼容引用（允许 EnhancedBacktestEngine 通过 DataFetcher._TENCENT_BASE 访问）
_TENCENT_BASE_URL = _TENCENT_BASE
_EASTMONEY_BASE_URL = _EASTMONEY_BASE


def fetch_kline_eastmoney(ts_code: str, start_date: str, end_date: str) -> list[dict]:
    """通过东方财富 API 获取历史K线（备份源）"""
    start_clean = start_date.replace("-", "")
    end_clean = end_date.replace("-", "")

    # === L1 内存缓存 ===
    mem_key = _mem_cache_key("em", ts_code, start_clean, end_clean)
    cached = _mem_cache.get(mem_key)
    if cached is not None:
        logger.debug("MemCache HIT: em:%s [%s~%s]", ts_code, start_clean, end_clean)
        return cached

    symbol = ts_code.split(".", maxsplit=1)[0]
    market = "1" if symbol.startswith(("6", "68")) else "0"
    secid = f"{market}.{symbol}"

    cache_dir = _cache_dir()
    cache_file = os.path.join(cache_dir, f"kline_{symbol}_{start_clean}_{end_clean}.json")
    cache_ttl = _get_cache_ttl()

    try:
        if os.path.exists(cache_file):
            age = time.time() - os.path.getmtime(cache_file)
            if age < cache_ttl:
                with open(cache_file, encoding="utf-8") as f:
                    data = json.load(f)
                _mem_cache[mem_key] = data
                return data
            else:
                logger.debug(
                    "东方财富缓存过期，重新获取: %s (age=%.0fs > ttl=%ds)",
                    cache_file,
                    age,
                    cache_ttl,
                )
    except Exception:
        logger.debug("东方财富K线: 缓存读取失败，跳过", cache_file=cache_file)

    url = (
        f"{_EASTMONEY_BASE}?"
        f"fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&"
        f"ut=2887a9128e9d96a09a7f33fe1e6097c7&"
        f"secid={secid}&klt=101&fqt=1&"
        f"beg={start_clean}&end={end_clean}&lmt=500"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
    )

    data = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                break
        except Exception:
            if attempt < 1:
                time.sleep(0.5)

    if data and data.get("data") and data["data"].get("klines"):
        klines = []
        for line in data["data"]["klines"]:
            try:
                parts = line.split(",")
                klines.append(
                    {
                        "trade_date": str(parts[0]),
                        "open": float(parts[1]),
                        "close": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "vol": int(float(parts[5])),
                        "amount": float(parts[6]),
                    }
                )
            except (IndexError, ValueError, TypeError) as e:
                logger.warning("东方财富K线行解析失败: %s，原始行: %s", e, line)
                continue

        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(klines, f, ensure_ascii=False)
        except Exception:
            logger.debug("东方财富K线: 缓存写入失败", cache_file=cache_file)

        logger.info(f"Eastmoney: {ts_code} 获取 {len(klines)} 条K线")
        _mem_cache[mem_key] = klines
        return klines

    return []


# ============================================================
# 多源降级获取（含基准数据）
# ============================================================


class DataFetcher:
    """多源数据获取器，封装配置依赖和降级策略"""

    def __init__(self, config, get_data_service: Callable | None = None):
        """
        Args:
            config: BacktestConfig 实例
            get_data_service: 可选，延迟获取 DataService 的回调函数
        """
        self.config = config
        self._get_data_service_cb = get_data_service

    # ---- 内部方法 ----

    def _get_data_service(self):
        """延迟初始化 DataService（可选，用于兜底）"""
        if self._get_data_service_cb is not None:
            return self._get_data_service_cb()
        return None

    # ---- 行情获取 ----

    def fetch_market_data(self, ts_code: str, start_date: str, end_date: str) -> list[dict]:
        """获取历史行情数据（多源降级：腾讯财经 → 东方财富 → DataService）

        Args:
            ts_code: 股票代码（如 000001.SZ）
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            行情数据列表，按日期升序排列
        """
        # 策略1：腾讯财经（最稳定，HTTP公开API）
        result = fetch_kline_tencent(ts_code, start_date, end_date)
        if result:
            return result

        # 策略2：东方财富公开API
        result = fetch_kline_eastmoney(ts_code, start_date, end_date)
        if result:
            return result

        # 策略3：DataService 兜底（需要Tushare token）
        ds = self._get_data_service()
        if ds is None:
            logger.warning(
                f"DataFetcher: {ts_code} 无可用数据源（Eastmoney失败 + DataService未配置）"
            )
            return []
        try:
            result = ds.get_stock_daily_quote(ts_code, start_date, end_date)
            if result:
                for row in result:
                    td = row.get("trade_date", "")
                    if hasattr(td, "strftime"):
                        row["trade_date"] = td.strftime("%Y%m%d")
                logger.info(f"DataFetcher: {ts_code} 获取 {len(result)} 条日线 (via DataService)")
                return result
            logger.warning(f"DataFetcher: {ts_code} 返回空数据 (via DataService)")
            return []
        except Exception as e:
            logger.error(f"DataFetcher: {ts_code} 数据获取异常: {e}")
            return []

    def fetch_benchmark_data(self, start_date: str, end_date: str) -> list[dict]:
        """获取基准指数数据（东方财富API优先，多源降级）

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            基准指数行情数据列表
        """
        benchmark = self.config.benchmark

        # 策略1：腾讯财经（统一接口）
        result = fetch_kline_tencent(benchmark, start_date, end_date)
        if result:
            logger.info(f"基准数据 {benchmark} 获取 {len(result)} 条 (via Tencent)")
            return result

        # 策略2：AKShare 指数日线直连
        try:
            import akshare as ak

            code = benchmark.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            suffix = ".SH" if ".SH" in benchmark else ".SZ"
            ak_symbol = f"sh{code}" if suffix == ".SH" else f"sz{code}"
            df = ak.stock_zh_index_daily(symbol=ak_symbol)
            if df is not None and not df.empty:
                result = []
                for _, row in df.iterrows():
                    trade_date = str(row.get("date", "")).replace("-", "")
                    result.append(
                        {
                            "trade_date": trade_date,
                            "open": float(row.get("open", 0)),
                            "high": float(row.get("high", 0)),
                            "low": float(row.get("low", 0)),
                            "close": float(row.get("close", 0)),
                            "vol": int(float(row.get("volume", 0))),
                            "amount": float(row.get("amount", 0)),
                        }
                    )
                result = [r for r in result if start_date <= r["trade_date"] <= end_date]
                result.sort(key=lambda x: x["trade_date"])
                logger.info(f"DataFetcher: AKShare 基准数据获取 {len(result)} 条")
                return result
        except ImportError:
            logger.warning("DataFetcher: akshare 未安装，跳过 AKShare 数据源")
        except Exception as e:
            logger.warning(f"DataFetcher: AKShare 基准数据获取失败: {e}")

        logger.error(f"DataFetcher: 基准数据 {benchmark} 获取全失败")
        return []
