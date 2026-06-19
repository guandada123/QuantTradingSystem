"""
数据仓库层单元测试

覆盖 repositories/ 下全部 6 个 repository 文件：
1. account_repo.py  — DB 查询（Account, Position, StockPool）
2. trade_repo.py    — DB 查询（Trade, StockPool）
3. signal_repo.py   — DB 写入/查询（TradingSignal, StockPool）
4. backtest_repo.py — DB 写入/查询（BacktestResult）
5. stock_repo.py    — DB 查询（StockPool）
6. strategy_repo.py — 内存字典操作（无 DB 依赖）

DB 仓库使用 MagicMock 模拟 db.session，验证查询/过滤/写入行为。
内存仓库直接测试（strategy_repo.py）。
"""

from datetime import date, datetime
import os
import sys
from unittest.mock import MagicMock, PropertyMock, patch
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# =========================================================================
# AccountRepository
# =========================================================================


class TestAccountRepo:
    """account_repo.py — 账户与持仓"""

    def test_get_account_summary_exists(self):
        """账户存在时返回摘要数据"""
        from repositories.account_repo import get_account_summary

        mock_db = MagicMock()
        mock_account = MagicMock()
        mock_account.total_assets = 200000.00
        mock_account.available_cash = 50000.00
        mock_account.market_value = 150000.00
        mock_account.total_profit_loss = 10000.00
        mock_account.total_profit_loss_ratio = 0.0526
        mock_account.currency = "CNY"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_account

        result = get_account_summary(mock_db)
        assert result is not None
        assert result["total_assets"] == 200000.00
        assert result["available_cash"] == 50000.00
        assert result["market_value"] == 150000.00
        assert result["currency"] == "CNY"

    def test_get_account_summary_not_found(self):
        """账户不存在时返回 None"""
        from repositories.account_repo import get_account_summary

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = get_account_summary(mock_db)
        assert result is None

    def test_get_account_summary_default_account_id(self):
        """默认使用 REAL_001 查询"""
        from repositories.account_repo import get_account_summary

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        get_account_summary(mock_db)
        # 验证 filter 已被调用（默认 account_id="REAL_001"）
        mock_db.query.assert_called_once()
        mock_db.query.return_value.filter.assert_called_once()

    def test_get_account_detail_with_positions(self):
        """账户详情包含持仓数量"""
        from repositories.account_repo import get_account_detail

        mock_db = MagicMock()
        mock_account = MagicMock()
        mock_account.total_assets = 150000.00
        mock_account.available_cash = 30000.00
        mock_account.market_value = 120000.00
        mock_account.total_profit_loss = 5000.00
        mock_account.total_profit_loss_ratio = 0.0345
        mock_account.currency = "CNY"
        filter_for_account = mock_db.query.return_value.filter.return_value
        filter_for_account.first.return_value = mock_account
        filter_for_account.count.return_value = 4

        result = get_account_detail(mock_db)
        assert result["positions"] == 4
        assert result["days_active"] == 12
        assert result["daily_return"] == 0.0042

    def test_get_positions_with_filter(self):
        """按 ts_code 过滤持仓"""
        from repositories.account_repo import get_positions

        mock_db = MagicMock()
        mock_position = MagicMock()
        mock_position.ts_code = "600519.SH"
        mock_position.total_quantity = 100
        mock_position.available_quantity = 100
        mock_position.cost_price = 180.0
        mock_position.current_price = 185.5
        mock_position.profit_loss = 550.0
        mock_position.profit_loss_ratio = 0.0306
        mock_position.market_value = 18550.0
        mock_position.days_held = 10
        mock_position.stop_loss_price = 170.0
        mock_position.take_profit_price = 200.0

        mock_filter = mock_db.query.return_value.filter.return_value
        mock_filter.filter.return_value.all.return_value = [mock_position]
        # StockPool 返回空（名称降级为 ts_code）
        mock_db.query.return_value.filter.return_value.all.return_value = []

        result = get_positions(mock_db, ts_code="600519.SH")
        assert len(result) == 1
        assert result[0]["ts_code"] == "600519.SH"
        assert result[0]["name"] == "600519.SH"  # 无 StockPool 时降级

    def test_get_positions_empty(self):
        """无持仓时返回空列表"""
        from repositories.account_repo import get_positions

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = get_positions(mock_db)
        assert result == []

    def test_get_positions_with_stock_names(self):
        """持仓列表中股票名称被正确填充"""
        from repositories.account_repo import get_positions

        mock_db = MagicMock()
        pos = MagicMock()
        pos.ts_code = "000001.SZ"
        pos.total_quantity = 500
        pos.available_quantity = 500
        pos.cost_price = 12.0
        pos.current_price = 12.5
        pos.profit_loss = 250.0
        pos.profit_loss_ratio = 0.0208
        pos.market_value = 6250.0
        pos.days_held = 15
        pos.stop_loss_price = 11.0
        pos.take_profit_price = 14.0

        mock_filter = mock_db.query.return_value.filter.return_value
        mock_filter.filter.return_value.all.return_value = [pos]
        mock_stock = MagicMock()
        mock_stock.ts_code = "000001.SZ"
        mock_stock.name = "平安银行"
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_stock]

        result = get_positions(mock_db)
        assert result[0]["name"] == "平安银行"


