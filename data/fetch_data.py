"""
从Tushare获取A股历史日K线数据并写入PostgreSQL
运行环境：Docker容器内（quant-strategy）
"""
import sys
import os
import tushare as ts
from sqlalchemy import create_engine, text
import pandas as pd
from datetime import datetime, timedelta

# Docker容器内默认环境变量
DB_URL = os.environ.get('DATABASE_URL', 'postgresql://quant_user:quant_pass@postgres:5432/quant_trading')
TUSHARE_TOKEN = os.environ.get('TUSHARE_TOKEN', os.environ.get('ts_token', 'deda9ab7f4f62de8351e88f93751373eff49542f9005c547389dfc88'))

def get_stock_list(pro):
    """获取A股主板股票列表"""
    df = pro.stock_basic(exchange='', list_status='L', 
                         fields='ts_code,symbol,name,area,industry,list_date')
    # 过滤：仅主板（排除创业板300/301，科创板688/689，北交所8/4开头）
    df = df[~df['ts_code'].str.startswith(('300', '301', '688', '689', '8', '4'))]
    return df

def fetch_daily_kline(pro, ts_code, start_date, end_date):
    """拉取单只股票日K线"""
    try:
        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df['ts_code'] = ts_code
            return df
    except Exception as e:
        print(f"  [SKIP] {ts_code}: {e}")
    return None

def main():
    print(f"[{datetime.now()}] 量化数据拉取开始...")
    
    pro = ts.pro_api(TUSHARE_TOKEN)
    print(f"Tushare连接: OK")
    
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
    print(f"数据库连接: OK")
    
    # 获取股票列表
    stocks = get_stock_list(pro)
    print(f"主板股票数量: {len(stocks)}")
    
    # 拉取最近30天数据
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
    
    all_data = []
    success_count = 0
    fail_count = 0
    
    for _, row in stocks.head(20).iterrows():  # 先拉前20只测试
        ts_code = row['ts_code']
        print(f"  拉取 {ts_code} {row['name']}...", end=' ')
        df = fetch_daily_kline(pro, ts_code, start_date, end_date)
        if df is not None and not df.empty:
            all_data.append(df)
            success_count += 1
            print(f"OK ({len(df)}条)")
        else:
            fail_count += 1
            print("FAIL")
    
    if all_data:
        result = pd.concat(all_data, ignore_index=True)
        result.to_sql('daily_kline', engine, if_exists='replace', index=False)
        print(f"\n写入完成: {len(result)} 条记录 → daily_kline 表")
    
    print(f"成功: {success_count}, 失败: {fail_count}")
    print(f"[{datetime.now()}] 数据拉取完成")

if __name__ == '__main__':
    main()
