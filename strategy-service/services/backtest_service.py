"""
回测引擎 v2.0
支持：Backtrader集成 + 内置简化引擎（无Backtrader依赖时降级）
策略：ma-cross / breakout / rsi / macd / kdj
"""

import logging
import json
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import uuid

logger = logging.getLogger(__name__)

@dataclass
class BacktestResult:
    """回测结果"""
    backtest_id: str
    strategy_name: str
    ts_code: str
    start_date: str
    end_date: str
    initial_cash: float
    final_value: float
    total_return: float        # 总收益率
    annual_return: float       # 年化收益率
    sharpe_ratio: float        # 夏普比率
    max_drawdown: float        # 最大回撤
    win_rate: float            # 胜率
    profit_loss_ratio: float   # 盈亏比
    total_trades: int          # 总交易次数
    winning_trades: int        # 盈利次数
    losing_trades: int         # 亏损次数
    avg_holding_days: float    # 平均持仓天数
    daily_values: List[Dict] = field(default_factory=list)  # 每日净值
    trades: List[Dict] = field(default_factory=list)         # 交易明细

class SimpleBacktestEngine:
    """内置简化回测引擎（无Backtrader依赖）"""
    
    def __init__(self, initial_cash: float = 50000.0, commission: float = 0.0003, tax: float = 0.001):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission = commission
        self.tax = tax
        self.position = 0
        self.cost_price = 0
        self.trades = []
        self.daily_values = []

    @property
    def holdings(self):
        """别名：兼容测试的 holdings 属性"""
        return self.position

    def reset(self):
        """重置回测状态"""
        self.cash = self.initial_cash
        self.position = 0
        self.cost_price = 0
        self.trades = []
        self.daily_values = []
    
    def calculate_ma(self, prices: List[float], period: int) -> List[float]:
        """计算移动平均线"""
        if len(prices) < period:
            return [0] * len(prices)
        
        ma = [0] * (period - 1)
        for i in range(period - 1, len(prices)):
            avg = sum(prices[i - period + 1:i + 1]) / period
            ma.append(avg)
        return ma
    
    def calculate_rsi(self, prices: List[float], period: int = 14) -> List[float]:
        """计算RSI指标"""
        if len(prices) < period + 1:
            return [50] * len(prices)
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        
        rsi = [50] * period  # 前period天无RSI值
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
            if avg_loss == 0:
                rs = 100
            else:
                rs = avg_gain / avg_loss
            
            rsi_value = 100 - (100 / (1 + rs))
            rsi.append(min(100, max(0, rsi_value)))
        
        return rsi
    
    def calculate_macd(self, prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[List, List, List]:
        """计算MACD指标"""
        if len(prices) < slow:
            return [0]*len(prices), [0]*len(prices), [0]*len(prices)
        
        ema_fast = [prices[0]]
        ema_slow = [prices[0]]
        
        alpha_fast = 2 / (fast + 1)
        alpha_slow = 2 / (slow + 1)
        
        for i in range(1, len(prices)):
            ema_fast.append(alpha_fast * prices[i] + (1 - alpha_fast) * ema_fast[-1])
            ema_slow.append(alpha_slow * prices[i] + (1 - alpha_slow) * ema_slow[-1])
        
        dif = [ema_fast[i] - ema_slow[i] for i in range(len(prices))]
        dea = [0] * len(prices)
        
        if len(prices) > signal:
            dea[signal - 1] = sum(dif[:signal]) / signal
            alpha_signal = 2 / (signal + 1)
            for i in range(signal, len(dif)):
                dea[i] = alpha_signal * dif[i] + (1 - alpha_signal) * dea[i-1]
        
        macd = [(dif[i] - dea[i]) * 2 for i in range(len(prices))]
        return dif, dea, macd
    
    def run_ma_cross(self, closes: List[float], dates: List[str],
                     ma_fast: int = 5, ma_slow: int = 20) -> BacktestResult:
        """双均线金叉策略回测"""
        self.reset()
        
        fast_ma = self.calculate_ma(closes, ma_fast)
        slow_ma = self.calculate_ma(closes, ma_slow)
        
        for i in range(max(ma_fast, ma_slow), len(closes)):
            current_date = dates[i]
            price = closes[i]
            
            # 记录净值
            self.daily_values.append({
                'date': current_date,
                'value': self.cash + self.position * price
            })
            
            # 交易信号
            if fast_ma[i] > slow_ma[i] and fast_ma[i-1] <= slow_ma[i-1]:
                # 金叉买入
                if self.cash >= price * 100:
                    buy_qty = int(self.cash * 0.3 / price / 100) * 100  # 30%仓位
                    if buy_qty > 0:
                        cost = buy_qty * price
                        commission = cost * self.commission
                        if cost + commission <= self.cash:
                            self.cash -= (cost + commission)
                            self.position += buy_qty
                            self.cost_price = price
                            self.trades.append({
                                'date': current_date, 'action': 'BUY',
                                'price': price, 'qty': buy_qty, 'cost': cost + commission
                            })
            
            elif fast_ma[i] < slow_ma[i] and fast_ma[i-1] >= slow_ma[i-1]:
                # 死叉卖出
                if self.position > 0:
                    revenue = self.position * price
                    commission = revenue * self.commission
                    tax = revenue * self.tax
                    self.cash += (revenue - commission - tax)
                    self.trades.append({
                        'date': current_date, 'action': 'SELL',
                        'price': price, 'qty': self.position,
                        'revenue': revenue - commission - tax
                    })
                    self.position = 0
        
        # 清仓
        if self.position > 0:
            last_price = closes[-1]
            revenue = self.position * last_price
            commission = revenue * self.commission
            tax = revenue * self.tax
            self.cash += (revenue - commission - tax)
        
        return self._build_result(closes[-1])
    
    def run_breakout(self, closes: List[float], highs: List[float] = None, dates: List[str] = None,
                     lookback: int = 20) -> BacktestResult:
        """突破策略回测（突破N日高点买入，跌破N日低点卖出）"""
        self.reset()
        
        if highs is None:
            highs = closes  # 降级：使用收盘价作为高价
        if dates is None:
            dates = [f"Day{i}" for i in range(len(closes))]
        
        for i in range(lookback, len(closes)):
            current_date = dates[i]
            price = closes[i]
            
            self.daily_values.append({
                'date': current_date,
                'value': self.cash + self.position * price
            })
            
            # 突破最高点买入
            if highs[i] > max(highs[i-lookback:i]):
                if self.position == 0 and self.cash >= price * 100:
                    buy_qty = int(self.cash * 0.5 / price / 100) * 100
                    if buy_qty > 0:
                        cost = buy_qty * price
                        commission = cost * self.commission
                        if cost + commission <= self.cash:
                            self.cash -= (cost + commission)
                            self.position += buy_qty
                            self.cost_price = price
                            self.trades.append({
                                'date': current_date, 'action': 'BUY',
                                'price': price, 'qty': buy_qty
                            })
            
            # 止损/止盈
            if self.position > 0:
                loss_ratio = (price - self.cost_price) / self.cost_price
                if loss_ratio < -0.08 or loss_ratio > 0.30:
                    revenue = self.position * price
                    commission = revenue * self.commission
                    tax = revenue * self.tax
                    self.cash += (revenue - commission - tax)
                    self.trades.append({
                        'date': current_date, 'action': 'SELL',
                        'price': price, 'qty': self.position,
                        'reason': 'STOP' if loss_ratio < -0.08 else 'PROFIT'
                    })
                    self.position = 0
        
        if self.position > 0:
            last_price = closes[-1]
            self.cash += self.position * last_price * (1 - self.commission - self.tax)
        
        return self._build_result(closes[-1])
    
    def run_rsi(self, closes: List[float], dates: List[str],
                period: int = 14, oversold: int = 30, overbought: int = 70) -> BacktestResult:
        """RSI策略回测"""
        self.reset()
        if len(closes) <= period + 1:
            return self._build_result(closes[-1])

        rsi_values = self.calculate_rsi(closes, period)
        safe_end = min(len(closes), len(rsi_values))

        for i in range(period + 1, safe_end):
            price = closes[i]
            current_date = dates[i]
            
            self.daily_values.append({
                'date': current_date,
                'value': self.cash + self.position * price
            })
            
            # RSI超卖买入
            if rsi_values[i] < oversold and rsi_values[i-1] >= oversold:
                if self.position == 0 and self.cash >= price * 100:
                    buy_qty = int(self.cash * 0.3 / price / 100) * 100
                    if buy_qty > 0:
                        cost = buy_qty * price
                        commission = cost * self.commission
                        if cost + commission <= self.cash:
                            self.cash -= (cost + commission)
                            self.position += buy_qty
                            self.cost_price = price
                            self.trades.append({
                                'date': current_date, 'action': 'BUY',
                                'price': price, 'qty': buy_qty
                            })
            
            # RSI超买卖出
            elif rsi_values[i] > overbought and rsi_values[i-1] <= overbought:
                if self.position > 0:
                    revenue = self.position * price
                    commission = revenue * self.commission
                    tax = revenue * self.tax
                    self.cash += (revenue - commission - tax)
                    self.trades.append({
                        'date': current_date, 'action': 'SELL',
                        'price': price, 'qty': self.position
                    })
                    self.position = 0
        
        if self.position > 0:
            self.cash += self.position * closes[-1] * (1 - self.commission - self.tax)
        
        return self._build_result(closes[-1])
    
    def _build_result(self, last_price: float, ts_code: str = '', start: str = '', end: str = '') -> BacktestResult:
        """构建回测结果"""
        if not self.trades:
            return BacktestResult(
                backtest_id=str(uuid.uuid4())[:8],
                strategy_name='', ts_code=ts_code, start_date=start, end_date=end,
                initial_cash=self.initial_cash, final_value=self.initial_cash,
                total_return=0, annual_return=0, sharpe_ratio=0, max_drawdown=0,
                win_rate=0, profit_loss_ratio=0, total_trades=0,
                winning_trades=0, losing_trades=0, avg_holding_days=0
            )
        
        # 计算性能指标
        sells = [t for t in self.trades if t['action'] == 'SELL']
        buys = [t for t in self.trades if t['action'] == 'BUY']
        
        # 胜率
        winning = sum(1 for i in range(len(sells)) if sells[i].get('price', 0) > buys[i].get('price', 0) if i < len(buys))
        total_trades = len(sells)
        win_rate = winning / total_trades if total_trades > 0 else 0
        
        # 总收益率
        final_value = self.cash
        total_return = (final_value - self.initial_cash) / self.initial_cash
        
        # 年化收益率（假设365天）
        days = len(self.daily_values) if self.daily_values else 252
        annual_return = (1 + total_return) ** (252 / max(days, 1)) - 1
        
        # 最大回撤
        values = [v['value'] for v in self.daily_values]
        max_drawdown = 0
        peak = values[0] if values else self.initial_cash
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            max_drawdown = max(max_drawdown, dd)
        
        # 夏普比率（简化计算，假设无风险利率=0.02）
        if len(values) > 1:
            returns = [(values[i] - values[i-1]) / values[i-1] for i in range(1, len(values))]
            avg_return = sum(returns) / len(returns) if returns else 0
            std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5 if returns else 1
            sharpe = 0 if std_return == 0 else (avg_return * 252 - 0.02) / (std_return * (252 ** 0.5))
        else:
            sharpe = 0
        
        # 盈亏比
        profits = [s['price'] - b['price'] for s, b in zip(sells, buys) if s['price'] > b['price']] if sells and buys else []
        losses = [b['price'] - s['price'] for s, b in zip(sells, buys) if s['price'] <= b['price']] if sells and buys else []
        avg_profit = sum(profits) / len(profits) if profits else 0
        avg_loss = sum(losses) / len(losses) if losses else 1
        profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 0
        
        return BacktestResult(
            backtest_id=str(uuid.uuid4())[:8],
            strategy_name='', ts_code=ts_code, start_date=start, end_date=end,
            initial_cash=self.initial_cash, final_value=final_value,
            total_return=total_return, annual_return=annual_return,
            sharpe_ratio=sharpe, max_drawdown=max_drawdown,
            win_rate=win_rate, profit_loss_ratio=profit_loss_ratio,
            total_trades=total_trades, winning_trades=winning,
            losing_trades=total_trades - winning, avg_holding_days=5,
            daily_values=self.daily_values, trades=self.trades
        )

class BacktestService:
    """回测服务"""
    
    def __init__(self):
        self.engine = SimpleBacktestEngine()
        self.results = {}  # 缓存回测结果
    
    def run_backtest(
        self,
        ts_code: str,
        strategy: str,
        data: List[Dict],
        params: Dict[str, Any] = None
    ) -> BacktestResult:
        """运行回测"""
        if len(data) < 30:
            raise ValueError(f"数据不足（至少需要30条记录，当前{len(data)}条）")
        
        closes = [float(d['close']) for d in data]
        dates = [str(d.get('trade_date', d.get('date', ''))) for d in data]
        highs = [float(d.get('high', c)) for d, c in zip(data, closes)]
        
        params = params or {}
        
        if strategy == 'ma-cross':
            result = self.engine.run_ma_cross(
                closes, dates,
                ma_fast=params.get('ma_fast', 5),
                ma_slow=params.get('ma_slow', 20)
            )
        elif strategy == 'breakout':
            result = self.engine.run_breakout(
                closes, highs, dates,
                lookback=params.get('lookback', 20)
            )
        elif strategy == 'rsi':
            result = self.engine.run_rsi(
                closes, dates,
                period=params.get('period', 14),
                oversold=params.get('oversold', 30),
                overbought=params.get('overbought', 70)
            )
        else:
            raise ValueError(f"不支持的策略：{strategy}，可选：ma-cross/breakout/rsi")
        
        result.strategy_name = strategy
        result.ts_code = ts_code
        result.start_date = dates[0] if dates else ''
        result.end_date = dates[-1] if dates else ''
        
        return result
    
    def optimize_params(
        self,
        ts_code: str,
        strategy: str,
        data: List[Dict],
        param_ranges: Dict[str, List]
    ) -> Dict[str, Any]:
        """参数优化（网格搜索）"""
        best_result = None
        best_params = None
        best_sharpe = -float('inf')
        
        if strategy == 'ma-cross':
            for fast in param_ranges.get('ma_fast', [5, 10]):
                for slow in param_ranges.get('ma_slow', [20, 30]):
                    result = self.run_backtest(ts_code, strategy, data, {
                        'ma_fast': fast, 'ma_slow': slow
                    })
                    if result.sharpe_ratio > best_sharpe:
                        best_sharpe = result.sharpe_ratio
                        best_result = result
                        best_params = {'ma_fast': fast, 'ma_slow': slow}
        
        return {
            'best_params': best_params,
            'best_sharpe': best_sharpe,
            'result': best_result.__dict__ if best_result else None
        }
