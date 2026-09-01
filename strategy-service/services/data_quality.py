"""
数据质量监控服务
检查行情数据新鲜度、完整性、异常值，通过 Prometheus 指标暴露
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

from shared.trading_calendar import is_trading_time, to_beijing

logger = logging.getLogger("data-quality")

# 合法 SQL 标识符（表名/列名白名单，防拼接注入）
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 数据质量 Prometheus 指标
data_freshness_seconds = Gauge(
    "data_freshness_seconds", "Seconds since last successful data update", ["data_source"]
)
data_gap_count = Gauge("data_gap_count", "Number of detected data gaps", ["data_source", "symbol"])
data_anomaly_count = Counter(
    "data_anomaly_count",
    "Number of anomalous data points detected",
    ["data_source", "anomaly_type"],
)
data_quality_score = Gauge(
    "data_quality_score", "Overall data quality score (0-100)", ["data_source"]
)
data_update_latency = Histogram(
    "data_update_latency_seconds", "Data update operation latency", ["data_source"]
)

# 数据源状态
source_online = Gauge("data_source_online", "Data source online status (1=online)", ["source_name"])


@dataclass
class DataQualityRule:
    """数据质量检查规则"""

    name: str
    source: str
    max_freshness_minutes: int = 30  # 最大数据新鲜度（分钟）
    check_weekend: bool = False  # 是否检查周末
    check_gaps: bool = True  # 是否检查数据缺失
    check_anomalies: bool = True  # 是否检查异常值
    # 真实新鲜度来源：查该表该列的最新值。留空则无数据库真值（见 _probe_latest）
    db_table: str | None = None
    db_ts_col: str | None = None
    # True = 盘中数据源。收盘后本就不会更新，非交易时段不应判陈旧
    market_hours_only: bool = False


class _Probe:
    """_probe_latest() 的返回状态（不用 None 表达，避免与「空表」歧义）。"""

    UNMAPPED = "unmapped"  # 该数据源没有配置库表 → 退回进程内记录
    ERROR = "error"  # 查询失败 → 无法判定，按不通过计（fail-safe）
    EMPTY = "empty"  # 表存在但 0 行 → 从未采集过
    OK = "ok"


class DataQualityMonitor:
    """数据质量监控器"""

    def _now(self) -> datetime:
        """可 mock 的时间获取方法"""
        return datetime.now()

    def _today(self) -> date:
        """可 mock 的日期获取方法。

        按**北京时间**取值：容器内 TZ=UTC，``date.today()`` 在北京 00:00–08:00
        期间会返回前一天，导致交易日判断整体错位一天。
        """
        return to_beijing(self._now()).date()

    def __init__(self):
        # db_table/db_ts_col = 新鲜度的数据库真值来源。
        # 此前 freshness 只读进程内 self.last_update，而 mark_update() 在生产侧
        # **零调用** —— 于是 last_update 恒为 __init__ 播种的启动时刻，
        # 评分退化成「容器运行时长」的纯函数（<1h→100、1h~24h→55、>24h→25），
        # 与真实数据毫无关系（2026-09-02 实测：6 次 100→55 跃迁全部落在重启后
        # 60~82 分钟）。改为查库后，评分才真正反映「数据有多旧」。
        self.rules: list[DataQualityRule] = [
            DataQualityRule(
                "每日行情",
                "daily_quote",
                max_freshness_minutes=24 * 60,
                db_table="daily_quote",
                db_ts_col="updated_at",
            ),
            DataQualityRule(
                "实时行情",
                "realtime_quote",
                max_freshness_minutes=10,
                db_table="minute_quote_metadata",
                db_ts_col="updated_at",
                market_hours_only=True,
            ),
            DataQualityRule(
                "指数行情",
                "index_quote",
                max_freshness_minutes=10,
                db_table="index_snapshots",
                db_ts_col="recorded_at",
                market_hours_only=True,
            ),
            # 北向资金：QTS 库内无对应存储表（Claw 侧用东财 kamt 接口，未落 QTS）。
            # 保持未映射 → 有数据接入前会稳定判不通过，属如实暴露缺口。
            DataQualityRule(
                "北向资金",
                "northbound_flow",
                max_freshness_minutes=60,
                market_hours_only=True,
            ),
            DataQualityRule(
                "股票池",
                "stock_pool",
                max_freshness_minutes=24 * 60,
                db_table="stock_pool",
                db_ts_col="updated_at",
            ),
        ]
        self.last_check_time: datetime | None = None
        self.last_update: dict[str, datetime] = {}
        # 初始化所有规则的数据新鲜度时间戳为当前时间，避免启动时因"从未更新"全部扣分
        for rule in self.rules:
            self.last_update[rule.source] = self._now()

    def is_trading_day(self) -> bool:
        """判断是否为A股交易日（简化版：周一至周五，非中国节假日）"""
        today = self._today()
        if today.weekday() >= 5:  # 周六日
            return False
        return True

    def is_trading_hours(self) -> bool:
        """判断是否在A股交易时段（**北京时间**口径）。

        复用 :mod:`shared.trading_calendar` 单一真源。此前直接拿 ``_now().hour``
        与 ``CHINA_MARKET_HOURS=(9,15)`` 比较，而 ``_now()`` 在容器内是 **UTC**
        —— 于是"交易时段"实际被判成北京时间 17:00–23:00，与真实盘中完全错位。
        """
        return is_trading_time(self._now())

    def mark_update(self, source: str):
        """标记数据源已更新"""
        self.last_update[source] = self._now()
        data_freshness_seconds.labels(data_source=source).set(0)

    async def check_data_source_online(self, source_name: str) -> bool:
        """检查数据源是否在线"""
        try:
            import akshare as ak

            if source_name == "akshare":
                # 尝试获取指数日线（轻量调用，避免 stock_zh_index_spot_em 远端断连）
                df = ak.stock_zh_index_daily(symbol="sh000001")
                online = len(df) > 0
            elif source_name == "tushare":
                online = True  # Tushare 不在这里做实际连接测试
            else:
                online = True

            source_online.labels(source_name=source_name).set(1 if online else 0)
            return online
        except Exception as e:
            logger.warning(f"数据源 {source_name} 离线: {e}")
            source_online.labels(source_name=source_name).set(0)
            return False

    def _probe_latest(self, rule: DataQualityRule) -> tuple[str, datetime | None]:
        """探测该数据源在数据库中的真实最后更新时间。

        Returns:
            ``(_Probe.OK, ts)`` / ``(_Probe.EMPTY, None)`` / ``(_Probe.ERROR, None)``
            / ``(_Probe.UNMAPPED, None)``
        """
        if not (rule.db_table and rule.db_ts_col):
            return _Probe.UNMAPPED, None
        # 表名/列名无法参数化，只能拼进 SQL —— 故用白名单把输入锁死成合法标识符
        if not (_IDENT_RE.match(rule.db_table) and _IDENT_RE.match(rule.db_ts_col)):
            logger.warning(f"数据质量: {rule.source} 的库表标识不合法，跳过库探测")
            return _Probe.UNMAPPED, None
        try:
            from models.database import get_db_session
            from sqlalchemy import text

            with get_db_session() as db:
                # noqa: S608 - 表名/列名已由 _IDENT_RE 白名单校验，非外部输入
                ts = db.execute(
                    text(f"SELECT MAX({rule.db_ts_col}) FROM {rule.db_table}")  # noqa: S608
                ).scalar()
        except Exception as e:  # noqa: BLE001 - 探测失败不得拖垮巡检主循环
            logger.warning(f"数据质量: 查询 {rule.source} 最新时间失败: {e}")
            return _Probe.ERROR, None
        return (_Probe.OK, ts) if ts is not None else (_Probe.EMPTY, None)

    async def check_freshness(self, rule: DataQualityRule) -> tuple[bool, float]:
        """检查数据新鲜度，返回 (是否正常, 延迟秒数)

        延迟一律按**北京时间**计算：库里的时间列是 naive，容器内写入方按 UTC
        落库，直接用 ``_now() - last`` 在不同时区下会得到不同结果。
        """
        # 盘中数据源：非交易时段本就不会更新，判陈旧只会制造噪音
        if rule.market_hours_only and not self.is_trading_hours():
            return True, 0.0

        status, ts = self._probe_latest(rule)
        if status == _Probe.ERROR:
            # 查不到真值 → 无法判定，按不通过计（fail-safe）
            return False, float("inf")
        if status == _Probe.EMPTY:
            # 表存在但 0 行：从未采集过，不是"旧"，是"没有"
            return False, float("inf")

        last = ts if status == _Probe.OK else self.last_update.get(rule.source)
        if last is None:
            # 从未更新过的数据源
            return False, float("inf")

        now = to_beijing(self._now())
        delay = (now - to_beijing(last)).total_seconds()

        # 非交易日跳过检查
        if not self.is_trading_day() and not rule.check_weekend:
            return True, delay

        max_delay = rule.max_freshness_minutes * 60
        is_fresh = delay < max_delay

        data_freshness_seconds.labels(data_source=rule.source).set(delay)
        return is_fresh, delay

    async def check_gaps(self, source: str, symbol: str, timestamps: list[datetime]) -> int:
        """检查数据时间序列是否有缺失（数据间隔）"""
        if len(timestamps) < 2:
            return 0

        gaps = 0
        expected_interval = timedelta(minutes=1)  # 预期1分钟间隔

        for i in range(1, len(timestamps)):
            actual_interval = timestamps[i] - timestamps[i - 1]
            if actual_interval > expected_interval * 3:  # 超过3倍预期间隔算缺失
                gaps += 1

        data_gap_count.labels(data_source=source, symbol=symbol).set(gaps)
        return gaps

    async def check_anomalies(
        self, source: str, values: list[float], threshold: float = 3.0
    ) -> int:
        """检查异常值（Z-score 方法）"""
        if len(values) < 10:
            return 0

        import statistics

        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0

        if stdev == 0:
            return 0

        anomalies = 0
        for v in values:
            z_score = abs((v - mean) / stdev)
            if z_score > threshold:
                anomalies += 1
                data_anomaly_count.labels(data_source=source, anomaly_type="zscore").inc()

        # 额外检查：负价格 / 超大波动
        for v in values:
            if v < 0:
                data_anomaly_count.labels(data_source=source, anomaly_type="negative_price").inc()
                anomalies += 1
            if v > 100000:  # 价格超过10万
                data_anomaly_count.labels(data_source=source, anomaly_type="extreme_value").inc()
                anomalies += 1

        return anomalies

    async def run_check(self) -> dict:
        """运行全部数据质量检查"""
        results: dict[str, Any] = {
            "timestamp": self._now().isoformat(),
            "trading_day": self.is_trading_day(),
            "trading_hours": self.is_trading_hours(),
            "checks": [],
            "overall_score": 100,
        }

        # 1. 检查数据源在线状态
        for source in ["akshare", "tushare"]:
            online = await self.check_data_source_online(source)
            results["checks"].append(
                {
                    "type": "source_online",
                    "source": source,
                    "online": online,
                    "passed": online,
                }
            )
            if not online:
                results["overall_score"] -= 10

        # 2. 检查数据新鲜度
        for rule in self.rules:
            is_fresh, delay = await self.check_freshness(rule)
            # 2026-09-01 修复：此前该项**没有 passed 键**，而下方统计用
            # c.get('passed', True) → 键缺失即默认「通过」，于是出现
            # 「评分 55/100 却报 通过 7/7」的自相矛盾日志（实测 24h 内 295 次检查
            # 有 251 次如此，占比 85%）。passed 语义固定为「是否触发扣分」，
            # 保证 评分=100 ⟺ 通过 N/N，两者不再各说各话。
            penalised = not is_fresh and delay > 3600  # 超过1小时未更新
            results["checks"].append(
                {
                    "type": "freshness",
                    "source": rule.source,
                    "fresh": is_fresh,
                    "delay_seconds": delay,
                    "max_allowed_minutes": rule.max_freshness_minutes,
                    "passed": not penalised,
                }
            )
            if penalised:
                results["overall_score"] -= 15

        # 3. 更新综合质量评分
        results["overall_score"] = max(0, min(100, results["overall_score"]))
        for rule in self.rules:
            data_quality_score.labels(data_source=rule.source).set(results["overall_score"])

        # 统计改为「键缺失即不算通过」（fail-safe）：一个报不出状态的检查项，
        # 不应该被静默认定为通过 —— 那正是本次假通过的根因。
        passed_n = sum(1 for c in results["checks"] if c.get("passed") is True)
        total_n = len(results["checks"])
        failed = [c for c in results["checks"] if c.get("passed") is not True]
        failed_desc = ", ".join(f"{c.get('type')}:{c.get('source')}" for c in failed)
        self.last_check_time = self._now()
        logger.info(
            f"数据质量检查完成 | 评分: {results['overall_score']}/100 | "
            f"交易日: {results['trading_day']} | 通过: {passed_n}/{total_n}"
            + (f" | 不通过: {failed_desc}" if failed_desc else "")
        )

        return results

    async def run_loop(self, interval: int = 300):
        """后台定时运行数据质量检查"""
        logger.info(f"[DataQuality] 启动数据质量监控（间隔 {interval}s）")
        while True:
            try:
                await self.run_check()
            except Exception as e:
                logger.error(f"[DataQuality] 检查失败: {e}")
            await asyncio.sleep(interval)


# 全局实例
monitor = DataQualityMonitor()