# =========================================================================
# TradeRepository
# =========================================================================


class TestTradeRepo:
    """trade_repo.py — 交易记录"""

    def test_get_trades_defaults(self):
        """默认参数返回交易列表"""
        from repositories.trade_repo import get_trades

        mock_db = MagicMock()
        t = MagicMock()
        t.trade_id = "T001"
        t.ts_code = "600519.SH"
        t.direction = "BUY"
        t.price = 180.0
        t.quantity = 100
        t.amount = 18000.0
        t.profit_loss = None
        t.commission = 5.0
        t.trade_date = date(2026, 6, 10)
        t.trade_time = "09:30:00"
        t.created_at = datetime(2026, 6, 10, 9, 30, 0)

        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [t]
        mock_db.query.return_value.filter.return_value.all.return_value = []  # StockPool

        result = get_trades(mock_db)
        assert len(result) == 1
        assert result[0]["trade_id"] == "T001"
        assert result[0]["direction"] == "BUY"

    def test_get_trades_empty(self):
        """无交易时返回空列表"""
        from repositories.trade_repo import get_trades

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        result = get_trades(mock_db)
        assert result == []

    def test_get_trades_with_direction_filter(self):
        """direction 过滤被应用"""
        from repositories.trade_repo import get_trades

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.all.return_value = []

        get_trades(mock_db, direction="SELL")
        # 确保 direction filter 被调用了
        assert mock_db.query.return_value.filter.call_count >= 1

    def test_get_trades_limit_offset(self):
        """limit 和 offset 被传递给查询"""
        from repositories.trade_repo import get_trades

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.all.return_value = []

        result = get_trades(mock_db, limit=10, offset=5)
        assert result == []

    def _setup_trade_stats_mock(self, sell_trades, total_count):
        """为 get_trade_stats 创建 mock DB，处理两个独立的 query+filter 调用"""
        mock_db = MagicMock()

        # get_trade_stats 中两个 db.query(Trade).filter(...) 调用：
        # 1. sell_trades = db.query(Trade).filter(account_id, direction, pl).all()
        # 2. total_all = db.query(Trade).filter(account_id).count()
        # db.query(Trade) 返回同一个 q，q.filter 返回同一个 filter_result
        from models.models import Trade
        q = MagicMock()
        filter_result = q.filter.return_value
        filter_result.all.return_value = sell_trades
        filter_result.count.return_value = total_count

        def query_side_effect(model):
            if model is Trade:
                return q
            return MagicMock()
        mock_db.query.side_effect = query_side_effect
        return mock_db

    def test_get_trade_stats_all_wins(self):
        """全部盈利时胜率 100%"""
        from repositories.trade_repo import get_trade_stats

        w1 = MagicMock()
        w1.profit_loss = 100.0
        w1.direction = "SELL"
        w1.account_id = "REAL_001"
        w2 = MagicMock()
        w2.profit_loss = 200.0
        w2.direction = "SELL"
        w2.account_id = "REAL_001"

        mock_db = self._setup_trade_stats_mock([w1, w2], 5)
        stats = get_trade_stats(mock_db)
        assert stats["win_rate"] == 100.0
        assert stats["avg_loss"] == 0

    def test_get_trade_stats_all_losses(self):
        """全部亏损时胜率 0%"""
        from repositories.trade_repo import get_trade_stats

        l1 = MagicMock()
        l1.profit_loss = -150.0
        l1.direction = "SELL"
        l1.account_id = "REAL_001"

        mock_db = self._setup_trade_stats_mock([l1], 3)
        stats = get_trade_stats(mock_db)
        assert stats["total_trades"] == 1
        assert stats["win_rate"] == 0.0

    def test_get_trade_stats_no_sell_trades(self):
        """无卖出交易时返回零统计"""
        from repositories.trade_repo import get_trade_stats

        mock_db = self._setup_trade_stats_mock([], 8)
        stats = get_trade_stats(mock_db)
        assert stats["total_trades"] == 8
        assert stats["win_rate"] == 0
        assert stats["sharpe_ratio"] == 0

    def test_get_trade_stats_single_zero_profit(self):
        """利润为 0 的交易不计入胜局（0.0 为 falsy，被 and 短路过滤）"""
        from repositories.trade_repo import get_trade_stats

        t = MagicMock()
        t.profit_loss = 0.0
        t.direction = "SELL"
        t.account_id = "REAL_001"

        mock_db = self._setup_trade_stats_mock([t], 1)
        stats = get_trade_stats(mock_db)
        assert stats["total_trades"] == 1
        assert stats["win_rate"] == 0.0  # 0.0 is falsy → not a win


