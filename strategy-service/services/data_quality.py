"""
数据质量监控服务
检查行情数据新鲜度、完整性、异常值，通过 Prometheus 指标暴露
"""

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger("data-quality")

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


class DataQualityMonitor:
    """数据质量监控器"""

    CHINA_MARKET_HOURS = (9, 15)  # A股交易时间 9:00-15:00

    def __init__(self):
        self.rules: list[DataQualityRule] = [
            DataQualityRule("每日行情", "daily_quote", max_freshness_minutes=24 * 60),
            DataQualityRule("实时行情", "realtime_quote", max_freshness_minutes=10),
            DataQualityRule("指数行情", "index_quote", max_freshness_minutes=10),
            DataQualityRule("北向资金", "northbound_flow", max_freshness_minutes=60),
            DataQualityRule("股票池", "stock_pool", max_freshness_minutes=24 * 60),
        ]
        self.last_check_time: datetime | None = None
        self.last_update: dict[str, datetime] = {}

    def is_trading_day(self) -> bool:
        """判断是否为A股交易日（简化版：周一至周五，非中国节假日）"""
        today = date.today()
        if today.weekday() >= 5:  # 周六日
            return False
        return True

    def is_trading_hours(self) -> bool:
        """判断是否在A股交易时段"""
        now = datetime.now()
        hour = now.hour
        return self.CHINA_MARKET_HOURS[0] <= hour < self.CHINA_MARKET_HOURS[1]

    def mark_update(self, source: str):
        """标记数据源已更新"""
        self.last_update[source] = datetime.now()
        data_freshness_seconds.labels(data_source=source).set(0)

    async def check_data_source_online(self, source_name: str) -> bool:
        """检查数据源是否在线"""
        try:
            import akshare as ak

            if source_name == "akshare":
                # 尝试获取指数行情
                df = ak.stock_zh_index_spot_em()
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

    async def check_freshness(self, rule: DataQualityRule) -> tuple[bool, float]:
        """检查数据新鲜度，返回 (是否正常, 延迟秒数)"""
        last = self.last_update.get(rule.source)
        if not last:
            # 从未更新过的数据源
            return False, float("inf")

        now = datetime.now()
        delay = (now - last).total_seconds()

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
        results = {
            "timestamp": datetime.now().isoformat(),
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
            results["checks"].append(
                {
                    "type": "freshness",
                    "source": rule.source,
                    "fresh": is_fresh,
                    "delay_seconds": delay,
                    "max_allowed_minutes": rule.max_freshness_minutes,
                }
            )
            if not is_fresh and delay > 3600:  # 超过1小时未更新
                results["overall_score"] -= 15

        # 3. 更新综合质量评分
        results["overall_score"] = max(0, min(100, results["overall_score"]))
        for rule in self.rules:
            data_quality_score.labels(data_source=rule.source).set(results["overall_score"])

        self.last_check_time = datetime.now()
        logger.info(
            f"数据质量检查完成 | 评分: {results['overall_score']}/100 | "
            f"交易日: {results['trading_day']} | 通过: {sum(1 for c in results['checks'] if c.get('passed', True))}/{len(results['checks'])}"
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
