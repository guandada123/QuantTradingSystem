-- 2026-10-12 结构对齐迁移：把「代码先行、schema 没到」的缺口一次补齐
-- 背景：真跑契约测试时先撞出 positions/500，做「模型 vs 库」全量对账后确认这是一整片缺口。
-- 安全性：全部为**追加式 DDL**（加列/建表），不动既有数据；回滚见文件尾注释。
BEGIN;

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'CNY';  -- 模型: currency = Column(String(10), default="CNY")
ALTER TABLE orders ADD COLUMN IF NOT EXISTS account_id VARCHAR(20) DEFAULT 'REAL_001' NOT NULL;  -- 模型: account_id = Column(String(20), ForeignKey("accounts.account_id"), nullable=False)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS account_id VARCHAR(20);  -- 模型: account_id = Column(String(20), ForeignKey("accounts.account_id"))
ALTER TABLE trades ADD COLUMN IF NOT EXISTS profit_loss NUMERIC(20,2);  -- 模型: profit_loss = Column(Numeric(20, 2))
ALTER TABLE stock_info ADD COLUMN IF NOT EXISTS circ_mv NUMERIC(20,2);  -- 模型: circ_mv = Column(Numeric(20, 2))
ALTER TABLE stock_info ADD COLUMN IF NOT EXISTS dividend_yield NUMERIC(10,4);  -- 模型: dividend_yield = Column(Numeric(10, 4))
ALTER TABLE stock_info ADD COLUMN IF NOT EXISTS pb NUMERIC(10,2);  -- 模型: pb = Column(Numeric(10, 2))
ALTER TABLE stock_info ADD COLUMN IF NOT EXISTS pe NUMERIC(10,2);  -- 模型: pe = Column(Numeric(10, 2))
ALTER TABLE stock_info ADD COLUMN IF NOT EXISTS total_mv NUMERIC(20,2);  -- 模型: total_mv = Column(Numeric(20, 2))
ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS backtest_details_compressed BYTEA;  -- 模型: backtest_details_compressed = Column(LargeBinary, nullable=True)

-- 模型有、库缺整表（回测走查结果）
CREATE TABLE IF NOT EXISTS walk_forward_results (
    id SERIAL PRIMARY KEY,
    wf_id UUID,
    strategy_name VARCHAR(50) NOT NULL,
    ts_code VARCHAR(20) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    train_days INTEGER NOT NULL,
    test_days INTEGER NOT NULL,
    step_days INTEGER NOT NULL,
    param_grid JSONB,
    initial_cash NUMERIC(20,2) NOT NULL,
    slippage NUMERIC(10,4),
    commission_rate NUMERIC(10,6),
    benchmark VARCHAR(20),
    windows JSONB,
    overall_test_return NUMERIC(10,6),
    overfit_ratio NUMERIC(10,4),
    num_windows INTEGER,
    data_source VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (wf_id)
);

COMMIT;

-- 回滚（如需）：
--   ALTER TABLE accounts DROP COLUMN currency;
--   ALTER TABLE orders DROP COLUMN account_id;
--   ALTER TABLE trades DROP COLUMN account_id, DROP COLUMN profit_loss;
--   ALTER TABLE stock_info DROP COLUMN circ_mv, DROP COLUMN dividend_yield, DROP COLUMN pb, DROP COLUMN pe, DROP COLUMN total_mv;
--   ALTER TABLE backtest_results DROP COLUMN backtest_details_compressed;
--   DROP TABLE walk_forward_results;