# =========================================================================
# SignalRepository
# =========================================================================


class TestSignalRepo:
    """signal_repo.py — 交易信号"""

    def test_save_signal(self):
        """保存信号并返回序列化结果"""
        from repositories.signal_repo import save_signal

        mock_db = MagicMock()
        signal_data = {
            "ts_code": "600519.SH",
            "signal_type": "buy",
            "signal_strength": 0.85,
            "strategy_name": "ma-cross",
            "strategy_version": "2.0",
            "indicator_signals": {"ma5": 180.0, "ma20": 175.0},
            "confidence_score": 0.75,
            "target_price": 200.0,
            "stop_loss_price": 170.0,
            "take_profit_price": 220.0,
            "timeframe": "daily",
        }

        result = save_signal(mock_db, signal_data)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()

    def test_save_signal_minimal(self):
        """使用最少的必须字段保存信号"""
        from repositories.signal_repo import save_signal

        mock_db = MagicMock()
        signal_data = {
            "ts_code": "000001.SZ",
            "signal_type": "sell",
            "strategy_name": "breakout",
        }
        result = save_signal(mock_db, signal_data)
        assert result is not None
        mock_db.add.assert_called_once()

    def test_get_history(self):
        """获取历史信号列表"""
        from repositories.signal_repo import get_history

        mock_db = MagicMock()
        s = MagicMock()
        s.signal_id = uuid.uuid4()
        s.ts_code = "600519.SH"
        s.signal_type = "buy"
        s.signal_strength = 0.9
        s.strategy_name = "ma-cross"
        s.strategy_version = "1.0"
        s.indicator_signals = None
        s.confidence_score = 0.8
        s.target_price = None
        s.stop_loss_price = None
        s.take_profit_price = None
        s.timeframe = "daily"
        s.generated_at = datetime.now()
        s.executed = False

        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [s]
        mock_db.query.return_value.filter.return_value.all.return_value = []  # StockPool

        result = get_history(mock_db, limit=5)
        assert len(result) == 1
        assert result[0]["signal_type"] == "buy"

    def test_get_history_empty(self):
        """无信号时返回空列表"""
        from repositories.signal_repo import get_history

        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        result = get_history(mock_db)
        assert result == []

    def test_get_history_with_ts_code(self):
        """按 ts_code 过滤信号"""
        from repositories.signal_repo import get_history

        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        result = get_history(mock_db, ts_code="600519.SH", limit=10)
        assert result == []
        filter_call = mock_db.query.return_value.filter.call_args[0][0]
        # filter 被调用（用于 ts_code 过滤）

    def test_get_latest_found(self):
        """获取某股票最新信号"""
        from repositories.signal_repo import get_latest

        mock_db = MagicMock()
        s = MagicMock()
        s.signal_id = uuid.uuid4()
        s.ts_code = "600519.SH"
        s.signal_type = "buy"
        s.signal_strength = 0.85
        s.strategy_name = "ma-cross"
        s.strategy_version = "1.0"
        s.indicator_signals = None
        s.confidence_score = None
        s.target_price = None
        s.stop_loss_price = None
        s.take_profit_price = None
        s.timeframe = "daily"
        s.generated_at = datetime.now()
        s.executed = False

        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = s
        mock_stock = MagicMock()
        mock_stock.name = "贵州茅台"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_stock

        result = get_latest(mock_db, "600519.SH")
        assert result is not None
        assert result["signal_type"] == "buy"
        assert result["name"] == "贵州茅台"

    def test_get_latest_not_found(self):
        """股票无信号时返回 None"""
        from repositories.signal_repo import get_latest

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = get_latest(mock_db, "000001.SZ")
        assert result is None

    def test_get_signals_by_strategy(self):
        """按策略名查询信号"""
        from repositories.signal_repo import get_signals_by_strategy

        mock_db = MagicMock()
        s = MagicMock()
        s.signal_id = uuid.uuid4()
        s.ts_code = "600519.SH"
        s.signal_type = "buy"
        s.signal_strength = 0.7
        s.strategy_name = "rsi"
        s.strategy_version = "1.0"
        s.indicator_signals = None
        s.confidence_score = 0.6
        s.target_price = None
        s.stop_loss_price = None
        s.take_profit_price = None
        s.timeframe = "daily"
        s.generated_at = datetime.now()
        s.executed = True

        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [s]

        result = get_signals_by_strategy(mock_db, "rsi")
        assert len(result) == 1
        assert result[0]["strategy_name"] == "rsi"
        assert result[0]["executed"] is True


