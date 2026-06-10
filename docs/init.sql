-- ============================================
-- QuantTradingSystem 数据库初始化脚本
-- 数据库：PostgreSQL 15+
-- 编码：UTF-8
-- 创建时间：2026-06-07
-- ============================================

-- 创建数据库（如果不存在）
-- CREATE DATABASE quant_trading;

-- 连接到数据库
\c quant_trading;

-- 创建扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- 创建扩展（TimescaleDB需要单独安装，Homebrew版本跳过）
-- CREATE EXTENSION IF NOT EXISTS "timescaledb" CASCADE;

-- ============================================
-- 1. 用户与权限表
-- ============================================

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE users IS '系统用户表';
COMMENT ON COLUMN users.user_id IS '用户ID（主键）';
COMMENT ON COLUMN users.username IS '用户名';
COMMENT ON COLUMN users.email IS '邮箱地址';

-- ============================================
-- 2. 股票基础数据表
-- ============================================

-- 股票池表
CREATE TABLE IF NOT EXISTS stock_pool (
    id SERIAL PRIMARY KEY,
    ts_code VARCHAR(10) UNIQUE NOT NULL,
    name VARCHAR(50) NOT NULL,
    industry VARCHAR(50),
    sector VARCHAR(50),
    list_date DATE,
    market VARCHAR(10),  -- 主板/中小板/创业板/科创板
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_stock_pool_ts_code ON stock_pool(ts_code);
CREATE INDEX idx_stock_pool_industry ON stock_pool(industry);
COMMENT ON TABLE stock_pool IS '股票池表，存储可交易的股票列表';

-- 股票基本信息表
CREATE TABLE IF NOT EXISTS stock_info (
    id SERIAL PRIMARY KEY,
    ts_code VARCHAR(10) UNIQUE NOT NULL REFERENCES stock_pool(ts_code),
    total_share BIGINT,  -- 总股本
    float_share BIGINT,    -- 流通股本
    total_assets DECIMAL(20,2),  -- 总资产
    total_liabilities DECIMAL(20,2),  -- 总负债
    total_market_cap DECIMAL(20,2),  -- 总市值
    float_market_cap DECIMAL(20,2),  -- 流通市值
    pe_ratio DECIMAL(10,2),  -- 市盈率
    pb_ratio DECIMAL(10,2),  -- 市净率
    roe DECIMAL(10,4),  -- 净资产收益率
    debt_ratio DECIMAL(10,4),  -- 资产负债率
    revenue_growth DECIMAL(10,4),  -- 营收增长率
    profit_growth DECIMAL(10,4),  -- 利润增长率
    updated_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE stock_info IS '股票基本面信息表';

-- ============================================
-- 3. 行情数据表（使用TimescaleDB分区）
-- ============================================

-- 日行情数据表
CREATE TABLE IF NOT EXISTS daily_quote (
    id BIGSERIAL PRIMARY KEY,
    ts_code VARCHAR(10) NOT NULL REFERENCES stock_pool(ts_code),
    trade_date DATE NOT NULL,
    open DECIMAL(10,2),
    high DECIMAL(10,2),
    low DECIMAL(10,2),
    close DECIMAL(10,2),
    pre_close DECIMAL(10,2),
    change DECIMAL(10,2),
    pct_change DECIMAL(10,2),
    volume BIGINT,
    amount DECIMAL(20,2),
    turnover_ratio DECIMAL(10,4),  -- 换手率
    pe_ratio DECIMAL(10,2),
    pb_ratio DECIMAL(10,2),
    ps_ratio DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ts_code, trade_date)
);

-- 创建普通索引替代TimescaleDB超表（本地开发环境）
CREATE INDEX idx_daily_quote_date ON daily_quote(trade_date DESC);

CREATE INDEX idx_daily_quote_ts_code_date ON daily_quote(ts_code, trade_date DESC);
COMMENT ON TABLE daily_quote IS '日行情数据表';

-- 分钟级K线数据表（存储在QuestDB，这里仅作为元数据）
CREATE TABLE IF NOT EXISTS minute_quote_metadata (
    id BIGSERIAL PRIMARY KEY,
    ts_code VARCHAR(10) NOT NULL REFERENCES stock_pool(ts_code),
    freq VARCHAR(5) NOT NULL,  -- 1min/5min/15min/30min/60min
    questdb_table_name VARCHAR(50),  -- QuestDB中的表名
    start_date DATE,
    end_date DATE,
    record_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ts_code, freq)
);

