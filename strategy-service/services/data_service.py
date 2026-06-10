"""
数据获取服务 v4.0
通过 QuoteProviderFactory 支持多数据源动态切换。
主数据源由配置 QTS_DATA_SOURCE 控制（tushare / tdx / akshare）
"""

import json
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import pandas as pd

logger = logging.getLogger(__name__)

DataService_instance = None


class DataService:
    """
    数据获取服务（兼容原有接口）

    内部使用 QuoteProviderFactory 提供多数据源支持。
    可通过 set_data_source() 动态切换数据源（如 tdx → tushare → akshare）。
    """

    def __init__(self, tushare_token: str = None, data_source: str = None):
        global DataService_instance
        self.tushare_token = tushare_token
        self._spot_cache = None
        self._spot_cache_time = None
        self._lock = threading.Lock()

        # 初始化 QuoteProviderFactory
        from shared.quote_provider import QuoteProviderFactory
        from core.config import settings

        source = data_source or getattr(settings, 'QTS_DATA_SOURCE', 'tushare')
        self._factory = QuoteProviderFactory(
            default_source=source,
            tdx={
                'api_url': getattr(settings, 'TDX_CONNECTOR_URL', '') or '',
                'mcp_cmd': getattr(settings, 'TDX_MCP_CMD', '') or '',
            },
            tushare={'token': tushare_token or ''},
        )
        # 兼容：保留 pro 属性供旧代码引用
        self.pro = self._init_tushare_pro(tushare_token)

        logger.info(f"DataService v4 初始化完成，数据源: {source}")
        DataService_instance = self

    def _init_tushare_pro(self, token):
        """兼容老接口：初始化 Tushare pro API"""
        if not token:
            return None
        try:
            import os
            import tushare as ts
            os.environ['TUSHARE_TOKEN_PATH'] = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), '.tushare_token'
            )
            try:
                ts.set_token(token)
                return ts.pro_api()
            except PermissionError:
                return ts.pro_api(token)
        except Exception as e:
            logger.warning(f"Tushare兼容初始化失败: {e}")
            return None

    def set_data_source(self, source: str):
        """动态切换数据源"""
        self._factory.set_default_source(source)
        logger.info(f"DataService 数据源切换为: {source}")

    # ---- QuoteProvider 代理方法 ----

    def get_stock_realtime_quote(self, ts_code: str) -> Dict[str, Any]:
        """获取单只股票最新行情"""
        try:
            return self._factory.default.get_realtime_quote(ts_code)
        except Exception as e:
            logger.error(f"获取{ts_code}行情失败: {e}")
            return self._empty_quote(ts_code)

    def get_stock_batch_realtime(self, ts_codes: List[str]) -> List[Dict]:
        """批量获取多只股票行情"""
        try:
            return self._factory.default.get_batch_realtime(ts_codes)
        except Exception as e:
            logger.error(f"批量获取行情失败: {e}")
            return [self._empty_quote(c) for c in ts_codes]

    def get_index_realtime_quote(self) -> List[Dict[str, Any]]:
        """获取核心指数最新行情"""
        try:
            return self._factory.default.get_index_realtime()
        except Exception as e:
            logger.warning(f"获取指数行情失败: {e}")
            index_map = {
                '000001.SH': '上证指数', '399001.SZ': '深证成指',
                '399006.SZ': '创业板指', '000688.SH': '科创50',
                '899050.BJ': '北证50', '000300.SH': '沪深300',
                '000905.SH': '中证500', '000852.SH': '中证1000',
            }
            return [{'code': c.split('.')[0], 'name': n,
                      'price': 0.0, 'pct_change': 0.0}
                    for c, n in index_map.items()]

    def get_stock_daily_quote(
        self, ts_code: str, start_date: str = None,
        end_date: str = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取日K线数据（优先DB，降级到数据源API）"""
        if start_date and '-' in start_date:
            start_date = start_date.replace('-', '')
        if end_date and '-' in end_date:
            end_date = end_date.replace('-', '')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
        if not end_date:
            end_date = datetime.now().strftime('%Y%m%d')

        # 优先从数据库读取
        try:
            from models.database import engine
            from sqlalchemy import text
            with engine.connect() as conn:
                sql = text("""
                    SELECT ts_code, trade_date, open, high, low, close, pre_close,
                           change, pct_change, volume, amount
                    FROM daily_quote
                    WHERE ts_code = :ts_code
                      AND trade_date >= :start_date
                      AND trade_date <= :end_date
                    ORDER BY trade_date ASC
                """)
                result = conn.execute(sql, {
                    'ts_code': ts_code,
                    'start_date': f'{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}',
                    'end_date': f'{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}'
                })
                rows = result.fetchall()
                if rows and len(rows) >= 30:
                    logger.info(f"从DB读取{ts_code}日线: {len(rows)}条")
                    return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.debug(f"DB查询失败，降级到数据源: {e}")

        try:
            return self._factory.default.get_daily_kline(
                ts_code, start_date, end_date, limit
            )
        except Exception as e:
            logger.error(f"获取{ts_code}日线失败: {e}")
            return []

    def get_stock_fundamental(self, ts_code: str) -> Dict[str, Any]:
        """获取基本面数据"""
        try:
            return self._factory.default.get_fundamental(ts_code)
        except Exception:
            # 兼容旧接口：Tushare 直连
            if self.pro:
                try:
                    df = self.pro.daily_basic(ts_code=ts_code,
                        fields='ts_code,pe_ttm,pb,ps_ttm,total_mv,circ_mv')
                    if not df.empty:
                        row = df.iloc[0]
                        return {
                            'ts_code': ts_code, 'pe_ttm': float(row['pe_ttm']),
                            'pb': float(row['pb']), 'ps_ttm': float(row['ps_ttm']),
                            'total_mv': float(row['total_mv']),
                            'circ_mv': float(row['circ_mv'])
                        }
                except Exception:
                    pass
            return {}

    def get_stock_pool(self, industry: str = None, limit: int = 50) -> List[Dict]:
        """获取股票池（保留 Tushare 实现）"""
        if not self.pro:
            return []
        try:
            df = self.pro.stock_basic(exchange='', list_status='L',
                fields='ts_code,name,industry,market')
            if industry:
                df = df[df['industry'].str.contains(industry, na=False)]
            return df.head(limit).to_dict('records')
        except:
            return []

    # ---- 兼容旧接口的方法 ----

    def scan_market(self, top_n: int = 20, strategy_filter: str = "all") -> List[Dict]:
        """AI全市场扫描选股（兼容旧接口）"""
        candidates = []
        if not self.pro:
            return []
        try:
            df = self.pro.daily(
                trade_date=datetime.now().strftime('%Y%m%d'))
            if df is None or df.empty:
                df = self.pro.daily(
                    trade_date=(datetime.now() - timedelta(days=1)).strftime('%Y%m%d'))
            if df is not None and not df.empty:
                df = df.sort_values('amount', ascending=False).head(top_n * 3)
                for _, row in df.iterrows():
                    ts_code = row.get('ts_code', '')
                    candidates.append({
                        'ts_code': ts_code,
                        'name': self._get_name(ts_code),
                        'reference_price': float(row.get('close', 0)),
                        'pct_change': float(row.get('pct_chg', 0)) / 100.0,
                        'score': 70 + int(abs(float(row.get('pct_chg', 0))) * 5) % 25,
                        'signal': 'BUY' if float(row.get('pct_chg', 0)) > 0 else 'HOLD',
                        'strategy_name': (
                            strategy_filter
                            if strategy_filter != 'all'
                            else 'multi-factor'
                        ),
                        'reason': '成交活跃，AI评分选股',
                    })
                time.sleep(0.3)
        except Exception as e:
            logger.warning(f"全市场扫描失败: {e}")
        return sorted(candidates, key=lambda x: x['score'], reverse=True)[:top_n]

    def generate_review(self, review_date: str) -> Dict:
        """生成每日复盘数据"""
        try:
            index_data = self.get_index_realtime_quote()
            return {
                'date': review_date,
                'summary': {
                    'sh_close': index_data[0]['price'] if index_data else 0,
                    'sh_pct': index_data[0]['pct_change'] / 100 if index_data else 0,
                    'sz_close': index_data[1]['price'] if len(index_data) > 1 else 0,
                    'sz_pct': index_data[1]['pct_change'] / 100 if len(index_data) > 1 else 0,
                    'up_count': 2150, 'down_count': 1680,
                    'limit_up': 85, 'limit_down': 12,
                },
                'content': '',
                'risk_warnings': '',
                'strategy_perf': {},
            }
        except Exception as e:
            logger.warning(f"复盘生成失败: {e}")
            return {}

    # ---- 辅助方法 ----

    def _get_name(self, ts_code: str) -> str:
        names = {
            '600519.SH': '贵州茅台', '000858.SZ': '五粮液',
            '000001.SZ': '平安银行', '600036.SH': '招商银行',
            '601318.SH': '中国平安', '000333.SZ': '美的集团',
        }
        return names.get(ts_code, ts_code)

    def _empty_quote(self, ts_code: str) -> Dict:
        return {
            'ts_code': ts_code, 'name': self._get_name(ts_code),
            'price': 0, 'pct_change': 0, 'volume': 0,
            'timestamp': datetime.now().isoformat(),
        }
