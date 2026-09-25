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

import json
import os
import time
import urllib.request
from collections.abc import Callable
from datetime import date as dt_date
from datetime import timedelta as dt_timedelta

from cachetools import TTLCache

from shared.structured_log import get_logger

logger = get_logger(__name__)

# 进程内共享内存缓存（所有 DataFetcher 实例共享）
_mem_cache: TTLCache = TTLCache(maxsize=256, ttl=3600)

# 缓存 TTL 默认值
_default_cache_ttl: int = 86400  # 1 天

# 本地库新鲜度检查结果（进程内只查一次，1 小时后复检）
_DB_FRESHNESS: dict = {"checked_at": 0.0, "ok": None}

# 判定"某个交易日数据完整"的最小记录数。
# 全市场 5044 只中约 4890 只有数据，取 1000 足以区分完整日与灌库截断日
# （2026-09-02/09-03 事故值：44 行）。与 report_service 的选股池基准日口径保持一致。
_MIN_ROWS_COMPLETE_DAY: int = 1000


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

        ttl: int = settings.CACHE_TTL_SECONDS
        return ttl
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

# 2026-09-03: web.ifzq.gtimg.cn 被腾讯 WAF 拦截(稳定返回 HTTP 501) → 全市场回测取数全空。
# 同路径的 ifzq.gtimg.cn(无 web. 前缀) 验证可用(HTTP 200, 数据格式完全一致)。
# 保留双 host 轮转: 主域名恢复或备用域名再被封都能自愈, 不硬编码单一入口。
_TENCENT_HOSTS = (
    "https://ifzq.gtimg.cn/appstock/app/fqkline/get",
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
)
_TENCENT_BASE = _TENCENT_HOSTS[0]


def _local_db_fresh() -> bool:
    """本地库 daily_quote 是否够新鲜（进程内只查一次）

    判定：max(trade_date) 距今 ≤ 5 个自然日即视为可用。
    超过则放弃本地源，走网络，避免用陈数据静默跑出错误回测。
    """
    cached = _DB_FRESHNESS["ok"]
    now = time.time()
    if cached is not None and now - _DB_FRESHNESS["checked_at"] < 3600:
        return bool(cached)

    # 同时取两个口径：
    #   max_date           = 原始 MAX(trade_date)，灌库截断时它仍指向那个残缺日
    #   last_complete_date = 记录数 >= 门槛的最后一个交易日，真正的"数据截止日"
    # 2026-09-04 修复：只看 max_date 会被截断写入骗过 —— 09-02/09-03 各仅 44 行
    # （全市场 5044 只），max_date 照样返回 09-03，本函数判"可用(本地优先)"，
    # 结果回测静默跑在 09-01 的数据上，连续 3 天无人发现。
    max_date = None
    last_complete_date = None
    try:
        from models.database import get_db_session
        from sqlalchemy import text as _sa_text

        with get_db_session() as db:
            max_date = db.execute(_sa_text("SELECT MAX(trade_date) FROM daily_quote")).scalar()
            last_complete_date = db.execute(
                _sa_text(
                    """SELECT trade_date FROM daily_quote
                       GROUP BY trade_date
                       HAVING COUNT(*) >= :min_rows
                       ORDER BY trade_date DESC LIMIT 1"""
                ),
                {"min_rows": _MIN_ROWS_COMPLETE_DAY},
            ).scalar()
    except Exception as e:  # 库不可用 → 直接走网络，不阻断主流程
        logger.debug("本地库新鲜度检查失败，改用网络源: %s", e)
        _DB_FRESHNESS.update(checked_at=now, ok=False)
        return False

    # 没有任何完整交易日时，退回 MAX，行为与修复前一致（库里就那么点数据，
    # 走网络也补不回全市场，别在这里把自己拖垮）
    effective = last_complete_date or max_date
    if effective is None:
        _DB_FRESHNESS.update(checked_at=now, ok=False)
        return False

    max_allowed = (dt_date.today() - dt_timedelta(days=5)).isoformat()
    ok = str(effective) >= max_allowed

    truncated = (
        last_complete_date is not None and max_date is not None and max_date > last_complete_date
    )
    if truncated:
        # ⚠️ 关键取舍：此时**不**退回网络。本函数一返回 False，上层会对池中每只股票
        # 逐个发起网络请求 —— 1232 只 × 腾讯 fqkline 会立刻触发 WAF 频控，
        # 就是 09-03 那次 14min+ 雪崩的同一条路径。残缺的本地数据仍比打爆网络可取，
        # 但必须让这条告警出现在日志里，不能再静默。
        logger.warning(
            "⚠️ 本地行情库数据截断: MAX(trade_date)=%s 但该日起记录数 < %d，"
            "最后一个完整交易日=%s。回测将跑在截止 %s 的数据上。"
            "（灌库任务大概率被中断，请检查 qts_daily_backfill.py / automation-1784811393302）",
            max_date,
            _MIN_ROWS_COMPLETE_DAY,
            last_complete_date,
            last_complete_date,
        )

    _DB_FRESHNESS.update(checked_at=now, ok=ok)
    logger.info(
        "本地行情库新鲜度检查: 完整截止日=%s (MAX=%s)%s → %s",
        effective,
        max_date,
        " [截断!]" if truncated else "",
        "可用(本地优先)" if ok else "过旧(走网络)",
    )
    return ok


