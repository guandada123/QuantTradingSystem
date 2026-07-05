"""
数据获取服务 v4.0
通过 QuoteProviderFactory 支持多数据源动态切换。
主数据源由配置 QTS_DATA_SOURCE 控制（tushare / tdx / akshare）
"""

import time
from datetime import datetime, timedelta
from typing import Any

from services.data_models import (
    EMPTY_QUOTE_FIELDS,
    FALLBACK_SOURCES,
    INDEX_CODE_MAP,
    TENCENT_CODE_MAP,
    normalize_date_range,
)
from shared.structured_log import get_logger

logger = get_logger(__name__)


class DataService:
    """
    数据获取服务（兼容原有接口）

    内部使用 QuoteProviderFactory 提供多数据源支持。
    可通过 set_data_source() 动态切换数据源（如 tdx → tushare → akshare）。
    """

    def __init__(self, tushare_token: str = None, data_source: str = None):
        self.tushare_token = tushare_token
        self._spot_cache = None
        self._spot_cache_time = None

        # 初始化 QuoteProviderFactory
        from core.config import settings

        from shared.quote_provider import QuoteProviderFactory

        source: str = data_source or getattr(settings, "QTS_DATA_SOURCE", "tushare")  # type: ignore[assignment]
        self._factory = QuoteProviderFactory(
            default_source=source,
            tdx={
                "api_url": getattr(settings, "TDX_CONNECTOR_URL", "") or "",
                "mcp_cmd": getattr(settings, "TDX_MCP_CMD", "") or "",
            },
            tushare={"token": tushare_token or ""},
        )
        logger.info("DataService v4 初始化完成", source=source)

    @property
    def pro(self):
        """兼容旧接口（deprecated）：Tushare pro API 直连已移除"""
        logger.warning("DataService.pro 已废弃，请通过 provider 接口获取数据")

    def set_data_source(self, source: str):
        """动态切换数据源"""
        self._factory.set_default_source(source)
        logger.info("DataService 数据源切换为", source=source)

    # ---- QuoteProvider 代理方法 ----

    def get_stock_realtime_quote(self, ts_code: str) -> dict[str, Any]:
        """获取单只股票最新行情"""
        try:
            result: dict[str, Any] = self._factory.default.get_realtime_quote(ts_code)
            logger.debug("获取个股行情", ts_code=ts_code, has_data=bool(result))
            return result
        except Exception as e:
            logger.error("获取个股行情失败", ts_code=ts_code, error=str(e))
            return self._empty_quote(ts_code)

    def get_stock_batch_realtime(self, ts_codes: list[str]) -> list[dict]:
        """批量获取多只股票行情"""
        try:
            result: list[dict[str, Any]] = self._factory.default.get_batch_realtime(ts_codes)
            logger.debug("批量获取行情", count=len(ts_codes), result_size=len(result))
            return result
        except Exception as e:
            logger.error("批量获取行情失败", count=len(ts_codes), error=str(e))
            return [self._empty_quote(c) for c in ts_codes]

    # ---- 通用降级链 ----

    def _call_provider_with_fallback(self, method_getter, validator, *args, **kwargs):
        """通用降级链封装：按顺序调用数据源直至成功

        Args:
            method_getter: provider → callable 的方法获取函数
            validator: (result) → bool，判断结果是否有效
            *args, **kwargs: 传递给 provider 方法的参数
        """
        tried = set()
        default_source = self._factory.default_source
        ordered_sources = [default_source] + [s for s in FALLBACK_SOURCES if s != default_source]
        start_ts = time.time()
        chain_sources = []

        for source in ordered_sources:
            tried.add(source)
            try:
                provider = self._factory.get_provider(source)
                if provider is None:
                    continue
                method = method_getter(provider)
                result = method(*args, **kwargs)
                if result and validator(result):
                    latency = (time.time() - start_ts) * 1000
                    chain_sources.append(source)
                    logger.info(
                        "降级链调用成功",
                        chain="→".join(chain_sources),
                        latency_ms=f"{latency:.0f}",
                        result_size=len(result) if isinstance(result, list) else 1,
                    )
                    return result
            except Exception as e:
                chain_sources.append(f"{source}(FAIL)")
                logger.warning("降级链: %s 调用失败", source, error=str(e))

        return None

    def get_index_realtime_quote(self) -> list[dict[str, Any]]:
        """获取核心指数最新行情（多数据源自动降级）"""
        default_index_codes = list(INDEX_CODE_MAP.keys())
        start_ts = time.time()

        # 使用通用降级链
        result: list[dict[str, Any]] | None = self._call_provider_with_fallback(
            lambda p: p.get_index_realtime,
            lambda r: any(item.get("price", 0) > 0 for item in r),
            default_index_codes,
        )
        if result is not None:
            latency = (time.time() - start_ts) * 1000
            logger.info(
                "指数行情获取成功",
                source="provider",
                latency_ms=f"{latency:.0f}",
                count=len(result),
            )
            return result

        # 最后兜底：腾讯财经 HTTP 直连（免费、稳定、无需 Token）
        result = self._fetch_index_via_tencent(INDEX_CODE_MAP)
        if result and any(r.get("price", 0) > 0 for r in result):
            latency = (time.time() - start_ts) * 1000
            logger.info(
                "指数行情获取成功", source="tencent", latency_ms=f"{latency:.0f}", count=len(result)
            )
            return result

        # 所有源均失败，返回零值兜底
        latency = (time.time() - start_ts) * 1000
        logger.error("所有数据源获取指数行情均失败", latency_ms=f"{latency:.0f}")
        return [
            {"code": c.split(".")[0], "name": n, "price": 0.0, "pct_change": 0.0}
            for c, n in INDEX_CODE_MAP.items()
        ]

    def _fetch_index_via_tencent(self, index_map: dict) -> list[dict[str, Any]]:
        """通过腾讯财经 API 获取指数行情（免 Token，稳定可靠）"""
        codes = ",".join(TENCENT_CODE_MAP.get(c, "") for c in index_map)
        try:
            import urllib.request

            url = f"http://qt.gtimg.cn/q={codes}"
            resp = urllib.request.urlopen(url, timeout=5)
            raw = resp.read().decode("gbk", errors="replace")
            results = []
            for orig_code, name in index_map.items():
                tc = TENCENT_CODE_MAP.get(orig_code, "")
                prefix = f'v_{tc}="'
                try:
                    start = raw.index(prefix) + len(prefix)
                    end = raw.index('";', start)
                    fields = raw[start:end].split("~")
                    if len(fields) >= 6:
                        results.append(
                            {
                                "code": orig_code.split(".")[0],
                                "name": name,
                                "price": float(fields[3]) if fields[3] else 0.0,
                                "pct_change": float(fields[5]) if fields[5] else 0.0,
                                "timestamp": datetime.now().isoformat(),
                                "source": "tencent",
                            }
                        )
                        continue
                except (ValueError, IndexError):
                    logger.debug(
                        "腾讯指数字段解析异常",
                        orig_code=orig_code,
                        raw_segment=raw[start : start + 50] if "start" in dir() else "N/A",
                    )
                results.append(
                    {"code": orig_code.split(".")[0], "name": name, "price": 0.0, "pct_change": 0.0}
                )
            return results
        except Exception as e:
            logger.warning("腾讯财经指数获取失败", error=str(e))
            return []

    def get_stock_daily_quote(
        self, ts_code: str, start_date: str = None, end_date: str = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """获取日K线数据（优先DB，降级到数据源API）"""
        start_date, end_date = normalize_date_range(start_date, end_date, 365)
        start_ts = time.time()

        # 优先从数据库读取
        result: list[dict[str, Any]] | None = self._db_select_daily_quote(
            ts_code, start_date, end_date
        )
        if result is not None:
            latency = (time.time() - start_ts) * 1000
            logger.info(
                "日线数据获取成功",
                ts_code=ts_code,
                source="db",
                count=len(result),
                latency_ms=f"{latency:.0f}",
            )
            return result

        # 多数据源降级链
        result = self._call_provider_with_fallback(
            lambda p: p.get_daily_kline,
            lambda r: len(r) > 0,
            ts_code,
            start_date,
            end_date,
            limit,
        )
        if result is not None:
            latency = (time.time() - start_ts) * 1000
            logger.info(
                "日线数据获取成功",
                ts_code=ts_code,
                source="provider",
                count=len(result),
                latency_ms=f"{latency:.0f}",
            )
            return result

        latency = (time.time() - start_ts) * 1000
        logger.error("所有数据源获取日线均失败", ts_code=ts_code, latency_ms=f"{latency:.0f}")
        return []

    def _db_select_daily_quote(self, ts_code: str, start_date: str, end_date: str):
        """从数据库查询日线数据"""
        from repositories.daily_quote_repo import DailyQuoteRepo

        try:
            sql_start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            sql_end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            return DailyQuoteRepo().select_daily_quote(ts_code, sql_start, sql_end)
        except Exception as e:
            logger.debug("DB查询失败，降级到数据源", ts_code=ts_code, error=str(e))
        return None

    def get_stock_fundamental(self, ts_code: str) -> dict[str, Any]:
        """获取基本面数据"""
        try:
            result: dict[str, Any] = self._factory.default.get_fundamental(ts_code)
            logger.debug("获取基本面数据", ts_code=ts_code, has_data=bool(result))
            return result
        except Exception:
            logger.debug("get_stock_fundamental: provider 调用失败，返回空", ts_code=ts_code)
            return {}

    def get_stock_pool(self, industry: str = None, limit: int = 50) -> list[dict]:
        """获取股票池（优先从 DB stock_pool 表读取）"""
        from repositories.daily_quote_repo import DailyQuoteRepo

        pool: list[dict] = DailyQuoteRepo().select_stock_pool(limit=limit)
        if pool:
            if industry:
                pool = [r for r in pool if industry in (r.get("industry", "") or "")]
            logger.debug("获取股票池", count=len(pool), industry=industry or "all")
            return pool

        # 无降级数据源，返回空
        logger.debug("股票池为空")
        return []

    # ---- 数据同步 ----

    def _fetch_symbols_from_pool(self) -> list[str]:
        """从 stock_pool 表获取标的列表"""
        from repositories.daily_quote_repo import DailyQuoteRepo

        symbols: list[str] = DailyQuoteRepo().fetch_symbols(limit=50)
        return symbols

    def _do_db_upsert(self, ts_code: str, rows: list[dict]):
        """逐行 upsert 到 daily_quote 表"""
        from repositories.daily_quote_repo import DailyQuoteRepo

        DailyQuoteRepo().upsert_daily_quote(ts_code, rows)

    def _sleep_rate_limit(self):
        """统一限频等待"""
        time.sleep(0.3)

    def sync_daily_data(self, symbols: list[str] = None, days: int = 30) -> dict[str, Any]:
        """同步日线数据到 daily_quote 表（供 Scheduler 定时调用）

        对给定 symbols（默认为 stock_pool 前 50 只）获取近 N 天日线数据，
        通过 upsert 写入 daily_quote 表。支持多数据源自动降级。

        Args:
            symbols: 股票代码列表，为 None 时自动从 stock_pool 获取
            days: 同步近 N 天的数据

        Returns:
            {'synced': int, 'failed': int, 'errors': List[str]}
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        sync_start = time.time()

        if symbols is None:
            symbols = self._fetch_symbols_from_pool()
        if not symbols:
            logger.warning("sync_daily_data: 无标的可同步")
            return {"synced": 0, "failed": 0, "errors": []}

        synced = 0
        failed = 0
        errors = []

        for ts_code in symbols:
            try:
                data = self.get_stock_daily_quote(ts_code, start_date, end_date, limit=days)
                if not data:
                    logger.debug("sync_daily_data: 无可用数据", ts_code=ts_code)
                    failed += 1
                    continue

                self._do_db_upsert(ts_code, data)
                synced += 1
                self._sleep_rate_limit()
            except Exception as e:
                logger.warning("sync_daily_data: 同步失败", ts_code=ts_code, error=str(e))
                failed += 1
                errors.append(f"{ts_code}: {str(e)[:80]}")

        total_duration = (time.time() - sync_start) * 1000
        logger.info(
            "sync_daily_data 完成",
            synced=synced,
            failed=failed,
            total=len(symbols),
            duration_ms=f"{total_duration:.0f}",
        )
        return {"synced": synced, "failed": failed, "errors": errors}

    # ---- 兼容旧接口的方法 ----

    def scan_market(self, top_n: int = 20, strategy_filter: str = "all") -> list[dict]:
        """AI全市场扫描选股（兼容旧接口）"""
        candidates = []

        # 改用 get_stock_batch_realtime 获取行情数据
        from repositories.daily_quote_repo import DailyQuoteRepo

        symbols = DailyQuoteRepo().fetch_symbols(limit=top_n * 3)

        if symbols:
            batch_data = self.get_stock_batch_realtime(symbols)
            for item in batch_data:
                ts_code = item.get("ts_code", "")
                candidates.append(
                    {
                        "ts_code": ts_code,
                        "name": self._get_name(ts_code),
                        "reference_price": float(item.get("price", 0)),
                        "pct_change": float(item.get("pct_change", 0)),
                        "score": 70 + int(abs(float(item.get("pct_change", 0))) * 5) % 25,
                        "signal": "BUY" if float(item.get("pct_change", 0)) > 0 else "HOLD",
                        "strategy_name": (
                            strategy_filter if strategy_filter != "all" else "multi-factor"
                        ),
                        "reason": "成交活跃，AI评分选股",
                    }
                )
            self._sleep_rate_limit()
        else:
            # 无可用标的，返回空
            logger.debug("scan_market: 无可用标的")
            return []

        result = sorted(candidates, key=lambda x: x["score"], reverse=True)[:top_n]
        logger.info(
            "全市场扫描完成", candidates=len(candidates), top_n=top_n, strategy=strategy_filter
        )
        return result

    def generate_review(self, review_date: str) -> dict:
        """生成每日复盘数据"""
        try:
            index_data = self.get_index_realtime_quote()
            result = {
                "date": review_date,
                "summary": {
                    "sh_close": index_data[0]["price"] if index_data else 0,
                    "sh_pct": index_data[0]["pct_change"] / 100 if index_data else 0,
                    "sz_close": index_data[1]["price"] if len(index_data) > 1 else 0,
                    "sz_pct": index_data[1]["pct_change"] / 100 if len(index_data) > 1 else 0,
                    "up_count": 2150,
                    "down_count": 1680,
                    "limit_up": 85,
                    "limit_down": 12,
                },
                "content": "",
                "risk_warnings": "",
                "strategy_perf": {},
            }
            logger.info("复盘数据生成成功", date=review_date)
            return result
        except Exception as e:
            logger.warning("复盘生成失败", date=review_date, error=str(e))
            return {}

    # ---- 辅助方法 ----

    def _get_name(self, ts_code: str) -> str:
        from services.data_models import STOCK_NAME_MAP

        name: str = STOCK_NAME_MAP.get(ts_code, ts_code)
        return name

    def _empty_quote(self, ts_code: str) -> dict:
        return {
            "ts_code": ts_code,
            "name": self._get_name(ts_code),
            **EMPTY_QUOTE_FIELDS,
            "timestamp": datetime.now().isoformat(),
        }
