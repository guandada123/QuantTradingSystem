"""
SQLAlchemy ORM 模型 - 对应数据库表结构
"""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from .database import Base


class Account(Base):
    """账户表"""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), unique=True, nullable=False)
    account_name = Column(String(50))
    account_type = Column(String(20), nullable=False)  # SIMULATION / REAL
    total_assets = Column(Numeric(20, 2), default=0.0)
    available_cash = Column(Numeric(20, 2), default=0.0)
    market_value = Column(Numeric(20, 2), default=0.0)
    total_profit_loss = Column(Numeric(20, 2), default=0.0)
    total_profit_loss_ratio = Column(Numeric(10, 4), default=0.0)
    currency = Column(String(10), default="CNY")


class Position(Base):
    """持仓表"""

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(20), ForeignKey("accounts.account_id"), nullable=False)
    ts_code = Column(String(10), ForeignKey("stock_pool.ts_code"), nullable=False)
    direction = Column(String(4), nullable=False)
    total_quantity = Column(Integer, nullable=False)
    available_quantity = Column(Integer, nullable=False)
    locked_quantity = Column(Integer, default=0)
    cost_price = Column(Numeric(10, 2), nullable=False)
    current_price = Column(Numeric(10, 2))
    market_value = Column(Numeric(20, 2))
    profit_loss = Column(Numeric(20, 2))
    profit_loss_ratio = Column(Numeric(10, 4))
    days_held = Column(Integer)
    stop_loss_price = Column(Numeric(10, 2))
    take_profit_price = Column(Numeric(10, 2))
    strategy_name = Column(String(50))
    opened_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now())


class Trade(Base):
    """成交记录表"""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(50), unique=True, nullable=False)
    order_id = Column(String(50), ForeignKey("orders.order_id"))
    account_id = Column(String(20), ForeignKey("accounts.account_id"))
    ts_code = Column(String(10), ForeignKey("stock_pool.ts_code"), nullable=False)
    direction = Column(String(4), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    quantity = Column(Integer, nullable=False)
    amount = Column(Numeric(20, 2), nullable=False)
    commission = Column(Numeric(20, 2))
    tax = Column(Numeric(20, 2))
    profit_loss = Column(Numeric(20, 2))
    trade_date = Column(Date, nullable=False)
    trade_time = Column(Time, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Order(Base):
    """订单表"""

    __tablename__ = "orders"

    order_id = Column(String(50), primary_key=True)
    account_id = Column(String(20), ForeignKey("accounts.account_id"), nullable=False)
    ts_code = Column(String(10), ForeignKey("stock_pool.ts_code"), nullable=False)
    direction = Column(String(4), nullable=False)
    order_type = Column(String(10), nullable=False)
    price = Column(Numeric(10, 2))
    quantity = Column(Integer, nullable=False)
    amount = Column(Numeric(20, 2))
    status = Column(String(20), nullable=False)
    filled_price = Column(Numeric(10, 2))
    filled_quantity = Column(Integer)
    filled_amount = Column(Numeric(20, 2))
    commission = Column(Numeric(20, 2))
    tax = Column(Numeric(20, 2))
    slippage = Column(Numeric(10, 2))
    order_source = Column(String(20))
    strategy_name = Column(String(50))
    signal_id = Column(UUID(as_uuid=True), ForeignKey("trading_signal.signal_id"))
    error_message = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


class StockPool(Base):
    """股票池表"""

    __tablename__ = "stock_pool"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(10), unique=True, nullable=False)
    name = Column(String(50), nullable=False)
    industry = Column(String(50))
    sector = Column(String(50))
    list_date = Column(Date)
    market = Column(String(10))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


class DailyQuote(Base):
    """日线行情表"""

    __tablename__ = "daily_quote"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), nullable=False)
    trade_date = Column(Date, nullable=False)
    open = Column(Numeric(12, 2))
    high = Column(Numeric(12, 2))
    low = Column(Numeric(12, 2))
    close = Column(Numeric(12, 2))
    pre_close = Column(Numeric(12, 2))
    change = Column(Numeric(12, 2))
    pct_change = Column(Numeric(12, 4))
    volume = Column(Integer)
    amount = Column(Numeric(20, 2))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("ts_code", "trade_date", name="uq_daily_quote"),)