def _fetch_kline_from_db(ts_code: str, start_clean: str, end_clean: str) -> list[dict]:
    """本地库 daily_quote 取K线（无网络、无频控、无重试退避）

    返回格式与 fetch_kline_tencent 完全一致：
    [{trade_date, open, close, high, low, vol, amount}, ...]
    """
    if not _local_db_fresh():
        return []

    start_fmt = f"{start_clean[:4]}-{start_clean[4:6]}-{start_clean[6:8]}"
    end_fmt = f"{end_clean[:4]}-{end_clean[4:6]}-{end_clean[6:8]}"

    try:
        from models.database import get_db_session
        from sqlalchemy import text as _sa_text

        with get_db_session() as db:
            rows = db.execute(
                _sa_text(
                    """
                    SELECT trade_date, open, high, low, close, volume, amount
                    FROM daily_quote
                    WHERE ts_code = :ts_code
                      AND trade_date BETWEEN :start AND :end
                    ORDER BY trade_date
                    """
                ),
                {"ts_code": ts_code, "start": start_fmt, "end": end_fmt},
            ).fetchall()
    except Exception as e:
        logger.debug("本地库取数失败 %s: %s", ts_code, e)
        return []

    if not rows:
        return []

    klines: list[dict] = []
    for r in rows:
        try:
            klines.append(
                {
                    "trade_date": str(r[0]),
                    "open": float(r[1]),
                    "close": float(r[4]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "vol": int(float(r[5] or 0)),
                    "amount": float(r[6] or 0.0),
                }
            )
        except (TypeError, ValueError):
            continue
    return klines


def fetch_kline_tencent(ts_code: str, start_date: str, end_date: str) -> list[dict]:
    """通过腾讯财经 API 获取历史K线（最稳定，有本地缓存）

    2026-09-03 变更：本地库 daily_quote 优先。
    原因：腾讯 fqkline 两域名（web.ifzq / ifzq）对单 IP 有 WAF 频控，
    全市场 4579 只串行请求约 2000 次后稳定返回 HTTP 501，回测必然跑不完。
    本地库覆盖 5044 只 / 304 万行，且与腾讯前复权数据逐笔一致
    （已用 000001.SZ 2026-09-02 校验：OHLC/量完全对齐），
    故改本地优先；网络源保留为库缺失/库过旧时的补充。

    Args:
        ts_code: 股票代码（如 000001.SZ）
        start_date: 起始日期 YYYYMMDD 或 YYYY-MM-DD
        end_date: 结束日期 YYYYMMDD 或 YYYY-MM-DD

    Returns:
        K线数据列表 [{trade_date, open, close, high, low, vol, amount}, ...]
    """
    start_clean = start_date.replace("-", "")
    end_clean = end_date.replace("-", "")

    mem_key = _mem_cache_key("tx", ts_code, start_clean, end_clean)

    # === L0 内存缓存（最廉价，必须排在最前）===
    # 2026-09-03 修正: 初版把本地库查询排在内存缓存之前, 导致每次调用都打一次 DB,
    #   内存缓存形同虚设(回归测试 test_local_db_hit_populates_mem_cache 实锤:
    #   同参数二次调用仍触发第二次查库)。同参数在 11 策略 × N 只股票下会被反复命中,
    #   顺序错了等于把 DB QPS 放大一个量级。
    cached = _mem_cache.get(mem_key)
    if cached is not None:
        logger.debug("MemCache HIT: tx:%s [%s~%s]", ts_code, start_clean, end_clean)
        result: list[dict] = cached
        return result

    # === L1 本地库 daily_quote（无网络/无频控）===
    local = _fetch_kline_from_db(ts_code, start_clean, end_clean)
    if local:
        _mem_cache[mem_key] = local
        return local

    # 腾讯API需要 YYYY-MM-DD 格式
    start_fmt = f"{start_clean[:4]}-{start_clean[4:6]}-{start_clean[6:8]}"
    end_fmt = f"{end_clean[:4]}-{end_clean[4:6]}-{end_clean[6:8]}"

    # 归一化非标代码格式: SZ002636/SH603002 -> 002636.SZ/603002.SH
    # 根因: daily_kline 表混用两套格式, 非标码会被误判为北交所(bj)导致腾讯API请求失败
    _ts = ts_code.strip().upper()
    if "." not in _ts and len(_ts) >= 8 and _ts[:2] in ("SZ", "SH", "BJ"):
        _mkt, _num = _ts[:2], _ts[2:]
        _suffix = {"SZ": "SZ", "SH": "SH", "BJ": "BJ"}[_mkt]
        _ts = f"{_num}.{_suffix}"
    symbol = _ts.split(".", maxsplit=1)[0]
    suffix = _ts.rsplit(".", maxsplit=1)[-1].upper() if "." in _ts else "SZ"
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
                result = data
                return result
            else:
                logger.debug(
                    "缓存过期，重新获取: %s (age=%.0fs > ttl=%ds)", cache_file, age, cache_ttl
                )
    except Exception:
        logger.debug("腾讯K线: 缓存读取失败，跳过", cache_file=str(cache_file))

    data = None
    for attempt in range(3):
        # 逐次轮转 host：第一个失败(WAF 501/超时)时自动切备用域名
        base = _TENCENT_HOSTS[attempt % len(_TENCENT_HOSTS)]
        url = f"{base}?param={code},day,{start_fmt},{end_fmt},500,qfq"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            # HTTP 200 但业务码异常(WAF 拦截会返回非 0)→ 视同失败，切下一个 host
            if data and data.get("code") == 0:
                break
            data = None
        except Exception:
            data = None
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
        result: list[dict] = cached
        return result

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
                result = data
                return result
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
                output: list[dict] = result
                return output
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
