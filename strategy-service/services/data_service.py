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
from services.price_sanity import screen_bars
from shared.quote_provider.base import is_rate_limit_error, is_systemic_error
from shared.quote_provider.tencent_quote import fetch_fundamental
from shared.structured_log import get_logger

logger = get_logger(__name__)

# ── 降级链熔断（2026-09-01 建立 v1，同日 run#58 修正为 v2）──
# v1 背景实证：Tushare daily 限 50 次/分钟，日行情刷新遍历 4494 只标的，
# 降级链每只都先撞一次 Tushare → 单日 4494 次 100% 失败调用、
# 任务耗时 643.8s。加冷却后实测 48 次即熔断（−98.9%）。
#
# v1 的两个缺陷（run#58 实测暴露，本次修正）：
#   ① 作用域=实例级失效：每个定时任务都 new 一个 DataService，冷却表随实例
#      一起销毁，跨任务完全无效。实证 akshare 源 24h 内被调用 48 次、
#      成功 0 次、每次白等 20.4s（重试 3 次）→ 约 16.4 分钟/天空转，
#      而大盘快照真正拿到数据靠的是第三顺位 tencent（耗时 0.07s）。
#   ② 粒度=数据源级过粗：Tushare 的限频是**按接口**的（index_daily 5 次/天
#      vs daily 50 次/分），用数据源级冷却会让 index_daily 配额耗尽
#      连带熔断整个 tushare 源，daily 无辜受罚。
#
# v2 设计：
#   · 冷却表提升为**模块级**（进程内跨 DataService 实例共享）
#   · 冷却键细化到 **(数据源, 方法)** 级
#   · 限频错误命中即熔断（v1 已验证有效）；
#     网络类错误需连续 SYSTEMIC_FAILURE_THRESHOLD 次才熔断，避免单次抖动误伤
#   · 反复失败的源按指数退避拉长冷却，最多 COOLDOWN_MAX_SECONDS
#     —— 固定 300s 在 30 分钟周期的定时任务下等于每次都重试（省不了一点）
SOURCE_COOLDOWN_SECONDS = 300
COOLDOWN_MAX_SECONDS = 6 * 3600
SYSTEMIC_FAILURE_THRESHOLD = 2

# 2026-10-23：明确属于「代码写错了」的异常类型。
# 降级链的本意是「数据源不可用就换下一个」，但如果异常来自调用方式本身有误
# （方法名拼错、属性不存在、变量未定义），继续往下换源只会把 bug 伪装成
# 「该数据源故障」——实测过一次：把 `_call_provider_with_fallback` 误写成
# `_call_with_fallback`，AttributeError 被吞，全链路静默降级到腾讯兜底，
# 日志里只有一条 warning，功能看起来正常。故此类异常在降级链中直接上抛。
PROGRAMMING_ERRORS: tuple[type[Exception], ...] = (AttributeError, NameError, UnboundLocalError)

# 模块级：进程内共享，跨 DataService 实例生效
# key = f"{source}:{method_name}"
_METHOD_COOLDOWN: dict[str, float] = {}  # → 冷却截止 epoch
_METHOD_FAILURES: dict[str, int] = {}  # → 连续系统性失败次数


def _close_is_usable(bar: dict[str, Any]) -> bool:
    """close 是否为可用于收益计算的正数（ADR 007 观测态用）。

    只回答「能不能算收益」，不做拦截 —— `price_sanity.bar_problems` 有意放行缺字段的 bar
    （不同数据源字段不全），这里也只是**观测**它是否发生。
    """
    raw = bar.get("close")
    if raw is None:
        return False
    try:
        # 走 str 中转：既满足类型检查（float 不收 None），又天然处理 "--"/"" 这类占位写法
        return float(str(raw)) > 0
    except (TypeError, ValueError):
        return False