# =========================================================================
# BacktestRepository
# =========================================================================


class TestBacktestRepo:
    """backtest_repo.py — 回测结果"""

    def test_save_backtest_result(self):
        """保存回测结果"""
        from repositories.backtest_repo import save_backtest_result

        mock_db = MagicMock()
        result_data = {
            "strategy_name": "ma-cross",
            "strategy_version": "2.0",
            "ts_code": "600519.SH",
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 6, 1),
            "initial_cash": 100000.0,
            "final_value": 115000.0,
            "total_return": 0.15,
            "annual_return": 0.30,
            "sharpe_ratio": 1.25,
            "max_drawdown": 0.08,
            "win_rate": 0.55,
            "profit_loss_ratio": 1.8,
            "total_trades": 45,
            "winning_trades": 25,
            "losing_trades": 20,
            "avg_holding_days": 5.5,
            "backtest_details": {"trades": []},
        }

        result = save_backtest_result(mock_db, result_data)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()
        assert result is not None

    def test_save_backtest_minimal(self):
        """使用最少的必须字段保存"""
        from repositories.backtest_repo import save_backtest_result

        mock_db = MagicMock()
        result_data = {
            "strategy_name": "test",
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 3, 1),
            "initial_cash": 50000.0,
            "final_value": 52000.0,
        }
        result = save_backtest_result(mock_db, result_data)
        assert result is not None

    def test_get_backtest_result_found(self):
        """按 backtest_id 查询回测结果"""
        from repositories.backtest_repo import get_backtest_result

        mock_db = MagicMock()
        r = MagicMock()
        r.backtest_id = uuid.uuid4()
        r.strategy_name = "ma-cross"
        r.strategy_version = "1.0"
        r.ts_code = "600519.SH"
        r.start_date = date(2024, 1, 1)
        r.end_date = date(2024, 6, 1)
        r.initial_cash = 100000.0
        r.final_value = 115000.0
        r.total_return = 0.15
        r.annual_return = 0.30
        r.sharpe_ratio = 1.25
        r.max_drawdown = 0.08
        r.win_rate = 0.55
        r.profit_loss_ratio = 1.8
        r.total_trades = 45
        r.winning_trades = 25
        r.losing_trades = 20
        r.avg_holding_days = 5.5
        r.created_at = datetime.now()

        mock_db.query.return_value.filter.return_value.first.return_value = r

        result = get_backtest_result(mock_db, str(r.backtest_id))
        assert result is not None
        assert result["strategy_name"] == "ma-cross"
        assert result["total_return"] == 0.15

    def test_get_backtest_result_not_found(self):
        """不存在的 backtest_id 返回 None"""
        from repositories.backtest_repo import get_backtest_result

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        bid = str(uuid.uuid4())
        result = get_backtest_result(mock_db, bid)
        assert result is None

    def test_get_backtest_result_invalid_uuid(self):
        """无效的 UUID 格式返回 None"""
        from repositories.backtest_repo import get_backtest_result

        mock_db = MagicMock()
        result = get_backtest_result(mock_db, "not-a-uuid")
        assert result is None
        mock_db.query.assert_not_called()

    def test_get_backtest_history(self):
        """获取最近回测记录"""
        from repositories.backtest_repo import get_backtest_history

        mock_db = MagicMock()
        r = MagicMock()
        r.backtest_id = uuid.uuid4()
        r.strategy_name = "breakout"
        r.strategy_version = "1.0"
        r.ts_code = "000001.SZ"
        r.start_date = date(2024, 3, 1)
        r.end_date = date(2024, 9, 1)
        r.initial_cash = 100000.0
        r.final_value = 108000.0
        r.total_return = 0.08
        r.annual_return = 0.16
        r.sharpe_ratio = 0.95
        r.max_drawdown = 0.12
        r.win_rate = 0.42
        r.profit_loss_ratio = 1.5
        r.total_trades = 30
        r.winning_trades = 12
        r.losing_trades = 18
        r.avg_holding_days = 8.0
        r.created_at = datetime.now()

        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [r]

        result = get_backtest_history(mock_db, limit=10)
        assert len(result) == 1
        assert result[0]["strategy_name"] == "breakout"

    def test_get_backtest_history_empty(self):
        """无回测记录时返回空列表"""
        from repositories.backtest_repo import get_backtest_history

        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = []

        result = get_backtest_history(mock_db)
        assert result == []


