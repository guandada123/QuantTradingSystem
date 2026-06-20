"""
增强版回测引擎 V2
支持：滑点模型、T+1限制、涨跌停限制、基准对比、组合回测、Walk-Forward验证
策略：ma-cross / breakout / rsi / macd / kdj
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import product
import logging
from typing import TYPE_CHECKING
import uuid

from . import (
    indicators,  # 模块级纯函数指标计算
    signals,  # 模块级策略信号生成
)
from .data_fetcher import DataFetcher
from .market_regime import MarketRegimeFilter  # L1 市场状态过滤
from .param_grids import get_default_param_grid  # 默认参数搜索空间（API/引擎共用）
from .performance_calc import PerformanceCalculator  # 绩效计算（模块级导入无循环依赖）
from .trade_executor import TradeExecutor  # 交易执行（模块级导入无循环依赖）

if TYPE_CHECKING:
    from services.data_service import DataService

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
    # L1 市场状态过滤（v2.3 新增）
    regime_filter: bool = False  # 是否启用市场状态过滤
    regime_per_stock: bool = False  # True=按个股判定, False=按基准指数判定
    regime_ma_fast: int = 50  # 快速均线
    regime_ma_slow: int = 200  # 慢速均线
    regime_adx_threshold: float = 22.0  # ADX 趋势强度阈值


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
        self._executor = TradeExecutor(self.config)
        self._perf = PerformanceCalculator(self.config)
        self._data_fetcher = DataFetcher(self.config, get_data_service=self._get_data_service)
        self._data_service_ref: DataService | None = None
        self._reset_state()

    def _get_data_service(self):
        """延迟初始化 DataService（可选，用于兜底）"""
        if not hasattr(self, "_data_service_ref") or self._data_service_ref is None:
            try:
                from core.config import settings

                from services.data_service import DataService

                self._data_service_ref = DataService(tushare_token=settings.TUSHARE_TOKEN or None)
            except Exception:
                self._data_service_ref = None  # DataService 不可用时返回 None
        return self._data_service_ref

    @staticmethod
    def _empty_result(msg: str = "") -> BacktestResult:
        """返回空回测结果（用于错误路径，统一格式）

        Args:
            msg: 可选的日志消息，为空时不记日志

        Returns:
            全零的 BacktestResult 实例
        """
        if msg:
            logger.warning("BacktestEngine: %s", msg)
        return BacktestResult()

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
        """计算滑点后的成交价（委托至 TradeExecutor）"""
        return self._executor.apply_slippage(price, direction)

    def calc_commission(self, amount: float) -> float:
        """计算佣金（委托至 TradeExecutor）"""
        return self._executor.calc_commission(amount)

    def calc_tax(self, amount: float, direction: str) -> float:
        """计算印花税（委托至 TradeExecutor）"""
        return self._executor.calc_tax(amount, direction)

    # ============================================================
    # T+1 与涨跌停限制
    # ============================================================

    def check_t1(self, ts_code: str, trade_date: str) -> bool:
        """检查T+1限制（委托至 TradeExecutor）"""
        return self._executor.check_t1(ts_code, trade_date, self.buy_date_map)

    def check_limit(self, close: float, prev_close: float) -> tuple[bool, bool]:
        """检查涨跌停限制（委托至 TradeExecutor）"""
        return self._executor.check_limit(close, prev_close)

    # ============================================================
    # 技术指标计算
    # ============================================================

    def generate_signals(
        self, df_data: list[dict], strategy: str, params: dict = None
    ) -> list[int]:
        """统一策略信号生成接口（委托至 signals.generate_signals）"""
        return signals.generate_signals(df_data, strategy, params)

    # ---- 行情数据获取 ----

    def fetch_market_data(self, ts_code: str, start_date: str, end_date: str) -> list[dict]:
        """获取历史行情数据（委托至 DataFetcher.fetch_market_data）"""
        return self._data_fetcher.fetch_market_data(ts_code, start_date, end_date)

    def fetch_benchmark_data(self, start_date: str, end_date: str) -> list[dict]:
        """获取基准指数数据（委托至 DataFetcher.fetch_benchmark_data）"""
        return self._data_fetcher.fetch_benchmark_data(start_date, end_date)

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

        # 解析个股最优参数
        if not strategy_params:
            from .param_grids import get_stock_params

            for s in self.config.strategies:
                for ts_code in self.config.ts_codes:
                    # 组合策略：合并 VWM + BBR 个股参数
                    if s == "combo-vwm-bbr":
                        if s not in strategy_params:
                            strategy_params[s] = {}
                        vwm_sp = get_stock_params(ts_code, "vwm")
                        bbr_sp = get_stock_params(ts_code, "bollinger")
                        if vwm_sp and "vwm_params" not in strategy_params[s]:
                            strategy_params[s]["vwm_params"] = vwm_sp
                        if bbr_sp and "bbr_params" not in strategy_params[s]:
                            strategy_params[s]["bbr_params"] = bbr_sp
                    else:
                        sp = get_stock_params(ts_code, s)
                        if sp:
                            if s not in strategy_params:
                                strategy_params[s] = {}
                            strategy_params[s].update(sp)

        # 1. 数据准备
        data, benchmark_data = self._prepare_bt_data(data, benchmark_data)
        if not data:
            return self._empty_result("无可用行情数据")

        # 2. 构建日期索引和信号索引
        common_dates, date_index, signal_index = self._build_bt_indices(data, strategy_params)
        if not common_dates:
            return self._empty_result("无公共交易日，无法回测")

        # 2.5 L1 市场状态过滤（v2.3）
        regime_index = None
        if self.config.regime_filter:
            regime_index = self._build_regime_index(data, benchmark_data)

        # 3. 逐日模拟交易
        self._run_bt_simulation(data, common_dates, date_index, signal_index, regime_index)

        # 4. 清仓 & 更新净值曲线
        self._finalize_bt_positions(date_index, common_dates, benchmark_data)

        # 5. 构建回测结果
        bench_nav = self._calc_benchmark_nav(benchmark_data, common_dates)
        self._enrich_equity_curve(bench_nav)
        return self._build_result(bench_nav)

    def _prepare_bt_data(
        self,
        data: dict[str, list[dict]] | None,
        benchmark_data: list[dict] | None,
    ) -> tuple[dict[str, list[dict]], list[dict]]:
        """准备回测数据：自动获取行情和基准数据"""
        if data is None:
            data = {}
            for ts_code in self.config.ts_codes:
                market_data = self.fetch_market_data(
                    ts_code, self.config.start_date, self.config.end_date
                )
                if market_data:
                    data[ts_code] = market_data

        if benchmark_data is None:
            benchmark_data = self.fetch_benchmark_data(self.config.start_date, self.config.end_date)
        return data, benchmark_data

    def _build_bt_indices(
        self,
        data: dict[str, list[dict]],
        strategy_params: dict[str, dict],
    ) -> tuple[list[str], dict[str, dict[str, dict]], dict[str, dict[str, int]]]:
        """构建回测日期索引和信号索引

        Returns:
            (common_dates, date_index, signal_index)
        """
        # 生成各标的各策略的信号
        all_signals: dict[str, dict[str, list[int]]] = {}
        for ts_code, market_data in data.items():
            all_signals[ts_code] = {}
            for strategy in self.config.strategies:
                params = strategy_params.get(strategy, {})
                signals = self.generate_signals(market_data, strategy, params)
                all_signals[ts_code][strategy] = signals

        # 找到所有标的的公共交易日
        date_sets = []
        for ts_code, market_data in data.items():
            dates = [d["trade_date"] for d in market_data]
            date_sets.append(set(dates))

        if not date_sets:
            return [], {}, {}

        common_dates = (
            sorted(set.intersection(*date_sets)) if len(date_sets) > 1 else sorted(date_sets[0])
        )

        # 建立日期到数据的索引
        date_index: dict[str, dict[str, dict]] = {}
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
                        signal_index[ts_code][d] = sigs[idx]

        return common_dates, date_index, signal_index

    # -----------------------------------------------------------
    # L1 市场状态过滤 (v2.3)
    # -----------------------------------------------------------

    def _build_regime_index(
        self,
        data: dict[str, list[dict]],
        benchmark_data: list[dict] | None = None,
    ) -> dict[str, dict[str, float]]:
        """构建市场状态仓位乘数索引

        对每个标的，逐日判定当前市场状态，输出动态仓位乘数。
        regime_per_stock=True → 使用个股自身数据判定
        regime_per_stock=False → 使用基准指数判定（需要 benchmark_data）

        Returns:
            {ts_code: {date: position_mult}}
        """
        cfg = self.config
        regime_index: dict[str, dict[str, float]] = {}

        if cfg.regime_per_stock or not benchmark_data:
            # 模式A: 按个股自身趋势判定
            for ts_code, market_data in data.items():
                regime_index[ts_code] = {}
                closes = [float(r["close"]) for r in market_data]
                highs = [float(r.get("high", r["close"])) for r in market_data]
                lows = [float(r.get("low", r["close"])) for r in market_data]
                volumes = [float(r.get("vol", 0)) for r in market_data]

                rf = MarketRegimeFilter(
                    ma_fast=cfg.regime_ma_fast,
                    ma_slow=cfg.regime_ma_slow,
                    adx_threshold=cfg.regime_adx_threshold,
                )

                for i in range(len(market_data)):
                    date = market_data[i]["trade_date"]
                    if i < cfg.regime_ma_slow:  # 数据不足，默认全仓
                        regime_index[ts_code][date] = 1.0
                        continue
                    regime = rf.classify(
                        closes[: i + 1], highs[: i + 1], lows[: i + 1], volumes[: i + 1]
                    )
                    regime_index[ts_code][date] = MarketRegimeFilter.get_position_mult(regime)
        else:
            # 模式B: 按基准指数判定（统一乘数应用于所有股票）
            regime_index_all: dict[str, float] = {}
            bench_closes = [float(r["close"]) for r in benchmark_data]
            bench_highs = [float(r.get("high", r["close"])) for r in benchmark_data]
            bench_lows = [float(r.get("low", r["close"])) for r in benchmark_data]

            rf = MarketRegimeFilter(
                ma_fast=cfg.regime_ma_fast,
                ma_slow=cfg.regime_ma_slow,
                adx_threshold=cfg.regime_adx_threshold,
            )

            for i in range(len(benchmark_data)):
                date = benchmark_data[i]["trade_date"]
                if i < cfg.regime_ma_slow:
                    regime_index_all[date] = 1.0
                    continue
                regime = rf.classify(
                    bench_closes[: i + 1], bench_highs[: i + 1], bench_lows[: i + 1]
                )
                regime_index_all[date] = MarketRegimeFilter.get_position_mult(regime)

            for ts_code in data:
                regime_index[ts_code] = dict(regime_index_all)

        return regime_index

    def _run_bt_simulation(
        self,
        data: dict[str, list[dict]],
        common_dates: list[str],
        date_index: dict[str, dict[str, dict]],
        signal_index: dict[str, dict[str, int]],
        regime_index: dict[str, dict[str, float]] | None = None,
    ):
        """逐日模拟交易"""
        prev_closes: dict[str, float] = {}
        for date in common_dates:
            day_data = date_index.get(date, {})

            for ts_code in data.keys():
                if ts_code not in day_data:
                    continue

                row = day_data[ts_code]
                close = float(row["close"])
                prev_close = prev_closes.get(ts_code, float(row.get("pre_close", close)))

                can_buy, can_sell = self.check_limit(close, prev_close)
                sig = signal_index.get(ts_code, {}).get(date, 0)

                if sig == 1 and can_buy:
                    # L1 市场状态仓位乘数
                    regime_mult = 1.0
                    if self.config.regime_filter and regime_index:
                        regime_mult = regime_index.get(ts_code, {}).get(date, 1.0)
                    self._execute_buy(ts_code, close, date, regime_mult)
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

    def _finalize_bt_positions(
        self,
        date_index: dict[str, dict[str, dict]],
        common_dates: list[str],
        benchmark_data: list[dict],
    ):
        """清仓所有持仓"""
        for ts_code in list(self.positions.keys()):
            if not common_dates:
                continue
            last_date = common_dates[-1]
            last_data = date_index.get(last_date, {})
            if ts_code in last_data:
                last_price = float(last_data[ts_code]["close"])
                self._execute_sell(ts_code, last_price, last_date, force=True)

    def _enrich_equity_curve(self, bench_nav: list[float]):
        """补充净值曲线中的回撤和基准净值字段"""
        peak = 0.0
        for i, dv in enumerate(self.daily_values):
            nav = dv["nav"]
            peak = max(peak, nav)
            dv["drawdown"] = (peak - nav) / peak if peak > 0 else 0.0
            dv["benchmark_nav"] = bench_nav[i] if i < len(bench_nav) else 1.0

    def _execute_buy(self, ts_code: str, price: float, date: str, regime_mult: float = 1.0):
        """执行买入操作

        Args:
            ts_code: 股票代码
            price: 当前价格
            date: 交易日期
            regime_mult: 市场状态仓位乘数（L1 过滤，默认 1.0=全仓）
        """
        # 检查持仓数量限制
        if len(self.positions) >= self.config.max_positions and ts_code not in self.positions:
            return

        # 计算可用资金（按最大仓位比例 * 市场状态乘数）
        max_amount = self.config.initial_cash * self.config.position_size * regime_mult
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
        """计算基准净值曲线（委托至 PerformanceCalculator）"""
        return self._perf.calc_benchmark_nav(benchmark_data, common_dates)

    # ============================================================
    # 绩效分析
    # ============================================================

    def _build_result(self, bench_nav: list[float]) -> BacktestResult:
        """构建回测结果（委托至 PerformanceCalculator）"""
        return self._perf.build_result(
            self.trades, self.daily_values, self.total_trade_amount, self.config
        )

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
        """获取策略的默认参数搜索空间（委托至 param_grids 模块）

        Args:
            strategy: 策略名称

        Returns:
            参数网格字典
        """
        return get_default_param_grid(strategy)

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
            params: 策略参数（None 或空字典时自动查找个股最优参数）

        Returns:
            BacktestResult
        """
        # 自动解析个股最优参数
        if not params:
            from .param_grids import get_stock_params

            params = get_stock_params(ts_code, strategy) or {}

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
# 主程序入口（真实行情自检）
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    print("=" * 60)
    print("EnhancedBacktestEngine V2 - 真实行情自检")
    print("=" * 60)

    config = BacktestConfig(
        ts_codes=["000333.SZ"],
        strategies=["ma-cross"],
        start_date="20250612",
        end_date="20260612",
        initial_cash=100000,
        slippage=0.001,
        commission_rate=0.00025,
        stamp_tax=0.001,
        enable_t1=True,
        enable_limit=True,
    )
    engine = EnhancedBacktestEngine(config)
    result = engine.run()

    print(f"  标的: {config.ts_codes[0]}")
    print("  数据源: 腾讯财经 → 东方财富 → DataService")
    print(f"  净值曲线: {len(result.equity_curve)} 条")
    print(f"  总收益率: {result.total_return:.4f} ({result.total_return * 100:.2f}%)")
    print(f"  年化收益: {result.annual_return:.4f} ({result.annual_return * 100:.2f}%)")
    print(f"  夏普比率: {result.sharpe_ratio:.4f}")
    print(f"  最大回撤: {result.max_drawdown:.4f} ({result.max_drawdown * 100:.2f}%)")
    print(f"  总交易: {result.total_trades} 次")