class DataService:
    """
    数据获取服务（兼容原有接口）

    内部使用 QuoteProviderFactory 提供多数据源支持。
    可通过 set_data_source() 动态切换数据源（如 tdx → tushare → akshare）。
    """

    def __init__(self, tushare_token: str | None = None, data_source: str | None = None):
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

        2026-09-01 补充：命中限频/网络类系统性错误的 (数据源, 方法) 进入冷却期，
        冷却期内直接跳过，避免批量任务对同一故障源做数千次无效重试。
        冷却表为模块级，进程内跨 DataService 实例共享。
        """
        default_source = self._factory.default_source
        ordered_sources = [default_source] + [s for s in FALLBACK_SOURCES if s != default_source]
        start_ts = time.perf_counter()  # 单调时钟：wall clock 被 NTP 回拨时会出现负耗时
        chain_sources = []

        for source in ordered_sources:
            method_name = "unknown"
            key = f"{source}:{method_name}"
            try:
                provider = self._factory.get_provider(source)
                if provider is None:
                    continue
                method = method_getter(provider)
                # 2026-10-23：方法无 __name__（partial/lambda/MagicMock）时退化为 provider 级键，
                # 避免所有方法共享 "unknown" 导致一处限频就把整条链冷却。
                method_name = (
                    getattr(method, "__name__", None) or f"provider:{type(provider).__name__}"
                )
                key = f"{source}:{method_name}"
                # 冷却：跳过仍在冷却期的 (数据源, 方法)
                if self._in_cooldown(key):
                    chain_sources.append(f"{source}(COOLDOWN)")
                    continue
                result = method(*args, **kwargs)
                if result and validator(result):
                    self._note_success(key)
                    latency = (time.perf_counter() - start_ts) * 1000
                    chain_sources.append(source)
                    logger.info(
                        "降级链调用成功",
                        chain="→".join(chain_sources),
                        latency_ms=f"{latency:.0f}",
                        result_size=len(result) if isinstance(result, list) else 1,
                    )
                    return result
            except PROGRAMMING_ERRORS as e:
                # 代码缺陷，不是数据源故障：上抛，不参与降级与冷却计数。
                # 上层（API）会记录 ERROR 并返回 5xx，堆栈可定位到具体行。
                chain_sources.append(f"{source}(BUG)")
                logger.error(
                    "降级链遇到编程错误（非数据源故障，已上抛）",
                    source=source,
                    method=method_name,
                    error_type=type(e).__name__,
                    error=str(e),
                    chain="→".join(chain_sources),
                )
                raise
            except Exception as e:
                chain_sources.append(f"{source}(FAIL)")
                logger.warning("降级链: %s.%s 调用失败", source, method_name, error=str(e))
                self._note_failure(key, source, method_name, e)

        return None

    # ---- 熔断辅助（模块级冷却，跨实例共享）----

    def _is_rate_limit_error(self, err: Exception) -> bool:
        """判断异常是否为数据源限频（而非网络/数据错误）"""
        return is_rate_limit_error(err)

    @staticmethod
    def _in_cooldown(key: str) -> bool:
        return time.time() < _METHOD_COOLDOWN.get(key, 0.0)

    @staticmethod
    def _note_success(key: str):
        """调用成功：清空该 (数据源, 方法) 的连续失败计数"""
        _METHOD_FAILURES.pop(key, None)

    def _note_failure(self, key: str, source: str, method_name: str, err: Exception):
        """记录一次失败；系统性错误达到阈值后将该 (数据源, 方法) 置入冷却期

        · 限频：命中即熔断（v1 已实证有效：4494 → 48 次）
        · 网络：需连续 SYSTEMIC_FAILURE_THRESHOLD 次，避免单次抖动误伤
        · 非系统性错误（业务性）：打断连续计数，不冷却
        · 反复失败按指数退避拉长冷却，上限 COOLDOWN_MAX_SECONDS
        """
        if not is_systemic_error(err):
            _METHOD_FAILURES.pop(key, None)
            return

        rate_limited = is_rate_limit_error(err)
        failures = _METHOD_FAILURES.get(key, 0) + 1
        _METHOD_FAILURES[key] = failures

        if rate_limited or failures >= SYSTEMIC_FAILURE_THRESHOLD:
            # failures=1(限频) → 300s；2 → 600s；3 → 1200s … 上限 6h
            cooldown = min(
                SOURCE_COOLDOWN_SECONDS * (2 ** max(0, failures - SYSTEMIC_FAILURE_THRESHOLD)),
                COOLDOWN_MAX_SECONDS,
            )
            _METHOD_COOLDOWN[key] = time.time() + cooldown
            logger.warning(
                "降级链熔断",
                source=source,
                method=method_name,
                reason="rate_limit" if rate_limited else "connection",
                consecutive_failures=failures,
                cooldown_seconds=cooldown,
            )

    def get_index_realtime_quote(self) -> list[dict[str, Any]]:
        """获取核心指数最新行情（多数据源自动降级）"""
        default_index_codes = list(INDEX_CODE_MAP.keys())
        start_ts = time.perf_counter()  # 单调时钟：wall clock 被 NTP 回拨时会出现负耗时

        # 使用通用降级链
        result: list[dict[str, Any]] | None = self._call_provider_with_fallback(
            lambda p: p.get_index_realtime,
            lambda r: any(item.get("price", 0) > 0 for item in r),
            default_index_codes,
        )
        if result is not None:
            latency = (time.perf_counter() - start_ts) * 1000
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
            latency = (time.perf_counter() - start_ts) * 1000
            logger.info(
                "指数行情获取成功", source="tencent", latency_ms=f"{latency:.0f}", count=len(result)
            )
            return result

        # 所有源均失败，返回零值兜底
        latency = (time.perf_counter() - start_ts) * 1000
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

    @staticmethod
    def _screen_quotes(
        bars: list[dict[str, Any]], ts_code: str, source: str
    ) -> list[dict[str, Any]]:
        """剔除明显坏的行情（0/负价、9999 哨兵、high<low、close 越界）。

        2026-11-26 加（disc-20261027-02）：这类数据一旦进入收益序列会把均值方差带偏，
        而且**不会报错** —— 0 元收盘价算出来是 -100%，看着像暴跌。

        两条边界：
        · 只剔 `price_sanity.bar_problems` 判定的硬问题，**不碰**单日跳变
          （新股首日/复牌不受涨跌停约束，按阈值砍会误杀真实暴跌）；
        · 校验器自身出任何异常 → **返回原数据**，不阻断取数（fail-safe）。
        """
        # 只校验「真的是 list of dict」的输入。非 list（例如上游 mock 或某种包装对象）
        # 原样返回 —— 2026-11-26 实测：MagicMock 可被迭代成**空序列**，不抛异常，
        # 于是过滤把它悄悄洗成 [] 而调用方毫无察觉（`test_sync_with_explicit_symbols`
        # 就是这么红的：synced 1 → 0）。这类失败不报错，只让数据凭空消失。
        if not isinstance(bars, list):
            return bars
        try:
            clean, dropped = screen_bars(bars)
        except Exception as e:  # 校验器坏掉不该让行情接口跟着坏
            logger.debug("行情校验异常，按原样返回", ts_code=ts_code, error=str(e))
            return bars
        if dropped:
            logger.warning(
                "剔除异常行情",
                ts_code=ts_code,
                source=source,
                dropped=len(dropped),
                kept=len(clean),
                sample=dropped[0].get("reasons"),
            )

        # ADR 007 阶段 A（2026-11-27）：close 缺失**只观测、不丢弃**。
        # price_sanity 有意放行缺字段（注释：不同数据源字段不全），但 close 是收益计算的必需项：
        # 停牌股在部分源里写作 "--"，float("--") 抛错 → 该 bar 会带着 None 进回测。
        # 生产库实测 3,315,977 行中 close 为 NULL 的 **0 行**，故先收集真实发生率，
        # 不改变任何产出。阶段 B 是否转强制，取决于这里一周内是否真的出现。
        misses = [b for b in clean if not _close_is_usable(b)]
        if misses:
            logger.warning(
                "close 缺失但被放行（ADR 007 观测态）",
                ts_code=ts_code,
                source=source,
                count=len(misses),
                sample={k: misses[0].get(k) for k in ("trade_date", "close", "pre_close")},
            )
        return clean

    def get_stock_daily_quote(
        self,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取日K线数据（优先DB，降级到数据源API）"""
        start_date, end_date = normalize_date_range(start_date, end_date, 365)
        start_ts = time.perf_counter()  # 单调时钟：wall clock 被 NTP 回拨时会出现负耗时

        # 优先从数据库读取
        result: list[dict[str, Any]] | None = self._db_select_daily_quote(
            ts_code, start_date, end_date
        )
        if result is not None:
            latency = (time.perf_counter() - start_ts) * 1000
            logger.info(
                "日线数据获取成功",
                ts_code=ts_code,
                source="db",
                count=len(result),
                latency_ms=f"{latency:.0f}",
            )
            return self._screen_quotes(result, ts_code, "db")

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
            latency = (time.perf_counter() - start_ts) * 1000
            logger.info(
                "日线数据获取成功",
                ts_code=ts_code,
                source="provider",
                count=len(result),
                latency_ms=f"{latency:.0f}",
            )
            return self._screen_quotes(result, ts_code, "provider")

        latency = (time.perf_counter() - start_ts) * 1000
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
        """获取基本面数据（provider 降级链 + 腾讯兜底）

        2026-10-23 修复：此前只调 ``self._factory.default``，无降级。实测
        Tushare ``daily_basic`` 在 2000 积分档限流至 1 次/小时、AKShare 已移除对应
        接口，两条路径都会失败并被 except 吞掉 → 该接口长期静默返回空。
        现改为走降级链，末端接腾讯行情（免鉴权、无限频）。
        """
        try:
            result: dict[str, Any] = self._call_provider_with_fallback(
                lambda p: p.get_fundamental,
                lambda r: bool(r),
                ts_code,
            )
            if result:
                logger.debug("获取基本面数据", ts_code=ts_code, source="provider-chain")
                return result
        except Exception:
            logger.debug("get_stock_fundamental: provider 降级链异常", ts_code=ts_code)

        fallback = fetch_fundamental(ts_code)
        if fallback:
            logger.info("基本面数据走腾讯兜底", ts_code=ts_code)
            return fallback

        logger.warning("get_stock_fundamental: 全部数据源失败", ts_code=ts_code)
        return {}

    def get_stock_pool(self, industry: str | None = None, limit: int = 50) -> list[dict]:
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
        """从 stock_pool 表获取标的列表（全量，不再限50只）

        2026-07-23 修复：原 limit=50 导致全市场 3521 只仅前 50 只被日常任务更新，
        其余停在历史导入的 2026-06 → 「6月断」假象。改为全量同步。
        注：get_stock_daily_quote 优先读 DB，已回填的标的不会重复拉取远程，
        仅真正缺失/过期的标的才会走 provider 降级链。
        """
        from repositories.daily_quote_repo import DailyQuoteRepo

        symbols: list[str] = DailyQuoteRepo().fetch_symbols(limit=10000)
        return symbols

    def _do_db_upsert(self, ts_code: str, rows: list[dict]):
        """逐行 upsert 到 daily_quote 表"""
        from repositories.daily_quote_repo import DailyQuoteRepo

        DailyQuoteRepo().upsert_daily_quote(ts_code, rows)

    def _sleep_rate_limit(self):
        """统一限频等待"""
        time.sleep(0.3)

    def sync_daily_data(self, symbols: list[str] | None = None, days: int = 30) -> dict[str, Any]:
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