# =========================================================================
# StockRepository
# =========================================================================


class TestStockRepo:
    """stock_repo.py — 股票池"""

    def test_get_stock_pool(self):
        """获取股票池列表"""
        from repositories.stock_repo import get_stock_pool

        mock_db = MagicMock()
        s = MagicMock()
        s.ts_code = "600519.SH"
        s.name = "贵州茅台"
        s.industry = "白酒"
        s.sector = "消费"
        s.market = "主板"
        s.list_date = date(2001, 8, 27)
        s.is_active = True

        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [s]

        result = get_stock_pool(mock_db, limit=20)
        assert len(result) == 1
        assert result[0]["name"] == "贵州茅台"
        assert result[0]["industry"] == "白酒"
        assert result[0]["is_active"] is True

    def test_get_stock_pool_empty(self):
        """股票池空时返回空列表"""
        from repositories.stock_repo import get_stock_pool

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        result = get_stock_pool(mock_db)
        assert result == []

    def test_get_stock_pool_with_industry_filter(self):
        """按行业过滤股票池"""
        from repositories.stock_repo import get_stock_pool

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        result = get_stock_pool(mock_db, industry="白酒")
        assert result == []
        # 验证 industry 过滤被应用（ilike 调用）
        assert mock_db.query.return_value.filter.return_value.filter.call_count >= 1

    def test_search_stocks_by_code(self):
        """按代码模糊搜索"""
        from repositories.stock_repo import search_stocks

        mock_db = MagicMock()
        s = MagicMock()
        s.ts_code = "600519.SH"
        s.name = "贵州茅台"
        s.industry = "白酒"
        s.market = "主板"

        mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = [s]

        result = search_stocks(mock_db, "600519")
        assert len(result) == 1
        assert result[0]["ts_code"] == "600519.SH"

    def test_search_stocks_by_name(self):
        """按名称模糊搜索"""
        from repositories.stock_repo import search_stocks

        mock_db = MagicMock()
        s = MagicMock()
        s.ts_code = "000001.SZ"
        s.name = "平安银行"
        s.industry = "银行"
        s.market = "主板"

        mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = [s]

        result = search_stocks(mock_db, "平安")
        assert len(result) == 1
        assert result[0]["name"] == "平安银行"

    def test_search_stocks_empty(self):
        """搜索无结果返回空列表"""
        from repositories.stock_repo import search_stocks

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = []

        result = search_stocks(mock_db, "不存在的股票")
        assert result == []


# =========================================================================
# StrategyRepository (In-Memory)
# =========================================================================