class TradingSignal(Base):
    """交易信号表"""

    __tablename__ = "trading_signal"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(UUID(as_uuid=True), unique=True, default=uuid.uuid4)
    ts_code = Column(String(10), ForeignKey("stock_pool.ts_code"), nullable=False)
    signal_type = Column(String(10), nullable=False)  # BUY / SELL / HOLD
    signal_strength = Column(Numeric(5, 2))
    strategy_name = Column(String(50), nullable=False)
    strategy_version = Column(String(20))
    indicator_signals = Column(JSON)
    confidence_score = Column(Numeric(5, 2))
    target_price = Column(Numeric(10, 2))
    stop_loss_price = Column(Numeric(10, 2))
    take_profit_price = Column(Numeric(10, 2))
    timeframe = Column(String(10))  # daily / weekly / monthly
    generated_at = Column(DateTime, nullable=False)
    executed = Column(Boolean, default=False)
    executed_at = Column(DateTime)
    execution_result = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())


class BacktestResult(Base):
    """回测结果表"""

    __tablename__ = "backtest_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backtest_id = Column(UUID(as_uuid=True), default=uuid.uuid4)
    strategy_name = Column(String(50), nullable=False)
    strategy_version = Column(String(20), nullable=False)
    ts_code = Column(String(20), nullable=False, default="")
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    initial_cash = Column(Numeric(20, 2), nullable=False)
    final_value = Column(Numeric(20, 2), nullable=False)
    total_return = Column(Numeric(10, 4))
    annual_return = Column(Numeric(10, 4))
    sharpe_ratio = Column(Numeric(10, 4))
    max_drawdown = Column(Numeric(10, 4))
    win_rate = Column(Numeric(10, 4))
    profit_loss_ratio = Column(Numeric(10, 4))
    total_trades = Column(Integer)
    winning_trades = Column(Integer)
    losing_trades = Column(Integer)
    avg_holding_days = Column(Numeric(10, 2))
    backtest_details = Column(JSON)
    backtest_details_compressed = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class WalkForwardResult(Base):
    """Walk-Forward 分析结果表"""

    __tablename__ = "walk_forward_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wf_id = Column(UUID(as_uuid=True), default=uuid.uuid4)
    strategy_name = Column(String(50), nullable=False)
    ts_code = Column(String(20), nullable=False, default="")
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    train_days = Column(Integer, nullable=False)
    test_days = Column(Integer, nullable=False)
    step_days = Column(Integer, nullable=False)
    param_grid = Column(JSON)
    initial_cash = Column(Numeric(20, 2), nullable=False)
    slippage = Column(Numeric(10, 4))
    commission_rate = Column(Numeric(10, 6))
    benchmark = Column(String(20))
    windows = Column(JSON)
    overall_test_return = Column(Numeric(10, 6))
    overfit_ratio = Column(Numeric(10, 4))
    num_windows = Column(Integer)
    data_source = Column(String(20))
    created_at = Column(DateTime, server_default=func.now())


class BacktestReport(Base):
    """回测报告表"""

    __tablename__ = "backtest_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(UUID(as_uuid=True), default=uuid.uuid4)
    report_type = Column(String(10), nullable=False)  # daily / weekly / monthly
    report_date = Column(Date, nullable=False)
    ts_codes = Column(JSON)  # 存储为JSON数组（SQLite/PostgreSQL兼容）
    strategy_count = Column(Integer, default=0)
    strategies_covered = Column(JSON)  # 覆盖策略详情
    summary = Column(JSON)  # 摘要
    detail_content = Column(Text)  # 报告正文 Markdown
    feishu_msg_id = Column(String(100))
    push_success = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class User(Base):
    """用户表"""

    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


class StockInfo(Base):
    """股票基本信息表"""

    __tablename__ = "stock_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(10), ForeignKey("stock_pool.ts_code"), unique=True, nullable=False)
    total_share = Column(Numeric(20, 2))
    float_share = Column(Numeric(20, 2))
    total_mv = Column(Numeric(20, 2))
    circ_mv = Column(Numeric(20, 2))
    pe = Column(Numeric(10, 2))
    pb = Column(Numeric(10, 2))
    dividend_yield = Column(Numeric(10, 4))
    updated_at = Column(DateTime, server_default=func.now())