COMMENT ON TABLE minute_quote_metadata IS '分钟级K线元数据表，实际数据存储在QuestDB';

-- ============================================
-- 4. 技术指标表
-- ============================================

-- 技术指标数据表
CREATE TABLE IF NOT EXISTS technical_indicators (
    id BIGSERIAL PRIMARY KEY,
    ts_code VARCHAR(10) NOT NULL REFERENCES stock_pool(ts_code),
    trade_date DATE NOT NULL,
    indicator_name VARCHAR(20) NOT NULL,  -- MA/MACD/RSI/KDJ/BOLL/ATR等
    indicator_value DECIMAL(20,6),  -- 指标值（如MA5/MA10）
    indicator_signal INTEGER,  -- 信号：1买入/0持有/-1卖出
    params JSONB,  -- 指标参数（如{"n": 5}）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ts_code, trade_date, indicator_name)
);

CREATE INDEX idx_technical_indicators_ts_code_date ON technical_indicators(ts_code, trade_date DESC);
COMMENT ON TABLE technical_indicators IS '技术指标数据表';

-- ============================================
-- 5. 交易信号表
-- ============================================

-- 交易信号表
CREATE TABLE IF NOT EXISTS trading_signal (
    id BIGSERIAL PRIMARY KEY,
    signal_id UUID UNIQUE DEFAULT uuid_generate_v4(),
    ts_code VARCHAR(10) NOT NULL REFERENCES stock_pool(ts_code),
    signal_type VARCHAR(10) NOT NULL,  -- 'BUY'/'SELL'/'HOLD'
    signal_strength DECIMAL(5,2),  -- 信号强度（0-100）
    strategy_name VARCHAR(50) NOT NULL,  -- 策略名称
    strategy_version VARCHAR(20),  -- 策略版本
    indicator_signals JSONB,  -- 各指标信号详情
    confidence_score DECIMAL(5,2),  -- 置信度评分
    target_price DECIMAL(10,2),  -- 目标价位
    stop_loss_price DECIMAL(10,2),  -- 止损价位
    take_profit_price DECIMAL(10,2),  -- 止盈价位
    timeframe VARCHAR(10),  -- 时间框架：1d/1w/1M
    generated_at TIMESTAMP NOT NULL,
    executed BOOLEAN DEFAULT FALSE,
    executed_at TIMESTAMP,
    execution_result JSONB,  -- 执行结果
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_trading_signal_ts_code ON trading_signal(ts_code);
CREATE INDEX idx_trading_signal_generated_at ON trading_signal(generated_at DESC);
CREATE INDEX idx_trading_signal_executed ON trading_signal(executed);
COMMENT ON TABLE trading_signal IS '交易信号表，存储策略生成的买卖信号';

-- ============================================
-- 6. 订单与交易表
-- ============================================

-- 订单表
CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(50) UNIQUE NOT NULL,
    ts_code VARCHAR(10) NOT NULL REFERENCES stock_pool(ts_code),
    direction VARCHAR(4) NOT NULL,  -- 'BUY'/'SELL'
    order_type VARCHAR(10) NOT NULL,  -- 'LIMIT'/'MARKET'/'STOP'/'STOP_LIMIT'
    price DECIMAL(10,2),  -- 委托价格（市价单可为空）
    quantity INTEGER NOT NULL,  -- 委托数量
    amount DECIMAL(20,2),  -- 委托金额
    status VARCHAR(20) NOT NULL,  -- 'PENDING'/'PARTIAL'/'FILLED'/'CANCELED'/'REJECTED'
    filled_price DECIMAL(10,2),  -- 成交价格
    filled_quantity INTEGER,  -- 成交数量
    filled_amount DECIMAL(20,2),  -- 成交金额
    commission DECIMAL(20,2),  -- 佣金
    tax DECIMAL(20,2),  -- 印花税
    slippage DECIMAL(10,2),  -- 滑点
    order_source VARCHAR(20),  -- 'MANUAL'/'AUTO'/'AI'
    strategy_name VARCHAR(50),  -- 关联策略
    signal_id UUID REFERENCES trading_signal(signal_id),
    error_message TEXT,  -- 错误信息
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_orders_ts_code ON orders(ts_code);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);
COMMENT ON TABLE orders IS '订单表，存储所有交易订单';