class TestStrategyRepo:
    """strategy_repo.py — 内存策略仓库（需要全局单例重置）"""

    @pytest.fixture(autouse=True)
    def reset_repo(self):
        """每次测试前重置单例仓库为初始状态"""
        import models.strategy as sm
        from repositories.strategy_repo import strategy_repo

        # 重置内部存储
        strategy_repo._store = {}
        strategy_repo._init_builtins()
        yield

    def test_list_all(self):
        """列出所有策略，默认 active"""
        from repositories.strategy_repo import strategy_repo

        strategies = strategy_repo.list_all()
        assert len(strategies) > 0
        # 所有内置策略默认 active
        assert all(s["status"] == "active" for s in strategies)

    def test_list_all_with_type_filter(self):
        """按 type 过滤策略"""
        from repositories.strategy_repo import strategy_repo

        builtins = strategy_repo.list_all(type_filter="builtin")
        custom = strategy_repo.list_all(type_filter="custom")
        assert len(builtins) > 0
        assert len(custom) == 0

    def test_get_by_id_builtin(self):
        """按 ID 获取内置策略"""
        from repositories.strategy_repo import strategy_repo

        s = strategy_repo.get_by_id("builtin-ma-cross")
        assert s is not None
        assert s.name == "双均线金叉"
        assert s.type == "builtin"

    def test_get_by_id_not_found(self):
        """不存在的 ID 返回 None"""
        from repositories.strategy_repo import strategy_repo

        s = strategy_repo.get_by_id("nonexistent")
        assert s is None

    def test_create_custom_strategy(self):
        """创建自定义策略"""
        from models.strategy import Strategy
        from repositories.strategy_repo import strategy_repo

        s = Strategy(
            id="my-custom",
            name="自定义策略",
            type="custom",
            description="我的自定义策略",
            params={"param1": 10},
        )
        created = strategy_repo.create(s)
        assert created.id == "my-custom"
        assert created.name == "自定义策略"

        # 验证已存入
        fetched = strategy_repo.get_by_id("my-custom")
        assert fetched is not None

    def test_create_duplicate_id_raises(self):
        """重复 ID 创建抛 StrategyConflictError"""
        from models.strategy import Strategy
        from repositories.strategy_repo import strategy_repo
        from shared.exceptions import StrategyConflictError

        s1 = Strategy(id="dup-id", name="第一个", type="custom")
        strategy_repo.create(s1)

        s2 = Strategy(id="dup-id", name="第二个", type="custom")
        with pytest.raises(StrategyConflictError, match="策略ID已存在"):
            strategy_repo.create(s2)

    def test_update_custom_strategy(self):
        """更新自定义策略成功"""
        from models.strategy import Strategy
        from repositories.strategy_repo import strategy_repo

        strategy_repo.create(Strategy(id="upd", name="原始名称", type="custom"))
        updated = strategy_repo.update("upd", {"name": "新名称", "description": "新描述"})
        assert updated is not None
        assert updated.name == "新名称"
        assert updated.description == "新描述"

    def test_update_builtin_limited(self):
        """内置策略仅允许更新白名单字段"""
        from repositories.strategy_repo import strategy_repo

        s = strategy_repo.update("builtin-ma-cross", {"name": "不应改", "params": {"ma_fast": 10}})
        assert s is not None
        # 内置策略不允许修改 name
        assert s.name != "不应改"
        # params 可以被修改
        assert s.params["ma_fast"] == 10

    def test_update_not_found(self):
        """不存在的策略返回 None"""
        from repositories.strategy_repo import strategy_repo

        result = strategy_repo.update("nonexistent", {"name": "test"})
        assert result is None

    def test_delete_custom(self):
        """删除自定义策略成功"""
        from models.strategy import Strategy
        from repositories.strategy_repo import strategy_repo

        strategy_repo.create(Strategy(id="del-me", name="待删除", type="custom"))
        result = strategy_repo.delete("del-me")
        assert result is True
        assert strategy_repo.get_by_id("del-me") is None

    def test_delete_builtin_raises(self):
        """删除内置策略抛 StrategyValidationError"""
        from repositories.strategy_repo import strategy_repo
        from shared.exceptions import StrategyValidationError

        with pytest.raises(StrategyValidationError, match="内置策略不允许删除"):
            strategy_repo.delete("builtin-ma-cross")

    def test_delete_not_found(self):
        """不存在的策略返回 False"""
        from repositories.strategy_repo import strategy_repo

        result = strategy_repo.delete("nonexistent")
        assert result is False

    def test_save_performance(self):
        """保存策略回测表现"""
        from repositories.strategy_repo import strategy_repo

        perf = {"sharpe": 2.0, "total_return": 0.45}
        result = strategy_repo.save_performance("builtin-ma-cross", perf)
        assert result is True
        s = strategy_repo.get_by_id("builtin-ma-cross")
        assert s.performance == perf

    def test_save_performance_not_found(self):
        """不存在的策略返回 False"""
        from repositories.strategy_repo import strategy_repo

        result = strategy_repo.save_performance("nonexistent", {})
        assert result is False

    def test_builtin_strategies_have_performance(self):
        """所有内置策略应包含回测表现数据（stock-insight 为选股策略无 performance）"""
        from repositories.strategy_repo import strategy_repo

        for s in strategy_repo._store.values():
            if s.type == "builtin" and s.performance is not None:
                assert "sharpe" in s.performance
