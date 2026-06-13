"""
增强版回测引擎 V2
支持：滑点模型、T+1限制、涨跌停限制、基准对比、组合回测、Walk-Forward验证
策略：ma-cross / breakout / rsi / macd / kdj
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import product
import logging
import math
import uuid

logger = logging.getLogger(__name__)


# ============================================================
# 数据类定义
# ============================================================


@dataclass
class BacktestConfig:
    """回测配置"""

    ts_codes: list[str] = field(default_factory=lambda: ["000001.SZ"])
    strategies: list[str] = field(default_factory=lambda: ["ma-cross"])
    start_date: str = "20200101"
    end_date: str = "20241231"
    initial_cash: float = 100000.0
    slippage: float = 0.001  # 滑点 0.1%
    commission_rate: float = 0.00025  # 佣金万2.5
    stamp_tax: float = 0.001  # 印花税千1(仅卖出)
    enable_t1: bool = True  # T+1限制
    enable_limit: bool = True  # 涨跌停限制
    benchmark: str = "000300.SH"  # 基准指数
    position_size: float = 0.3  # 单只股票最大仓位30%
    max_positions: int = 5  # 最大持仓数
    risk_free_rate: float = 0.02  # 无风险利率


@dataclass
class TradeRecord:
    """交易记录"""

    date: str
    ts_code: str
    direction: str  # BUY / SELL
    price: float
    quantity: int
    amount: float
    slippage_cost: float
    commission: float
    tax: float
    pnl: float = 0.0
    hold_days: int = 0


@dataclass
class BacktestResult:
    """增强回测结果"""

    # 基础指标
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    # 增强指标
    calmar_ratio: float = 0.0
    sortino_ratio: float = 0.0
    information_ratio: float = 0.0
    alpha: float = 0.0
    beta: float = 0.0
    volatility: float = 0.0
    turnover_rate: float = 0.0
    # 时间序列
    equity_curve: list[dict] = field(default_factory=list)
    monthly_returns: list[dict] = field(default_factory=list)
    # 交易明细
    trades: list[TradeRecord] = field(default_factory=list)
    # 对比数据
    benchmark_return: float = 0.0
    excess_return: float = 0.0
    # 元信息
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_hold_days: float = 0.0
    backtest_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


# ============================================================
# 增强回测引擎
# ============================================================


class EnhancedBacktestEngine:
    """增强版回测引擎 V2

    特性：
    - 真实交易成本模型（滑点 + 佣金 + 印花税）
    - T+1 交易限制
    - 涨跌停限制
    - 基准指数对比
    - 多标的组合回测
    - Walk-Forward 前进分析验证
    - 完善的绩效分析指标
    """

    def __init__(self, config: BacktestConfig = None):
        """初始化回测引擎

        Args:
            config: 回测配置，为 None 时使用默认配置
        """
        self.config = config or BacktestConfig()
        self._data_service = None
        self._reset_state()

    def _get_data_service(self):
        """延迟初始化 DataService（避免模块导入时的循环依赖）"""
        if self._data_service is None:
            from core.config import settings

            from services.data_service import DataService

            self._data_service = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
        return self._data_service

    def _reset_state(self):
        """重置引擎内部状态"""
        self.cash = self.config.initial_cash
        self.positions: dict[str, dict] = {}  # {ts_code: {qty, cost_price, buy_date}}
        self.buy_date_map: dict[str, str] = {}  # T+1: {ts_code: last_buy_date}
        self.trades: list[TradeRecord] = []
        self.daily_values: list[dict] = []
        self.total_trade_amount: float = 0.0

    # ============================================================
    # 交易成本模型
    # ============================================================

    def apply_slippage(self, price: float, direction: str) -> float:
        """计算滑点后的成交价

        买入时加滑点（成交价更高），卖出时减滑点（成交价更低）。

        Args:
            price: 原始价格
            direction: 交易方向 "BUY" 或 "SELL"

        Returns:
            滑点调整后的价格
        """
        if direction == "BUY":
            return price * (1 + self.config.slippage)
        return price * (1 - self.config.slippage)

    def calc_commission(self, amount: float) -> float:
        """计算佣金（双向收取，最低5元）

        Args:
            amount: 交易金额

        Returns:
            佣金金额
        """
        commission = amount * self.config.commission_rate
        return max(commission, 5.0)

    def calc_tax(self, amount: float, direction: str) -> float:
        """计算印花税（仅卖出收取）

        Args:
            amount: 交易金额
            direction: 交易方向

        Returns:
            印花税金额
        """
        if direction == "SELL":
            return amount * self.config.stamp_tax
        return 0.0

    # ============================================================
    # T+1 与涨跌停限制
    # ============================================================

    def check_t1(self, ts_code: str, trade_date: str) -> bool:
        """检查T+1限制：当日买入的股票不能当日卖出

        Args:
            ts_code: 股票代码
            trade_date: 当前交易日

        Returns:
            True 表示可以卖出，False 表示受T+1限制不能卖出
        """
        if not self.config.enable_t1:
            return True
        buy_date = self.buy_date_map.get(ts_code)
        if buy_date and buy_date == trade_date:
            return False
        return True

    def check_limit(self, close: float, prev_close: float) -> tuple[bool, bool]:
        """检查涨跌停限制

        主板涨跌停 ±10%（ST 为 ±5%，此处简化按主板处理）。
        - 当日涨停（close >= prev_close * 1.098）：不能买入
        - 当日跌停（close <= prev_close * 0.902）：不能卖出

        Args:
            close: 当日收盘价
            prev_close: 前一日收盘价

        Returns:
            (can_buy, can_sell) 元组
        """
        if not self.config.enable_limit or prev_close <= 0:
            return True, True

        can_buy = close < prev_close * 1.098
        can_sell = close > prev_close * 0.902
        return can_buy, can_sell

    # ============================================================
    # 技术指标计算
    # ============================================================

    @staticmethod
    def calculate_ma(prices: list[float], period: int) -> list[float]:
        """计算简单移动平均线

        Args:
            prices: 价格序列
            period: 均线周期

        Returns:
            移动平均线列表，前 period-1 个值为 NaN
        """
        ma = [float("nan")] * (period - 1)
        for i in range(period - 1, len(prices)):
            avg = sum(prices[i - period + 1 : i + 1]) / period
            ma.append(avg)
        return ma

    @staticmethod
    def calculate_rsi(prices: list[float], period: int = 14) -> list[float]:
        """计算RSI（相对强弱指标）

        使用 Wilder 平滑法。

        Args:
            prices: 价格序列
            period: RSI周期，默认14

        Returns:
            RSI值列表
        """
        if len(prices) < period + 1:
            return [50.0] * len(prices)

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]

        rsi = [50.0] * period

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

            if avg_loss == 0:
                rsi.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi.append(100.0 - (100.0 / (1 + rs)))

        return rsi

    @staticmethod
    def calculate_macd(
        prices: list[float], fast: int = 12, slow: int = 26, signal: int = 9
    ) -> tuple[list[float], list[float], list[float]]:
        """计算MACD指标

        Args:
            prices: 价格序列
            fast: 快线EMA周期
            slow: 慢线EMA周期
            signal: 信号线EMA周期

        Returns:
            (DIF, DEA, MACD柱) 三元组
        """
        if len(prices) < slow:
            n = len(prices)
            return [0.0] * n, [0.0] * n, [0.0] * n

        alpha_fast = 2.0 / (fast + 1)
        alpha_slow = 2.0 / (slow + 1)

        ema_fast = [prices[0]]
        ema_slow = [prices[0]]

        for i in range(1, len(prices)):
            ema_fast.append(alpha_fast * prices[i] + (1 - alpha_fast) * ema_fast[-1])
            ema_slow.append(alpha_slow * prices[i] + (1 - alpha_slow) * ema_slow[-1])

        dif = [ema_fast[i] - ema_slow[i] for i in range(len(prices))]

        # DEA: DIF 的 EMA
        dea = [0.0] * len(prices)
        if len(prices) > signal:
            dea[signal - 1] = sum(dif[:signal]) / signal
            alpha_signal = 2.0 / (signal + 1)
            for i in range(signal, len(dif)):
                dea[i] = alpha_signal * dif[i] + (1 - alpha_signal) * dea[i - 1]

        macd_hist = [(dif[i] - dea[i]) * 2 for i in range(len(prices))]
        return dif, dea, macd_hist

    @staticmethod
    def calculate_kdj(
        closes: list[float],
        highs: list[float],
        lows: list[float],
        period: int = 9,
        k_smooth: int = 3,
        d_smooth: int = 3,
    ) -> tuple[list[float], list[float], list[float]]:
        """计算KDJ指标

        Args:
            closes: 收盘价序列
            highs: 最高价序列
            lows: 最低价序列
            period: RSV周期
            k_smooth: K线平滑系数
            d_smooth: D线平滑系数

        Returns:
            (K, D, J) 三元组
        """
        n = len(closes)
        k_vals = [50.0] * n
        d_vals = [50.0] * n
        j_vals = [50.0] * n

        for i in range(period - 1, n):
            high_max = max(highs[i - period + 1 : i + 1])
            low_min = min(lows[i - period + 1 : i + 1])
            if high_max == low_min:
                rsv = 50.0
            else:
                rsv = (closes[i] - low_min) / (high_max - low_min) * 100

            if i >= period:
                k_vals[i] = (k_smooth - 1) / k_smooth * k_vals[i - 1] + 1 / k_smooth * rsv
                d_vals[i] = (d_smooth - 1) / d_smooth * d_vals[i - 1] + 1 / d_smooth * k_vals[i]
            else:
                k_vals[i] = rsv
                d_vals[i] = rsv
            j_vals[i] = 3 * k_vals[i] - 2 * d_vals[i]

        return k_vals, d_vals, j_vals

    # ============================================================
    # 策略信号生成
    # ============================================================

    def generate_signals(
        self, df_data: list[dict], strategy: str, params: dict = None
    ) -> list[int]:
        """统一策略信号生成接口

        根据策略类型和参数，对行情数据生成交易信号。

        Args:
            df_data: 行情数据列表，每项包含 close/high/low/trade_date 等字段
            strategy: 策略名称 (ma-cross/breakout/rsi/macd/kdj)
            params: 策略参数字典

        Returns:
            信号列表，signal in {1(买), -1(卖), 0(持有)}
        """
        params = params or {}
        closes = [float(d["close"]) for d in df_data]
        n = len(closes)
        signals = [0] * n

        if strategy == "ma-cross":
            signals = self._signal_ma_cross(closes, params)
        elif strategy == "breakout":
            highs = [float(d.get("high", d["close"])) for d in df_data]
            signals = self._signal_breakout(closes, highs, params)
        elif strategy == "rsi":
            signals = self._signal_rsi(closes, params)
        elif strategy == "macd":
            signals = self._signal_macd(closes, params)
        elif strategy == "kdj":
            highs = [float(d.get("high", d["close"])) for d in df_data]
            lows = [float(d.get("low", d["close"])) for d in df_data]
            signals = self._signal_kdj(closes, highs, lows, params)
        else:
            logger.warning(f"未知策略: {strategy}，返回空信号")

        return signals

    def _signal_ma_cross(self, closes: list[float], params: dict) -> list[int]:
        """双均线金叉/死叉信号"""
        ma_fast_period = params.get("ma_fast", 5)
        ma_slow_period = params.get("ma_slow", 20)
        fast_ma = self.calculate_ma(closes, ma_fast_period)
        slow_ma = self.calculate_ma(closes, ma_slow_period)

        n = len(closes)
        signals = [0] * n
        start = max(ma_fast_period, ma_slow_period)

        for i in range(start, n):
            if math.isnan(fast_ma[i]) or math.isnan(slow_ma[i]):
                continue
            if math.isnan(fast_ma[i - 1]) or math.isnan(slow_ma[i - 1]):
                continue
            # 金叉买入
            if fast_ma[i] > slow_ma[i] and fast_ma[i - 1] <= slow_ma[i - 1]:
                signals[i] = 1
            # 死叉卖出
            elif fast_ma[i] < slow_ma[i] and fast_ma[i - 1] >= slow_ma[i - 1]:
                signals[i] = -1

        return signals

    def _signal_breakout(self, closes: list[float], highs: list[float], params: dict) -> list[int]:
        """突破N日高点买入信号"""
        lookback = params.get("lookback", 20)
        n = len(closes)
        signals = [0] * n

        for i in range(lookback, n):
            # 突破前N日最高价
            prev_high = max(highs[i - lookback : i])
            if highs[i] > prev_high:
                signals[i] = 1
            # 跌破前N日最低价
            prev_low = min(closes[i - lookback : i])
            if closes[i] < prev_low:
                signals[i] = -1

        return signals

    def _signal_rsi(self, closes: list[float], params: dict) -> list[int]:
        """RSI超买超卖信号"""
        period = params.get("period", 14)
        oversold = params.get("oversold", 30)
        overbought = params.get("overbought", 70)

        rsi_values = self.calculate_rsi(closes, period)
        n = len(closes)
        signals = [0] * n

        for i in range(period + 1, min(n, len(rsi_values))):
            # RSI下穿超卖线 → 买入
            if rsi_values[i] < oversold and rsi_values[i - 1] >= oversold:
                signals[i] = 1
            # RSI上穿超买线 → 卖出
            elif rsi_values[i] > overbought and rsi_values[i - 1] <= overbought:
                signals[i] = -1

        return signals

    def _signal_macd(self, closes: list[float], params: dict) -> list[int]:
        """MACD金叉/死叉信号"""
        fast = params.get("fast", 12)
        slow = params.get("slow", 26)
        signal = params.get("signal", 9)

        dif, dea, _ = self.calculate_macd(closes, fast, slow, signal)
        n = len(closes)
        signals = [0] * n

        for i in range(slow + signal, n):
            # DIF上穿DEA → 金叉买入
            if dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]:
                signals[i] = 1
            # DIF下穿DEA → 死叉卖出
            elif dif[i] < dea[i] and dif[i - 1] >= dea[i - 1]:
                signals[i] = -1

        return signals

    def _signal_kdj(
        self, closes: list[float], highs: list[float], lows: list[float], params: dict
    ) -> list[int]:
        """KDJ金叉/死叉信号"""
        period = params.get("period", 9)
        k_smooth = params.get("k_smooth", 3)
        d_smooth = params.get("d_smooth", 3)

        k_vals, d_vals, j_vals = self.calculate_kdj(closes, highs, lows, period, k_smooth, d_smooth)
        n = len(closes)
        signals = [0] * n

        for i in range(period + k_smooth, n):
            # K上穿D + J<40(超卖区) → 买入
            if k_vals[i] > d_vals[i] and k_vals[i - 1] <= d_vals[i - 1] and j_vals[i] < 40:
                signals[i] = 1
            # K下穿D + J>60(超买区) → 卖出
            elif k_vals[i] < d_vals[i] and k_vals[i - 1] >= d_vals[i - 1] and j_vals[i] > 60:
                signals[i] = -1

        return signals

    # ============================================================
    # 数据获取
    # ============================================================

    def fetch_market_data(self, ts_code: str, start_date: str, end_date: str) -> list[dict]:
        """获取历史行情数据（通过 DataService，享有多源降级 + DB 优先）

        Args:
            ts_code: 股票代码（如 000001.SZ）
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            行情数据列表，按日期升序排列
        """
        ds = self._get_data_service()
        try:
            result = ds.get_stock_daily_quote(ts_code, start_date, end_date)
            if result:
                # 归一化 trade_date 字段（DB 返回 datetime.date，API 返回 str）
                for row in result:
                    td = row.get("trade_date", "")
                    if hasattr(td, "strftime"):
                        row["trade_date"] = td.strftime("%Y%m%d")
                logger.info(f"EnhancedBacktest: {ts_code} 获取 {len(result)} 条日线")
                return result
            logger.warning(f"EnhancedBacktest: {ts_code} 返回空数据")
            return []
        except Exception as e:
            logger.error(f"EnhancedBacktest: {ts_code} 数据获取异常: {e}")
            return []

    def fetch_benchmark_data(self, start_date: str, end_date: str) -> list[dict]:
        """获取基准指数数据（多数据源自动降级）

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            基准指数行情数据列表
        """
        # 策略1: 通过 DataService 获取（享有多源降级）
        ds = self._get_data_service()
        try:
            result = ds.get_stock_daily_quote(self.config.benchmark, start_date, end_date)
            if result and len(result) > 0:
                logger.info(
                    f"EnhancedBacktest: 基准数据 {self.config.benchmark} 获取 {len(result)} 条 (via DataService)"
                )
                return result
        except Exception as e:
            logger.debug(f"EnhancedBacktest: DataService 基准数据获取失败: {e}")

        # 策略2: AKShare 指数日线直连
        try:
            import akshare as ak

            code = self.config.benchmark.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            suffix = ".SH" if ".SH" in self.config.benchmark else ".SZ"
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
                logger.info(f"EnhancedBacktest: AKShare 基准数据获取 {len(result)} 条")
                return result
        except Exception as e:
            logger.warning(f"EnhancedBacktest: AKShare 基准数据获取失败: {e}")

        logger.error(f"EnhancedBacktest: 基准数据 {self.config.benchmark} 获取全失败")
        return []

    # ============================================================
    # 核心回测逻辑
    # ============================================================

    def run(
        self,
        data: dict[str, list[dict]] = None,
        benchmark_data: list[dict] = None,
        strategy_params: dict[str, dict] = None,
    ) -> BacktestResult:
        """执行回测

        Args:
            data: 行情数据字典 {ts_code: [行情记录列表]}，为 None 时自动获取
            benchmark_data: 基准数据列表，为 None 时自动获取
            strategy_params: 策略参数 {strategy_name: {param: value}}

        Returns:
            BacktestResult 回测结果
        """
        self._reset_state()
        strategy_params = strategy_params or {}

        # 获取行情数据
        if data is None:
            data = {}
            for ts_code in self.config.ts_codes:
                market_data = self.fetch_market_data(
                    ts_code, self.config.start_date, self.config.end_date
                )
                if market_data:
                    data[ts_code] = market_data

        if not data:
            logger.error("无可用行情数据")
            return BacktestResult()

        # 获取基准数据
        if benchmark_data is None:
            benchmark_data = self.fetch_benchmark_data(self.config.start_date, self.config.end_date)

        # 生成各标的各策略的信号
        all_signals: dict[str, dict[str, list[int]]] = {}
        for ts_code, market_data in data.items():
            all_signals[ts_code] = {}
            for strategy in self.config.strategies:
                params = strategy_params.get(strategy, {})
                signals = self.generate_signals(market_data, strategy, params)
                all_signals[ts_code][strategy] = signals

        # 按日期逐日模拟交易
        # 找到所有标的的公共交易日
        date_sets = []
        for ts_code, market_data in data.items():
            dates = [d["trade_date"] for d in market_data]
            date_sets.append(set(dates))

        if not date_sets:
            return BacktestResult()

        common_dates = (
            sorted(set.intersection(*date_sets)) if len(date_sets) > 1 else sorted(date_sets[0])
        )

        # 建立日期到数据的索引
        date_index: dict[str, dict[str, dict]] = {}  # {date: {ts_code: row}}
        for ts_code, market_data in data.items():
            for row in market_data:
                d = row["trade_date"]
                if d not in date_index:
                    date_index[d] = {}
                date_index[d][ts_code] = row

        # 信号索引 {ts_code: {date: signal}}
        signal_index: dict[str, dict[str, int]] = {}
        for ts_code, market_data in data.items():
            signal_index[ts_code] = {}
            for strategy in self.config.strategies:
                sigs = all_signals[ts_code][strategy]
                for idx, row in enumerate(market_data):
                    d = row["trade_date"]
                    if idx < len(sigs) and sigs[idx] != 0:
                        # 多策略取多数信号（简化：取最后一个非零信号）
                        signal_index[ts_code][d] = sigs[idx]

        # 逐日模拟
        prev_closes: dict[str, float] = {}
        for date in common_dates:
            day_data = date_index.get(date, {})

            for ts_code in data.keys():
                if ts_code not in day_data:
                    continue

                row = day_data[ts_code]
                close = float(row["close"])
                prev_close = prev_closes.get(ts_code, float(row.get("pre_close", close)))

                # 涨跌停检查
                can_buy, can_sell = self.check_limit(close, prev_close)

                # 获取当日信号
                sig = signal_index.get(ts_code, {}).get(date, 0)

                # 买入信号
                if sig == 1 and can_buy:
                    self._execute_buy(ts_code, close, date)

                # 卖出信号
                elif sig == -1 and can_sell:
                    self._execute_sell(ts_code, close, date)

                prev_closes[ts_code] = close

            # 记录当日组合净值
            portfolio_value = self.cash
            for ts_code, pos in self.positions.items():
                if ts_code in day_data:
                    portfolio_value += pos["qty"] * float(day_data[ts_code]["close"])
                else:
                    portfolio_value += pos["qty"] * pos["cost_price"]

            self.daily_values.append(
                {
                    "date": date,
                    "nav": portfolio_value / self.config.initial_cash,
                    "value": portfolio_value,
                }
            )

        # 清仓
        for ts_code in list(self.positions.keys()):
            if common_dates:
                last_date = common_dates[-1]
                last_data = date_index.get(last_date, {})
                if ts_code in last_data:
                    last_price = float(last_data[ts_code]["close"])
                    self._execute_sell(ts_code, last_price, last_date, force=True)

        # 计算基准净值曲线
        bench_nav = self._calc_benchmark_nav(benchmark_data, common_dates)

        # 更新 equity_curve 中的 benchmark_nav 和 drawdown
        peak = 0.0
        for i, dv in enumerate(self.daily_values):
            nav = dv["nav"]
            peak = max(peak, nav)
            drawdown = (peak - nav) / peak if peak > 0 else 0.0
            dv["drawdown"] = drawdown
            dv["benchmark_nav"] = bench_nav[i] if i < len(bench_nav) else 1.0

        # 构建回测结果
        result = self._build_result(bench_nav)
        return result

    def _execute_buy(self, ts_code: str, price: float, date: str):
        """执行买入操作

        Args:
            ts_code: 股票代码
            price: 当前价格
            date: 交易日期
        """
        # 检查持仓数量限制
        if len(self.positions) >= self.config.max_positions and ts_code not in self.positions:
            return

        # 计算可用资金（按最大仓位比例）
        max_amount = self.config.initial_cash * self.config.position_size
        # 已有持仓则跳过
        if ts_code in self.positions:
            return

        exec_price = self.apply_slippage(price, "BUY")
        buy_qty = int(min(self.cash * 0.95, max_amount) / exec_price / 100) * 100

        if buy_qty <= 0:
            return

        amount = buy_qty * exec_price
        commission = self.calc_commission(amount)
        total_cost = amount + commission

        if total_cost > self.cash:
            return

        self.cash -= total_cost
        self.positions[ts_code] = {"qty": buy_qty, "cost_price": exec_price, "buy_date": date}
        self.buy_date_map[ts_code] = date
        self.total_trade_amount += amount

        slippage_cost = abs(exec_price - price) * buy_qty
        self.trades.append(
            TradeRecord(
                date=date,
                ts_code=ts_code,
                direction="BUY",
                price=exec_price,
                quantity=buy_qty,
                amount=amount,
                slippage_cost=slippage_cost,
                commission=commission,
                tax=0.0,
            )
        )

    def _execute_sell(self, ts_code: str, price: float, date: str, force: bool = False):
        """执行卖出操作

        Args:
            ts_code: 股票代码
            price: 当前价格
            date: 交易日期
            force: 是否强制卖出（清仓时忽略T+1）
        """
        if ts_code not in self.positions:
            return

        # T+1 检查
        if not force and not self.check_t1(ts_code, date):
            return

        pos = self.positions[ts_code]
        exec_price = self.apply_slippage(price, "SELL")
        sell_qty = pos["qty"]
        amount = sell_qty * exec_price
        commission = self.calc_commission(amount)
        tax = self.calc_tax(amount, "SELL")

        net_revenue = amount - commission - tax
        self.cash += net_revenue
        self.total_trade_amount += amount

        # 计算盈亏
        cost_basis = pos["cost_price"] * sell_qty
        pnl = net_revenue - cost_basis

        # 持仓天数
        try:
            buy_dt = datetime.strptime(pos["buy_date"], "%Y%m%d")
            sell_dt = datetime.strptime(date, "%Y%m%d")
            hold_days = (sell_dt - buy_dt).days
        except (ValueError, TypeError):
            hold_days = 0

        slippage_cost = abs(price - exec_price) * sell_qty
        self.trades.append(
            TradeRecord(
                date=date,
                ts_code=ts_code,
                direction="SELL",
                price=exec_price,
                quantity=sell_qty,
                amount=amount,
                slippage_cost=slippage_cost,
                commission=commission,
                tax=tax,
                pnl=pnl,
                hold_days=hold_days,
            )
        )

        del self.positions[ts_code]
        if ts_code in self.buy_date_map:
            del self.buy_date_map[ts_code]

    # ============================================================
    # 基准处理
    # ============================================================

    def _calc_benchmark_nav(
        self, benchmark_data: list[dict], common_dates: list[str]
    ) -> list[float]:
        """计算基准净值曲线

        Args:
            benchmark_data: 基准指数数据
            common_dates: 公共交易日列表

        Returns:
            基准净值列表（初始为1.0）
        """
        if not benchmark_data:
            return [1.0] * len(common_dates)

        bench_map = {d["trade_date"]: float(d["close"]) for d in benchmark_data}
        bench_navs = []
        first_price = None

        for date in common_dates:
            if date in bench_map:
                if first_price is None:
                    first_price = bench_map[date]
                bench_navs.append(bench_map[date] / first_price)
            else:
                bench_navs.append(bench_navs[-1] if bench_navs else 1.0)

        return bench_navs

    # ============================================================
    # 绩效分析
    # ============================================================

    def _build_result(self, bench_nav: list[float]) -> BacktestResult:
        """构建回测结果并计算所有绩效指标

        Args:
            bench_nav: 基准净值曲线

        Returns:
            BacktestResult
        """
        result = BacktestResult()
        result.trades = self.trades
        result.equity_curve = self.daily_values

        if not self.daily_values:
            return result

        # 基础数据
        navs = [dv["nav"] for dv in self.daily_values]
        final_nav = navs[-1] if navs else 1.0
        trading_days = len(navs)

        # 总收益率
        result.total_return = final_nav - 1.0

        # 年化收益率
        if trading_days > 0:
            result.annual_return = (final_nav ** (252.0 / trading_days)) - 1.0
        else:
            result.annual_return = 0.0

        # 日收益率序列
        daily_returns = []
        for i in range(1, len(navs)):
            if navs[i - 1] != 0:
                daily_returns.append((navs[i] - navs[i - 1]) / navs[i - 1])
            else:
                daily_returns.append(0.0)

        # 年化波动率
        if daily_returns:
            avg_ret = sum(daily_returns) / len(daily_returns)
            variance = sum((r - avg_ret) ** 2 for r in daily_returns) / len(daily_returns)
            result.volatility = math.sqrt(variance) * math.sqrt(252)
        else:
            result.volatility = 0.0

        # 夏普比率 = (年化收益 - 无风险) / 年化波动率
        rf = self.config.risk_free_rate
        if result.volatility > 0:
            result.sharpe_ratio = (result.annual_return - rf) / result.volatility
        else:
            result.sharpe_ratio = 0.0

        # 最大回撤
        peak = 0.0
        max_dd = 0.0
        for nav in navs:
            peak = max(peak, nav)
            dd = (peak - nav) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
        result.max_drawdown = max_dd

        # Calmar Ratio = 年化收益 / 最大回撤
        result.calmar_ratio = (
            result.annual_return / result.max_drawdown if result.max_drawdown > 0 else 0.0
        )

        # Sortino Ratio = (年化收益 - 无风险) / 下行波动率
        downside_returns = [r for r in daily_returns if r < 0]
        if downside_returns:
            downside_var = sum(r**2 for r in downside_returns) / len(daily_returns)
            downside_vol = math.sqrt(downside_var) * math.sqrt(252)
            result.sortino_ratio = (
                (result.annual_return - rf) / downside_vol if downside_vol > 0 else 0.0
            )
        else:
            result.sortino_ratio = 0.0

        # 基准相关指标
        bench_returns = []
        if len(bench_nav) > 1:
            for i in range(1, len(bench_nav)):
                if bench_nav[i - 1] != 0:
                    bench_returns.append((bench_nav[i] - bench_nav[i - 1]) / bench_nav[i - 1])
                else:
                    bench_returns.append(0.0)

        result.benchmark_return = (bench_nav[-1] - 1.0) if bench_nav else 0.0
        result.excess_return = result.total_return - result.benchmark_return

        # Beta = cov(策略日收益, 基准日收益) / var(基准日收益)
        min_len = min(len(daily_returns), len(bench_returns))
        if min_len > 1:
            strat_r = daily_returns[:min_len]
            bench_r = bench_returns[:min_len]
            avg_s = sum(strat_r) / min_len
            avg_b = sum(bench_r) / min_len
            cov = sum((strat_r[i] - avg_s) * (bench_r[i] - avg_b) for i in range(min_len)) / min_len
            var_b = sum((bench_r[i] - avg_b) ** 2 for i in range(min_len)) / min_len
            result.beta = cov / var_b if var_b > 0 else 0.0

            # Alpha (Jensen's Alpha)
            bench_annual = (
                (bench_nav[-1] ** (252.0 / max(len(bench_nav), 1))) - 1.0 if bench_nav else 0.0
            )
            result.alpha = result.annual_return - (rf + result.beta * (bench_annual - rf))

            # Information Ratio = (策略年化 - 基准年化) / tracking_error
            tracking_diff = [strat_r[i] - bench_r[i] for i in range(min_len)]
            avg_td = sum(tracking_diff) / min_len
            te_var = sum((td - avg_td) ** 2 for td in tracking_diff) / min_len
            tracking_error = math.sqrt(te_var) * math.sqrt(252)
            result.information_ratio = (
                (result.annual_return - bench_annual) / tracking_error
                if tracking_error > 0
                else 0.0
            )
        else:
            result.beta = 0.0
            result.alpha = 0.0
            result.information_ratio = 0.0

        # 交易统计
        sell_trades = [t for t in self.trades if t.direction == "SELL"]
        result.total_trades = len(sell_trades)
        result.winning_trades = sum(1 for t in sell_trades if t.pnl > 0)
        result.losing_trades = sum(1 for t in sell_trades if t.pnl <= 0)
        result.win_rate = (
            result.winning_trades / result.total_trades if result.total_trades > 0 else 0.0
        )

        # 盈亏比 Profit Factor
        total_profit = sum(t.pnl for t in sell_trades if t.pnl > 0)
        total_loss = abs(sum(t.pnl for t in sell_trades if t.pnl < 0))
        result.profit_factor = total_profit / total_loss if total_loss > 0 else 0.0

        # 平均持仓天数
        if sell_trades:
            result.avg_hold_days = sum(t.hold_days for t in sell_trades) / len(sell_trades)

        # 换手率 = 总交易金额 / 平均持仓市值
        avg_value = (
            sum(dv["value"] for dv in self.daily_values) / len(self.daily_values)
            if self.daily_values
            else 1.0
        )
        result.turnover_rate = self.total_trade_amount / avg_value if avg_value > 0 else 0.0

        # 月度收益
        result.monthly_returns = self.calc_monthly_returns(self.daily_values)

        return result

    def calc_monthly_returns(self, equity_curve: list[dict]) -> list[dict]:
        """计算每月收益率

        将净值曲线按月聚合，计算每个自然月的收益率。

        Args:
            equity_curve: 每日净值列表 [{date, nav, ...}]

        Returns:
            月度收益列表 [{year, month, return}, ...]
        """
        if not equity_curve:
            return []

        monthly = {}  # (year, month) -> [first_nav, last_nav]
        for dv in equity_curve:
            date_str = dv["date"]
            try:
                if len(date_str) == 8:  # YYYYMMDD
                    year = int(date_str[:4])
                    month = int(date_str[4:6])
                else:  # YYYY-MM-DD
                    parts = date_str.split("-")
                    year = int(parts[0])
                    month = int(parts[1])
            except (ValueError, IndexError):
                continue

            key = (year, month)
            nav = dv["nav"]
            if key not in monthly:
                monthly[key] = [nav, nav]
            else:
                monthly[key][1] = nav

        results = []
        sorted_keys = sorted(monthly.keys())
        prev_nav = 1.0
        for key in sorted_keys:
            first_nav, last_nav = monthly[key]
            # 月度收益 = 月末净值 / 上月末净值 - 1
            month_ret = (last_nav / prev_nav) - 1.0 if prev_nav > 0 else 0.0
            results.append({"year": key[0], "month": key[1], "return": round(month_ret, 6)})
            prev_nav = last_nav

        return results

    # ============================================================
    # Walk-Forward 前进分析验证
    # ============================================================

    def walk_forward(
        self,
        ts_code: str,
        strategy: str,
        train_days: int = 252,
        test_days: int = 63,
        step_days: int = 63,
        param_grid: dict[str, list] = None,
    ) -> dict:
        """滚动窗口前进分析（Walk-Forward Analysis）

        1. 训练期：用网格搜索找最优参数
        2. 测试期：用训练期最优参数回测
        3. 滑动 step_days 天重复
        用于检测策略过拟合。

        Args:
            ts_code: 股票代码
            strategy: 策略名称
            train_days: 训练期天数（默认252个交易日≈1年）
            test_days: 测试期天数（默认63个交易日≈1季度）
            step_days: 滑动步长（默认63天）
            param_grid: 参数搜索空间，如 {'ma_fast': [5,10,15], 'ma_slow': [20,30,60]}

        Returns:
            dict 包含：
            - windows: 每个窗口的训练/测试绩效
            - overall_test_return: 所有测试期拼接的总收益
            - overfit_ratio: 过拟合比率（测试期夏普/训练期夏普的均值）
        """
        # 获取数据
        data = self.fetch_market_data(ts_code, self.config.start_date, self.config.end_date)
        if not data:
            return {"error": "无数据", "windows": []}

        if param_grid is None:
            param_grid = self._default_param_grid(strategy)

        total_len = len(data)
        windows = []
        offset = 0

        while offset + train_days + test_days <= total_len:
            train_data = data[offset : offset + train_days]
            test_data = data[offset + train_days : offset + train_days + test_days]

            # 训练期：网格搜索
            best_params, best_train_sharpe = self._grid_search(
                ts_code, strategy, train_data, param_grid
            )

            # 测试期：用最优参数回测
            test_result = self._run_single(ts_code, strategy, test_data, best_params)

            windows.append(
                {
                    "train_start": train_data[0]["trade_date"],
                    "train_end": train_data[-1]["trade_date"],
                    "test_start": test_data[0]["trade_date"],
                    "test_end": test_data[-1]["trade_date"],
                    "best_params": best_params,
                    "train_sharpe": best_train_sharpe,
                    "test_sharpe": test_result.sharpe_ratio,
                    "test_return": test_result.total_return,
                    "test_max_dd": test_result.max_drawdown,
                }
            )

            offset += step_days

        # 汇总
        if windows:
            overall_test_return = 1.0
            for w in windows:
                overall_test_return *= 1 + w["test_return"]
            overall_test_return -= 1.0

            # 过拟合比率
            ratios = []
            for w in windows:
                if w["train_sharpe"] != 0:
                    ratios.append(w["test_sharpe"] / w["train_sharpe"])
            overfit_ratio = sum(ratios) / len(ratios) if ratios else 0.0
        else:
            overall_test_return = 0.0
            overfit_ratio = 0.0

        return {
            "windows": windows,
            "overall_test_return": overall_test_return,
            "overfit_ratio": overfit_ratio,
            "num_windows": len(windows),
        }

    def _default_param_grid(self, strategy: str) -> dict[str, list]:
        """获取策略的默认参数搜索空间

        Args:
            strategy: 策略名称

        Returns:
            参数网格字典
        """
        grids = {
            "ma-cross": {"ma_fast": [5, 10, 15, 20], "ma_slow": [20, 30, 40, 60]},
            "breakout": {"lookback": [10, 15, 20, 30, 40]},
            "rsi": {"period": [6, 14, 21], "oversold": [20, 30], "overbought": [70, 80]},
            "macd": {"fast": [8, 12, 16], "slow": [20, 26, 30], "signal": [7, 9, 11]},
            "kdj": {"period": [5, 9, 14], "k_smooth": [3, 5], "d_smooth": [3, 5]},
        }
        return grids.get(strategy, {})

    def _grid_search(
        self, ts_code: str, strategy: str, data: list[dict], param_grid: dict[str, list]
    ) -> tuple[dict, float]:
        """网格搜索最优参数

        Args:
            ts_code: 股票代码
            strategy: 策略名称
            data: 训练数据
            param_grid: 参数搜索空间

        Returns:
            (最优参数字典, 最优夏普比率)
        """
        if not param_grid:
            return {}, 0.0

        keys = list(param_grid.keys())
        values = list(param_grid.values())
        best_sharpe = -float("inf")
        best_params = {}

        for combo in product(*values):
            params = dict(zip(keys, combo))
            # 过滤无效参数组合（如 ma_fast >= ma_slow）
            if strategy == "ma-cross" and params.get("ma_fast", 0) >= params.get("ma_slow", 1):
                continue

            result = self._run_single(ts_code, strategy, data, params)
            if result.sharpe_ratio > best_sharpe:
                best_sharpe = result.sharpe_ratio
                best_params = params

        return best_params, best_sharpe

    def _run_single(
        self, ts_code: str, strategy: str, data: list[dict], params: dict
    ) -> BacktestResult:
        """对单只股票单策略运行简单回测（用于网格搜索）

        Args:
            ts_code: 股票代码
            strategy: 策略名称
            data: 行情数据
            params: 策略参数

        Returns:
            BacktestResult
        """
        # 创建临时引擎实例避免污染主引擎状态
        temp_config = BacktestConfig(
            ts_codes=[ts_code],
            strategies=[strategy],
            start_date=data[0]["trade_date"] if data else "",
            end_date=data[-1]["trade_date"] if data else "",
            initial_cash=self.config.initial_cash,
            slippage=self.config.slippage,
            commission_rate=self.config.commission_rate,
            stamp_tax=self.config.stamp_tax,
            enable_t1=self.config.enable_t1,
            enable_limit=self.config.enable_limit,
            benchmark=self.config.benchmark,
            position_size=1.0,  # 单只股票回测不限仓位
            max_positions=1,
        )
        temp_engine = EnhancedBacktestEngine(temp_config)
        return temp_engine.run(
            data={ts_code: data}, benchmark_data=[], strategy_params={strategy: params}
        )

    # ============================================================
    # 便捷接口
    # ============================================================

    def run_single_stock(
        self, ts_code: str, strategy: str, data: list[dict] = None, params: dict = None
    ) -> BacktestResult:
        """单只股票单策略回测的便捷入口

        Args:
            ts_code: 股票代码
            strategy: 策略名称
            data: 行情数据列表，为 None 时自动获取
            params: 策略参数

        Returns:
            BacktestResult
        """
        self.config.ts_codes = [ts_code]
        self.config.strategies = [strategy]
        self.config.position_size = 1.0
        self.config.max_positions = 1

        data_dict = None
        if data is not None:
            data_dict = {ts_code: data}

        strategy_params = {strategy: params} if params else None
        return self.run(data=data_dict, strategy_params=strategy_params)


# ============================================================
# 主程序入口（简单测试）
# ============================================================

if __name__ == "__main__":
    import random

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    print("=" * 60)
    print("EnhancedBacktestEngine V2 - 自检测试")
    print("=" * 60)

    # 生成模拟数据
    def generate_mock_data(days: int = 500, start_price: float = 10.0) -> list[dict]:
        """生成模拟行情数据用于测试"""
        data = []
        price = start_price
        base_date = datetime(2022, 1, 4)

        for i in range(days):
            trade_date = base_date + timedelta(days=i)
            # 跳过周末
            if trade_date.weekday() >= 5:
                continue

            change = random.gauss(0.0005, 0.02)
            price = price * (1 + change)
            high = price * (1 + abs(random.gauss(0, 0.01)))
            low = price * (1 - abs(random.gauss(0, 0.01)))

            data.append(
                {
                    "trade_date": trade_date.strftime("%Y%m%d"),
                    "open": round(price * (1 + random.gauss(0, 0.005)), 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(price, 2),
                    "pre_close": round(price / (1 + change), 2),
                    "vol": random.randint(50000, 500000),
                    "amount": random.randint(5000000, 50000000),
                }
            )

        return data

    # 测试1：单策略回测
    print("\n[测试1] 单只股票 ma-cross 策略回测")
    mock_data = generate_mock_data(500)
    print(f"  模拟数据量: {len(mock_data)} 条")

    config = BacktestConfig(
        ts_codes=["000001.SZ"],
        strategies=["ma-cross"],
        initial_cash=100000,
        slippage=0.001,
        commission_rate=0.00025,
        stamp_tax=0.001,
        enable_t1=True,
        enable_limit=True,
    )
    engine = EnhancedBacktestEngine(config)
    result = engine.run(data={"000001.SZ": mock_data}, benchmark_data=[])

    print(f"  总收益率: {result.total_return:.4f} ({result.total_return * 100:.2f}%)")
    print(f"  年化收益: {result.annual_return:.4f} ({result.annual_return * 100:.2f}%)")
    print(f"  夏普比率: {result.sharpe_ratio:.4f}")
    print(f"  最大回撤: {result.max_drawdown:.4f} ({result.max_drawdown * 100:.2f}%)")
    print(f"  胜率: {result.win_rate:.4f} ({result.win_rate * 100:.1f}%)")
    print(f"  盈亏比: {result.profit_factor:.4f}")
    print(f"  Calmar: {result.calmar_ratio:.4f}")
    print(f"  Sortino: {result.sortino_ratio:.4f}")
    print(f"  波动率: {result.volatility:.4f}")
    print(f"  换手率: {result.turnover_rate:.4f}")
    print(f"  总交易: {result.total_trades} 次")
    print(f"  月度收益记录数: {len(result.monthly_returns)}")

    # 测试2：多策略信号生成
    print("\n[测试2] 策略信号生成测试")
    for strat in ["ma-cross", "breakout", "rsi", "macd", "kdj"]:
        signals = engine.generate_signals(mock_data, strat)
        buy_count = signals.count(1)
        sell_count = signals.count(-1)
        print(f"  {strat:10s}: 买入信号 {buy_count:3d}, 卖出信号 {sell_count:3d}")

    # 测试3：组合回测
    print("\n[测试3] 多标的组合回测")
    mock_data2 = generate_mock_data(500, start_price=25.0)
    config_multi = BacktestConfig(
        ts_codes=["000001.SZ", "600519.SH"],
        strategies=["ma-cross", "rsi"],
        initial_cash=200000,
        max_positions=5,
        position_size=0.3,
    )
    engine_multi = EnhancedBacktestEngine(config_multi)
    result_multi = engine_multi.run(
        data={"000001.SZ": mock_data, "600519.SH": mock_data2}, benchmark_data=[]
    )
    print(f"  组合总收益: {result_multi.total_return:.4f}")
    print(f"  组合夏普: {result_multi.sharpe_ratio:.4f}")
    print(f"  总交易次数: {result_multi.total_trades}")

    # 测试4：滑点/T+1/涨跌停模型验证
    print("\n[测试4] 交易限制模型验证")
    test_engine = EnhancedBacktestEngine(BacktestConfig())
    buy_price = test_engine.apply_slippage(10.0, "BUY")
    sell_price = test_engine.apply_slippage(10.0, "SELL")
    print(f"  原价10.0 → 买入成交价: {buy_price:.4f}, 卖出成交价: {sell_price:.4f}")

    can_buy, can_sell = test_engine.check_limit(11.0, 10.0)
    print(f"  涨幅10% → can_buy={can_buy}, can_sell={can_sell}")
    can_buy, can_sell = test_engine.check_limit(9.0, 10.0)
    print(f"  跌幅10% → can_buy={can_buy}, can_sell={can_sell}")

    print("\n" + "=" * 60)
    print("所有测试完成！EnhancedBacktestEngine V2 就绪。")
    print("=" * 60)
