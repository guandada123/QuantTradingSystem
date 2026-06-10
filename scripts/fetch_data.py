"""
从Tushare获取历史日K线数据并写入PostgreSQL
"""
import sys
sys.path.insert(0, '/app')
import tushare as ts
import os
from sqlalchemy import create_engine, text
import pandas as pd

# Connect to DB
db_url = os.environ.get('DATABASE_URL', 'postgresql://quant_user:quant_pass@postgres:5432/quant_trading')
engine = create_engine(db_url)

# Get Tushare token
token = os.environ.get('TUSHARE_TOKEN', '')
pro = ts.pro_api(token)
print(f'Tushare token: {token[:8]}..., connected: {pro is not None}')

# 要获取的股票列表
stocks = ['600519.SH', '000858.SZ', '600036.SH', '601318.SH', '000333.SZ']
stock_names = ['贵州茅台', '五粮液', '招商银行', '中国平安', '美的集团']

total_inserted = 0
for ts_code, name in zip(stocks, stock_names):
    print(f'\n=== 获取 {name}({ts_code}) 2025年日K线 ===')
    try:
        df = pro.daily(ts_code=ts_code, start_date='20250101', end_date='20251231')
        if df is None or len(df) == 0:
            print(f'  ⚠️ 无数据返回')
            continue
        
        print(f'  获取到 {len(df)} 条')
        
        # Map columns
        df_db = df.rename(columns={'pct_chg': 'pct_change', 'vol': 'volume'})
        df_db['trade_date'] = pd.to_datetime(df_db['trade_date']).dt.date
        
        cols = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 
                'pre_close', 'change', 'pct_change', 'volume', 'amount']
        df_db = df_db[cols]
        
        # Insert (ignore duplicates)
        try:
            df_db.to_sql('daily_quote', engine, if_exists='append', index=False, method='multi')
            total_inserted += len(df_db)
            print(f'  ✅ 写入 {len(df_db)} 条')
        except Exception as e:
            if 'duplicate' in str(e).lower() or 'unique' in str(e).lower():
                print(f'  ⚠️ 数据已存在，跳过')
            else:
                print(f'  ❌ 写入失败: {e}')
    except Exception as e:
        print(f'  ❌ 获取失败: {e}')

# Verify total
with engine.connect() as conn:
    result = conn.execute(text("SELECT COUNT(*) FROM daily_quote"))
    count = result.scalar()
    print(f'\n=== 总计 ===')
    print(f'daily_quote 表总行数: {count}')
    print(f'本次写入: {total_inserted} 条')

print('\n✅ 数据采集完成')