-- 成交记录表
CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    trade_id VARCHAR(50) UNIQUE NOT NULL,
    order_id VARCHAR(50) REFERENCES orders(order_id),
    ts_code VARCHAR(10) NOT NULL REFERENCES stock_pool(ts_code),
    direction VARCHAR(4) NOT NULL,  -- 'BUY'/'SELL'
    price DECIMAL(10,2) NOT NULL,  -- 成交价格
    quantity INTEGER NOT NULL,  -- 成交数量
    amount DECIMAL(20,2) NOT NULL,  -- 成交金额
    commission DECIMAL(20,2),  -- 佣金
    tax DECIMAL(20,2),  -- 印花税
    trade_date DATE NOT NULL,
    trade_time TIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_trades_ts_code ON trades(ts_code);
CREATE INDEX idx_trades_trade_date ON trades(trade_date DESC);
COMMENT ON TABLE trades IS '成交记录表，存储每笔成交明细';

-- ============================================
-- 7. 持仓与账户表
-- ============================================

-- 持仓表
CREATE TABLE IF NOT EXISTS positions (
    id BIGSERIAL PRIMARY KEY,
    ts_code VARCHAR(10) UNIQUE NOT NULL REFERENCES stock_pool(ts_code),
    direction VARCHAR(4) NOT NULL,  -- 'LONG'/'SHORT'
    total_quantity INTEGER NOT NULL,  -- 总持仓数量
    available_quantity INTEGER NOT NULL,  -- 可用数量（可卖出）
    locked_quantity INTEGER DEFAULT 0,  -- 锁定数量（挂单中）
    cost_price DECIMAL(10,2) NOT NULL,  -- 持仓成本价
    current_price DECIMAL(10,2),  -- 当前价格
    market_value DECIMAL(20,2),  -- 市值
    profit_loss DECIMAL(20,2),  -- 浮动盈亏
    profit_loss_ratio DECIMAL(10,4),  -- 盈亏比例
    days_held INTEGER,  -- 持仓天数
    stop_loss_price DECIMAL(10,2),  -- 止损价
    take_profit_price DECIMAL(10,2),  -- 止盈价
    strategy_name VARCHAR(50),  -- 建仓策略
    opened_at TIMESTAMP NOT NULL,  -- 开仓时间
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_positions_ts_code ON positions(ts_code);
COMMENT ON TABLE positions IS '持仓表，存储当前持仓详情';

-- 账户表
CREATE TABLE IF NOT EXISTS accounts (
    id BIGSERIAL PRIMARY KEY,
    account_id VARCHAR(50) UNIQUE NOT NULL,
    account_name VARCHAR(50),
    account_type VARCHAR(20) NOT NULL,  -- 'SIMULATION'/'REAL'
    total_assets DECIMAL(20,2),  -- 总资产
    available_cash DECIMAL(20,2),  -- 可用资金
    market_value DECIMAL(20,2),  -- 持仓市值
    total_profit_loss DECIMAL(20,2),  -- 总盈亏
    total_profit_loss_ratio DECIMAL(10,4),  -- 总盈亏比例
    day_profit_loss DECIMAL(20,2),  -- 当日盈亏
    day_profit_loss_ratio DECIMAL(10,4),  -- 当日盈亏比例
    max_drawdown DECIMAL(10,4),  -- 最大回撤
    sharpe_ratio DECIMAL(10,4),  -- 夏普比率
    win_rate DECIMAL(10,4),  -- 胜率
    profit_loss_ratio DECIMAL(10,4),  -- 盈亏比
    total_trades INTEGER,  -- 总交易次数
    winning_trades INTEGER,  -- 盈利交易次数
    losing_trades INTEGER,  -- 亏损交易次数
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE accounts IS '账户表，存储账户资金与绩效信息';

-- ============================================
-- 8. 策略与回测表
-- ============================================

-- 策略表
CREATE TABLE IF NOT EXISTS strategies (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(50) UNIQUE NOT NULL,
    strategy_version VARCHAR(20) NOT NULL,
    strategy_type VARCHAR(20),  -- 'TECHNICAL'/'ML'/'RL'/'HYBRID'
    description TEXT,
    parameters JSONB,  -- 策略参数
    indicators JSONB,  -- 使用的技术指标
    risk_control JSONB,  -- 风控规则
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(strategy_name, strategy_version)
);

COMMENT ON TABLE strategies IS '策略表，存储所有交易策略';

-- 回测结果表
CREATE TABLE IF NOT EXISTS backtest_results (
    id BIGSERIAL PRIMARY KEY,
    backtest_id UUID DEFAULT uuid_generate_v4(),
    strategy_name VARCHAR(50) NOT NULL,
    strategy_version VARCHAR(20) NOT NULL,
    ts_code VARCHAR(20) NOT NULL DEFAULT '',  -- 回测标的代码
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_cash DECIMAL(20,2) NOT NULL,
    final_value DECIMAL(20,2) NOT NULL,
    total_return DECIMAL(10,4),  -- 总收益率
    annual_return DECIMAL(10,4),  -- 年化收益率
    sharpe_ratio DECIMAL(10,4),  -- 夏普比率
    max_drawdown DECIMAL(10,4),  -- 最大回撤
    win_rate DECIMAL(10,4),  -- 胜率
    profit_loss_ratio DECIMAL(10,4),  -- 盈亏比
    total_trades INTEGER,  -- 总交易次数
    winning_trades INTEGER,  -- 盈利次数
    losing_trades INTEGER,  -- 亏损次数
    avg_holding_days DECIMAL(10,2),  -- 平均持仓天数
    backtest_details JSONB,  -- 回测详情（每日净值、交易记录等）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_backtest_results_strategy ON backtest_results(strategy_name);
CREATE INDEX idx_backtest_results_ts_code ON backtest_results(ts_code);
COMMENT ON TABLE backtest_results IS '回测结果表';

-- ============================================
-- 9. 回测报告表
-- ============================================
CREATE TABLE IF NOT EXISTS backtest_reports (
    id BIGSERIAL PRIMARY KEY,
    report_id UUID DEFAULT uuid_generate_v4(),
    report_type VARCHAR(10) NOT NULL,       -- daily / weekly / monthly
    report_date DATE NOT NULL,              -- 报告日期
    ts_codes TEXT[],                        -- 回测标的列表
    strategy_count INTEGER DEFAULT 0,       -- 覆盖策略数
    strategies_covered JSONB,               -- 覆盖策略详情
    summary JSONB,                          -- 摘要（指标汇总）
    detail_content TEXT,                    -- 报告正文（Markdown）
    feishu_msg_id VARCHAR(100),             -- 飞书消息ID
    push_success BOOLEAN DEFAULT FALSE,     -- 推送成功标记
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_reports_type_date ON backtest_reports(report_type, report_date);
COMMENT ON TABLE backtest_reports IS '回测报告表';

-- ============================================
-- 10. AI调用日志表
-- ============================================

-- AI模型调用日志表
CREATE TABLE IF NOT EXISTS ai_call_log (
    id BIGSERIAL PRIMARY KEY,
    call_id UUID DEFAULT uuid_generate_v4(),
    task_type VARCHAR(50) NOT NULL,  -- 任务类型
    model_name VARCHAR(50) NOT NULL,  -- 模型名称
    model_version VARCHAR(20),  -- 模型版本
    input_tokens INTEGER,  -- 输入Token数
    output_tokens INTEGER,  -- 输出Token数
    total_tokens INTEGER,  -- 总Token数
    cost DECIMAL(10,4),  -- 成本（美元）
    latency_ms INTEGER,  -- 延迟（毫秒）
    status VARCHAR(20),  -- 'SUCCESS'/'FAILED'/'TIMEOUT'
    error_message TEXT,  -- 错误信息
    request_payload JSONB,  -- 请求数据
    response_payload JSONB,  -- 响应数据
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_ai_call_log_model ON ai_call_log(model_name);
CREATE INDEX idx_ai_call_log_created_at ON ai_call_log(created_at DESC);
COMMENT ON TABLE ai_call_log IS 'AI模型调用日志表，用于成本分析和优化';

-- AI模型成本统计表（物化视图）
CREATE MATERIALIZED VIEW IF NOT EXISTS ai_cost_daily_stats AS
SELECT 
    DATE(created_at) as date,
    model_name,
    task_type,
    COUNT(*) as call_count,
    SUM(input_tokens) as total_input_tokens,
    SUM(output_tokens) as total_output_tokens,
    SUM(total_tokens) as total_tokens,
    SUM(cost) as total_cost,
    AVG(latency_ms) as avg_latency_ms,
    COUNT(CASE WHEN status = 'SUCCESS' THEN 1 END) as success_count,
    COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as failed_count
FROM ai_call_log
GROUP BY DATE(created_at), model_name, task_type
WITH NO DATA;

COMMENT ON MATERIALIZED VIEW ai_cost_daily_stats IS 'AI模型成本日统计物化视图';

-- ============================================
-- 10. 风险管理表
-- ============================================

-- 风险事件表
CREATE TABLE IF NOT EXISTS risk_events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID DEFAULT uuid_generate_v4(),
    event_type VARCHAR(50) NOT NULL,  -- 'DRAWDOWN'/'LOSS'/'CONCENTRATION'/'VOLATILITY'
    severity VARCHAR(10) NOT NULL,  -- 'LOW'/'MEDIUM'/'HIGH'/'CRITICAL'
    ts_code VARCHAR(10) REFERENCES stock_pool(ts_code),
    account_id VARCHAR(50) REFERENCES accounts(account_id),
    description TEXT,
    threshold_value DECIMAL(20,4),  -- 阈值
    actual_value DECIMAL(20,4),  -- 实际值
    action_taken VARCHAR(50),  -- 'WARN'/'REDUCE'/'LIQUIDATE'/'STOP'
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_risk_events_created_at ON risk_events(created_at DESC);
COMMENT ON TABLE risk_events IS '风险事件表，记录所有风险预警与处理';

-- ============================================
-- 11. 系统配置表
-- ============================================

-- 系统配置表
CREATE TABLE IF NOT EXISTS system_config (
    id SERIAL PRIMARY KEY,
    config_key VARCHAR(50) UNIQUE NOT NULL,
    config_value TEXT,
    config_type VARCHAR(20),  -- 'STRING'/'INTEGER'/'FLOAT'/'BOOLEAN'/'JSON'
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE system_config IS '系统配置表';

-- 插入默认配置
INSERT INTO system_config (config_key, config_value, config_type, description) VALUES
('max_position_ratio', '0.30', 'FLOAT', '单只股票最大仓位比例'),
('max_total_positions', '3', 'INTEGER', '最大持仓数量'),
('stop_loss_ratio', '0.08', 'FLOAT', '止损比例'),
('take_profit_ratio', '0.30', 'FLOAT', '止盈比例'),
('max_daily_loss', '0.05', 'FLOAT', '单日最大亏损比例'),
('ai_budget_total', '10000', 'INTEGER', 'AI调用总预算（美元）'),
('data_source_priority', '["tdx", "tushare", "akshare"]', 'JSON', '数据源优先级（tdx/通达信 > tushare > akshare）'),
('data_source', 'tushare', 'STRING', '当前活跃数据源（tdx / tushare / akshare）')
ON CONFLICT (config_key) DO NOTHING;

-- ============================================
-- 12. 创建索引与约束
-- ============================================

-- 创建复合索引
CREATE INDEX idx_daily_quote_date_close ON daily_quote(trade_date DESC, close);

-- 创建分区表（如果不使用TimescaleDB，使用PostgreSQL原生分区）
-- 已经在上面使用TimescaleDB的create_hypertable实现分区

-- ============================================
-- 13. 创建视图
-- ============================================

-- 持仓汇总视图
CREATE OR REPLACE VIEW v_positions_summary AS
SELECT 
    p.ts_code,
    s.name as stock_name,
    p.direction,
    p.total_quantity,
    p.cost_price,
    p.current_price,
    p.market_value,
    p.profit_loss,
    p.profit_loss_ratio,
    p.days_held,
    p.opened_at
FROM positions p
JOIN stock_pool s ON p.ts_code = s.ts_code
WHERE p.total_quantity > 0;

COMMENT ON VIEW v_positions_summary IS '持仓汇总视图';

-- 账户绩效视图
CREATE OR REPLACE VIEW v_account_performance AS
SELECT 
    a.account_id,
    a.account_name,
    a.account_type,
    a.total_assets,
    a.available_cash,
    a.market_value,
    a.total_profit_loss,
    a.total_profit_loss_ratio,
    a.day_profit_loss,
    a.max_drawdown,
    a.sharpe_ratio,
    a.win_rate,
    a.total_trades,
    a.updated_at
FROM accounts a;

COMMENT ON VIEW v_account_performance IS '账户绩效视图';

-- ============================================
-- 14. 创建存储过程与函数
-- ============================================

-- 更新持仓盈亏的存储过程
CREATE OR REPLACE FUNCTION update_positions_profit_loss()
RETURNS VOID AS $$
BEGIN
    UPDATE positions p
    SET 
        current_price = (
            SELECT close 
            FROM daily_quote d 
            WHERE d.ts_code = p.ts_code 
            ORDER BY trade_date DESC 
            LIMIT 1
        ),
        market_value = total_quantity * (
            SELECT close 
            FROM daily_quote d 
            WHERE d.ts_code = p.ts_code 
            ORDER BY trade_date DESC 
            LIMIT 1
        ),
        profit_loss = (
            SELECT close 
            FROM daily_quote d
            WHERE d.ts_code = p.ts_code
            ORDER BY trade_date DESC
            LIMIT 1
        ) * total_quantity - cost_price * total_quantity,
        profit_loss_ratio = (
            (
                SELECT close 
                FROM daily_quote d
                WHERE d.ts_code = p.ts_code
                ORDER BY trade_date DESC
                LIMIT 1
            ) - cost_price
        ) / cost_price,
        updated_at = CURRENT_TIMESTAMP
    WHERE total_quantity > 0;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_positions_profit_loss() IS '更新所有持仓的盈亏信息';

-- ============================================
-- 15. 初始化数据
-- ============================================

-- 插入示例股票池数据（A股主板+中小板）
INSERT INTO stock_pool (ts_code, name, industry, sector, list_date, market) VALUES
('600519.SH', '贵州茅台', '食品饮料', '消费', '2001-08-27', '主板'),
('000858.SZ', '五粮液', '食品饮料', '消费', '1998-04-27', '主板'),
('600036.SH', '招商银行', '银行', '金融', '2002-04-09', '主板'),
('601318.SH', '中国平安', '保险', '金融', '2007-03-01', '主板'),
('000333.SZ', '美的集团', '家电', '消费', '2013-09-18', '主板'),
('002415.SZ', '海康威视', '电子', '科技', '2010-05-28', '中小板'),
('600276.SH', '恒瑞医药', '医药', '医药', '2000-10-18', '主板'),
('000568.SZ', '泸州老窖', '食品饮料', '消费', '1994-05-09', '主板'),
('601888.SH', '中国中免', '商贸零售', '消费', '2009-10-15', '主板'),
('002475.SZ', '立讯精密', '电子', '科技', '2010-09-15', '中小板')
ON CONFLICT (ts_code) DO NOTHING;

-- 插入示例账户数据
INSERT INTO accounts (account_id, account_name, account_type, total_assets, available_cash, market_value)
VALUES
('SIM_001', '模拟账户', 'SIMULATION', 50000.00, 50000.00, 0.00),
('REAL_001', '实盘账户', 'REAL', 30000.00, 30000.00, 0.00)
ON CONFLICT (account_id) DO NOTHING;

-- ============================================
-- 完成
-- ============================================

-- 显示所有表
\dt

-- 显示所有视图
\dv

-- 完成提示
SELECT 'Database initialization completed successfully!' as status;
